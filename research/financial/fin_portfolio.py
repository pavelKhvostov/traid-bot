"""Decorrelated-basket portfolio aggregation from per-strategy monthly_series.

Takes the monthly_series (at each strategy's best_rr_sharpe) reported by the
fin_<key>.py per-strategy runs and combines selected members EQUAL-WEIGHTED
per calendar month (equal-risk sizing: each strategy contributes its monthly
R as-is; equal weight = each strategy gets the same risk budget per month).

Computes for the combined monthly series:
  monthly_mean_R, pct_pos_months, worst_month_R, sharpe_monthly (mean/std,
  population ddof=0), max_drawdown_R (running cumulative peak-to-trough).

monthly_pct_at_1pct_risk: convert mean monthly R -> % assuming 1% account
risk per 1R trade-unit. Equal-weight basket of N strategies, each sized so
that 1R = 1% of account => portfolio monthly % = monthly_mean_R * 1%.

This is a pure aggregation of REAL per-strategy stdout monthly_series (no
re-simulation); numbers below are real stdout from this script.
"""
from __future__ import annotations

import numpy as np

# --- per-strategy monthly_series at best_rr_sharpe (copied from the per-strategy
#     fin_<key>.py REAL stdout JSON) ---------------------------------------------

MS = {}

MS["111"] = {  # best_rr_sharpe = 1.5
    "2020-01": 1.5, "2020-02": -1, "2020-03": -1, "2020-04": -2, "2020-06": -0.5,
    "2020-07": -1, "2020-08": -2, "2020-09": -0.5, "2020-10": 0, "2020-11": 1.5,
    "2020-12": -1, "2021-01": 5, "2021-02": 1, "2021-03": 6.5, "2021-04": 8,
    "2021-05": 1, "2021-06": -3, "2021-07": 1, "2021-08": 11.5, "2021-09": -0.5,
    "2021-10": -2, "2021-11": 1.5, "2021-12": 4.5, "2022-01": 2, "2022-02": -4,
    "2022-03": 3, "2022-04": 1.5, "2022-05": 1, "2022-06": -0.5, "2022-07": 1,
    "2022-08": 5, "2022-09": 8, "2022-10": 1.5, "2022-11": 1, "2022-12": 1.5,
    "2023-01": 0.5, "2023-02": -2, "2023-03": 4.5, "2023-04": -3.5, "2023-05": 1.5,
    "2023-06": -1, "2023-07": 5.5, "2023-08": 1.5, "2023-09": 3, "2023-10": 6,
    "2023-11": 5, "2023-12": 3.5, "2024-01": 0.5, "2024-02": 3, "2024-03": 0.5,
    "2024-04": -1, "2024-05": 2, "2024-06": 0.5, "2024-07": -1, "2024-08": 0,
    "2024-09": 1, "2024-10": 4, "2024-11": 0.5, "2024-12": 1, "2025-01": 0.5,
    "2025-02": 2, "2025-03": 2.5, "2025-04": 0.5, "2025-05": 0, "2025-06": 1.5,
    "2025-07": 2.5, "2025-08": 5.5, "2025-09": 0.5, "2025-10": 0.5, "2025-11": -0.5,
    "2025-12": 12, "2026-01": 3.5, "2026-02": 3.5, "2026-03": -2, "2026-04": 2,
    "2026-05": -0.5, "2026-06": 2,
}

MS["112"] = {  # best_rr_sharpe = 2.2
    "2023-06": -4.8, "2023-07": 9.6, "2023-08": 24, "2023-09": 3.8, "2023-10": 7.4,
    "2023-11": 10.8, "2023-12": 8.4, "2024-01": 5, "2024-02": 4.4, "2024-03": 1,
    "2024-04": -2, "2024-05": 5.2, "2024-06": 3.6, "2024-07": 11.4, "2024-08": 9.8,
    "2024-09": 5.6, "2024-10": 21.6, "2024-11": 18, "2024-12": 6.8, "2025-01": 13.2,
    "2025-02": 0.4, "2025-03": 3, "2025-04": 4.8, "2025-05": 3.4, "2025-06": 3.8,
    "2025-07": -4, "2025-08": 3, "2025-09": 13.2, "2025-10": -1, "2025-11": 8.6,
    "2025-12": 18.4, "2026-01": 14.4, "2026-02": 3.8, "2026-03": 4.4, "2026-04": 12.8,
    "2026-05": 1.8, "2026-06": -4,
}

