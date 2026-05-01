"""Grid search оптимума entry/SL для Strategy RDRB.

Параметры:
  - Entry в зоне FVG-15m: ep ∈ [0, 1] от FVG.bottom (LONG) / FVG.top (SHORT).
  - SL в диапазоне [ob_htf.bottom, rdrb.bottom] для LONG / [ob_htf.top, rdrb.top] для SHORT.
    Параметр sp ∈ [0, 1]:
      LONG  SL = ob_htf.bottom + sp x (rdrb.bottom - ob_htf.bottom)
      SHORT SL = ob_htf.top    + sp x (rdrb.top    - ob_htf.top)
  - RR=2.2 фиксирован.

Выход: топ-10 по PnL + confluence-разбивка (1d daily momentum TOTALES + USDT.D mirror).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df
from strategies.strategy_rdrb import detect_strategy_rdrb_signals

DAYS_BACK = 1095
SYMBOL = "BTCUSDT"
RR = 2.7
ENTRY_STEPS = np.arange(0.0, 1.01, 0.05)  # 0.0, 0.05, ..., 1.0
SL_STEPS    = np.arange(0.0, 1.01, 0.05)
OUTPUT_PATH = Path("signals/optimize_rdrb_entry_sl.csv")


def precompute_signal(sig: dict, df_1m: pd.DataFrame) -> dict | None:
    fvg_b, fvg_t = sig["fvg_zone"]
    obh_b, obh_t = sig["ob_htf_zone"]
    rdrb_b, rdrb_t = sig["rdrb_zone"]
    direction = sig["direction"]
    tf_minutes = 15 if sig["fvg_tf"] == "15m" else 20
    fill_scan_start = sig["signal_time"] + pd.Timedelta(minutes=tf_minutes)
    forward = df_1m[df_1m.index >= fill_scan_start]
    if forward.empty:
        return None
    return {
        "direction": direction,
        "fvg_b": float(fvg_b), "fvg_t": float(fvg_t),
        "obh_b": float(obh_b), "obh_t": float(obh_t),
        "rdrb_b": float(rdrb_b), "rdrb_t": float(rdrb_t),
        "highs": forward["high"].values.astype(np.float64),
        "lows": forward["low"].values.astype(np.float64),
        "signal_time": pd.Timestamp(sig["signal_time"]),
    }


def simulate(s: dict, entry: float, sl: float, tp: float) -> str:
    highs, lows = s["highs"], s["lows"]
    if s["direction"] == "LONG":
        fill_mask = lows <= entry
        if not fill_mask.any():
            return "not_filled"
        fill_idx = int(np.argmax(fill_mask))
        post_l = lows[fill_idx:]
        post_h = highs[fill_idx:]
        sl_mask = post_l <= sl
        tp_mask = post_h >= tp
    else:
        fill_mask = highs >= entry
        if not fill_mask.any():
            return "not_filled"
        fill_idx = int(np.argmax(fill_mask))
        post_l = lows[fill_idx:]
        post_h = highs[fill_idx:]
        sl_mask = post_h >= sl
        tp_mask = post_l <= tp
    sl_first = int(np.argmax(sl_mask)) if sl_mask.any() else -1
    tp_first = int(np.argmax(tp_mask)) if tp_mask.any() else -1
    if sl_first == -1 and tp_first == -1:
        return "open"
    if sl_first == -1:
        return "win"
    if tp_first == -1:
        return "loss"
    return "win" if tp_first < sl_first else "loss"


def daily_momentum(df: pd.DataFrame, ts: pd.Timestamp, lookback: int) -> int:
    if df.empty:
        return 0
    day = ts.normalize()
    prev_day = day - pd.Timedelta(days=lookback)
    n = df[df.index <= day]
    p = df[df.index <= prev_day]
    if n.empty or p.empty:
        return 0
    delta = float(n["close"].iloc[-1]) - float(p["close"].iloc[-1])
    return 1 if delta > 0 else (-1 if delta < 0 else 0)


def main() -> None:
    print(f"[INFO] Optimize RDRB entry/SL @ RR={RR}, grid {len(ENTRY_STEPS)}x{len(SL_STEPS)}")
    print()

    print("[INFO] загрузка данных")
    df_1d = load_df(SYMBOL, "1d")
    df_1h = load_df(SYMBOL, "1h")
    df_12h = compose_from_base(df_1h, "12h")
    df_2h = compose_from_base(df_1h, "2h")
    df_15m = load_df(SYMBOL, "15m")
    df_1m = load_df(SYMBOL, "1m")
    df_20m = compose_from_base(df_1m, "20m")

    today = pd.Timestamp.now(tz="UTC").normalize()
    cutoff = today - pd.Timedelta(days=DAYS_BACK)
    df_1d_f = df_1d[df_1d.index >= cutoff - pd.Timedelta(days=5)]
    df_12h_f = df_12h[df_12h.index >= cutoff - pd.Timedelta(days=5)]
    df_1h_f = df_1h[df_1h.index >= cutoff - pd.Timedelta(days=2)]
    df_2h_f = df_2h[df_2h.index >= cutoff - pd.Timedelta(days=2)]
    df_15m_f = df_15m[df_15m.index >= cutoff - pd.Timedelta(days=2)]
    df_20m_f = df_20m[df_20m.index >= cutoff - pd.Timedelta(days=2)]

    print("[INFO] детект RDRB сигналов")
    signals = detect_strategy_rdrb_signals(
        df_1d_f, df_12h_f, df_1h_f, df_2h_f, df_15m_f, df_20m_f, verbose=False,
    )
    print(f"  raw: {len(signals)}")

    cache = []
    for s in signals:
        c = precompute_signal(s, df_1m)
        if c is not None:
            cache.append(c)
    print(f"  cached: {len(cache)}")

    # Загрузка confluence-источников
    df_totales = load_df("TOTALES", "1d")
    df_usdtd = load_df("USDT_D", "1d")

    # Pre-compute confluence flags для каждого сигнала на 1d lookback (лучший для RDRB).
    for c in cache:
        sign = 1 if c["direction"] == "LONG" else -1
        tot = daily_momentum(df_totales, c["signal_time"], 1)
        usd = daily_momentum(df_usdtd, c["signal_time"], 1)
        c["triple"] = (tot == sign) and (usd == -sign)
        c["any_sync"] = (tot == sign) or (usd == -sign)

    print()
    print(f"[INFO] grid search ({len(ENTRY_STEPS) * len(SL_STEPS)} combos)")
    rows = []
    for ep in ENTRY_STEPS:
        for sp in SL_STEPS:
            wins = losses = nf = skip = 0
            wins_tr = losses_tr = 0  # triple confluence
            wins_an = losses_an = 0  # any sync
            for s in cache:
                fvg_w = s["fvg_t"] - s["fvg_b"]
                if s["direction"] == "LONG":
                    entry = s["fvg_b"] + ep * fvg_w
                    sl = s["obh_b"] + sp * (s["rdrb_b"] - s["obh_b"])
                    if sl >= entry:
                        skip += 1
                        continue
                    risk = entry - sl
                    tp = entry + risk * RR
                else:
                    entry = s["fvg_t"] - ep * fvg_w
                    sl = s["obh_t"] + sp * (s["rdrb_t"] - s["obh_t"])
                    if sl <= entry:
                        skip += 1
                        continue
                    risk = sl - entry
                    tp = entry - risk * RR
                outcome = simulate(s, entry, sl, tp)
                if outcome == "win":
                    wins += 1
                    if s["triple"]:
                        wins_tr += 1
                    if s["any_sync"]:
                        wins_an += 1
                elif outcome == "loss":
                    losses += 1
                    if s["triple"]:
                        losses_tr += 1
                    if s["any_sync"]:
                        losses_an += 1
                else:
                    nf += 1
            closed = wins + losses
            wr = wins / closed * 100 if closed else 0
            pnl = wins * RR - losses
            cl_tr = wins_tr + losses_tr
            wr_tr = wins_tr / cl_tr * 100 if cl_tr else 0
            pnl_tr = wins_tr * RR - losses_tr
            cl_an = wins_an + losses_an
            wr_an = wins_an / cl_an * 100 if cl_an else 0
            pnl_an = wins_an * RR - losses_an
            rows.append({
                "entry_pct": round(ep, 2),
                "sl_pct": round(sp, 2),
                "wins": wins, "losses": losses, "not_filled": nf, "skipped": skip,
                "wr": round(wr, 1),
                "pnl": round(pnl, 1),
                "n_triple": cl_tr, "wr_triple": round(wr_tr, 1),
                "pnl_triple": round(pnl_tr, 1),
                "n_any": cl_an, "wr_any": round(wr_an, 1),
                "pnl_any": round(pnl_an, 1),
            })

    df = pd.DataFrame(rows)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.sort_values("pnl", ascending=False).to_csv(OUTPUT_PATH, index=False)
    print(f"  записано в {OUTPUT_PATH}")

    print()
    print("=" * 100)
    print("TOP 10 by baseline PnL@2.2 (все сделки):")
    print("=" * 100)
    top = df.sort_values("pnl", ascending=False).head(10)
    print(top[["entry_pct","sl_pct","wins","losses","not_filled","wr","pnl",
              "n_triple","wr_triple","pnl_triple","n_any","wr_any","pnl_any"]].to_string(index=False))

    print()
    print("=" * 100)
    print("TOP 10 by Triple-confluence PnL@2.2 (1d momentum):")
    print("=" * 100)
    top_tr = df.sort_values("pnl_triple", ascending=False).head(10)
    print(top_tr[["entry_pct","sl_pct","wins","losses","wr","pnl",
                  "n_triple","wr_triple","pnl_triple"]].to_string(index=False))

    print()
    print("=" * 100)
    print("Базовая (entry_pct=0.5 = середина FVG, sl_pct=0.85 ≈ как просил):")
    print("=" * 100)
    base = df[(df["entry_pct"] == 0.5) & (df["sl_pct"] == 0.85)]
    if not base.empty:
        print(base.to_string(index=False))


if __name__ == "__main__":
    main()
