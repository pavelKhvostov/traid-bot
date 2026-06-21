"""Lean ML test — only 22 high-signal features (wait + HMA-9 dist_pct).

Compare against full v3 (601 features).
"""
from __future__ import annotations
import pathlib
import sys
import time
import warnings

import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from sklearn.metrics import roc_auc_score, brier_score_loss

warnings.filterwarnings("ignore")

# Reuse ML modules from v2 PC1 archive
sys.path.insert(0, str(pathlib.Path("/Users/vadim/Desktop/compute-archives/compute-2026-06-09-ob-vc-hma-v3-pc1")))

from ml.splits import purged_walkforward_splits
from ml.sample_weights import compute_sample_weights
# LightGBM требует libomp на Mac → используем sklearn HGB как заменитель
from sklearn.ensemble import HistGradientBoostingClassifier


def make_lightgbm(seed=42, n_jobs=4):
    """Mac substitute: HistGradientBoosting tuned to match LightGBM behavior."""
    return HistGradientBoostingClassifier(
        learning_rate=0.05,
        max_iter=300,
        max_leaf_nodes=31,
        max_depth=None,
        min_samples_leaf=40,
        l2_regularization=0.1,
        random_state=seed,
    )


SRC = pathlib.Path("/Users/vadim/smc-lib/projects/ob-vc/ml_v3/features_v3_hma.parquet")
OUT = pathlib.Path("/Users/vadim/smc-lib/projects/ob-vc/ml_v3/lean_results")
OUT.mkdir(exist_ok=True)


RR_GRID = ["hit_RR_14", "hit_RR_15", "hit_RR_17", "hit_RR_20",
            "hit_RR_23", "hit_RR_25", "hit_RR_28"]
RR_MULTIPLIER = {"hit_RR_14": 1.4, "hit_RR_15": 1.5, "hit_RR_17": 1.7,
                  "hit_RR_20": 2.0, "hit_RR_23": 2.3, "hit_RR_25": 2.5,
                  "hit_RR_28": 2.8}


def get_lean_features(df: pd.DataFrame) -> list[str]:
    """Select 22 lean features: wait_* + hma_{tf}_9_dist_pct."""
    feat = []
    # Wait window (11)
    for c in df.columns:
        if c.startswith("wait_") or c == "fill_delay_min":
            feat.append(c)
    # HMA-9 dist_pct on all TFs (11)
    for c in df.columns:
        if c.endswith("_9_dist_pct") and c.startswith("hma_"):
            feat.append(c)
    return feat


def train_eval_one(df, train_idx, test_idx, target, feat_cols, seed):
    X_tr = df.loc[train_idx, feat_cols].to_numpy(dtype=np.float32)
    y_tr = df.loc[train_idx, target].to_numpy()
    X_te = df.loc[test_idx, feat_cols].to_numpy(dtype=np.float32)
    y_te = df.loc[test_idx, target].to_numpy()
    w_tr = df.loc[train_idx, "sample_weight"].to_numpy()

    model = make_lightgbm(seed=seed, n_jobs=4)
    model.fit(X_tr, y_tr, sample_weight=w_tr)
    proba = model.predict_proba(X_te)[:, 1]

    auc = roc_auc_score(y_te, proba) if len(np.unique(y_te)) > 1 else float("nan")
    brier = brier_score_loss(y_te, proba)
    return {
        "target": target, "seed": seed, "auc": auc, "brier": brier,
        "n_test": len(test_idx),
        "proba": proba.tolist(), "y_true": y_te.tolist(),
        "event_idx": test_idx.tolist(),
    }


