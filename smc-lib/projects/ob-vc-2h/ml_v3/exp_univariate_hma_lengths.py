"""Univariate AUC analysis — каждая HMA-L × TF фича отдельно.

Без ML. Просто ранжируем events по dist_pct и считаем AUC.
"""
from __future__ import annotations
import pathlib

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score


SRC = pathlib.Path("/Users/vadim/smc-lib/projects/ob-vc/ml_v3/features_hma_lengths_9_21.parquet")
OUT_DIR = pathlib.Path("/Users/vadim/smc-lib/projects/ob-vc/ml_v3/lean_results")
OUT_DIR.mkdir(exist_ok=True)

LENGTHS = list(range(9, 22))
TFS = ["15m", "20m", "1h", "90m", "2h", "4h", "6h", "12h", "1d", "2d", "3d"]
TARGET = "hit_RR_17"


def univariate_auc(values, y):
    """AUC of single feature vs binary target.
    Returns max(AUC, 1-AUC) so direction-agnostic."""
    mask = ~(np.isnan(values) | np.isnan(y))
    if mask.sum() < 50: return np.nan, 0
    v = values[mask]
    yt = y[mask].astype(int)
    if len(np.unique(yt)) < 2: return np.nan, 0
    auc = roc_auc_score(yt, v)
    return max(auc, 1 - auc), mask.sum()   # direction-agnostic


def top_decile_wr(values, y, n_top=1100):
    """WR at top-N events ranked by feature value (or 1-feature for inverse)."""
    mask = ~(np.isnan(values) | np.isnan(y))
    if mask.sum() < n_top: return np.nan, np.nan
    v = values[mask]
    yt = y[mask].astype(int)

    # Try both directions
    idx_pos = np.argsort(-v)[:n_top]
    wr_pos = yt[idx_pos].mean()
    idx_neg = np.argsort(v)[:n_top]
    wr_neg = yt[idx_neg].mean()
    if wr_pos >= wr_neg:
        return wr_pos, "high"
    return wr_neg, "low"


