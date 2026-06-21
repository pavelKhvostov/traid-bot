"""Deep analysis of HMA v3.3 production strategy.

v3.3 canon (accepted 2026-06-09):
  hit_RR_20, lgb, N=1100 (proba >= 0.6088), WR 72.4%, Σ R +1288R, RR=2.0
"""
from __future__ import annotations
import pathlib
from datetime import datetime, timezone

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd


OUT_PC1 = pathlib.Path("/Users/vadim/Desktop/output4")
FEATURES_PATH = pathlib.Path("/Users/vadim/smc-lib/projects/ob-vc/ml_v3/features_v33_picked.parquet")
OUT = pathlib.Path("/Users/vadim/Desktop/output4")

TARGET = "hit_RR_20"
MODEL = "lgb"
RR_MULTIPLIER = 2.0
N_GOAL = 1100


def main():
    print("=" * 72)
    print(f"v3.3 deep analysis: {TARGET} {MODEL} N={N_GOAL} (production canon)")
    print("=" * 72)

    oos = pd.read_parquet(OUT_PC1 / "oos_predictions.parquet")
    print(f"\nOOS predictions total: {len(oos):,}")

    sub = oos[(oos.target == TARGET) & (oos.model == MODEL)].copy()
    sub = sub.groupby("event_idx").agg(
        proba=("proba", "mean"), y_true=("y_true", "first")
    ).reset_index()
    print(f"Aggregated events: {len(sub):,}")

    sub_sorted = sub.sort_values("proba", ascending=False).reset_index(drop=True)
    selected = sub_sorted.head(N_GOAL).copy()
    threshold = float(selected.proba.iloc[-1])
    print(f"\nSelected top {len(selected)} events:")
    print(f"  threshold (min proba): {threshold:.4f}")
    print(f"  WR: {selected.y_true.mean()*100:.1f}%")

    selected["R"] = selected.y_true * RR_MULTIPLIER - (1 - selected.y_true) * 1.0
    print(f"  Σ R: {selected.R.sum():.1f}")
    print(f"  E[R] per trade: {selected.R.mean():.3f}")

    feats = pd.read_parquet(FEATURES_PATH)
    feats = feats[feats.fill_touched & feats.r_pct_pass].reset_index(drop=True)
    feats["row_idx"] = feats.index
    print(f"\nFeatures viable: {len(feats):,}")

    merged = selected.merge(
        feats[["row_idx", "asset", "direction", "t_id", "n_comp",
                "born_ms", "entry", "r_pct"]],
        left_on="event_idx", right_on="row_idx", how="left")
    print(f"Merged with metadata: {len(merged):,}")

    REGIME_CUT_MS = int(datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    merged["regime"] = np.where(merged.born_ms < REGIME_CUT_MS, "pre_2023", "post_2023")
    merged["born_dt"] = pd.to_datetime(merged.born_ms, unit="ms", utc=True)
    merged["n_FVG_class"] = np.where(merged.n_comp >= 2, ">=2", "=1")
    merged["year"] = merged.born_dt.dt.year

    for label, group_col in [("DIRECTION", "direction"),
                              ("ASSET", "asset"),
                              ("REGIME", "regime"),
                              ("n_FVG", "n_FVG_class"),
                              ("YEAR", "year")]:
        print(f"\n— By {label} —")
        g = merged.groupby(group_col).agg(
            n=("R", "count"), wins=("y_true", "sum"),
            wr=("y_true", "mean"), sum_r=("R", "sum"), e_r=("R", "mean"),
        ).round(3)
        g["wr_pct"] = (g.wr * 100).round(1)
        print(g[["n", "wins", "wr_pct", "e_r", "sum_r"]].to_string())

    print("\n— By T-TYPE —")
    g = merged.groupby("t_id").agg(
        n=("R", "count"), wins=("y_true", "sum"),
        wr=("y_true", "mean"), sum_r=("R", "sum"), e_r=("R", "mean"),
    ).round(3)
    g["wr_pct"] = (g.wr * 100).round(1)
    print(g.sort_values("sum_r", ascending=False)[["n", "wins", "wr_pct", "e_r", "sum_r"]].to_string())

    merged_sorted = merged.sort_values("born_dt").copy()
    merged_sorted["cum_R"] = merged_sorted.R.cumsum()
    merged_sorted["trade_num"] = np.arange(1, len(merged_sorted) + 1)
    merged_sorted["cum_R_peak"] = merged_sorted.cum_R.cummax()
    merged_sorted["drawdown_R"] = merged_sorted.cum_R - merged_sorted.cum_R_peak
    max_dd = merged_sorted.drawdown_R.min()
    max_dd_idx = merged_sorted.drawdown_R.idxmin()
    max_dd_date = merged_sorted.loc[max_dd_idx, "born_dt"]

    win_seq = merged_sorted.y_true.to_numpy()
    max_loss_streak = max_win_streak = 0
    cur_l = cur_w = 0
    for w in win_seq:
        if w == 1:
            cur_w += 1; cur_l = 0
            max_win_streak = max(max_win_streak, cur_w)
        else:
            cur_l += 1; cur_w = 0
            max_loss_streak = max(max_loss_streak, cur_l)

    print(f"\nMax drawdown: {max_dd:.1f}R at {max_dd_date:%Y-%m-%d}")
    print(f"Max loss streak: {max_loss_streak}, max win streak: {max_win_streak}")

    merged_sorted.to_csv(OUT / "production_strategy_trades_v33.csv", index=False)
    print(f"\n[saved] {OUT / 'production_strategy_trades_v33.csv'}")


if __name__ == "__main__":
    main()