MS["115"] = {  # best_rr_sharpe = 3.0
    "2020-02": 3, "2020-03": 9, "2020-04": -1, "2020-06": -3, "2020-07": -1,
    "2020-09": 3, "2020-10": -1, "2020-11": 8, "2020-12": 2, "2021-01": 1,
    "2021-02": 1, "2021-03": 1, "2021-04": -2, "2021-05": 0, "2021-06": 1,
    "2021-07": 0, "2021-08": 3, "2021-09": 0, "2021-10": -1, "2021-11": 2,
    "2021-12": 5, "2022-01": 4, "2022-03": 0, "2022-04": 5, "2022-05": 4,
    "2022-06": 0, "2022-07": -2, "2022-08": 5, "2022-09": 7, "2022-10": 0,
    "2022-11": 1, "2022-12": 3, "2023-01": 2, "2023-02": 8, "2023-03": 1,
    "2023-04": 5, "2023-05": 3, "2023-06": -3, "2023-07": 1, "2023-08": 0,
    "2023-09": 2, "2023-10": 4, "2023-11": -2, "2023-12": -5, "2024-01": 2,
    "2024-02": 0, "2024-03": 1, "2024-04": 0, "2024-05": 3, "2024-06": -2,
    "2024-07": 4, "2024-08": 7, "2024-09": -2, "2024-10": -4, "2024-11": 1,
    "2024-12": 5, "2025-01": -3, "2025-02": 4, "2025-03": 8, "2025-04": -2,
    "2025-05": 3, "2025-06": 9, "2025-07": 6, "2025-08": 5, "2025-09": 5,
    "2025-10": -1, "2025-11": 0, "2025-12": 3, "2026-01": -7, "2026-02": 3,
    "2026-03": 2, "2026-04": 4, "2026-05": -2, "2026-06": -2,
}

MS["A"] = {  # A i-RDRB+FVG, best_rr_sharpe = 1.0
    "2020-01": 4, "2020-02": 0, "2020-03": 3, "2020-04": -1, "2020-05": 8,
    "2020-06": 5, "2020-07": 6, "2020-08": 7, "2020-09": 7, "2020-10": 3,
    "2020-11": 4, "2020-12": 1, "2021-01": -5, "2021-02": -6, "2021-03": 0,
    "2021-04": 1, "2021-05": 0, "2021-06": 0, "2021-07": 0, "2021-08": 2,
    "2021-09": 5, "2021-10": -1, "2021-11": 10, "2021-12": 4, "2022-01": 2,
    "2022-02": 1, "2022-03": -1, "2022-04": 5, "2022-05": 5, "2022-06": 4,
    "2022-07": 7, "2022-08": 13, "2022-09": 10, "2022-10": 15, "2022-11": 4,
    "2022-12": 10, "2023-01": 11, "2023-02": 7, "2023-03": 4, "2023-04": -8,
    "2023-05": 5, "2023-06": 4, "2023-07": 0, "2023-08": 15, "2023-09": 1,
    "2023-10": 9, "2023-11": 7, "2023-12": 4, "2024-01": -3, "2024-02": -2,
    "2024-03": 10, "2024-04": -8, "2024-05": 1, "2024-06": 6, "2024-07": 0,
    "2024-08": 3, "2024-09": 0, "2024-10": 0, "2024-11": 9, "2024-12": -2,
    "2025-01": 1, "2025-02": 5, "2025-03": 0, "2025-04": 8, "2025-05": 1,
    "2025-06": 4, "2025-07": 13, "2025-08": -7, "2025-09": -2, "2025-10": 6,
    "2025-11": -5, "2025-12": 7, "2026-01": 8, "2026-02": 6, "2026-03": 5,
    "2026-04": -4, "2026-05": -2, "2026-06": -4,
}

