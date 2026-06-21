"""Stage A — LightGBM ranker: per-zone "was_strong" prediction.

Inputs:
  features_parquet — per-snapshot features (t0, current_price, + 1052 cols)
  zone_labels_parquet — per (snap × zone) rows with `was_strong`, zone meta

Join on t0. Each snapshot = ranking group. Train LightGBM lambdarank,
evaluate NDCG@K + top-1 precision via Purged K-Fold.

Зоны-features (per-zone): element/tf/side/dist/age/mit_count + snapshot features.
"""
from __future__ import annotations

import sys
import json
import time
import pathlib
import argparse

import numpy as np
import pandas as pd
import lightgbm as lgb

SMC_LIB = pathlib.Path.home() / "smc-lib"
sys.path.insert(0, str(SMC_LIB))
from projects.прометей.training.lopez_cv import (  # noqa: E402
    purged_kfold_splits,
    time_decay_weights,
)


def prepare_dataset(
    features_path: pathlib.Path,
    zone_labels_path: pathlib.Path,
) -> tuple:
    """Returns (X_sparse, y, groups_meta, feature_cols).

    Strategy (memory-safe для 3.9M × 1055):
      1. Load feats (2190 × 1055) — light
      2. Apply variance + correlation filter ON FEATS ONLY (small, fast)
      3. Drop reduced columns from feats BEFORE merge
      4. Merge reduced feats (~300 cols) с zones → ~5 GB
      5. Convert to sparse CSR → 1-2 GB
    """
    feats = pd.read_parquet(features_path)
    zones = pd.read_parquet(zone_labels_path)

    feats = feats.rename(columns={"t0": "group_id"})
    print(f"Features: {feats.shape}  zone-labels: {zones.shape}", file=sys.stderr)

    # ─── Filter features columns BEFORE merge ─────────────────
    # Non-feature meta in feats parquet
    feats_meta = ["group_id", "t0_iso_msk"]
    feats_cols_all = [c for c in feats.columns if c not in feats_meta]
    feats_X = feats[feats_cols_all].astype(np.float32)

    # Layer 1: variance filter (on feats only — 2190 rows × 1055 cols, fast)
    variances = feats_X.var(axis=0).values
    high_var_mask = variances > 1e-6
    feats_cols_kept = [c for c, m in zip(feats_cols_all, high_var_mask) if m]
    print(f"  Layer 1 (variance > 1e-6 on feats): "
          f"{len(feats_cols_kept)}/{len(feats_cols_all)} kept", file=sys.stderr)

    # Layer 2: correlation pruning (on feats only)
    feats_X = feats_X.loc[:, feats_cols_kept]
    corr = feats_X.corr().abs().values
    np.fill_diagonal(corr, 0)
    to_drop = set()
    for i in range(len(feats_cols_kept)):
        if i in to_drop:
            continue
        high = np.where(corr[i] > 0.95)[0]
        for j in high:
            if j != i and j not in to_drop:
                to_drop.add(j)
    keep_mask = np.array([i not in to_drop for i in range(len(feats_cols_kept))])
    feats_cols_final = [c for c, m in zip(feats_cols_kept, keep_mask) if m]
    print(f"  Layer 2 (corr ≤ 0.95): {len(feats_cols_final)}/{len(feats_cols_kept)} kept",
          file=sys.stderr)

    # Drop "current_price" from feats — оно есть в zones_slim, чтобы избежать suffix conflict
    feats_cols_final = [c for c in feats_cols_final if c != "current_price"]
    # Reduce feats DataFrame BEFORE merge + cast to float32
    feats_reduced = feats[["group_id"] + feats_cols_final].copy()
    for c in feats_cols_final:
        feats_reduced[c] = feats_reduced[c].astype(np.float32)

    # Subsample groups (OOM fix): random 500 из 2190 (uniform по времени)
    SUBSAMPLE_GROUPS = 500
    if len(feats_reduced) > SUBSAMPLE_GROUPS:
        rng = np.random.RandomState(42)
        step = len(feats_reduced) // SUBSAMPLE_GROUPS
        idx = np.arange(0, len(feats_reduced), step)[:SUBSAMPLE_GROUPS]
        feats_reduced = feats_reduced.iloc[idx].reset_index(drop=True)
        print(f"  Subsampled groups: {len(feats_reduced)}/{2190}", file=sys.stderr)

    # Output constraint: candidates только 4h+ TFs (защита от distance bias)
    OUTPUT_TFS = {"4h", "6h", "12h", "1D"}
    n_before = len(zones)
    zones = zones[zones["tf"].isin(OUTPUT_TFS)].reset_index(drop=True)
    print(f"  4h+ filter: {len(zones):,}/{n_before:,} rows kept "
          f"({len(zones)/n_before*100:.1f}%)", file=sys.stderr)

    # Encode categorical zone meta
    zones["element_code"] = zones["element"].astype("category").cat.codes
    zones["tf_code"] = zones["tf"].astype("category").cat.codes
    zones["side_long"] = (zones["side"] == "long").astype(int)
    zone_cols = [
        "group_id", "was_strong", "element_code", "tf_code", "side_long", "is_flip",
        "zone_lo_init", "zone_hi_init", "zone_lo_active", "zone_hi_active",
        "zone_width_pct", "dist_pct_signed", "dist_pct_abs",
        "age_bars", "mit_count", "is_inside_zone", "current_price",
    ]
    zones_slim = zones[zone_cols]
    print(f"Zones (slim): {zones_slim.shape}, Feats (reduced): {feats_reduced.shape}",
          file=sys.stderr)

    # ─── Memory-safe merge ────────────────────────────────────
    merged = zones_slim.merge(feats_reduced, on="group_id", how="inner")
    merged = merged[merged["current_price"] > 0].reset_index(drop=True)
    merged = merged.sort_values("group_id").reset_index(drop=True)
    print(f"After merge + price filter: {merged.shape}, "
          f"memory ≈ {merged.memory_usage(deep=True).sum() / 1e9:.1f} GB",
          file=sys.stderr)

    y = merged["was_strong"].astype(int).values
    group_ids = merged["group_id"].values.astype(np.int64)
    drop_cols = {"was_strong", "group_id"}
    feature_cols = [c for c in merged.columns if c not in drop_cols]

    # Dense float32 (sparse не помогает при 78% nnz)
    X_arr = merged[feature_cols].values.astype(np.float32)
    del merged
    print(f"  Final X dense: {X_arr.shape}, memory ≈ {X_arr.nbytes / 1e9:.2f} GB",
          file=sys.stderr)

    groups_meta = pd.DataFrame({"group_id": group_ids})
    return X_arr, pd.Series(y, name="was_strong"), groups_meta, feature_cols


