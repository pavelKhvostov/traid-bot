"""
Train 5 раздельных logistic regression моделей (L2) на per-element datasets.

Coefficients learned:
  FVG:           81 (9 features × 9 TFs)
  fractal:       81
  OB:            81
  block_orders:  72 (8 × 9)
  RDRB:          72
  --------------
  TOTAL:        387

Output: dict[element_type → fitted model + diagnostics].
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

warnings.filterwarnings("ignore", category=FutureWarning, module="sklearn")

from force_model_v2.dataset import FEATURES, SMC_TFS, expand_to_cell_wise


CANDLE_CONTEXT_FEATS = ("candle_body_atr", "candle_range_atr", "candle_direction", "prior_n_bars_trend")


def train_one_element(
    df: pd.DataFrame,
    element_type: str,
    tfs: tuple = SMC_TFS,
    C: float = 1.0,
    test_split_ts: pd.Timestamp | None = None,
    zone_only: bool = False,
) -> dict:
    """Train LogisticRegression(L2) на одном element-датасете.

    test_split_ts: если задан — out-of-sample split (train < ts < test); иначе in-sample AUC.

    Returns:
      {
        "model": LogisticRegression,
        "coefficients": dict[(feature, tf) → float],
        "n_train": int,
        "n_test": int,
        "auc_train": float,
        "auc_test": float | None,
        "positive_rate_train": float,
        "positive_rate_test": float | None,
        "intercept": float,
      }
    """
    if df.empty:
        return {"error": "empty dataset", "model": None}

    feat_cols = list(FEATURES[element_type])
    if zone_only:
        feat_cols = [f for f in feat_cols if f not in CANDLE_CONTEXT_FEATS]
    expanded = expand_to_cell_wise(df, feat_cols, tfs=tfs)
    cell_cols = [c for c in expanded.columns if c not in ("target", "candle_open_ts")]

    if test_split_ts is not None:
        train_mask = expanded["candle_open_ts"] < test_split_ts
        test_mask = ~train_mask
        X_train = expanded.loc[train_mask, cell_cols].to_numpy()
        y_train = expanded.loc[train_mask, "target"].to_numpy()
        X_test = expanded.loc[test_mask, cell_cols].to_numpy()
        y_test = expanded.loc[test_mask, "target"].to_numpy()
    else:
        X_train = expanded[cell_cols].to_numpy()
        y_train = expanded["target"].to_numpy()
        X_test = None
        y_test = None

    if len(np.unique(y_train)) < 2:
        return {"error": "only one class in target", "n_train": len(y_train)}

    model = LogisticRegression(
        C=C,
        max_iter=1000,
        solver="lbfgs",
    )
    model.fit(X_train, y_train)

    p_train = model.predict_proba(X_train)[:, 1]
    auc_train = roc_auc_score(y_train, p_train) if len(np.unique(y_train)) > 1 else None

    auc_test = None
    n_test = 0
    pos_test = None
    if X_test is not None and len(X_test) > 0:
        n_test = len(X_test)
        if len(np.unique(y_test)) > 1:
            p_test = model.predict_proba(X_test)[:, 1]
            auc_test = roc_auc_score(y_test, p_test)
        pos_test = float(np.mean(y_test))

    # Pack coefficients: cell_cols имеют формат "{feature}__{tf}"
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
        "auc_train": float(auc_train) if auc_train is not None else None,
        "auc_test": float(auc_test) if auc_test is not None else None,
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
    """Train 5 моделей. Returns {element_type: result_dict}."""
    results = {}
    total_coefs = 0
    for elem in ("FVG", "fractal", "OB", "block_orders", "RDRB"):
        df = datasets.get(elem)
        if df is None or df.empty:
            print(f"  [{elem}] SKIP — empty dataset")
            results[elem] = {"error": "empty", "n_coefficients": 0}
            continue
        print(f"  [{elem}] training on n={len(df)} rows...")
        res = train_one_element(df, elem, tfs=tfs, C=C, test_split_ts=test_split_ts, zone_only=zone_only)
        if "error" in res:
            print(f"    error: {res['error']}")
        else:
            n_coefs = res["n_coefficients"]
            total_coefs += n_coefs
            print(f"    coefs={n_coefs}  auc_train={res['auc_train']:.4f}"
                  + (f"  auc_test={res['auc_test']:.4f}" if res["auc_test"] is not None else "")
                  + f"  pos_rate={res['positive_rate_train']:.3f}")
        results[elem] = res
    print(f"\n  total coefficients across 5 models: {total_coefs} (target: 387)")
    return results


def coefficients_summary(results: dict[str, dict]) -> pd.DataFrame:
    """Свести коэффициенты всех моделей в одну таблицу."""
    rows = []
    for elem, res in results.items():
        if "coefficients" not in res:
            continue
        for (feat, tf), w in res["coefficients"].items():
            rows.append({
                "element": elem,
                "feature": feat,
                "tf": tf,
                "coefficient": w,
            })
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    return df.sort_values(["element", "feature", "tf"]).reset_index(drop=True)
