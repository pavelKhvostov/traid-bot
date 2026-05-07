"""Partition 1 of unconventional hypotheses: N1, N2, N3, N4, N5, N7."""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    if _ROOT.parent == _ROOT:
        raise RuntimeError("repo root not found")
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

from pathlib import Path

import numpy as np
import pandas as pd

INPUT_CSV = Path("signals/strategy_3_2_3y_RR1_unconventional.csv")
RR = 1.0


def stats(closed: pd.DataFrame, label: str, total: int) -> str:
    n = len(closed)
    if n == 0:
        return f"  {label:<55s}  n=0"
    w = int((closed["outcome"] == "win").sum())
    l = n - w
    wr = w / n * 100
    pnl = w * RR - l
    rt = pnl / n
    share = n / total * 100 if total else 0
    return (f"  {label:<55s}  n={n:<3d} ({share:5.1f}%)  W={w:<3d} L={l:<3d}  "
            f"WR={wr:5.1f}%  PnL={pnl:+5.1f}R  R/tr={rt:+.3f}")


def main():
    df = pd.read_csv(INPUT_CSV)
    closed = df[df["outcome"].isin(["win", "loss"])].copy()
    total = len(closed)
    print(f"BASELINE  closed={total}  WR={(closed['outcome']=='win').mean()*100:.1f}%")
    print()

    # ---------- N1 cluster ----------
    print("=" * 100)
    print("N1 — CLUSTER vs LONE signals")
    print("=" * 100)
    lone = closed["signals_in_prev_24h"] == 0
    cluster_low = (closed["signals_in_prev_24h"] >= 1) & (closed["signals_in_prev_24h"] <= 2)
    cluster_high = closed["signals_in_prev_24h"] >= 3
    print(stats(closed[lone], "Lone (0 prev-24h signals)", total))
    print(stats(closed[cluster_low], "Cluster low (1-2 prev)", total))
    print(stats(closed[cluster_high], "Cluster high (3+ prev)", total))

    # hours_since_last_signal
    print()
    print("hours_since_last_signal сегменты:")
    fast = closed["hours_since_last_signal"] < 6
    medium = (closed["hours_since_last_signal"] >= 6) & (closed["hours_since_last_signal"] < 24)
    slow = closed["hours_since_last_signal"] >= 24
    print(stats(closed[fast], "<6h since last (very fast)", total))
    print(stats(closed[medium], "6-24h since last", total))
    print(stats(closed[slow], ">=24h since last (cooled)", total))

    # ---------- N2 session ----------
    print()
    print("=" * 100)
    print("N2 — TIME / SESSION analysis")
    print("=" * 100)
    for sess in ["asia", "europe", "us", "late_us"]:
        m = closed["session"] == sess
        print(stats(closed[m], f"Session: {sess}", total))
    print()
    print("По дню недели:")
    for day in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]:
        m = closed["weekday"] == day
        if m.any():
            print(stats(closed[m], f"  {day}", total))

    # ---------- N3 FVG age/size ----------
    print()
    print("=" * 100)
    print("N3 — FVG age & size")
    print("=" * 100)
    age = closed["fvg_4h_age_hours"]
    fresh = age < 24
    medium_age = (age >= 24) & (age < 168)
    old = age >= 168  # >7d
    print(stats(closed[fresh], "Fresh FVG-4h (<24h)", total))
    print(stats(closed[medium_age], "Medium age (24-168h)", total))
    print(stats(closed[old], "Old FVG-4h (>=168h, >7d)", total))

    print()
    size = closed["fvg_4h_size_pct"]
    quartiles = size.quantile([0.25, 0.5, 0.75])
    print(f"FVG-4h size quartiles: q25={quartiles[0.25]:.3f}% q50={quartiles[0.5]:.3f}% q75={quartiles[0.75]:.3f}%")
    small = size < quartiles[0.25]
    medium_s = (size >= quartiles[0.25]) & (size < quartiles[0.75])
    large = size >= quartiles[0.75]
    print(stats(closed[small], "Small FVG-4h (Q1)", total))
    print(stats(closed[medium_s], "Medium FVG-4h (Q2-Q3)", total))
    print(stats(closed[large], "Large FVG-4h (Q4)", total))

    # Combo: fresh AND small
    print()
    print(stats(closed[fresh & small], "Fresh + Small (target H3)", total))
    print(stats(closed[old & large], "Old + Large", total))

    # ---------- N4 agreement entropy ----------
    print()
    print("=" * 100)
    print("N4 — AGREEMENT SCORE (8 flags ASVK+MH)")
    print("=" * 100)
    # agreement_score range [-1, +1]
    bins = [-1.01, -0.25, -0.05, 0.05, 0.25, 1.01]
    labels = ["strong opposed", "mild opposed", "neutral", "mild aligned", "strong aligned"]
    closed["agree_bin"] = pd.cut(closed["agreement_score"], bins=bins, labels=labels)
    for lbl in labels:
        m = closed["agree_bin"] == lbl
        if m.any():
            print(stats(closed[m], f"agreement: {lbl}", total))
    print()
    # Чёткие пороги
    very_strong = closed["agreement_score"] >= 0.5
    weak = (closed["agreement_score"] > 0) & (closed["agreement_score"] < 0.25)
    opposed = closed["agreement_score"] < 0
    print(stats(closed[very_strong], ">=0.5 (>=4 net flags aligned)", total))
    print(stats(closed[weak], "0..0.25 (1-2 net flags)", total))
    print(stats(closed[opposed], "<0 (more opposed than aligned)", total))

    # ---------- N5 divergence age ----------
    print()
    print("=" * 100)
    print("N5 — DIVERGENCE AGE (часы от последней aligned div до signal)")
    print("=" * 100)
    age_d = closed["aligned_div_age_hours"]
    has_age = age_d.notna()
    fresh_d = has_age & (age_d <= 6)
    medium_d = has_age & (age_d > 6) & (age_d <= 30)
    old_d = has_age & (age_d > 30)
    print(stats(closed[fresh_d], "Fresh aligned div (<=6h)", total))
    print(stats(closed[medium_d], "Medium aligned div (6-30h)", total))
    print(stats(closed[old_d], "Old aligned div (>30h)", total))
    print(stats(closed[~has_age], "No aligned div ever", total))

    # ---------- N7 |MF| as confidence ----------
    print()
    print("=" * 100)
    print("N7 — |MF| AS CONFIDENCE (low |MF| = market undecided = better for fade)")
    print("=" * 100)
    abs_mf = closed["abs_mf_at_signal"]
    quartiles_mf = abs_mf.quantile([0.25, 0.5, 0.75])
    print(f"|MF| quartiles: q25={quartiles_mf[0.25]:.2f} q50={quartiles_mf[0.5]:.2f} q75={quartiles_mf[0.75]:.2f}")
    low_conf = abs_mf < quartiles_mf[0.25]
    mid_conf = (abs_mf >= quartiles_mf[0.25]) & (abs_mf < quartiles_mf[0.75])
    high_conf = abs_mf >= quartiles_mf[0.75]
    print(stats(closed[low_conf], "Low |MF| (Q1, market undecided)", total))
    print(stats(closed[mid_conf], "Mid |MF| (Q2-Q3)", total))
    print(stats(closed[high_conf], "High |MF| (Q4, market confident)", total))

    print()
    print("Direction split for High |MF|:")
    long_mask = closed["direction"] == "LONG"
    short_mask = closed["direction"] == "SHORT"
    print(stats(closed[high_conf & long_mask], "High |MF| LONG", total))
    print(stats(closed[high_conf & short_mask], "High |MF| SHORT", total))


if __name__ == "__main__":
    main()
