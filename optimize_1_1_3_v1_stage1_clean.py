"""Stage 1 для 1.1.3 v1 (чистый прогон с полной сеткой):

  - fvg_variant = v1 (FVG = i, i+1, i+2)
  - ALL group (без SWEPT-фильтра)
  - entry варьируется ТОЛЬКО в границах FVG-htf:
      LONG:  entry = fvg.bottom + ep × (fvg.top - fvg.bottom)
      SHORT: entry = fvg.top    - ep × (fvg.top - fvg.bottom)
  - SL = константа на дальнем крае OB-htf:
      LONG:  SL = ob_htf.bottom
      SHORT: SL = ob_htf.top
  - TP = TP_const (price при default config: entry=mid FVG, SL=ob_htf far edge, RR=1)
  - no_entry: ON
  - untouched OB-macro: ON
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_3 import detect_strategy_1_1_3_signals

DAYS_BACK = 1095
SYMBOL = "BTCUSDT"
ENTRY_GRID = np.arange(0.0, 1.01, 0.05)


def precompute(sig, df_1m):
    fvg_b, fvg_t = sig["fvg_zone"]
    obh_b, obh_t = sig["ob_htf_zone"]
    direction = sig["direction"]
    tf_minutes = 60 if sig["fvg_tf"] == "1h" else 120
    forward = df_1m[df_1m.index >= sig["signal_time"] + pd.Timedelta(minutes=tf_minutes)]
    if forward.empty: return None
    entry_mid = (fvg_b + fvg_t) / 2
    if direction == "LONG":
        risk_mid = entry_mid - obh_b
        tp_const = entry_mid + risk_mid
    else:
        risk_mid = obh_t - entry_mid
        tp_const = entry_mid - risk_mid
    return {
        "direction": direction,
        "fvg_b": float(fvg_b), "fvg_t": float(fvg_t),
        "obh_b": float(obh_b), "obh_t": float(obh_t),
        "tp_const": float(tp_const),
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
    print(f"[INFO] 1.1.3 v1 Stage 1: entry в FVG, SL = ob_htf far edge, TP = TP_const")
    print(f"       no_entry=on, untouched=on, ALL group")
    print()

    df_1d = load_df(SYMBOL, "1d")
    df_12h = load_df(SYMBOL, "12h")
    df_4h = load_df(SYMBOL, "4h")
    df_1h = load_df(SYMBOL, "1h")
    df_6h = compose_from_base(df_1h, "6h")
    df_2h = compose_from_base(df_1h, "2h")
    df_1m = load_df(SYMBOL, "1m")
    today = pd.Timestamp.now(tz="UTC").normalize()
    cutoff = today - pd.Timedelta(days=DAYS_BACK)
    df_1d_f = df_1d[df_1d.index >= cutoff]
    df_12h_f = df_12h[df_12h.index >= cutoff]

    raw = detect_strategy_1_1_3_signals(
        df_1d_f, df_12h_f, df_4h, df_6h, df_1h, df_2h,
        fvg_variant="v1", verbose=False,
    )

    groups = defaultdict(list)
    for s in raw:
        key = (s["signal_time"], s["direction"], round(float(s["entry"]), 2))
        groups[key].append(s)
    deduped = [g[0] for g in groups.values()]
    cache = [c for c in (precompute(s, df_1m) for s in deduped) if c is not None]
    print(f"  raw paths: {len(raw)}  deduped: {len(deduped)}  cache: {len(cache)}")

    rows = []
    for ep in ENTRY_GRID:
        wins = losses = nf = no_entry = opens = skipped = 0
        pnl_r = 0.0; rr_sum = 0.0; n_with_rr = 0
        for s in cache:
            if s["direction"] == "LONG":
                entry = s["fvg_b"] + ep * (s["fvg_t"] - s["fvg_b"])
                sl = s["obh_b"]
            else:
                entry = s["fvg_t"] - ep * (s["fvg_t"] - s["fvg_b"])
                sl = s["obh_t"]
            tp = s["tp_const"]
            if s["direction"] == "LONG":
                if sl >= entry or tp <= entry: skipped += 1; continue
                risk = entry - sl
                rr = (tp - entry) / risk
            else:
                if sl <= entry or tp >= entry: skipped += 1; continue
                risk = sl - entry
                rr = (entry - tp) / risk
            outcome = simulate_no_entry(s, entry, sl, tp)
            if outcome == "win":
                wins += 1; pnl_r += rr; rr_sum += rr; n_with_rr += 1
            elif outcome == "loss":
                losses += 1; pnl_r -= 1.0; rr_sum += rr; n_with_rr += 1
            elif outcome == "no_entry": no_entry += 1
            elif outcome == "open": opens += 1
            else: nf += 1
        closed = wins + losses
        rows.append({
            "entry_pct": round(ep, 2),
            "wins": wins, "losses": losses, "no_entry": no_entry,
            "closed": closed,
            "wr": round(wins / closed * 100, 1) if closed else 0,
            "pnl_r": round(pnl_r, 2),
            "r_per_trade": round(pnl_r / closed, 3) if closed else 0,
            "avg_rr": round(rr_sum / n_with_rr, 3) if n_with_rr else 0,
        })

    df = pd.DataFrame(rows)
    print()
    print("=" * 100)
    print("Полная сетка (sorted by entry_pct):")
    print("=" * 100)
    print(df.to_string(index=False))

    print()
    print("=" * 100)
    print("Sorted by PnL:")
    print("=" * 100)
    df_sorted = df.sort_values("pnl_r", ascending=False)
    print(df_sorted.to_string(index=False))

    best = df_sorted.iloc[0]
    print()
    print(f"  >>> Best entry_pct = {best['entry_pct']}")
    print(f"      W={best['wins']} L={best['losses']} no_entry={best['no_entry']} closed={best['closed']}")
    print(f"      WR={best['wr']}% PnL={best['pnl_r']}R R/trade={best['r_per_trade']} avg_RR={best['avg_rr']}")

    out = Path("signals/optimize_1_1_3_v1_stage1.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    print(f"\n  saved: {out}")


if __name__ == "__main__":
    main()
