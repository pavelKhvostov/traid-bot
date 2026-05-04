"""Stage 2 на 1.1.3 v1 ALL с РАСШИРЕННЫМ диапазоном entry.

Новый диапазон entry (включает gap между OB-htf и FVG):
  LONG:  entry = ob_htf.top + ep × (fvg.top - ob_htf.top)
         ep=0  → ob_htf.top (самый deep, на верхнем крае OB-htf)
         ep=1  → fvg.top (самый shallow)
  SHORT: entry = ob_htf.bottom - ep × (ob_htf.bottom - fvg.bottom)
         ep=0  → ob_htf.bottom (deep)
         ep=1  → fvg.bottom (shallow)

SL варьируется ВНУТРИ OB-htf зоны (sl_pct ∈ [0..1] step 0.05):
  LONG:  sl = ob_htf.bottom + sp × (ob_htf.top - ob_htf.bottom)
  SHORT: sl = ob_htf.top    - sp × (ob_htf.top - ob_htf.bottom)

TP = TP_const (default config: entry=mid FVG, SL=ob_htf far edge, RR=1)
no_entry: ON, untouched: ON, ALL group.

Сравнение для ep ∈ {0.0, 0.25, 0.5, 0.75, 1.0}.
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
EP_LIST = [0.00, 0.25, 0.50, 0.75, 1.00]
SL_GRID = np.arange(0.0, 1.01, 0.05)


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


def stage2_grid_extended(cache, ep_fixed):
    rows = []
    for sp in SL_GRID:
        wins = losses = nf = no_entry = opens = skipped = 0
        pnl_r = 0.0; rr_sum = 0.0; n_with_rr = 0
        for s in cache:
            if s["direction"] == "LONG":
                # extended entry: from ob_htf.top (deep) to fvg.top (shallow)
                entry = s["obh_t"] + ep_fixed * (s["fvg_t"] - s["obh_t"])
                sl_lo = s["obh_b"]; sl_hi = s["obh_t"]
                sl = sl_lo + sp * (sl_hi - sl_lo)
            else:
                # extended entry: from ob_htf.bottom (deep) to fvg.bottom (shallow)
                entry = s["obh_b"] - ep_fixed * (s["obh_b"] - s["fvg_b"])
                sl_hi = s["obh_t"]; sl_lo = s["obh_b"]
                sl = sl_hi - sp * (sl_hi - sl_lo)
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
            "ep": ep_fixed,
            "sl_pct": round(sp, 2),
            "wins": wins, "losses": losses, "no_entry": no_entry,
            "skipped": skipped,
            "closed": closed,
            "wr": round(wins / closed * 100, 1) if closed else 0,
            "pnl_r": round(pnl_r, 2),
            "r_per_trade": round(pnl_r / closed, 3) if closed else 0,
            "avg_rr": round(rr_sum / n_with_rr, 3) if n_with_rr else 0,
        })
    return pd.DataFrame(rows)


def main():
    print(f"[INFO] Stage 2 1.1.3 v1, EXTENDED entry range [ob_htf far .. fvg far], ep in {EP_LIST}")
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
    print(f"  cache: {len(cache)}\n")

    grids = []
    for ep in EP_LIST:
        df = stage2_grid_extended(cache, ep)
        grids.append(df)
        print("=" * 100)
        print(f"ep={ep:.2f} (extended range)")
        print("=" * 100)
        df_sorted = df.sort_values("pnl_r", ascending=False)
        print(df_sorted.drop(columns=["ep"]).head(10).to_string(index=False))
        best = df_sorted.iloc[0]
        baseline = df[df["sl_pct"] == 0.0].iloc[0]
        print(f"\n  >>> Best sl_pct={best['sl_pct']}  WR={best['wr']}%  PnL={best['pnl_r']}R  "
              f"R/trade={best['r_per_trade']}  avg_RR={best['avg_rr']}")
        print(f"  Baseline (sl=0): WR={baseline['wr']}%  PnL={baseline['pnl_r']}R  "
              f"R/trade={baseline['r_per_trade']}")

        # WR>=50% top-5 для каждого ep
        sub_wr50 = df[df["wr"] >= 50].sort_values("pnl_r", ascending=False).head(5)
        if len(sub_wr50):
            print(f"  WR>=50% top-5:")
            print("  " + sub_wr50.drop(columns=["ep"]).to_string(index=False).replace("\n", "\n  "))
        else:
            print(f"  WR>=50% — нет конфигов")
        print()

    # Best per ep summary
    print("=" * 100)
    print("Best Stage 2 для каждого ep (extended):")
    print("=" * 100)
    summary = []
    for df in grids:
        best = df.sort_values("pnl_r", ascending=False).iloc[0]
        summary.append({
            "ep": best["ep"], "best_sl": best["sl_pct"],
            "wins": best["wins"], "losses": best["losses"], "no_entry": best["no_entry"],
            "closed": best["closed"], "wr": best["wr"],
            "pnl_r": best["pnl_r"], "r_per_trade": best["r_per_trade"],
            "avg_rr": best["avg_rr"],
        })
    print(pd.DataFrame(summary).to_string(index=False))

    out = Path("signals/optimize_1_1_3_v1_stage2_extended_entry.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.concat(grids).to_csv(out, index=False)
    print(f"\n  saved: {out}")


if __name__ == "__main__":
    main()
