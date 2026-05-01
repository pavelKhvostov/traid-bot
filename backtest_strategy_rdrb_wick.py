"""RDRB Premium шаг 2: wick filter на trigger-свече RDRB.

Идея: «сильный rejection» — wick свечи i должен быть существенным:
  LONG  trigger: lower_wick = min(open, close) - low
  SHORT trigger: upper_wick = high - max(open, close)
  range = high - low
  Pass if wick / range >= threshold

Перебираем threshold ∈ {0.20, 0.30, 0.40, 0.50}, отдельно baseline и
triple-confluence (1d daily-momentum TOTALES + USDT.D mirror).

Параметры trade'а: entry=0.95, sl=0.35, RR=2.2 (best from grid).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from data_manager import compose_from_base, load_df
from strategies.strategy_rdrb import detect_strategy_rdrb_signals

DAYS_BACK = 1095
SYMBOL = "BTCUSDT"
RR = 2.2
ENTRY_PCT = 0.95
SL_PCT = 0.35
THRESHOLDS = [0.0, 0.20, 0.30, 0.40, 0.50]


def passes_wick_filter(sig: dict, df_1d: pd.DataFrame, df_12h: pd.DataFrame,
                       threshold: float) -> tuple[bool, float]:
    """Возвращает (passes, wick_ratio)."""
    df_top = df_1d if sig["rdrb_tf"] == "1d" else df_12h
    trigger_time = pd.Timestamp(sig["rdrb_trigger_time"])
    if trigger_time.tz is None:
        trigger_time = trigger_time.tz_localize("UTC")
    if trigger_time not in df_top.index:
        return False, 0.0
    row = df_top.loc[trigger_time]
    o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
    rng = h - l
    if rng <= 0:
        return False, 0.0
    if sig["direction"] == "LONG":
        wick = min(o, c) - l
    else:
        wick = h - max(o, c)
    ratio = wick / rng
    return ratio >= threshold, ratio


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


def simulate_one(sig: dict, df_1m: pd.DataFrame) -> str:
    direction = sig["direction"]
    fvg_b, fvg_t = sig["fvg_zone"]
    obh_b, obh_t = sig["ob_htf_zone"]
    rdrb_b, rdrb_t = sig["rdrb_zone"]
    if direction == "LONG":
        entry = fvg_b + ENTRY_PCT * (fvg_t - fvg_b)
        sl = obh_b + SL_PCT * (rdrb_b - obh_b)
        if sl >= entry:
            return "skipped"
        risk = entry - sl
        tp = entry + risk * RR
    else:
        entry = fvg_t - ENTRY_PCT * (fvg_t - fvg_b)
        sl = obh_t + SL_PCT * (rdrb_t - obh_t)
        if sl <= entry:
            return "skipped"
        risk = sl - entry
        tp = entry - risk * RR

    tf_minutes = 15 if sig["fvg_tf"] == "15m" else 20
    fill_scan_start = sig["signal_time"] + pd.Timedelta(minutes=tf_minutes)
    forward = df_1m[df_1m.index >= fill_scan_start]
    activation = None
    for ts, c in forward.iterrows():
        h, l = float(c["high"]), float(c["low"])
        if direction == "LONG":
            if l <= entry:
                activation = ts; break
        else:
            if h >= entry:
                activation = ts; break
    if activation is None:
        return "not_filled"
    sim = df_1m[df_1m.index >= activation]
    for ts, c in sim.iterrows():
        h, l = float(c["high"]), float(c["low"])
        if direction == "LONG":
            if l <= sl: return "loss"
            if h >= tp: return "win"
        else:
            if h >= sl: return "loss"
            if l <= tp: return "win"
    return "open"


def stats(rows, rr=RR):
    closed = [r for r in rows if r["outcome"] in ("win", "loss")]
    n = len(rows); nc = len(closed)
    wins = sum(1 for r in closed if r["outcome"] == "win")
    losses = nc - wins
    wr = wins / nc * 100 if nc else 0.0
    return {"n": n, "closed": nc, "wins": wins, "losses": losses,
            "wr": round(wr, 1), "pnl": round(wins * rr - losses, 1)}


def main() -> None:
    print(f"[INFO] RDRB wick-filter sweep, RR={RR}, entry={ENTRY_PCT}, sl={SL_PCT}")
    print()

    print("[INFO] загрузка")
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

    print("[INFO] детект RDRB")
    signals = detect_strategy_rdrb_signals(
        df_1d_f, df_12h_f, df_1h_f, df_2h_f, df_15m_f, df_20m_f, verbose=False,
    )
    print(f"  raw: {len(signals)}")

    # Симулируем все + считаем wick ratio
    print("[INFO] симуляция всех + wick ratio")
    df_tot = load_df("TOTALES", "1d")
    df_usd = load_df("USDT_D", "1d")
    rows = []
    for s in signals:
        outcome = simulate_one(s, df_1m)
        if outcome == "skipped":
            continue
        _, wick = passes_wick_filter(s, df_1d, df_12h, threshold=0.0)
        sig_t = pd.Timestamp(s["signal_time"])
        if sig_t.tz is None:
            sig_t = sig_t.tz_localize("UTC")
        sign = 1 if s["direction"] == "LONG" else -1
        tot = daily_momentum(df_tot, sig_t, 1)
        usd = daily_momentum(df_usd, sig_t, 1)
        rows.append({
            "outcome": outcome,
            "direction": s["direction"],
            "wick_ratio": wick,
            "triple_1d": (tot == sign) and (usd == -sign),
            "rdrb_tf": s["rdrb_tf"],
        })
    print(f"  всего simulated: {len(rows)}")

    # Сравнение по threshold
    print()
    print("=" * 100)
    print(f"{'threshold':>10} | {'BASELINE':^32} | {'TRIPLE confluence (1d)':^32}")
    print(f"{'':>10} | {'n':>4} {'closed':>6} {'WR':>6} {'PnL':>7} | {'n':>4} {'closed':>6} {'WR':>6} {'PnL':>7}")
    print("=" * 100)
    for thr in THRESHOLDS:
        passing = [r for r in rows if r["wick_ratio"] >= thr]
        triple = [r for r in passing if r["triple_1d"]]
        s_all = stats(passing)
        s_tr = stats(triple)
        print(f"{thr:>10.2f} | {s_all['n']:>4} {s_all['closed']:>6} "
              f"{s_all['wr']:>5.1f}% {s_all['pnl']:>+6.1f}R | "
              f"{s_tr['n']:>4} {s_tr['closed']:>6} "
              f"{s_tr['wr']:>5.1f}% {s_tr['pnl']:>+6.1f}R")

    # Распределение wick ratio
    print()
    print("Распределение wick_ratio:")
    import numpy as np
    ratios = [r["wick_ratio"] for r in rows]
    print(f"  min={min(ratios):.3f} max={max(ratios):.3f} mean={sum(ratios)/len(ratios):.3f}")
    bins = [0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0]
    for lo, hi in zip(bins, bins[1:]):
        n = sum(1 for r in ratios if lo <= r < hi)
        print(f"  [{lo:.1f}, {hi:.1f}): {n}")

    # WR by ratio bucket
    print()
    print("WR / PnL по бакетам wick_ratio:")
    for lo, hi in [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 1.0)]:
        sub = [r for r in rows if lo <= r["wick_ratio"] < hi]
        s = stats(sub)
        print(f"  [{lo:.1f}, {hi:.1f}): n={s['n']:3d} closed={s['closed']:3d} "
              f"WR={s['wr']:5.1f}% PnL={s['pnl']:+5.1f}R")


if __name__ == "__main__":
    main()
