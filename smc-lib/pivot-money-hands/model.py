"""
Gradient Boosting classifier для прогноза pivot в 12h/24h + SHAP analysis
для feature importance и interactions.

Используем sklearn.HistGradientBoostingClassifier — нативная поддержка
категориальных, без зависимости от libomp (xgboost требует brew install libomp на macOS).
Алгоритм аналогичен xgboost. SHAP работает через TreeExplainer.

Целевые задачи:
  - pivot_in_12h_short
  - pivot_in_12h_long
  - 24h аналоги

Подход:
  - color → ordinal-encoded category
  - временной split (walk-forward, не shuffle)
  - HistGradientBoostingClassifier
  - SHAP TreeExplainer → feature_importance + interaction_values
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

from multi_tf_mh import MH_FIELDS, PIVOT_TFS

# Сколько признаков считаем "топовыми" в отчёте
TOP_K = 15


def feature_columns() -> list[str]:
    """Имена всех MH-фич: 7 TF × 4 numeric (bw2/mf/rsi_mod/stc_rsi_mod) + 7 color."""
    cols: list[str] = []
    for tf in PIVOT_TFS:
        for fld in ("bw2", "mf", "rsi_mod", "stc_rsi_mod"):
            cols.append(f"mh_{tf}_{fld}")
        cols.append(f"mh_{tf}_color")
    return cols


_COLOR_TO_INT = {None: 0, "green": 1, "white_weak_bull": 2, "white_weak_bear": 3, "red": 4, "neutral": 5}


def prepare_xy(ds: pd.DataFrame, label_col: str) -> tuple[pd.DataFrame, pd.Series]:
    cols = feature_columns()
    X = ds[cols].copy()
    for tf in PIVOT_TFS:
        X[f"mh_{tf}_color"] = X[f"mh_{tf}_color"].map(_COLOR_TO_INT).fillna(0).astype(int)
    for tf in PIVOT_TFS:
        for fld in ("bw2", "mf", "rsi_mod", "stc_rsi_mod"):
            X[f"mh_{tf}_{fld}"] = pd.to_numeric(X[f"mh_{tf}_{fld}"], errors="coerce")
    X = X.fillna(0.0)
    y = ds[label_col].astype(int)
    return X, y


@dataclass
class TrainResult:
    label: str
    n_train: int
    n_test: int
    baseline_pos_rate_test: float
    test_auc: float
    test_brier: float
    test_logloss: float
    feat_importance: pd.DataFrame    # columns: feature, gain
    top_shap: pd.DataFrame           # columns: feature, mean_abs_shap
    top_interactions: pd.DataFrame   # columns: feat_a, feat_b, mean_abs_interaction


def time_split(ds: pd.DataFrame, frac: float = 0.6) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Временной split по bar_ts — train = первые frac, test = остальное."""
    ds = ds.copy()
    ds["bar_ts"] = pd.to_datetime(ds["bar_ts"], utc=True)
    ds = ds.sort_values("bar_ts").reset_index(drop=True)
    cut = int(len(ds) * frac)
    return ds.iloc[:cut], ds.iloc[cut:]


