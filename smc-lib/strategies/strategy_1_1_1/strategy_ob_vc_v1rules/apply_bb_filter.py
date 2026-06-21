"""Apply bb-model predictions as filter to backtest trades.

Test period only (1y, where bb_predictions.csv has predictions).
Match by (touch_ts proximity, tf, direction) — touch ~ signal_time in current backtest.

Bucket trades by P_break, compute cumulative filter table.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

SMC_LIB = Path.home() / "smc-lib"

trades = pd.read_csv(SMC_LIB / "projects" / "strategy_ob_vc_v1rules" / "trades.csv")
trades["signal_time"] = pd.to_datetime(trades["signal_time"], utc=True)

preds = pd.read_csv(SMC_LIB / "projects" / "bb_dataset" / "bb_predictions.csv")
preds["touch_ts"] = pd.to_datetime(preds["touch_ts"], utc=True)
preds["born_ts"] = pd.to_datetime(preds["born_ts"], utc=True)
preds["direction_up"] = preds["direction"].str.upper()

# Test period
test_start = preds["touch_ts"].min() - pd.Timedelta(days=1)
test_end = preds["touch_ts"].max() + pd.Timedelta(days=1)
tr = trades[(trades["signal_time"] >= test_start) & (trades["signal_time"] <= test_end)].copy()
print(f"test period: {test_start} -> {test_end}")
print(f"trades in test period: {len(tr)}")
print(f"bb predictions: {len(preds)}")

# Match by (tf, direction, born_ts ≤ signal_time within 4h tolerance)
parts = []
for tf in ("1h", "2h"):
    for dr in ("LONG", "SHORT"):
        sub_tr = tr[(tr["htf"] == tf) & (tr["direction"] == dr)].sort_values("signal_time")
        sub_p = preds[(preds["tf"] == tf) & (preds["direction_up"] == dr)].sort_values("born_ts")
        if sub_p.empty or sub_tr.empty:
            continue
        m = pd.merge_asof(
            sub_tr,
            sub_p[["born_ts", "P_break", "label"]].rename(columns={"label": "bb_label"}),
            left_on="signal_time", right_on="born_ts",
            direction="backward",
            tolerance=pd.Timedelta(hours=4),
        )
        parts.append(m)

tr_merged = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
matched = tr_merged["P_break"].notna().sum() if "P_break" in tr_merged.columns else 0
print(f"\nmatched: {matched}/{len(tr_merged)} trades got P_break")
tr = tr_merged

closed = tr[(tr["outcome"].isin(["win", "loss", "flat"])) & tr["P_break"].notna()].copy()
print(f"closed + matched: {len(closed)}")

if len(closed) == 0:
    print("nothing to analyze")
    raise SystemExit(0)

# Bucket
bins = [0.0, 0.05, 0.1, 0.2, 0.3, 0.5, 1.01]
labels = ["<0.05", "0.05-0.1", "0.1-0.2", "0.2-0.3", "0.3-0.5", "0.5+"]
closed["P_bucket"] = pd.cut(closed["P_break"], bins=bins, right=False, labels=labels)

print("\n" + "=" * 80)
print("Per-bucket trade outcomes (test period, closed trades)")
print("=" * 80)
rows = []
for bk, g in closed.groupby("P_bucket", observed=False):
    if len(g) == 0:
        continue
    wins = (g["R"] > 0).sum()
    n = len(g)
    rows.append({
        "P_break_bucket": bk,
        "n": n,
        "WR_pct": round(wins/n*100, 1),
        "total_R": round(g["R"].sum(), 1),
        "R_per_tr": round(g["R"].mean(), 3),
        "med_R": round(g["R"].median(), 2),
        "actual_break_pct": round(g["bb_label"].mean()*100, 1),
    })
print(pd.DataFrame(rows).to_string(index=False))

# Cumulative filter — DROP trades if P_break >= threshold
print("\n" + "=" * 80)
print("Cumulative filter: KEEP trades with P_break < X (drop predicted-breaks)")
print("=" * 80)
rows = []
for th in [1.01, 0.5, 0.4, 0.3, 0.2, 0.15, 0.1, 0.05]:
    kept = closed[closed["P_break"] < th]
    if len(kept) == 0:
        continue
    wins = (kept["R"] > 0).sum()
    n = len(kept)
    rows.append({
        "drop_if_P_break_GE": th,
        "n_kept": n,
        "kept_pct": round(n/len(closed)*100, 1),
        "WR_pct": round(wins/n*100, 1),
        "total_R": round(kept["R"].sum(), 1),
        "R_per_tr": round(kept["R"].mean(), 3),
        "trades_per_year": round(n, 0),
    })
print(pd.DataFrame(rows).to_string(index=False))

# Stats baseline (all closed in test period)
all_closed = tr[tr["outcome"].isin(["win", "loss", "flat"])]
n0 = len(all_closed)
wins0 = (all_closed["R"] > 0).sum()
print(f"\nBASELINE (no bb filter, all closed in test period):")
print(f"  n={n0}, WR={wins0/n0*100:.1f}%, total_R={all_closed['R'].sum():+.1f}, R/tr={all_closed['R'].mean():+.3f}")