MS["32"] = {  # 3.2, best_rr_sharpe = 2.5
    "2020-01": -2, "2020-02": -1, "2020-03": -2, "2020-04": -1, "2020-05": 3,
    "2020-06": 0, "2020-07": 3.5, "2020-08": 13.5, "2020-09": 0, "2020-10": 5.5,
    "2020-11": 10.5, "2020-12": -8, "2021-01": 2, "2021-02": -2, "2021-03": 5,
    "2021-04": -2.5, "2021-05": 7, "2021-06": 5.5, "2021-07": 5, "2021-08": -3,
    "2021-09": 0, "2021-10": 9, "2021-11": -7.5, "2021-12": -3.5, "2022-01": 5.5,
    "2022-02": -3, "2022-03": 2, "2022-04": 1, "2022-05": -1, "2022-06": 0.5,
    "2022-07": 7, "2022-08": -0.5, "2022-09": 0.5, "2022-10": -4.5, "2022-11": 5,
    "2022-12": -2.5, "2023-01": 1.5, "2023-02": 3.5, "2023-03": 4, "2023-04": -3,
    "2023-05": -7, "2023-06": 0, "2023-07": -4, "2023-08": 10, "2023-09": -1,
    "2023-10": -5, "2023-11": 9, "2023-12": 9, "2024-01": 7, "2024-02": 4,
    "2024-03": 15, "2024-04": 8, "2024-05": -2, "2024-06": 7, "2024-07": 19,
    "2024-08": -4.5, "2024-09": 10.5, "2024-10": 9, "2024-11": 3.5, "2024-12": -5,
    "2025-01": -0.5, "2025-02": -1, "2025-03": -7, "2025-04": 2, "2025-05": 8.5,
    "2025-06": 4, "2025-07": -12, "2025-08": -3.5, "2025-09": -3.5, "2025-10": 2,
    "2025-11": 3.5, "2025-12": -5, "2026-01": -1.5, "2026-02": 8.5, "2026-03": 6.5,
    "2026-04": -9.5, "2026-05": -2.5, "2026-06": 0.5,
}

# 1.1.4 included for an alternative basket comparison (best_rr_sharpe=1.0)
MS["114"] = {
    "2020-01": 1, "2020-02": 1, "2020-03": -1, "2020-04": 0, "2020-05": 5,
    "2020-06": 0, "2020-07": -2, "2020-08": 5, "2020-09": 1, "2020-10": 1,
    "2020-11": 2, "2020-12": -1, "2021-01": 0, "2021-02": 1, "2021-03": 2,
    "2021-04": 1, "2021-05": 7, "2021-06": 0, "2021-07": 7, "2021-08": 4,
    "2021-09": -5, "2021-10": 2, "2021-11": 4, "2021-12": 7, "2022-01": 2,
    "2022-02": 4, "2022-03": 1, "2022-04": 3, "2022-05": 3, "2022-06": -1,
    "2022-07": 1, "2022-08": 1, "2022-09": 0, "2022-10": 7, "2022-11": 3,
    "2022-12": 2, "2023-01": 0, "2023-02": -12, "2023-03": 3, "2023-04": 5,
    "2023-05": 8, "2023-06": 0, "2023-07": 5, "2023-08": 2, "2023-09": 3,
    "2023-10": 4, "2023-11": -4, "2023-12": 2, "2024-01": -1, "2024-02": -4,
    "2024-03": 7, "2024-04": 2, "2024-05": 3, "2024-06": 1, "2024-07": -4,
    "2024-08": -2, "2024-09": 2, "2024-10": 10, "2024-11": 0, "2024-12": -4,
    "2025-01": 6, "2025-02": 6, "2025-03": -3, "2025-04": 2, "2025-05": 1,
    "2025-06": 2, "2025-07": 6, "2025-08": -4, "2025-09": 7, "2025-10": 5,
    "2025-11": -1, "2025-12": 6, "2026-01": 3, "2026-02": 0, "2026-03": 0,
    "2026-04": 1, "2026-05": -1, "2026-06": -1,
}


def combine_equal_weight(members):
    """Equal-weight per-month sum across members; only months where >=1 member
    has a trade contribute. Each present member contributes its monthly R / k
    where k = number of members PRESENT that month (equal risk budget split)."""
    months = sorted(set().union(*[set(MS[m].keys()) for m in members]))
    combined = {}
    for mo in months:
        vals = [MS[m][mo] for m in members if mo in MS[m]]
        if not vals:
            continue
        # equal-risk: split the monthly risk budget equally among the strategies
        # that actually traded that month -> average of present members' R
        combined[mo] = float(np.mean(vals))
    return months, combined


