"""Lean v3.3 ML test — 22 ML-picked features (best L per TF from v3.2 permutation).

Tests if hand-picking optimal HMA length per TF gives:
- Higher AUC than v3.1 lean (all L=9)
- Lower PBO than v3.2 (132 features)
- Confirmation that ML-picked L=4/6/7/8/12 per TF is the actual canon
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

sys.path.insert(0, str(pathlib.Path("/Users/vadim/Desktop/compute-archives/compute-2026-06-09-ob-vc-hma-v3-pc1")))

from ml.splits import purged_walkforward_splits
from ml.sample_weights import compute_sample_weights
from sklearn.ensemble import HistGradientBoostingClassifier


def make_model(seed=42):
    return HistGradientBoostingClassifier(
        learning_rate=0.05, max_iter=300, max_leaf_nodes=31, max_depth=None,
        min_samples_leaf=40, l2_regularization=0.1, random_state=seed,
    )


SRC = pathlib.Path("/Users/vadim/smc-lib/projects/ob-vc/ml_v3/features_v32_neighborhood.parquet")
OUT = pathlib.Path("/Users/vadim/smc-lib/projects/ob-vc/ml_v3/lean_v33_results")
OUT.mkdir(exist_ok=True)

RR_GRID = ["hit_RR_14", "hit_RR_15", "hit_RR_17", "hit_RR_20",
            "hit_RR_23", "hit_RR_25", "hit_RR_28"]
RR_MULTIPLIER = {"hit_RR_14": 1.4, "hit_RR_15": 1.5, "hit_RR_17": 1.7,
                  "hit_RR_20": 2.0, "hit_RR_23": 2.3, "hit_RR_25": 2.5,
                  "hit_RR_28": 2.8}

# v3.2 permutation-picked best L per TF
PICKED_HMA = [
    "hma_15m_7_dist_pct",
    "hma_20m_6_dist_pct",
    "hma_1h_4_dist_pct",
    "hma_90m_8_dist_pct",
    "hma_2h_4_dist_pct",
    "hma_4h_4_dist_pct",
    "hma_6h_6_dist_pct",
    "hma_12h_8_dist_pct",
    "hma_1d_8_dist_pct",
    "hma_2d_8_dist_pct",
    "hma_3d_12_dist_pct",
]


def get_lean_features(df: pd.DataFrame) -> list[str]:
    feat = []
    for c in df.columns:
        if c.startswith("wait_") or c == "fill_delay_min":
            feat.append(c)
    for c in PICKED_HMA:
        if c in df.columns:
            feat.append(c)
        else:
            raise KeyError(f"Missing picked feature: {c}")
    return feat


def train_eval_one(df, train_idx, test_idx, target, feat_cols, seed):
    X_tr = df.loc[train_idx, feat_cols].to_numpy(dtype=np.float32)
    y_tr = df.loc[train_idx, target].to_numpy()
    X_te = df.loc[test_idx, feat_cols].to_numpy(dtype=np.float32)
    y_te = df.loc[test_idx, target].to_numpy()
    w_tr = df.loc[train_idx, "sample_weight"].to_numpy()

    model = make_model(seed=seed)
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
    print("Lean v3.3 ML test (22 ML-picked features: wait + HMA best-L per TF)")
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
    print("\n-- v3.3 AUC summary --")
    print(aggregate.to_string(index=False))
    aggregate.to_csv(OUT / "v33_cv_summary.csv", index=False)

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
    oos_avg.to_parquet(OUT / "v33_oos_predictions.parquet", index=False)

    print("\n-- Selection per RR target (N=800-2000) --")
    sel_rows = []
    for target in RR_GRID:
        rr = RR_MULTIPLIER[target]
        sub = oos_avg[oos_avg.target == target].copy()
        sub_aggr = sub.groupby("event_idx").agg(
            proba=("proba", "mean"), y_true=("y_true", "first")
        ).reset_index()
        sub_sorted = sub_aggr.sort_values("proba", ascending=False).reset_index(drop=True)
        for N in [500, 800, 1000, 1100, 1200, 1500, 2000]:
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
                "goal_met": (900 <= N <= 1200) and (wr >= 0.70)
            })
    sel_df = pd.DataFrame(sel_rows)
    print(sel_df.to_string(index=False))
    sel_df.to_csv(OUT / "v33_selection.csv", index=False)

    print("\n" + "=" * 72)
    print("COMPARISON: v3 (53 fts L=9 only) vs v3.1 lean (22 L=9) vs v3.2 (53 picked) vs v3.3 lean (22 picked)")
    print("=" * 72)

    v3_full = pd.read_parquet("/Users/vadim/Desktop/output PC1 hma/cv_summary.parquet")
    v3_full = v3_full[v3_full.model == "lgb"][["target", "auc_mean"]].rename(columns={"auc_mean": "v3_auc"})

    v32 = pd.read_parquet("/Users/vadim/Desktop/output 3/cv_summary.parquet")
    v32 = v32[v32.model == "lgb"][["target", "auc_mean"]].rename(columns={"auc_mean": "v32_auc"})

    try:
        v31 = pd.read_csv("/Users/vadim/smc-lib/projects/ob-vc/ml_v3/lean_results/lean_cv_summary.csv")[["target", "auc_mean"]].rename(columns={"auc_mean": "v31_auc"})
    except Exception:
        v31 = pd.DataFrame({"target": v3_full.target.tolist(), "v31_auc": [np.nan]*len(v3_full)})

    compare = aggregate.rename(columns={"auc_mean": "v33_auc"})[["target", "v33_auc"]]
    compare = compare.merge(v3_full, on="target").merge(v31, on="target", how="left").merge(v32, on="target")
    compare["delta_vs_v32"] = compare.v33_auc - compare.v32_auc
    compare["delta_vs_v31"] = compare.v33_auc - compare.v31_auc
    print(compare.to_string(index=False))
    compare.to_csv(OUT / "v33_vs_all_comparison.csv", index=False)

    print(f"\nTotal elapsed: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
