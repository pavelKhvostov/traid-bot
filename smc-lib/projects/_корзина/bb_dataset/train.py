"""bb-model training: walk-forward HGBR Binary Classifier + isotonic.

Input:  ~/Desktop/bb_obvc_1h2h.parquet (output of builder.py)
Output: bb_predictions.csv (per-zone P_break + actual + features)
        bb_metrics.json
        bb_model.pkl (final model trained on full data)
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import brier_score_loss, roc_auc_score


DATA = Path.home() / "Desktop" / "bb_obvc_1h2h.parquet"
OUT_DIR = Path.home() / "smc-lib" / "projects" / "bb_dataset"


FEATURE_COLS = [
    "tf_hours",
    "direction_long",      # one-hot
    "width_pct",
    "age_bars",
    "n_fvg_components",
    "penetration_pct",
    "close_inside",
    "first_bar_wick_to_body",
    "n_touches_prior",
]


def prepare_features(df: pd.DataFrame) -> pd.DataFrame:
    """Encode categorical + final feature matrix."""
    out = df.copy()
    out["direction_long"] = (out["direction"].str.lower() == "long").astype(int)
    return out


def walk_forward_train(
    df: pd.DataFrame,
    train_years: int = 5,
    test_years: int = 1,
) -> dict:
    """Single split: train on first (full - test_years), test on last test_years."""
    df = df.sort_values("touch_ts").reset_index(drop=True)
    df["touch_ts"] = pd.to_datetime(df["touch_ts"], utc=True)

    end_ts = df["touch_ts"].max()
    test_start = end_ts - pd.Timedelta(days=365 * test_years)
    train_mask = df["touch_ts"] < test_start
    test_mask = ~train_mask

    train = df[train_mask].copy()
    test = df[test_mask].copy()
    print(f"  train: {len(train):,} rows ({train['touch_ts'].min()} -> {train['touch_ts'].max()})")
    print(f"  test:  {len(test):,} rows ({test['touch_ts'].min()} -> {test['touch_ts'].max()})")
    print(f"  train P(break) = {train['label'].mean():.4f}")
    print(f"  test  P(break) = {test['label'].mean():.4f}")

    X_tr = train[FEATURE_COLS].astype(float).to_numpy()
    y_tr = train["label"].astype(int).to_numpy()
    X_te = test[FEATURE_COLS].astype(float).to_numpy()
    y_te = test["label"].astype(int).to_numpy()

    # Class imbalance handle через sample_weight
    pos_weight = (1 - y_tr.mean()) / y_tr.mean()
    sw = np.where(y_tr == 1, pos_weight, 1.0)

    print(f"  pos_weight (for break): {pos_weight:.2f}")

    model = HistGradientBoostingClassifier(
        max_iter=300,
        learning_rate=0.05,
        max_leaf_nodes=31,
        min_samples_leaf=50,
        random_state=42,
    )
    model.fit(X_tr, y_tr, sample_weight=sw)

    # Predict raw
    p_raw_tr = model.predict_proba(X_tr)[:, 1]
    p_raw_te = model.predict_proba(X_te)[:, 1]

    # Isotonic calibration on train (Brier-honest in production: use OOF, here OK for MVP)
    iso = IsotonicRegression(out_of_bounds="clip")
    iso.fit(p_raw_tr, y_tr)
    p_te = iso.transform(p_raw_te)
    p_tr = iso.transform(p_raw_tr)

    # Metrics
    metrics = {}
    metrics["n_train"] = int(len(train))
    metrics["n_test"] = int(len(test))
    metrics["test_P_break_actual"] = float(y_te.mean())
    metrics["test_brier"] = float(brier_score_loss(y_te, p_te))
    metrics["test_brier_raw"] = float(brier_score_loss(y_te, p_raw_te))
    # Baseline Brier = predicting train P(break) for all
    base_p = float(y_tr.mean())
    metrics["baseline_brier"] = float(brier_score_loss(y_te, np.full(len(y_te), base_p)))
    metrics["brier_lift_pct"] = float((1 - metrics["test_brier"] / metrics["baseline_brier"]) * 100)
    if len(np.unique(y_te)) > 1:
        metrics["test_auc"] = float(roc_auc_score(y_te, p_te))
        metrics["test_auc_raw"] = float(roc_auc_score(y_te, p_raw_te))
    # Top-decile precision: of zones predicted most likely to break, what fraction actually broke?
    if len(p_te) > 0:
        top10 = max(1, int(len(p_te) * 0.1))
        top_idx = np.argsort(-p_te)[:top10]
        metrics["top_decile_precision"] = float(y_te[top_idx].mean())
    # Bottom-decile precision: of zones predicted most likely to bounce, what fraction actually bounced?
    if len(p_te) > 0:
        bot10 = max(1, int(len(p_te) * 0.1))
        bot_idx = np.argsort(p_te)[:bot10]
        metrics["bottom_decile_bounce_pct"] = float(1 - y_te[bot_idx].mean())

    print(f"\n  test Brier:   {metrics['test_brier']:.4f}  (baseline {metrics['baseline_brier']:.4f}; lift {metrics['brier_lift_pct']:.1f}%)")
    if "test_auc" in metrics:
        print(f"  test AUC:     {metrics['test_auc']:.3f}  (raw {metrics['test_auc_raw']:.3f})")
    print(f"  top-decile break precision: {metrics['top_decile_precision']:.3f}")
    print(f"  bot-decile bounce precision: {metrics['bottom_decile_bounce_pct']:.3f}")

    # Save predictions
    preds_df = test.copy()
    preds_df["P_break"] = p_te
    preds_df["P_break_raw"] = p_raw_te
    preds_df["actual_break"] = y_te

    return {
        "model": model,
        "iso": iso,
        "metrics": metrics,
        "preds": preds_df,
        "train_df": train,
    }


def main():
    t0 = time.time()
    print(f"[bb-train] loading {DATA}...")
    df = pd.read_parquet(DATA)
    print(f"  {len(df):,} rows, cols: {list(df.columns)}")
    df = prepare_features(df)

    print("\n[bb-train] walk-forward (last 1y test)...")
    res = walk_forward_train(df, test_years=1)

    OUT_DIR.mkdir(exist_ok=True)
    res["preds"][["zone_id", "tf", "direction", "born_ts", "touch_ts", "label",
                   "P_break", "P_break_raw", "actual_break"]].to_csv(
        OUT_DIR / "bb_predictions.csv", index=False
    )
    print(f"\n[bb-train] saved predictions to {OUT_DIR/'bb_predictions.csv'}")

    with open(OUT_DIR / "bb_metrics.json", "w") as f:
        json.dump(res["metrics"], f, indent=2, default=str)
    print(f"[bb-train] saved metrics to {OUT_DIR/'bb_metrics.json'}")

    import pickle
    with open(OUT_DIR / "bb_model.pkl", "wb") as f:
        pickle.dump({"model": res["model"], "iso": res["iso"],
                      "features": FEATURE_COLS}, f)
    print(f"[bb-train] saved model to {OUT_DIR/'bb_model.pkl'}")

    print(f"\n[bb-train] FINAL METRICS:")
    print(json.dumps(res["metrics"], indent=2, default=str))

    print(f"\n[bb-train] TOTAL: {(time.time()-t0)/60:.1f} min")


if __name__ == "__main__":
    main()
