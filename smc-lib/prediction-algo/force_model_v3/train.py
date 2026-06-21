"""
Train 5 раздельных logistic regression моделей с directional target.

Coefficients per element:
  FVG:           10 × 8 = 80
  fractal:       10 × 8 = 80
  OB:            10 × 8 = 80
  block_orders:   9 × 8 = 72
  RDRB:           9 × 8 = 72
  ───────────────────────
  TOTAL:                  384
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

from force_model_v3.dataset import FEATURES, SMC_TFS, expand_to_cell_wise

warnings.filterwarnings("ignore", category=FutureWarning, module="sklearn")

CANDLE_CONTEXT_FEATS = ("candle_body_atr", "candle_range_atr", "candle_direction", "prior_n_bars_trend")


def train_one_element(
    df: pd.DataFrame,
    element_type: str,
    tfs: tuple = SMC_TFS,
    C: float = 1.0,
    test_split_ts: pd.Timestamp | None = None,
    zone_only: bool = False,
) -> dict:
    if df.empty:
        return {"error": "empty dataset", "model": None}
    feat_cols = list(FEATURES[element_type])
    if zone_only:
        feat_cols = [f for f in feat_cols if f not in CANDLE_CONTEXT_FEATS]
    expanded = expand_to_cell_wise(df, feat_cols, tfs=tfs)
    cell_cols = [c for c in expanded.columns if c not in ("target", "candle_open_ts", "side")]

    if test_split_ts is not None:
        train_mask = expanded["candle_open_ts"] < test_split_ts
        X_train = expanded.loc[train_mask, cell_cols].to_numpy()
        y_train = expanded.loc[train_mask, "target"].to_numpy()
        X_test = expanded.loc[~train_mask, cell_cols].to_numpy()
        y_test = expanded.loc[~train_mask, "target"].to_numpy()
    else:
        X_train = expanded[cell_cols].to_numpy()
        y_train = expanded["target"].to_numpy()
        X_test = None
        y_test = None

    if len(np.unique(y_train)) < 2:
        return {"error": "only one class in target", "n_train": len(y_train)}

    model = LogisticRegression(C=C, max_iter=1000, solver="lbfgs")
    model.fit(X_train, y_train)

    p_train = model.predict_proba(X_train)[:, 1]
    auc_train = float(roc_auc_score(y_train, p_train))

    auc_test = None
    n_test = 0
    pos_test = None
    if X_test is not None and len(X_test) > 0:
        n_test = len(X_test)
        if len(np.unique(y_test)) > 1:
            p_test = model.predict_proba(X_test)[:, 1]
            auc_test = float(roc_auc_score(y_test, p_test))
        pos_test = float(np.mean(y_test))

    coefs = {}
    for name, w in zip(cell_cols, model.coef_[0]):
        feat, tf = name.split("__")
        coefs[(feat, tf)] = float(w)

    return {
        "element_type": element_type,
        "model": model,
        "coefficients": coefs,
        "cell_cols": cell_cols,
        "feature_cols": feat_cols,
        "n_train": int(len(y_train)),
        "n_test": int(n_test),
        "auc_train": auc_train,
        "auc_test": auc_test,
        "positive_rate_train": float(np.mean(y_train)),
        "positive_rate_test": pos_test,
        "intercept": float(model.intercept_[0]),
        "n_coefficients": len(coefs),
    }


def train_all(
    datasets: dict[str, pd.DataFrame],
    tfs: tuple = SMC_TFS,
    C: float = 1.0,
    test_split_ts: pd.Timestamp | None = None,
    zone_only: bool = False,
) -> dict[str, dict]:
    results = {}
    total_coefs = 0
    for elem in ("FVG", "fractal", "OB", "block_orders", "RDRB"):
        df = datasets.get(elem)
        if df is None or df.empty:
            print(f"  [{elem}] SKIP — empty"); results[elem] = {"error": "empty", "n_coefficients": 0}; continue
        print(f"  [{elem}] training on n={len(df)} rows...")
        res = train_one_element(df, elem, tfs=tfs, C=C, test_split_ts=test_split_ts, zone_only=zone_only)
        if "error" in res:
            print(f"    error: {res['error']}")
        else:
            total_coefs += res["n_coefficients"]
            msg = f"    coefs={res['n_coefficients']}  auc_train={res['auc_train']:.4f}"
            if res["auc_test"] is not None:
                msg += f"  auc_test={res['auc_test']:.4f}"
            msg += f"  pos_rate={res['positive_rate_train']:.3f}"
            print(msg)
        results[elem] = res
    print(f"\n  total coefficients across 5 models: {total_coefs}")
    return results


def coefficients_summary(results: dict[str, dict]) -> pd.DataFrame:
    rows = []
    for elem, res in results.items():
        if "coefficients" not in res:
            continue
        for (feat, tf), w in res["coefficients"].items():
            rows.append({"element": elem, "feature": feat, "tf": tf, "coefficient": w})
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["element", "feature", "tf"]).reset_index(drop=True)
