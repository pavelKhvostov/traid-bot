"""Phase 2 Step 3 PoC — train GradientBoostingClassifier on 1h cadence baseline.

Subset features (21) + 1 target (y_long_3pct_24h).
Purged K-Fold (5 folds) + embargo=24h (24 bars on 1h cadence).

Goal: verify pipeline works, baseline AUC > 0.55 (random); target > 0.65.
If AUC > 0.65 → architecture sound, scale to full feature port.
"""
from __future__ import annotations
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import (
    roc_auc_score,
    brier_score_loss,
    average_precision_score,
)

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RESULTS_DIR = ROOT / "results"
RESULTS_DIR.mkdir(exist_ok=True)

FEATURES = DATA_DIR / "features_poc_1h.parquet"
LABELS = DATA_DIR / "labels_1h.parquet"

TARGETS_TO_TRAIN = [
    "y_long_2pct_24h",
    "y_long_3pct_24h",
    "y_long_5pct_24h",
    "y_short_3pct_24h",
]

N_FOLDS = 5
EMBARGO_BARS = 24  # 24h gap between train and validation in Purged K-Fold


def purged_kfold_indices(n: int, n_folds: int, embargo: int):
    """Yield (train_idx, val_idx) for Purged K-Fold with embargo."""
    fold_size = n // n_folds
    for k in range(n_folds):
        val_start = k * fold_size
        val_end = val_start + fold_size if k < n_folds - 1 else n
        val_idx = np.arange(val_start, val_end)
        train_lo = max(0, val_start - embargo)
        train_hi = min(n, val_end + embargo)
        train_left = np.arange(0, train_lo)
        train_right = np.arange(train_hi, n)
        train_idx = np.concatenate([train_left, train_right])
        yield train_idx, val_idx


def sample_weights_uniqueness_return(returns: pd.Series, horizon: int = 24) -> np.ndarray:
    """Sample weight = 1 / overlap_count × |return|."""
    n = len(returns)
    overlap = np.full(n, horizon, dtype=float)
    # Roughly: each bar is in (horizon) overlapping windows; weight = 1/horizon × |ret|
    weights = (1.0 / overlap) * returns.abs().to_numpy()
    weights = np.where(np.isnan(weights), 0, weights)
    if weights.sum() > 0:
        weights = weights / weights.mean()  # normalize so mean = 1
    return weights