def fit_and_eval(ds: pd.DataFrame, label_col: str, frac: float = 0.6) -> TrainResult:
    """
    Time-split → XGBClassifier → SHAP. Возвращает метрики и top-фичи/interactions.
    """
    train, test = time_split(ds, frac)
    X_tr, y_tr = prepare_xy(train, label_col)
    X_te, y_te = prepare_xy(test, label_col)

    # color колонки указываем как categorical для HGB (native support)
    cat_features = [f"mh_{tf}_color" for tf in PIVOT_TFS]
    cat_mask = [c in cat_features for c in X_tr.columns]

    clf = HistGradientBoostingClassifier(
        max_iter=300,
        max_depth=4,
        learning_rate=0.05,
        categorical_features=cat_mask,
        random_state=42,
    )
    clf.fit(X_tr, y_tr)

    p_te = clf.predict_proba(X_te)[:, 1]
    from sklearn.metrics import roc_auc_score, log_loss, brier_score_loss
    auc = roc_auc_score(y_te, p_te) if y_te.nunique() > 1 else float("nan")
    brier = brier_score_loss(y_te, p_te)
    loglossv = log_loss(y_te, p_te, labels=[0, 1])

    # Permutation feature importance — universal proxy для gain
    from sklearn.inspection import permutation_importance
    perm = permutation_importance(clf, X_te, y_te, n_repeats=5, random_state=42, n_jobs=-1)
    fi_df = pd.DataFrame({
        "feature": X_te.columns.tolist(),
        "gain": perm.importances_mean,
    }).sort_values("gain", ascending=False).reset_index(drop=True)

    # SHAP via TreeExplainer
    import shap
    explainer = shap.TreeExplainer(clf)
    n_sample = min(2000, len(X_te))
    X_sample = X_te.sample(n=n_sample, random_state=42).reset_index(drop=True)
    sv_raw = explainer.shap_values(X_sample)
    # HGB binary возвращает либо (n, k) либо (n, k, 2). Берём положительный класс.
    sv = sv_raw[1] if isinstance(sv_raw, list) else (sv_raw[..., 1] if sv_raw.ndim == 3 else sv_raw)
    feat_names = X_sample.columns.tolist()
    mean_abs = np.abs(sv).mean(axis=0)
    shap_df = pd.DataFrame({"feature": feat_names, "mean_abs_shap": mean_abs}).sort_values(
        "mean_abs_shap", ascending=False
    ).reset_index(drop=True)

    # SHAP interactions (медленно)
    int_df = pd.DataFrame(columns=["feat_a", "feat_b", "mean_abs_interaction"])
    try:
        n_int = min(300, n_sample)
        X_int = X_sample.head(n_int)
        siv_raw = explainer.shap_interaction_values(X_int)
        siv = siv_raw[1] if isinstance(siv_raw, list) else (siv_raw[..., 1] if siv_raw.ndim == 4 else siv_raw)
        mean_abs_int = np.abs(siv).mean(axis=0)
        rows = []
        k = len(feat_names)
        for i in range(k):
            for j in range(i + 1, k):
                rows.append({"feat_a": feat_names[i], "feat_b": feat_names[j], "mean_abs_interaction": float(mean_abs_int[i, j])})
        int_df = pd.DataFrame(rows).sort_values("mean_abs_interaction", ascending=False).reset_index(drop=True)
    except Exception as e:
        print(f"  (SHAP interactions skipped: {e})")

    return TrainResult(
        label=label_col,
        n_train=len(train), n_test=len(test),
        baseline_pos_rate_test=float(y_te.mean()),
        test_auc=float(auc),
        test_brier=float(brier),
        test_logloss=float(loglossv),
        feat_importance=fi_df,
        top_shap=shap_df,
        top_interactions=int_df,
    )


def print_result(r: TrainResult) -> None:
    print(f"=== {r.label} ===")
    print(f"  Train: {r.n_train}  Test: {r.n_test}  Baseline pos rate: {r.baseline_pos_rate_test:.3f}")
    print(f"  AUC: {r.test_auc:.4f}  Brier: {r.test_brier:.4f}  Logloss: {r.test_logloss:.4f}")
    print(f"\n  Top-{TOP_K} feature importance (XGB gain):")
    print(r.feat_importance.head(TOP_K).to_string(index=False))
    print(f"\n  Top-{TOP_K} SHAP |value| mean:")
    print(r.top_shap.head(TOP_K).to_string(index=False))
    print(f"\n  Top-{TOP_K} feature interactions (|SHAP-interaction| mean):")
    print(r.top_interactions.head(TOP_K).to_string(index=False))


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--in", dest="inp", required=True)
    p.add_argument("--label", default="pivot_in_12h_short")
    p.add_argument("--frac", type=float, default=0.6)
    args = p.parse_args()

    ds = pd.read_csv(args.inp)
    ds[args.label] = ds[args.label].astype(bool)
    r = fit_and_eval(ds, args.label, frac=args.frac)
    print_result(r)


if __name__ == "__main__":
    main()
