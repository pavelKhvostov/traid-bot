"""Sensitivity 1.1.2 EXTENDED вокруг финального конфига.

Грид:
  entry_pct ∈ {0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85}  (центр 0.70 ± 0.15)
  sl_pct    ∈ {0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50}  (центр 0.35 ± 0.15)
  RR = 1.8 (фиксирован)
  no_entry: ON
  extended_macro_search: ON
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_2 import detect_strategy_1_1_2_signals

DAYS_BACK = 1095
SYMBOL = "BTCUSDT"
ENTRY_GRID = [0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85]
SL_GRID = [0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50]
RR_TARGET = 1.8


def precompute(sig, df_1m):
    fvg_b, fvg_t = sig["fvg_zone"]
    obh_b, obh_t = sig["ob_htf_zone"]
    direction = sig["direction"]
    tf_minutes = 15 if sig["fvg_tf"] == "15m" else 20
    forward = df_1m[df_1m.index >= sig["signal_time"] + pd.Timedelta(minutes=tf_minutes)]
    if forward.empty: return None
    return {
        "direction": direction,
        "fvg_b": float(fvg_b), "fvg_t": float(fvg_t),
        "obh_b": float(obh_b), "obh_t": float(obh_t),
        "highs": forward["high"].values.astype(np.float64),
        "lows": forward["low"].values.astype(np.float64),
    }


def simulate_no_entry(s, entry, sl, tp):
    highs, lows = s["highs"], s["lows"]
    n = len(highs)
    if s["direction"] == "LONG":
        entry_idxs = np.where(lows <= entry)[0]
        tp_pre_idxs = np.where(highs >= tp)[0]
    else:
        entry_idxs = np.where(highs >= entry)[0]
        tp_pre_idxs = np.where(lows <= tp)[0]
    entry_idx = int(entry_idxs[0]) if entry_idxs.size else n + 1
    tp_pre_idx = int(tp_pre_idxs[0]) if tp_pre_idxs.size else n + 1
    if tp_pre_idx < entry_idx: return "no_entry"
    if entry_idx >= n: return "not_filled"
    post_l = lows[entry_idx:]; post_h = highs[entry_idx:]
    if s["direction"] == "LONG":
        sl_mask = post_l <= sl; tp_mask = post_h >= tp
    else:
        sl_mask = post_h >= sl; tp_mask = post_l <= tp
    sl_first = int(np.argmax(sl_mask)) if sl_mask.any() else -1
    tp_first = int(np.argmax(tp_mask)) if tp_mask.any() else -1
    if sl_first == -1 and tp_first == -1: return "open"
    if sl_first == -1: return "win"
    if tp_first == -1: return "loss"
    return "win" if tp_first < sl_first else "loss"


def main():
    print(f"[INFO] 1.1.2 EXTENDED sensitivity 7x7 grid вокруг (ep=0.70, sl=0.35), RR={RR_TARGET}")
    df_1d = load_df(SYMBOL, "1d")
    df_12h = load_df(SYMBOL, "12h")
    df_4h = load_df(SYMBOL, "4h")
    df_1h = load_df(SYMBOL, "1h")
    df_6h = compose_from_base(df_1h, "6h")
    df_2h = compose_from_base(df_1h, "2h")
    df_15m = load_df(SYMBOL, "15m")
    df_1m = load_df(SYMBOL, "1m")
    df_20m = compose_from_base(df_1m, "20m")
    today = pd.Timestamp.now(tz="UTC").normalize()
    cutoff = today - pd.Timedelta(days=DAYS_BACK)
    df_1d_f = df_1d[df_1d.index >= cutoff]
    df_12h_f = df_12h[df_12h.index >= cutoff]

    raw = detect_strategy_1_1_2_signals(
        df_1d_f, df_12h_f, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m,
        extended_macro_search=True, verbose=False,
    )
    print(f"  raw paths: {len(raw)}")

    groups = defaultdict(list)
    for s in raw:
        key = (s["signal_time"], s["direction"], round(float(s["entry"]), 2))
        groups[key].append(s)
    deduped = [g[0] for g in groups.values()]
    cache = [c for c in (precompute(s, df_1m) for s in deduped) if c is not None]
    print(f"  cache: {len(cache)}\n")

    rows = []
    for ep in ENTRY_GRID:
        for sp in SL_GRID:
            wins = losses = ne = nf = opens = skipped = 0
            for s in cache:
                fw = s["fvg_t"] - s["fvg_b"]
                if s["direction"] == "LONG":
                    entry = s["fvg_b"] + ep * fw
                    sl = s["obh_b"] + sp * (s["fvg_b"] - s["obh_b"])
                else:
                    entry = s["fvg_t"] - ep * fw
                    sl = s["obh_t"] - sp * (s["obh_t"] - s["fvg_t"])
                if s["direction"] == "LONG":
                    if sl >= entry: skipped += 1; continue
                    risk = entry - sl
                    tp = entry + RR_TARGET * risk
                else:
                    if sl <= entry: skipped += 1; continue
                    risk = sl - entry
                    tp = entry - RR_TARGET * risk
                outcome = simulate_no_entry(s, entry, sl, tp)
                if outcome == "win": wins += 1
                elif outcome == "loss": losses += 1
                elif outcome == "no_entry": ne += 1
                elif outcome == "open": opens += 1
                else: nf += 1
            closed = wins + losses
            pnl = wins * RR_TARGET - losses
            rows.append({
                "ep": ep, "sl": sp,
                "wins": wins, "losses": losses, "no_entry": ne,
                "closed": closed,
                "wr": round(wins / closed * 100, 1) if closed else 0,
                "pnl_r": round(pnl, 2),
                "r_per_trade": round(pnl / closed, 3) if closed else 0,
            })
    df = pd.DataFrame(rows)

    # PnL heatmap
    pivot_pnl = df.pivot(index="ep", columns="sl", values="pnl_r")
    print("=" * 100)
    print(f"PnL R heatmap (RR={RR_TARGET}, EXTENDED, no_entry=on):")
    print("=" * 100)
    print("(rows=ep, cols=sl)")
    print(pivot_pnl.to_string())

    # WR heatmap
    pivot_wr = df.pivot(index="ep", columns="sl", values="wr")
    print()
    print("=" * 100)
    print("WR % heatmap:")
    print("=" * 100)
    print(pivot_wr.to_string())

    # R/trade heatmap
    pivot_rt = df.pivot(index="ep", columns="sl", values="r_per_trade")
    print()
    print("=" * 100)
    print("R/trade heatmap:")
    print("=" * 100)
    print(pivot_rt.to_string())

    # Closed heatmap
    pivot_cl = df.pivot(index="ep", columns="sl", values="closed")
    print()
    print("=" * 100)
    print("Closed trades heatmap:")
    print("=" * 100)
    print(pivot_cl.to_string())

    # Top 10 by PnL
    print()
    print("=" * 100)
    print("TOP-10 по PnL:")
    print("=" * 100)
    top = df.sort_values("pnl_r", ascending=False).head(10)
    print(top.to_string(index=False))

    # Top 10 by R/trade
    print()
    print("=" * 100)
    print("TOP-10 по R/trade:")
    print("=" * 100)
    top_rt = df.sort_values("r_per_trade", ascending=False).head(10)
    print(top_rt.to_string(index=False))

    # Center cell (0.70, 0.35)
    print()
    print("=" * 100)
    center = df[(df["ep"] == 0.70) & (df["sl"] == 0.35)].iloc[0]
    print(f"Center (ep=0.70, sl=0.35):")
    print(f"  W={center['wins']} L={center['losses']} no_entry={center['no_entry']} "
          f"closed={center['closed']}")
    print(f"  WR={center['wr']}%  PnL={center['pnl_r']}R  R/trade={center['r_per_trade']}")
    best = df.sort_values("pnl_r", ascending=False).iloc[0]
    print(f"\nBest (max PnL):")
    print(f"  ep={best['ep']} sl={best['sl']}")
    print(f"  W={best['wins']} L={best['losses']} no_entry={best['no_entry']} "
          f"closed={best['closed']}")
    print(f"  WR={best['wr']}%  PnL={best['pnl_r']}R  R/trade={best['r_per_trade']}")

    out = Path("signals/analyze_1_1_2_extended_sensitivity.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    print(f"\n  saved: {out}")


if __name__ == "__main__":
    main()