def train_one_target(
    target: str,
    feats: pd.DataFrame,
    labels: pd.DataFrame,
) -> dict:
    print(f"\n{'='*60}\n=== Training: {target} ===\n{'='*60}")
    t0 = time.time()

    # Align
    df = feats.join(labels[[target, "split", "range_up_pct_24h", "range_down_pct_24h"]], how="inner")
    df = df.dropna(subset=[target])

    train_df = df[df["split"] == "train"]
    test_df = df[df["split"] == "holdout"]

    feat_cols = [c for c in feats.columns if c in df.columns]

    X_train = train_df[feat_cols].to_numpy()
    y_train = train_df[target].astype(int).to_numpy()
    X_test = test_df[feat_cols].to_numpy()
    y_test = test_df[target].astype(int).to_numpy()

    # Returns for weights
    if "long" in target:
        ret_for_weight = train_df["range_up_pct_24h"].fillna(0)
    else:
        ret_for_weight = train_df["range_down_pct_24h"].fillna(0)

    w_train = sample_weights_uniqueness_return(ret_for_weight, horizon=24)

    pos_train = y_train.mean() * 100
    pos_test = y_test.mean() * 100
    print(f"  Train N={len(y_train):,}  pos={pos_train:.2f}%")
    print(f"  Test  N={len(y_test):,}  pos={pos_test:.2f}%")
    print(f"  Features: {len(feat_cols)}")

    # Purged K-Fold CV
    cv_aucs = []
    for fold_idx, (tr_i, va_i) in enumerate(purged_kfold_indices(len(X_train), N_FOLDS, EMBARGO_BARS)):
        clf = GradientBoostingClassifier(
            n_estimators=200,
            max_depth=3,
            learning_rate=0.05,
            subsample=0.85,
            random_state=42,
        )
        clf.fit(X_train[tr_i], y_train[tr_i], sample_weight=w_train[tr_i])
        prob_va = clf.predict_proba(X_train[va_i])[:, 1]
        if len(np.unique(y_train[va_i])) > 1:
            auc = roc_auc_score(y_train[va_i], prob_va)
            cv_aucs.append(auc)
            print(f"  Fold {fold_idx + 1}: AUC = {auc:.4f}  (n_train={len(tr_i):,}, n_val={len(va_i):,})")

    cv_mean = np.mean(cv_aucs)
    cv_std = np.std(cv_aucs)

    # Final fit on full train, evaluate on holdout
    clf_final = GradientBoostingClassifier(
        n_estimators=200,
        max_depth=3,
        learning_rate=0.05,
        subsample=0.85,
        random_state=42,
    )
    clf_final.fit(X_train, y_train, sample_weight=w_train)
    prob_test = clf_final.predict_proba(X_test)[:, 1]

    holdout_auc = roc_auc_score(y_test, prob_test) if len(np.unique(y_test)) > 1 else np.nan
    brier = brier_score_loss(y_test, prob_test)
    ap = average_precision_score(y_test, prob_test) if len(np.unique(y_test)) > 1 else np.nan

    print(f"\n  Purged CV AUC: {cv_mean:.4f} ± {cv_std:.4f}")
    print(f"  Holdout AUC:   {holdout_auc:.4f}")
    print(f"  Holdout Brier: {brier:.4f}")
    print(f"  Holdout AP:    {ap:.4f}  (baseline = {pos_test:.2f}%)")

    # Threshold sweep on holdout
    print(f"\n  Threshold sweep (holdout):")
    print(f"  {'thr':>5} {'n_kept':>7} {'kept%':>7} {'hit%':>6} {'lift':>6}")
    base = pos_test / 100
    for thr in [0.1, 0.2, 0.3, 0.5, 0.6, 0.7, 0.8]:
        keep = prob_test >= thr
        n_kept = int(keep.sum())
        if n_kept == 0:
            continue
        hit = y_test[keep].mean()
        lift = hit / base if base > 0 else np.inf
        print(f"  {thr:>5.2f} {n_kept:>7} {n_kept / len(y_test) * 100:>6.2f}% {hit * 100:>5.2f}% {lift:>5.2f}x")

    # Feature importance
    imp = sorted(zip(feat_cols, clf_final.feature_importances_), key=lambda x: -x[1])
    print(f"\n  Top-10 features:")
    for f, w in imp[:10]:
        print(f"    {w:.4f}  {f}")

    elapsed = time.time() - t0
    print(f"\n  Elapsed: {elapsed:.1f}s")

    return {
        "target": target,
        "cv_auc_mean": cv_mean,
        "cv_auc_std": cv_std,
        "holdout_auc": holdout_auc,
        "brier": brier,
        "ap": ap,
        "pos_train": pos_train,
        "pos_test": pos_test,
        "elapsed_s": elapsed,
    }


def main():
    print("Loading features + labels...")
    feats = pd.read_parquet(FEATURES)
    labels = pd.read_parquet(LABELS)
    print(f"  Features: {len(feats):,} rows × {len(feats.columns)} cols")
    print(f"  Labels:   {len(labels):,} rows × {len(labels.columns)} cols")

    results = []
    for target in TARGETS_TO_TRAIN:
        r = train_one_target(target, feats, labels)
        results.append(r)

    print(f"\n\n{'='*60}\n=== SUMMARY ===\n{'='*60}")
    summary = pd.DataFrame(results)
    print(summary.to_string(index=False))

    summary.to_csv(RESULTS_DIR / "poc_baseline_summary.csv", index=False)
    print(f"\n→ Saved: {RESULTS_DIR / 'poc_baseline_summary.csv'}")


if __name__ == "__main__":
    main()
