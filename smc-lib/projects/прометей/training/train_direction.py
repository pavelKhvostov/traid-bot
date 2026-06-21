"""Stage B — LightGBM multiclass classifier: ternary direction prediction.

Predicts target_direction ∈ {long, short, no_react} for each snapshot.

Inputs:
  features_parquet — per-snapshot features (t0 + 1052 cols)
  labels_parquet   — per-snapshot labels (t0, target_direction + meta)

Train LightGBM multiclass with Purged K-Fold + embargo + time-decay weights.
Report per-class precision/recall/F1, confusion matrix, multi-class AUC.
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
from projects.прометей.training.lopez_cv import (  # noqa: E402
    purged_kfold_splits,
    time_decay_weights,
)


CLASS_MAP = {"long": 0, "short": 1, "no_react": 2}
INV_CLASS = {v: k for k, v in CLASS_MAP.items()}


def prepare_dataset(
    features_path: pathlib.Path,
    labels_path: pathlib.Path,
) -> tuple[pd.DataFrame, np.ndarray, np.ndarray, list[str]]:
    feats = pd.read_parquet(features_path)
    labels = pd.read_parquet(labels_path)
    print(f"Features: {feats.shape}  Labels: {labels.shape}", file=sys.stderr)

    # Join on t0
    merged = feats.merge(
        labels[["t0", "target_direction", "target_magnitude_pct"]],
        on="t0", how="inner",
    )
    merged = merged.dropna(subset=["target_direction"])
    merged = merged[merged["current_price"] > 0].reset_index(drop=True)
    merged = merged.sort_values("t0").reset_index(drop=True)
    print(f"After join + price filter: {merged.shape}", file=sys.stderr)

    y = merged["target_direction"].map(CLASS_MAP).astype(int).values
    t0_arr = merged["t0"].values
    drop_cols = {"t0", "t0_iso_msk", "target_direction", "target_magnitude_pct"}
    feature_cols = [c for c in merged.columns if c not in drop_cols]
    X = merged[feature_cols].astype(np.float32)
    return X, y, t0_arr, feature_cols


def class_report(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    """Per-class precision, recall, F1, plus confusion matrix."""
    out = {}
    for cls_id, cls_name in INV_CLASS.items():
        tp = ((y_pred == cls_id) & (y_true == cls_id)).sum()
        fp = ((y_pred == cls_id) & (y_true != cls_id)).sum()
        fn = ((y_pred != cls_id) & (y_true == cls_id)).sum()
        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0
        out[f"{cls_name}_prec"] = prec
        out[f"{cls_name}_recall"] = rec
        out[f"{cls_name}_f1"] = f1
        out[f"{cls_name}_n"] = int((y_true == cls_id).sum())
    out["accuracy"] = (y_pred == y_true).mean()
    return out


def confusion_matrix(y_true: np.ndarray, y_pred: np.ndarray) -> np.ndarray:
    cm = np.zeros((3, 3), dtype=int)
    for t, p in zip(y_true, y_pred):
        cm[t][p] += 1
    return cm


def main(
    features_path: pathlib.Path,
    labels_path: pathlib.Path,
    out_dir: pathlib.Path,
    n_splits: int = 5,
    horizon_hr: int = 24,
    embargo_hr: int = 24,
    half_life_days: int = 90,
):
    out_dir.mkdir(parents=True, exist_ok=True)
    X, y, t0_arr, feature_cols = prepare_dataset(features_path, labels_path)
    print(
        f"Feature cols: {len(feature_cols)}  rows: {len(X)}\n"
        f"  class counts: " + ", ".join(
            f"{INV_CLASS[c]}={int((y == c).sum())}" for c in range(3)
        ),
        file=sys.stderr,
    )

    splits = purged_kfold_splits(
        t0_arr,
        n_splits=n_splits,
        horizon_seconds=horizon_hr * 3600,
        embargo_seconds=embargo_hr * 3600,
    )

    weights_all = time_decay_weights(t0_arr, half_life_seconds=half_life_days * 86400)

    fold_results = []
    feature_importance = np.zeros(len(feature_cols))
    total_cm = np.zeros((3, 3), dtype=int)
    oof_pred = np.zeros((len(X), 3), dtype=np.float64)
    oof_y = np.full(len(X), -1, dtype=int)
    for fold, (train_idx, test_idx) in enumerate(splits):
        Xtr = X.iloc[train_idx]
        ytr = y[train_idx]
        wtr = weights_all[train_idx]
        Xte = X.iloc[test_idx]
        yte = y[test_idx]

        train_set = lgb.Dataset(Xtr, label=ytr, weight=wtr, feature_name=feature_cols)
        t_start = time.time()
        model = lgb.train(
            params={
                "objective": "multiclass",
                "num_class": 3,
                "metric": ["multi_logloss"],
                "learning_rate": 0.05,
                "num_leaves": 63,
                "min_data_in_leaf": 20,
                "feature_fraction": 0.7,
                "bagging_fraction": 0.8,
                "bagging_freq": 5,
                "verbosity": -1,
                "force_col_wise": True,
            },
            train_set=train_set,
            num_boost_round=200,
        )
        elapsed = time.time() - t_start
        proba = model.predict(Xte)
        yhat = proba.argmax(axis=1)
        oof_pred[test_idx] = proba
        oof_y[test_idx] = yte

        cm = confusion_matrix(yte, yhat)
        total_cm += cm
        rep = class_report(yte, yhat)
        rep["fold"] = fold
        rep["n_train"] = len(train_idx)
        rep["n_test"] = len(test_idx)
        rep["elapsed_s"] = elapsed
        fold_results.append(rep)
        feature_importance += np.asarray(model.feature_importance(importance_type="gain"))
        print(
            f"Fold {fold}: n_tr={len(train_idx)} n_te={len(test_idx)} "
            f"acc={rep['accuracy']:.3f} | "
            f"long P/R/F1={rep['long_prec']:.2f}/{rep['long_recall']:.2f}/{rep['long_f1']:.2f}  "
            f"short P/R/F1={rep['short_prec']:.2f}/{rep['short_recall']:.2f}/{rep['short_f1']:.2f}  "
            f"no P/R/F1={rep['no_react_prec']:.2f}/{rep['no_react_recall']:.2f}/{rep['no_react_f1']:.2f}  "
            f"({elapsed:.1f}s)",
            file=sys.stderr,
        )

    # Aggregate
    res_df = pd.DataFrame(fold_results)
    print("\nCV averages:", file=sys.stderr)
    for col in ["accuracy", "long_prec", "long_recall", "long_f1",
                "short_prec", "short_recall", "short_f1",
                "no_react_prec", "no_react_recall", "no_react_f1"]:
        print(f"  {col}: {res_df[col].mean():.3f}", file=sys.stderr)

    print("\nConfusion matrix (rows=true, cols=pred):", file=sys.stderr)
    print(f"            pred_long  pred_short  pred_no", file=sys.stderr)
    for i, name in enumerate(["long", "short", "no_react"]):
        print(
            f"  {name:>8}    {total_cm[i,0]:>8}  {total_cm[i,1]:>10}  {total_cm[i,2]:>7}",
            file=sys.stderr,
        )

    # Save
    res_df.to_csv(out_dir / "direction_cv_results.csv", index=False)
    np.save(out_dir / "direction_confusion_matrix.npy", total_cm)

    fi = pd.DataFrame({"feature": feature_cols, "importance_gain": feature_importance})
    fi = fi.sort_values("importance_gain", ascending=False)
    fi.to_csv(out_dir / "direction_feature_importance.csv", index=False)
    print(f"\nTop 20 features by gain:", file=sys.stderr)
    print(fi.head(20).to_string(index=False), file=sys.stderr)

    # OOF predictions
    valid = oof_y >= 0
    oof_df = pd.DataFrame({
        "t0": t0_arr[valid],
        "true": [INV_CLASS[y_] for y_ in oof_y[valid]],
        "pred_long": oof_pred[valid, 0],
        "pred_short": oof_pred[valid, 1],
        "pred_no_react": oof_pred[valid, 2],
    })
    oof_df.to_parquet(out_dir / "direction_oof_predictions.parquet", index=False)
    print(f"\nSaved CV results + feature importance + OOF to {out_dir}", file=sys.stderr)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", required=True)
    ap.add_argument("--labels", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--n_splits", type=int, default=5)
    args = ap.parse_args()
    main(
        pathlib.Path(args.features),
        pathlib.Path(args.labels),
        pathlib.Path(args.out),
        n_splits=args.n_splits,
    )