def evaluate_ranker(
    model: lgb.Booster,
    X,  # sparse CSR or dense
    y: np.ndarray,
    group_ids: np.ndarray,
    top_k_list: tuple[int, ...] = (1, 3, 5, 10),
) -> dict:
    """Return per-group top-K hit rate (precision@K)."""
    preds = model.predict(X)
    df = pd.DataFrame({"group_id": group_ids, "pred": preds, "y": y})
    hits = {k: 0 for k in top_k_list}
    n_groups = 0
    for gid, sub in df.groupby("group_id"):
        sub = sub.sort_values("pred", ascending=False).reset_index(drop=True)
        n_groups += 1
        for k in top_k_list:
            if sub["y"].iloc[:k].sum() > 0:
                hits[k] += 1
    return {f"top{k}_hit": hits[k] / n_groups if n_groups else 0 for k in top_k_list}


def main(
    features_path: pathlib.Path,
    zone_labels_path: pathlib.Path,
    out_dir: pathlib.Path,
    n_splits: int = 5,
    horizon_hr: int = 24,
    embargo_hr: int = 24,
    half_life_days: int = 90,
):
    out_dir.mkdir(parents=True, exist_ok=True)
    X, y_ser, groups_meta, feature_cols = prepare_dataset(features_path, zone_labels_path)
    y = y_ser.values
    group_ids = groups_meta["group_id"].values  # zone-row t0
    print(f"Feature cols: {len(feature_cols)}  rows: {X.shape[0]}  positives: {y.sum()}",
          file=sys.stderr)

    # Compute per-snapshot t0_unix for CV split (one entry per unique group)
    unique_groups = np.sort(np.unique(group_ids))
    splits_per_group = purged_kfold_splits(
        unique_groups,
        n_splits=n_splits,
        horizon_seconds=horizon_hr * 3600,
        embargo_seconds=embargo_hr * 3600,
    )

    # Sample weights (per row, by group t0)
    snap_weights = time_decay_weights(unique_groups, half_life_seconds=half_life_days * 86400)
    weight_map = dict(zip(unique_groups, snap_weights))
    row_weights = np.array([weight_map[g] for g in group_ids], dtype=np.float32)

    # Fold loop
    results = []
    feature_importance = np.zeros(len(feature_cols))
    for fold, (train_groups_idx, test_groups_idx) in enumerate(splits_per_group):
        train_groups = unique_groups[train_groups_idx]
        test_groups = unique_groups[test_groups_idx]
        train_mask = np.isin(group_ids, train_groups)
        test_mask = np.isin(group_ids, test_groups)

        # Sparse-aware row indexing (X is scipy.sparse CSR matrix)
        train_idx_raw = np.where(train_mask)[0]
        train_sorted = train_idx_raw[np.argsort(group_ids[train_idx_raw], kind="stable")]
        Xtr = X[train_sorted]  # sparse CSR row-slice
        ytr = y[train_sorted]
        wtr = row_weights[train_sorted]
        gtr = group_ids[train_sorted]
        _, train_group_sizes = np.unique(gtr, return_counts=True)

        test_idx_raw = np.where(test_mask)[0]
        test_sorted = test_idx_raw[np.argsort(group_ids[test_idx_raw], kind="stable")]
        Xte = X[test_sorted]
        yte = y[test_sorted]
        gte = group_ids[test_sorted]

        train_set = lgb.Dataset(
            Xtr, label=ytr, weight=wtr,
            group=train_group_sizes,
            feature_name=feature_cols,
        )
        t_start = time.time()
        model = lgb.train(
            params={
                "objective": "lambdarank",
                "metric": ["ndcg"],
                "ndcg_eval_at": [1, 3, 5, 10],
                "learning_rate": 0.05,
                "num_leaves": 63,
                "min_data_in_leaf": 20,
                "feature_fraction": 0.7,
                "bagging_fraction": 0.8,
                "bagging_freq": 5,
                "verbosity": -1,
                "force_col_wise": True,
                # OOM mitigation
                "bin_construct_sample_cnt": 50_000,
                "max_bin": 127,
                "histogram_pool_size": 4096,
            },
            train_set=train_set,
            num_boost_round=200,
        )
        elapsed = time.time() - t_start
        res = evaluate_ranker(model, Xte, yte, gte)
        res["fold"] = fold
        res["n_train_groups"] = len(np.unique(gtr))
        res["n_test_groups"] = len(np.unique(gte))
        res["elapsed_s"] = elapsed
        results.append(res)
        feature_importance += np.asarray(model.feature_importance(importance_type="gain"))
        print(
            f"Fold {fold}: n_train={res['n_train_groups']} n_test={res['n_test_groups']} "
            f"top1={res['top1_hit']:.3f} top3={res['top3_hit']:.3f} top5={res['top5_hit']:.3f} "
            f"top10={res['top10_hit']:.3f} ({elapsed:.1f}s)",
            file=sys.stderr,
        )

    # Aggregate
    res_df = pd.DataFrame(results)
    avg_top1 = res_df["top1_hit"].mean()
    avg_top5 = res_df["top5_hit"].mean()
    avg_top10 = res_df["top10_hit"].mean()
    print(
        f"\nCV avg: top1={avg_top1:.3f} top3={res_df['top3_hit'].mean():.3f} "
        f"top5={avg_top5:.3f} top10={avg_top10:.3f}",
        file=sys.stderr,
    )

    # Save
    res_df.to_csv(out_dir / "ranker_cv_results.csv", index=False)
    fi = pd.DataFrame({"feature": feature_cols, "importance_gain": feature_importance})
    fi = fi.sort_values("importance_gain", ascending=False)
    fi.to_csv(out_dir / "ranker_feature_importance.csv", index=False)
    print(f"\nTop 20 features by gain:", file=sys.stderr)
    print(fi.head(20).to_string(index=False), file=sys.stderr)
    print(f"\nSaved CV results + feature importance to {out_dir}", file=sys.stderr)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", required=True)
    ap.add_argument("--zone_labels", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--n_splits", type=int, default=5)
    args = ap.parse_args()
    main(
        pathlib.Path(args.features),
        pathlib.Path(args.zone_labels),
        pathlib.Path(args.out),
        n_splits=args.n_splits,
    )
