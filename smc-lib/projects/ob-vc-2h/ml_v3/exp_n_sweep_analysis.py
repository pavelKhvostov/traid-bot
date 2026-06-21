"""Experiment 1: N sweep — что если N не 1100, а меньше/больше?

Reuse OOS predictions от lean experiment, extend sweep range to 50-3000.
"""
from __future__ import annotations
import pathlib

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


LEAN_OOS = pathlib.Path("/Users/vadim/smc-lib/projects/ob-vc/ml_v3/lean_results/lean_oos_predictions.parquet")
OUT_PNG = pathlib.Path("/Users/vadim/smc-lib/projects/ob-vc/ml_v3/lean_results/n_sweep_curves.png")

RR_GRID = ["hit_RR_14", "hit_RR_15", "hit_RR_17", "hit_RR_20",
            "hit_RR_23", "hit_RR_25", "hit_RR_28"]
RR_MULTIPLIER = {"hit_RR_14": 1.4, "hit_RR_15": 1.5, "hit_RR_17": 1.7,
                  "hit_RR_20": 2.0, "hit_RR_23": 2.3, "hit_RR_25": 2.5,
                  "hit_RR_28": 2.8}


def main():
    oos = pd.read_parquet(LEAN_OOS)

    fig, axes = plt.subplots(2, 2, figsize=(18, 12))

    # ─── Plot 1: WR vs N для каждого RR ───
    ax = axes[0, 0]
    colors = plt.cm.viridis(np.linspace(0, 1, len(RR_GRID)))
    for target, c in zip(RR_GRID, colors):
        sub = oos[oos.target == target].copy()
        sub_aggr = sub.groupby("event_idx").agg(
            proba=("proba", "mean"), y_true=("y_true", "first")
        ).reset_index()
        sub_sorted = sub_aggr.sort_values("proba", ascending=False).reset_index(drop=True)
        Ns = list(range(50, len(sub_sorted) + 1, 50))
        wrs = []
        for N in Ns:
            top = sub_sorted.head(N)
            wrs.append(top.y_true.mean() * 100)
        ax.plot(Ns, wrs, color=c, lw=2, label=f"{target} (RR={RR_MULTIPLIER[target]})")
    ax.axhline(70, color="red", ls="--", alpha=0.5, label="Goal 70%")
    ax.axhline(75, color="orange", ls="--", alpha=0.5, label="Stretch 75%")
    ax.axhline(80, color="green", ls="--", alpha=0.5, label="Premium 80%")
    ax.set_xlabel("N (number of selected trades)", fontsize=12, fontweight="bold")
    ax.set_ylabel("WR %", fontsize=12, fontweight="bold")
    ax.set_title("WR vs N — все RR targets (lean model)", fontsize=13, fontweight="bold")
    ax.legend(loc="upper right", fontsize=9, framealpha=0.9)
    ax.grid(alpha=0.3)
    ax.set_xlim(0, 3000)
    ax.set_ylim(40, 95)

    # ─── Plot 2: Σ R vs N для каждого RR ───
    ax = axes[0, 1]
    for target, c in zip(RR_GRID, colors):
        rr = RR_MULTIPLIER[target]
        sub = oos[oos.target == target].copy()
        sub_aggr = sub.groupby("event_idx").agg(
            proba=("proba", "mean"), y_true=("y_true", "first")
        ).reset_index()
        sub_sorted = sub_aggr.sort_values("proba", ascending=False).reset_index(drop=True)
        Ns = list(range(50, len(sub_sorted) + 1, 50))
        sum_rs = []
        for N in Ns:
            top = sub_sorted.head(N)
            wins = top.y_true.sum()
            losses = N - wins
            sum_rs.append(wins * rr - losses * 1.0)
        ax.plot(Ns, sum_rs, color=c, lw=2, label=f"{target}")
    ax.set_xlabel("N (number of selected trades)", fontsize=12, fontweight="bold")
    ax.set_ylabel("Σ R cumulative", fontsize=12, fontweight="bold")
    ax.set_title("Σ R vs N — find max profit point", fontsize=13, fontweight="bold")
    ax.legend(loc="lower right", fontsize=9, framealpha=0.9)
    ax.grid(alpha=0.3)

    # ─── Plot 3: E[R] per trade vs N ───
    ax = axes[1, 0]
    for target, c in zip(RR_GRID, colors):
        rr = RR_MULTIPLIER[target]
        sub = oos[oos.target == target].copy()
        sub_aggr = sub.groupby("event_idx").agg(
            proba=("proba", "mean"), y_true=("y_true", "first")
        ).reset_index()
        sub_sorted = sub_aggr.sort_values("proba", ascending=False).reset_index(drop=True)
        Ns = list(range(50, len(sub_sorted) + 1, 50))
        ers = []
        for N in Ns:
            top = sub_sorted.head(N)
            wins = top.y_true.sum()
            losses = N - wins
            ers.append((wins * rr - losses * 1.0) / N)
        ax.plot(Ns, ers, color=c, lw=2, label=f"{target}")
    ax.axhline(0, color="black", ls="--", alpha=0.5)
    ax.set_xlabel("N (number of selected trades)", fontsize=12, fontweight="bold")
    ax.set_ylabel("E[R] per trade", fontsize=12, fontweight="bold")
    ax.set_title("E[R] per trade vs N (quality vs quantity tradeoff)",
                  fontsize=13, fontweight="bold")
    ax.legend(loc="upper right", fontsize=9, framealpha=0.9)
    ax.grid(alpha=0.3)

    # ─── Plot 4: WR ≥ 75% и ≥ 80% zones ───
    ax = axes[1, 1]
    summary_rows = []
    for target in RR_GRID:
        rr = RR_MULTIPLIER[target]
        sub = oos[oos.target == target].copy()
        sub_aggr = sub.groupby("event_idx").agg(
            proba=("proba", "mean"), y_true=("y_true", "first")
        ).reset_index()
        sub_sorted = sub_aggr.sort_values("proba", ascending=False).reset_index(drop=True)
        # Find max N where WR >= 70/75/80%
        n_70, n_75, n_80 = 0, 0, 0
        sum_r_70, sum_r_75, sum_r_80 = 0, 0, 0
        for N in range(50, len(sub_sorted) + 1, 25):
            top = sub_sorted.head(N)
            wins = top.y_true.sum()
            wr = wins / N
            losses = N - wins
            sr = wins * rr - losses * 1.0
            if wr >= 0.70:
                n_70 = N
                sum_r_70 = sr
            if wr >= 0.75:
                n_75 = N
                sum_r_75 = sr
            if wr >= 0.80:
                n_80 = N
                sum_r_80 = sr
        summary_rows.append({
            "target": target, "rr": rr,
            "n_70": n_70, "sum_r_70": sum_r_70,
            "n_75": n_75, "sum_r_75": sum_r_75,
            "n_80": n_80, "sum_r_80": sum_r_80,
        })

    summary_df = pd.DataFrame(summary_rows)
    print("\n── Max N at each WR threshold ──")
    print(summary_df.to_string(index=False))
    summary_df.to_csv(pathlib.Path(LEAN_OOS).parent / "n_sweep_thresholds.csv", index=False)

    x = np.arange(len(RR_GRID))
    width = 0.25
    ax.bar(x - width, summary_df.n_70, width, color="#27ae60", label="WR ≥ 70%")
    ax.bar(x,         summary_df.n_75, width, color="#f39c12", label="WR ≥ 75%")
    ax.bar(x + width, summary_df.n_80, width, color="#c0392b", label="WR ≥ 80%")
    ax.set_xticks(x)
    ax.set_xticklabels([t.replace("hit_", "") for t in RR_GRID])
    ax.set_xlabel("Target RR", fontsize=12, fontweight="bold")
    ax.set_ylabel("Max N achievable", fontsize=12, fontweight="bold")
    ax.set_title("Max N at WR thresholds (sweet spots)", fontsize=13, fontweight="bold")
    ax.legend(fontsize=10)
    ax.grid(axis="y", alpha=0.3)

    for i, row in summary_df.iterrows():
        for j, (n, col) in enumerate([(row.n_70, -width), (row.n_75, 0), (row.n_80, width)]):
            if n > 0:
                ax.text(i + col, n + 30, str(n), ha="center", va="bottom",
                         fontsize=9, fontweight="bold")

    fig.suptitle("N Sweep Analysis (lean v3.1, 22 features) — Quality vs Quantity tradeoffs",
                  fontsize=16, fontweight="bold", y=0.995)

    plt.tight_layout()
    plt.savefig(OUT_PNG, dpi=110, bbox_inches="tight")
    print(f"\n[saved] {OUT_PNG}")


if __name__ == "__main__":
    main()
