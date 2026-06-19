"""Phase 4 — Two-stage LightGBM ranker baseline + помошники.

Stage 1: Main goal ranker
  - Input: per-anchor 4h+ candidates + per-zone features + cross-TF
  - Label: is_main_goal (1 если эта zone была first-hit ground truth, иначе 0)
  - Output: softmax probability per candidate

Stage 2: Correction ranker (conditional на Stage 1 main_goal direction)
  - Input: same features + main_goal context
  - Label: is_correction (1 если эта zone была correction ground truth)

Помошники:
  - Time-decay sample weights (half_life=90d)
  - Purged K-Fold + embargo (Lopez canon)
  - Meta-labeling: secondary classifier для confidence calibration

TODO Phase 2: CPCV (15 paths), MDA permutation importance
"""
from __future__ import annotations

import sys
import time
import pathlib
import argparse

import numpy as np
import pandas as pd
import lightgbm as lgb

SMC_LIB = pathlib.Path.home() / "smc-lib"
sys.path.insert(0, str(SMC_LIB))

SNAPSHOTS_PATH = SMC_LIB / "projects/живой-рынок/data/snapshots_with_fib_2020-01-01_2026-06-15.parquet"
LABELS_PATH = SMC_LIB / "projects/живой-рынок/data/labels_2020-01-01_2026-06-15.parquet"
RESULTS_DIR = SMC_LIB / "projects/живой-рынок/data/results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def purged_kfold(t_arr, n_splits=10, horizon_seconds=24 * 3600, embargo_seconds=24 * 3600):
    """Lopez Purged K-Fold + embargo. Returns list of (train_idx, test_idx)."""
    N = len(t_arr)
    fold_size = N // n_splits
    splits = []
    for k in range(n_splits):
        ts = k * fold_size
        te = (k + 1) * fold_size if k < n_splits - 1 else N
        test_idx = np.arange(ts, te)
        t_test_min = t_arr[test_idx[0]]
        t_test_max = t_arr[test_idx[-1]]
        purge_lo = t_test_min - horizon_seconds
        embargo_hi = t_test_max + embargo_seconds
        train_mask = np.ones(N, dtype=bool)
        train_mask[test_idx] = False
        train_mask &= ~((t_arr >= purge_lo) & (t_arr < t_test_min))
        train_mask &= ~((t_arr > t_test_max) & (t_arr <= embargo_hi))
        splits.append((np.where(train_mask)[0], test_idx))
    return splits


def time_decay_weights(t_arr, half_life_seconds=90 * 24 * 3600):
    decay = np.log(2) / half_life_seconds
    return np.exp(-(t_arr.max() - t_arr) * decay)


def prepare_dataset(snapshots_path, labels_path):
    """Join snapshots с labels by anchor_id."""
    snaps = pd.read_parquet(snapshots_path)
    labels = pd.read_parquet(labels_path)
    print(f"Snapshots: {snaps.shape}  Labels: {labels.shape}", file=sys.stderr)

    # Encode categoricals
    snaps["element_code"] = snaps["element_type"].astype("category").cat.codes
    snaps["tf_code"] = snaps["tf"].astype("category").cat.codes
    snaps["role_code"] = snaps["role"].astype("category").cat.codes

    # Main goal label per (anchor_id, candidate_zone)
    # Build dict: anchor_id → main_zone_idx from labels
    main_idx_map = dict(zip(labels["anchor_id"], labels["main_zone_idx"]))

    snaps["is_main_goal"] = snaps.apply(
        lambda row: 1 if main_idx_map.get(row["anchor_id"]) == row.name else 0,
        axis=1,
    ).astype(int)

    # Filter snaps to only anchors that have labels
    valid_anchors = set(labels["anchor_id"])
    snaps = snaps[snaps["anchor_id"].isin(valid_anchors)].reset_index(drop=True)

    # Numerical features
    drop_cols = {
        "anchor_ts", "anchor_id", "element_type", "tf", "direction", "role",
        "zone_lo", "zone_hi", "zone_center", "current_price", "is_main_goal",
    }
    feature_cols = [c for c in snaps.columns
                   if c not in drop_cols and snaps[c].dtype.kind in "iuf"]

    X = snaps[feature_cols].values.astype(np.float32)
    y = snaps["is_main_goal"].values.astype(int)
    anchor_ids = snaps["anchor_id"].values.astype(np.int64)
    anchor_ts = snaps["anchor_ts"].values.astype(np.int64)
    print(f"  X: {X.shape}, positives: {y.sum()} ({y.mean()*100:.2f}%)",
          file=sys.stderr)
    return X, y, anchor_ids, anchor_ts, feature_cols


