"""Deep analysis of HMA v3 production strategy.

Selected config: hit_RR_17, lgb, N=1100 (WR=70.5%, Σ R=+995R, goal_met=True)

Breakdown:
  - Per direction / asset / regime / n_FVG / t_id
  - Cumulative R timeline
  - Monthly distribution
  - Best / worst periods
"""
from __future__ import annotations
import pathlib
from datetime import datetime, timezone, timedelta

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd


# Paths
OUT_PC1 = pathlib.Path("/Users/vadim/Desktop/output PC1 hma")
FEATURES_PATH = pathlib.Path("/Users/vadim/smc-lib/projects/ob-vc/ml_v3/features_v3_hma.parquet")
OUT = pathlib.Path("/Users/vadim/Desktop/output PC1 hma")

# Production strategy parameters
TARGET = "hit_RR_17"
MODEL = "lgb"
RR_MULTIPLIER = 1.7
N_GOAL = 1100


def main():
    print("=" * 72)
    print(f"Deep analysis: {TARGET} {MODEL} N={N_GOAL} (production strategy)")
    print("=" * 72)

    # Load OOS predictions
    oos = pd.read_parquet(OUT_PC1 / "oos_predictions.parquet")
    print(f"\nOOS predictions total: {len(oos):,}")
    print(f"Columns: {list(oos.columns)}")

    # Filter to our target × model
    sub = oos[(oos.target == TARGET) & (oos.model == MODEL)].copy()
    print(f"Filtered to {TARGET} × {MODEL}: {len(sub):,} predictions")

    # Aggregate per event (multiple seeds → mean proba)
    sub = sub.groupby("event_idx").agg(
        proba=("proba", "mean"),
        y_true=("y_true", "first")
    ).reset_index()
    print(f"After aggregating across seeds: {len(sub):,} unique events")

    # Sort by proba descending and take top N
    sub_sorted = sub.sort_values("proba", ascending=False).reset_index(drop=True)
    selected = sub_sorted.head(N_GOAL).copy()
    threshold = float(selected.proba.iloc[-1])
    print(f"\nSelected top {len(selected)} events:")
    print(f"  threshold (min proba in selection): {threshold:.4f}")
    print(f"  WR: {selected.y_true.mean()*100:.1f}%")
    print(f"  wins: {selected.y_true.sum():.0f}  losses: {(1-selected.y_true).sum():.0f}")

    # Compute R per trade: win=+RR_multiplier, loss=-1
    selected["R"] = selected.y_true * RR_MULTIPLIER - (1 - selected.y_true) * 1.0
    print(f"  Σ R: {selected.R.sum():.1f}")
    print(f"  E[R] per trade: {selected.R.mean():.3f}")

    # Join with event metadata
    feats = pd.read_parquet(FEATURES_PATH)
    feats = feats[feats.fill_touched & feats.r_pct_pass].reset_index(drop=True)
    feats["row_idx"] = feats.index
    print(f"\nFeatures dataset (viable subset): {len(feats):,} events")

    # Merge: selected.event_idx maps to row index in df (after filter applied)
    merged = selected.merge(feats[["row_idx", "asset", "direction", "t_id", "n_comp",
                                     "born_ms", "entry", "r_pct"]],
                              left_on="event_idx", right_on="row_idx", how="left")
    print(f"Merged: {len(merged):,} events with metadata")

    # Add regime label
    REGIME_CUT_MS = int(datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    merged["regime"] = np.where(merged.born_ms < REGIME_CUT_MS, "pre_2023", "post_2023")
    merged["born_dt"] = pd.to_datetime(merged.born_ms, unit="ms", utc=True)

    # ─── BREAKDOWN by direction ────────
    print("\n" + "=" * 72)
    print("By DIRECTION")
    print("=" * 72)
    g = merged.groupby("direction").agg(
        n=("R", "count"),
        wins=("y_true", "sum"),
        wr=("y_true", "mean"),
        sum_r=("R", "sum"),
        e_r=("R", "mean"),
    ).round(3)
    g["wr_pct"] = (g.wr * 100).round(1)
    print(g[["n", "wins", "wr_pct", "e_r", "sum_r"]].to_string())

    # ─── BREAKDOWN by asset ────────
    print("\n" + "=" * 72)
    print("By ASSET")
    print("=" * 72)
    g = merged.groupby("asset").agg(
        n=("R", "count"),
        wins=("y_true", "sum"),
        wr=("y_true", "mean"),
        sum_r=("R", "sum"),
        e_r=("R", "mean"),
    ).round(3)
    g["wr_pct"] = (g.wr * 100).round(1)
    print(g[["n", "wins", "wr_pct", "e_r", "sum_r"]].to_string())

    # ─── BREAKDOWN by regime ────────
    print("\n" + "=" * 72)
    print("By REGIME")
    print("=" * 72)
    g = merged.groupby("regime").agg(
        n=("R", "count"),
        wins=("y_true", "sum"),
        wr=("y_true", "mean"),
        sum_r=("R", "sum"),
        e_r=("R", "mean"),
    ).round(3)
    g["wr_pct"] = (g.wr * 100).round(1)
    print(g[["n", "wins", "wr_pct", "e_r", "sum_r"]].to_string())

    # ─── BREAKDOWN by direction × asset ────────
    print("\n" + "=" * 72)
    print("By DIRECTION × ASSET")
    print("=" * 72)
    g = merged.groupby(["asset", "direction"]).agg(
        n=("R", "count"),
        wins=("y_true", "sum"),
        wr=("y_true", "mean"),
        sum_r=("R", "sum"),
        e_r=("R", "mean"),
    ).round(3)
    g["wr_pct"] = (g.wr * 100).round(1)
    print(g[["n", "wins", "wr_pct", "e_r", "sum_r"]].to_string())

    # ─── BREAKDOWN by n_FVG ────────
    print("\n" + "=" * 72)
    print("By n_FVG (1 vs >=2)")
    print("=" * 72)
    merged["n_FVG_class"] = np.where(merged.n_comp >= 2, ">=2", "=1")
    g = merged.groupby("n_FVG_class").agg(
        n=("R", "count"),
        wins=("y_true", "sum"),
        wr=("y_true", "mean"),
        sum_r=("R", "sum"),
        e_r=("R", "mean"),
    ).round(3)
    g["wr_pct"] = (g.wr * 100).round(1)
    print(g[["n", "wins", "wr_pct", "e_r", "sum_r"]].to_string())

    # ─── BREAKDOWN by t_id ────────
    print("\n" + "=" * 72)
    print("By T-TYPE (top 15 by Σ R)")
    print("=" * 72)
    g = merged.groupby("t_id").agg(
        n=("R", "count"),
        wins=("y_true", "sum"),
        wr=("y_true", "mean"),
        sum_r=("R", "sum"),
        e_r=("R", "mean"),
    ).round(3)
    g["wr_pct"] = (g.wr * 100).round(1)
    print(g.sort_values("sum_r", ascending=False).head(15)[["n", "wins", "wr_pct", "e_r", "sum_r"]].to_string())

    print("\n" + "=" * 72)
    print("By T-TYPE (bottom 5 by Σ R)")
    print("=" * 72)
    print(g.sort_values("sum_r", ascending=True).head(5)[["n", "wins", "wr_pct", "e_r", "sum_r"]].to_string())

    # ─── BREAKDOWN by YEAR ────────
    print("\n" + "=" * 72)
    print("By YEAR")
    print("=" * 72)
    merged["year"] = merged.born_dt.dt.year
    g = merged.groupby("year").agg(
        n=("R", "count"),
        wins=("y_true", "sum"),
        wr=("y_true", "mean"),
        sum_r=("R", "sum"),
        e_r=("R", "mean"),
    ).round(3)
    g["wr_pct"] = (g.wr * 100).round(1)
    print(g[["n", "wins", "wr_pct", "e_r", "sum_r"]].to_string())

    # ─── CUMULATIVE R timeline ───
    merged_sorted = merged.sort_values("born_dt").copy()
    merged_sorted["cum_R"] = merged_sorted.R.cumsum()
    merged_sorted["trade_num"] = np.arange(1, len(merged_sorted) + 1)

    # Drawdown analysis
    merged_sorted["cum_R_peak"] = merged_sorted.cum_R.cummax()
    merged_sorted["drawdown_R"] = merged_sorted.cum_R - merged_sorted.cum_R_peak
    max_dd = merged_sorted.drawdown_R.min()
    max_dd_idx = merged_sorted.drawdown_R.idxmin()
    max_dd_date = merged_sorted.loc[max_dd_idx, "born_dt"]

    # Consecutive losing streak
    win_seq = merged_sorted.y_true.to_numpy()
    max_loss_streak = 0
    cur_streak = 0
    for w in win_seq:
        if w == 0:
            cur_streak += 1
            max_loss_streak = max(max_loss_streak, cur_streak)
        else:
            cur_streak = 0

    # Win/loss streak stats
    max_win_streak = 0
    cur_streak = 0
    for w in win_seq:
        if w == 1:
            cur_streak += 1
            max_win_streak = max(max_win_streak, cur_streak)
        else:
            cur_streak = 0

    print("\n" + "=" * 72)
    print("RISK / DRAWDOWN")
    print("=" * 72)
    print(f"  Max drawdown: {max_dd:.1f}R  (at {max_dd_date:%Y-%m-%d})")
    print(f"  Max consecutive losses: {max_loss_streak}")
    print(f"  Max consecutive wins: {max_win_streak}")
    print(f"  Total wins: {win_seq.sum()}  losses: {len(win_seq) - win_seq.sum():.0f}")
    print(f"  R distribution: mean={merged_sorted.R.mean():.3f}, "
          f"std={merged_sorted.R.std():.3f}")

    # ─── Plots ───
    fig, axes = plt.subplots(3, 1, figsize=(16, 14))

    # Plot 1: Cumulative R
    ax = axes[0]
    ax.plot(merged_sorted.born_dt, merged_sorted.cum_R, color="#27ae60", lw=1.5)
    ax.fill_between(merged_sorted.born_dt, merged_sorted.cum_R_peak,
                     merged_sorted.cum_R, color="#c0392b", alpha=0.3, label="drawdown")
    ax.axhline(0, color="gray", ls="--", alpha=0.5)
    ax.set_ylabel("Cumulative R", fontsize=12)
    ax.set_title(f"Production strategy ({TARGET} @ N={N_GOAL}, WR={merged.y_true.mean()*100:.1f}%, "
                  f"Σ R = +{merged.R.sum():.0f}R, max_DD = {max_dd:.0f}R)",
                  fontsize=14, fontweight="bold")
    ax.grid(alpha=0.3)
    ax.legend(loc="upper left")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))

    # Plot 2: Monthly trades + WR
    monthly = merged.copy()
    monthly["ym"] = monthly.born_dt.dt.to_period("M").dt.to_timestamp()
    monthly_stats = monthly.groupby("ym").agg(
        n=("R", "count"),
        wins=("y_true", "sum"),
        sum_r=("R", "sum"),
    ).reset_index()
    monthly_stats["wr"] = monthly_stats.wins / monthly_stats.n

    ax = axes[1]
    ax.bar(monthly_stats.ym, monthly_stats.n, width=20, color="#3498db", alpha=0.65, label="trades/month")
    ax2 = ax.twinx()
    ax2.plot(monthly_stats.ym, monthly_stats.wr * 100, "o-", color="#c0392b",
              markersize=4, lw=1.5, label="WR %")
    ax2.axhline(70, color="#c0392b", ls=":", alpha=0.7)
    ax.set_ylabel("Trades / month", fontsize=12, color="#2980b9")
    ax2.set_ylabel("WR %", fontsize=12, color="#c0392b")
    ax.set_title("Monthly trade frequency + WR", fontsize=13)
    ax.grid(alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))

    # Plot 3: Σ R per month
    ax = axes[2]
    colors = ["#27ae60" if r > 0 else "#c0392b" for r in monthly_stats.sum_r]
    ax.bar(monthly_stats.ym, monthly_stats.sum_r, width=20, color=colors, alpha=0.75)
    ax.axhline(0, color="gray")
    ax.set_ylabel("Σ R per month", fontsize=12)
    ax.set_title("Monthly Σ R distribution", fontsize=13)
    ax.grid(alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))

    plt.tight_layout()
    out_png = OUT / "production_strategy_timeline.png"
    plt.savefig(out_png, dpi=110, bbox_inches="tight")
    print(f"\n[saved] {out_png}")

    # Save merged details for reference
    merged_sorted.to_csv(OUT / "production_strategy_trades.csv", index=False)
    print(f"[saved] {OUT / 'production_strategy_trades.csv'}")


if __name__ == "__main__":
    main()