def metrics(combined):
    months = sorted(combined.keys())
    arr = np.array([combined[m] for m in months], dtype=float)
    mean = float(np.mean(arr))
    std = float(np.std(arr))  # population
    sharpe = mean / std if std > 0 else 0.0
    pct_pos = 100.0 * float(np.mean(arr > 0))
    worst = float(np.min(arr))
    # max drawdown on running cumulative
    cum = np.cumsum(arr)
    peak = np.maximum.accumulate(cum)
    dd = cum - peak
    maxdd = float(np.min(dd))  # most negative
    total = float(np.sum(arr))
    return {
        "n_months": len(months),
        "monthly_mean_R": round(mean, 4),
        "monthly_std_R": round(std, 4),
        "sharpe_monthly": round(sharpe, 4),
        "pct_pos_months": round(pct_pos, 2),
        "worst_month_R": round(worst, 2),
        "max_drawdown_R": round(maxdd, 2),
        "total_R": round(total, 2),
        "first_month": months[0],
        "last_month": months[-1],
    }


def report(name, members):
    months, combined = combine_equal_weight(members)
    m = metrics(combined)
    print(f"\n=== Portfolio: {name} ===")
    print(f"members        = {members}")
    print(f"n_months       = {m['n_months']} ({m['first_month']} .. {m['last_month']})")
    print(f"monthly_mean_R = {m['monthly_mean_R']}")
    print(f"monthly_std_R  = {m['monthly_std_R']}")
    print(f"sharpe_monthly = {m['sharpe_monthly']}")
    print(f"pct_pos_months = {m['pct_pos_months']}%")
    print(f"worst_month_R  = {m['worst_month_R']}")
    print(f"max_drawdown_R = {m['max_drawdown_R']}")
    print(f"total_R        = {m['total_R']}")
    # 1% risk per 1R: monthly % = mean monthly R * 1%
    print(f"monthly_pct_at_1pct_risk = {round(m['monthly_mean_R']*1.0,2)}% mean "
          f"(worst month {round(m['worst_month_R']*1.0,2)}%)")
    return m


if __name__ == "__main__":
    # individual-strategy monthly stats (re-derived from their own monthly_series
    # at best_rr_sharpe) -- sanity that aggregation matches reported numbers
    print("### Per-strategy sanity (mean/sharpe from monthly_series) ###")
    for k in ["111", "112", "115", "A", "32", "114"]:
        arr = np.array(list(MS[k].values()), dtype=float)
        sh = float(np.mean(arr)) / float(np.std(arr)) if np.std(arr) > 0 else 0.0
        print(f"{k:4s}: n={len(arr):2d} mean={np.mean(arr):+.4f} "
              f"sharpe={sh:.4f} pos%={100*np.mean(arr>0):.1f} "
              f"worst={np.min(arr):+.1f} totalR={np.sum(arr):+.1f}")

    # DECORRELATED BASKET (most diverse, robust members):
    # A (i-RDRB+FVG, 1h, cross-asset) + 1.1.2 (OB-cascade) + 1.1.5 (fractal,
    # neg-corr to 1.1.1) + 3.2 (FVG failed-touch) -- 4 maximally different chains.
    report("DECORRELATED 4 [A + 1.1.2 + 1.1.5 + 3.2]", ["A", "112", "115", "32"])

    # 5-member adding an OB-cascade with full history depth (1.1.1) instead of /
    # in addition; per task suggestion "A + 1.1.2 + 1.1.5 + 3.2 + one OB-cascade"
    report("DECORRELATED 5 [A + 1.1.2 + 1.1.5 + 3.2 + 1.1.1]",
           ["A", "112", "115", "32", "111"])

    # alt: swap 1.1.2 issue (short history, starts 2023-06) -- show full-history 5
    report("FULL-HISTORY 5 [A + 1.1.1 + 1.1.5 + 3.2 + 1.1.4]",
           ["A", "111", "115", "32", "114"])