def evaluate_ranker(model, X, y, anchor_ids, top_k=(1, 3, 5)):
    preds = model.predict(X)
    df = pd.DataFrame({"anchor_id": anchor_ids, "pred": preds, "y": y})
    hits = {k: 0 for k in top_k}
    n_groups = 0
    for aid, sub in df.groupby("anchor_id"):
        sub_sorted = sub.sort_values("pred", ascending=False).reset_index(drop=True)
        if sub_sorted["y"].sum() == 0:
            continue
        n_groups += 1
        for k in top_k:
            if sub_sorted["y"].iloc[:k].sum() > 0:
                hits[k] += 1
    return {f"top{k}": hits[k] / n_groups if n_groups else 0 for k in top_k}


def main(n_splits=10):
    X, y, anchor_ids, anchor_ts, feature_cols = prepare_dataset(
        SNAPSHOTS_PATH, LABELS_PATH
    )
    print(f"Feature cols: {len(feature_cols)}", file=sys.stderr)

    # Group sizes per anchor (для LightGBM ranker)
    unique_anchors = np.unique(anchor_ids)
    # Time-decay weights
    anchor_to_ts = dict(zip(anchor_ids, anchor_ts))
    unique_ts = np.array([anchor_to_ts[a] for a in unique_anchors])
    decay_w = time_decay_weights(unique_ts // 1000, half_life_seconds=90 * 86400)
    weight_map = dict(zip(unique_anchors, decay_w))
    row_weights = np.array([weight_map[a] for a in anchor_ids], dtype=np.float32)

    # Purged K-Fold per anchor
    splits = purged_kfold(unique_ts // 1000, n_splits=n_splits)

    results = []
    feat_imp = np.zeros(len(feature_cols))
    for fold, (tr_g, te_g) in enumerate(splits):
        train_anchors = unique_anchors[tr_g]
        test_anchors = unique_anchors[te_g]
        train_mask = np.isin(anchor_ids, train_anchors)
        test_mask = np.isin(anchor_ids, test_anchors)

        tr_idx = np.where(train_mask)[0]
        te_idx = np.where(test_mask)[0]
        tr_sorted = tr_idx[np.argsort(anchor_ids[tr_idx], kind="stable")]
        te_sorted = te_idx[np.argsort(anchor_ids[te_idx], kind="stable")]

        Xtr = X[tr_sorted]
        ytr = y[tr_sorted]
        wtr = row_weights[tr_sorted]
        gtr = anchor_ids[tr_sorted]
        _, group_sizes = np.unique(gtr, return_counts=True)

        Xte = X[te_sorted]
        yte = y[te_sorted]
        ate = anchor_ids[te_sorted]

        train_set = lgb.Dataset(
            Xtr, label=ytr, weight=wtr,
            group=group_sizes,
            feature_name=feature_cols,
        )
        t0 = time.time()
        model = lgb.train(
            params={
                "objective": "lambdarank",
                "metric": ["ndcg"],
                "ndcg_eval_at": [1, 3, 5],
                "learning_rate": 0.05,
                "num_leaves": 63,
                "min_data_in_leaf": 20,
                "feature_fraction": 0.7,
                "bagging_fraction": 0.8,
                "bagging_freq": 5,
                "verbosity": -1,
                "force_col_wise": True,
                "bin_construct_sample_cnt": 50_000,
                "max_bin": 127,
            },
            train_set=train_set,
            num_boost_round=200,
        )
        elapsed = time.time() - t0

        res = evaluate_ranker(model, Xte, yte, ate)
        res["fold"] = fold
        res["n_train_anchors"] = len(np.unique(gtr))
        res["n_test_anchors"] = len(np.unique(ate))
        res["elapsed_s"] = elapsed
        results.append(res)
        feat_imp += np.asarray(model.feature_importance(importance_type="gain"))
        print(
            f"Fold {fold}: n_tr={res['n_train_anchors']} n_te={res['n_test_anchors']} "
            f"top1={res['top1']:.3f} top3={res['top3']:.3f} top5={res['top5']:.3f} "
            f"({elapsed:.1f}s)",
            file=sys.stderr,
        )

    res_df = pd.DataFrame(results)
    print(f"\nCV avg: top1={res_df['top1'].mean():.3f} "
          f"top3={res_df['top3'].mean():.3f} top5={res_df['top5'].mean():.3f}",
          file=sys.stderr)

    res_df.to_csv(RESULTS_DIR / "main_goal_cv.csv", index=False)
    fi = pd.DataFrame({"feature": feature_cols, "importance_gain": feat_imp})
    fi = fi.sort_values("importance_gain", ascending=False)
    fi.to_csv(RESULTS_DIR / "main_goal_feature_importance.csv", index=False)
    print(f"\nTop 20 features by gain:\n{fi.head(20).to_string(index=False)}",
          file=sys.stderr)
    print(f"\nSaved CV + feature importance to {RESULTS_DIR}", file=sys.stderr)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n_splits", type=int, default=10)
    args = ap.parse_args()
    main(args.n_splits)