def main():
    t0 = time.time()
    print("=" * 72)
    print("Lean ML test (22 features: wait + HMA-9 dist_pct)")
    print("=" * 72)

    df = pd.read_parquet(SRC)
    df = df[df.fill_touched & df.r_pct_pass].reset_index(drop=True)
    print(f"\nViable events: {len(df):,}")

    feat_cols = get_lean_features(df)
    print(f"\nLean features ({len(feat_cols)}):")
    for f in feat_cols:
        print(f"  {f}")

    df["sample_weight"] = compute_sample_weights(df)
    folds = list(purged_walkforward_splits(df, n_splits=5))
    seeds = (42, 1337, 2024)
    print(f"\nRunning {len(RR_GRID) * len(seeds) * len(folds)} tasks...")

    tasks = []
    for target in RR_GRID:
        for seed in seeds:
            for fold_i, (tr, te) in enumerate(folds):
                tasks.append((target, seed, fold_i, tr, te))

    results = Parallel(n_jobs=4, backend="threading")(
        delayed(train_eval_one)(df, tr, te, target, feat_cols, seed)
        for target, seed, fold_i, tr, te in tasks
    )
    for r, (target, seed, fold_i, tr, te) in zip(results, tasks):
        r["fold"] = fold_i

    summary = pd.DataFrame([{k: r[k] for k in ["target", "seed", "fold", "auc", "brier", "n_test"]}
                             for r in results])
    aggregate = summary.groupby("target").agg(
        auc_mean=("auc", "mean"),
        auc_std=("auc", "std"),
        brier_mean=("brier", "mean"),
        n_runs=("auc", "count"),
    ).reset_index()
    print("\n── Lean AUC summary ──")
    print(aggregate.to_string(index=False))
    aggregate.to_csv(OUT / "lean_cv_summary.csv", index=False)

    # OOS predictions aggregated
    oos_records = []
    for r in results:
        target = r["target"]
        seed = r["seed"]
        fold = r["fold"]
        for proba, y_true, idx in zip(r["proba"], r["y_true"], r["event_idx"]):
            oos_records.append({"target": target, "seed": seed, "fold": fold,
                                  "event_idx": idx, "proba": proba, "y_true": y_true})
    oos_df = pd.DataFrame(oos_records)
    oos_avg = oos_df.groupby(["target", "event_idx", "fold"]).agg(
        proba=("proba", "mean"), y_true=("y_true", "first"),
    ).reset_index()
    oos_avg.to_parquet(OUT / "lean_oos_predictions.parquet", index=False)

    # Selection per target (N range 800-1200)
    print("\n── Selection per RR target (N range 800-1200) ──")
    sel_rows = []
    for target in RR_GRID:
        rr = RR_MULTIPLIER[target]
        sub = oos_avg[oos_avg.target == target].copy()
        sub_aggr = sub.groupby("event_idx").agg(
            proba=("proba", "mean"), y_true=("y_true", "first")
        ).reset_index()
        sub_sorted = sub_aggr.sort_values("proba", ascending=False).reset_index(drop=True)
        for N in [800, 900, 1000, 1100, 1200, 1500, 2000]:
            if N > len(sub_sorted):
                continue
            top = sub_sorted.head(N)
            wins = int(top.y_true.sum())
            losses = N - wins
            wr = wins / N
            sum_r = wins * rr - losses * 1.0
            sel_rows.append({
                "target": target, "rr": rr, "N": N,
                "wins": wins, "losses": losses, "wr": wr,
                "sum_r": sum_r, "e_r": sum_r / N,
                "goal_met": (900 <= N <= 1100) and (wr >= 0.70)
            })
    sel_df = pd.DataFrame(sel_rows)
    print(sel_df.to_string(index=False))
    sel_df.to_csv(OUT / "lean_selection.csv", index=False)

    # Compare vs v3 baseline
    print("\n" + "=" * 72)
    print("COMPARISON v3 vs v3.1-lean")
    print("=" * 72)
    v3 = pd.read_parquet("/Users/vadim/Desktop/output PC1 hma/cv_summary.parquet")
    v3_lgb = v3[v3.model == "lgb"].rename(columns={"auc_mean": "v3_auc"})[["target", "v3_auc"]]
    compare = aggregate.merge(v3_lgb, on="target")
    compare["delta_auc"] = compare.auc_mean - compare.v3_auc
    compare = compare.rename(columns={"auc_mean": "lean_auc"})
    print(compare[["target", "v3_auc", "lean_auc", "delta_auc"]].to_string(index=False))
    compare.to_csv(OUT / "lean_vs_v3_comparison.csv", index=False)

    print(f"\nTotal elapsed: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