def main():
    df = pd.read_parquet(SRC)
    df = df[df.fill_touched & df.r_pct_pass].reset_index(drop=True)
    print(f"Viable events: {len(df):,}")

    y = df[TARGET].to_numpy(dtype=np.float64)
    print(f"Target: {TARGET}, base rate: {y.mean()*100:.1f}%")

    results = []
    for L in LENGTHS:
        for tf in TFS:
            col = f"hma_{tf}_{L}_dist_pct"
            if col not in df.columns: continue
            v = df[col].to_numpy(dtype=np.float64)
            auc, n = univariate_auc(v, y)
            wr_top, side = top_decile_wr(v, y, n_top=1100)
            results.append({
                "L": L, "tf": tf,
                "auc": auc, "n_valid": n,
                "wr_top1100": wr_top, "best_side": side,
            })

    rdf = pd.DataFrame(results)
    rdf.to_csv(OUT_DIR / "univariate_hma_lengths.csv", index=False)

    # Best per (L, TF)
    print("\n── Top-15 univariate AUC ──")
    print(rdf.sort_values("auc", ascending=False).head(15).to_string(index=False))

    print("\n── Top-15 univariate WR at N=1100 ──")
    print(rdf.sort_values("wr_top1100", ascending=False).head(15).to_string(index=False))

    # Aggregate by L (mean AUC over all TFs)
    print("\n── Mean AUC by HMA Length (across all TFs) ──")
    by_L = rdf.groupby("L").agg(
        mean_auc=("auc", "mean"),
        max_auc=("auc", "max"),
        mean_wr=("wr_top1100", "mean"),
        max_wr=("wr_top1100", "max"),
    ).round(4)
    print(by_L.to_string())

    print("\n── Mean AUC by TF (across all L) ──")
    by_tf = rdf.groupby("tf").agg(
        mean_auc=("auc", "mean"),
        max_auc=("auc", "max"),
        mean_wr=("wr_top1100", "mean"),
        max_wr=("wr_top1100", "max"),
    ).round(4)
    # Sort by TF natural order
    tf_order = {tf: i for i, tf in enumerate(TFS)}
    by_tf["order"] = by_tf.index.map(tf_order)
    by_tf = by_tf.sort_values("order").drop(columns="order")
    print(by_tf.to_string())

    # Heatmap visualization
    pivot_auc = rdf.pivot(index="L", columns="tf", values="auc")
    pivot_auc = pivot_auc[TFS]   # ordered columns
    pivot_wr = rdf.pivot(index="L", columns="tf", values="wr_top1100")
    pivot_wr = pivot_wr[TFS]

    fig, axes = plt.subplots(1, 2, figsize=(20, 8))

    im1 = axes[0].imshow(pivot_auc.values, cmap="RdYlGn", aspect="auto",
                          vmin=0.50, vmax=0.62)
    axes[0].set_xticks(range(len(TFS)))
    axes[0].set_xticklabels(TFS, fontsize=11)
    axes[0].set_yticks(range(len(LENGTHS)))
    axes[0].set_yticklabels(LENGTHS, fontsize=11)
    axes[0].set_xlabel("Timeframe", fontsize=12, fontweight="bold")
    axes[0].set_ylabel("HMA Length", fontsize=12, fontweight="bold")
    axes[0].set_title("Univariate AUC (heatmap)\nhit_RR_17, без ML, just feature ranking",
                       fontsize=13, fontweight="bold")
    # Annotate cells
    for i in range(len(LENGTHS)):
        for j in range(len(TFS)):
            v = pivot_auc.values[i, j]
            if not np.isnan(v):
                color = "white" if v > 0.58 or v < 0.52 else "black"
                axes[0].text(j, i, f"{v:.3f}", ha="center", va="center",
                              color=color, fontsize=9, fontweight="bold")
    plt.colorbar(im1, ax=axes[0])

    im2 = axes[1].imshow(pivot_wr.values * 100, cmap="RdYlGn", aspect="auto",
                          vmin=42, vmax=58)
    axes[1].set_xticks(range(len(TFS)))
    axes[1].set_xticklabels(TFS, fontsize=11)
    axes[1].set_yticks(range(len(LENGTHS)))
    axes[1].set_yticklabels(LENGTHS, fontsize=11)
    axes[1].set_xlabel("Timeframe", fontsize=12, fontweight="bold")
    axes[1].set_ylabel("HMA Length", fontsize=12, fontweight="bold")
    axes[1].set_title("WR at top-1100 (standalone, single feature)\nhit_RR_17",
                       fontsize=13, fontweight="bold")
    for i in range(len(LENGTHS)):
        for j in range(len(TFS)):
            v = pivot_wr.values[i, j] * 100
            if not np.isnan(v):
                color = "white" if v > 54 or v < 46 else "black"
                axes[1].text(j, i, f"{v:.1f}", ha="center", va="center",
                              color=color, fontsize=9, fontweight="bold")
    plt.colorbar(im2, ax=axes[1])

    fig.suptitle("Univariate analysis (без ML) — какая HMA-L × TF имеет signal?",
                  fontsize=15, fontweight="bold", y=0.995)
    plt.tight_layout()
    plt.savefig(OUT_DIR / "univariate_heatmap.png", dpi=110, bbox_inches="tight")
    print(f"\n[saved] {OUT_DIR / 'univariate_heatmap.png'}")

    # Cross-feature correlation between lengths on SAME TF
    print("\n── Cross-length correlation on SAME TF (selected examples) ──")
    for tf in ["4h", "6h", "1d"]:
        print(f"\n  {tf}:")
        cols = [f"hma_{tf}_{L}_dist_pct" for L in LENGTHS if f"hma_{tf}_{L}_dist_pct" in df.columns]
        corr = df[cols].corr()
        corr.columns = LENGTHS[:len(cols)]
        corr.index = LENGTHS[:len(cols)]
        print(corr.round(2).to_string())


if __name__ == "__main__":
    main()
