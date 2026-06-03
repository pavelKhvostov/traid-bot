"""Walk-forward LightGBM training для MH multi-horizon regression.

Methodology (matches prediction-algo):
  - rolling 365-day train window
  - monthly retrain (default 30 days = ~12 retrains per year)
  - 1y test period (last year of data)
  - 6 separate LGBMRegressor models (one per horizon)

Output: predictions DataFrame + evaluation metrics per horizon.

Hardware target: PC2 (i5-14600KF, 20 threads) for fast LightGBM training.
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

MH_ML = Path(__file__).resolve().parent
sys.path.insert(0, str(MH_ML))

from mh_features import build_features, TFS_8  # noqa: E402
from mh_labels import build_labels, HORIZONS_HOURS  # noqa: E402


@dataclass
class WalkForwardResult:
    predictions: pd.DataFrame                    # ts × (pred_{h}h for each horizon) + actuals
    metrics: dict[str, dict[str, float]]         # per horizon: MAE, RMSE, dir_acc, brier
    n_retrains: int
    train_window_days: int
    retrain_freq_days: int


def _evaluate(actual: np.ndarray, pred: np.ndarray) -> dict[str, float]:
    mask = ~(np.isnan(actual) | np.isnan(pred))
    if mask.sum() == 0:
        return {"mae": float("nan"), "rmse": float("nan"), "dir_acc": float("nan"),
                "n_samples": 0}
    a = actual[mask]
    p = pred[mask]
    mae = float(np.mean(np.abs(a - p)))
    rmse = float(np.sqrt(np.mean((a - p) ** 2)))
    dir_acc = float(np.mean(np.sign(a) == np.sign(p)))
    return {"mae": mae, "rmse": rmse, "dir_acc": dir_acc, "n_samples": int(mask.sum())}


def walk_forward(
    features: pd.DataFrame,
    labels: pd.DataFrame,
    train_window_days: int = 1825,    # 5 лет (canon 2026-05-29)
    retrain_freq_days: int = 30,
    test_start: pd.Timestamp | None = None,
    test_end: pd.Timestamp | None = None,
    horizons_hours: tuple[int, ...] = HORIZONS_HOURS,
    n_jobs: int = -1,
    verbose: bool = True,
) -> WalkForwardResult:
    """Walk-forward с monthly retrain для каждого horizon.

    Args:
        features, labels — выровненные DataFrame'ы по индексу 15m timestamps
        train_window_days — rolling window для тренировки (default 365d)
        retrain_freq_days — частота пересборки модели (default 30d = monthly)
        test_start, test_end — границы тестового периода (default = последний год)
        horizons_hours — горизонты прогноза в часах
        n_jobs — LightGBM n_jobs (-1 = все ядра)
    """
    if test_end is None:
        test_end = features.index[-1]
    if test_start is None:
        test_start = test_end - pd.Timedelta(days=365)

    # Align features+labels. HGBR нативно поддерживает NaN в фичах — не дропаем.
    # Только базовые требования: bw2_15m не должен быть NaN (= cold start period).
    df = features.join(labels, how="inner")
    df = df[~df["bw2_15m"].isna()]
    feature_cols = features.columns.tolist()
    if verbose:
        print(f"[wf] total aligned rows: {len(df):,}")
        print(f"[wf] feature_cols: {len(feature_cols)}")
        print(f"[wf] test period: {test_start} -> {test_end}")
        print(f"[wf] train window: {train_window_days}d, retrain every {retrain_freq_days}d")

    # Test timestamps
    test_mask = (df.index >= test_start) & (df.index <= test_end)
    test_ts = df.index[test_mask]
    if len(test_ts) == 0:
        raise ValueError("No test timestamps")

    # Result accumulator: predictions per timestamp per horizon
    pred_data = {f"pred_{h}h": np.full(len(test_ts), np.nan) for h in horizons_hours}
    actual_data = {f"actual_{h}h": np.full(len(test_ts), np.nan) for h in horizons_hours}

    ts_to_idx = {ts: i for i, ts in enumerate(test_ts)}

    # Schedule retrains
    retrain_dates = []
    cur = test_start
    while cur <= test_end:
        retrain_dates.append(cur)
        cur = cur + pd.Timedelta(days=retrain_freq_days)
    if verbose:
        print(f"[wf] retrains scheduled: {len(retrain_dates)}")

    n_retrains_done = 0
    for ri, retrain_ts in enumerate(retrain_dates):
        t0 = time.time()
        train_lo = retrain_ts - pd.Timedelta(days=train_window_days)
        train_data = df[(df.index >= train_lo) & (df.index < retrain_ts)]
        if len(train_data) < 100:
            if verbose:
                print(f"[wf]   skip retrain @ {retrain_ts}: too few train rows ({len(train_data)})")
            continue

        # Bounds for this retrain's test slice
        retrain_end = min(retrain_ts + pd.Timedelta(days=retrain_freq_days), test_end)
        slice_data = df[(df.index >= retrain_ts) & (df.index < retrain_end)]
        if len(slice_data) == 0:
            continue

        X_train = train_data[feature_cols].to_numpy()
        X_test_slice = slice_data[feature_cols].to_numpy()

        # Train + predict for each horizon
        for h in horizons_hours:
            label_col = f"pct_{h}h"
            y_train_full = train_data[label_col].to_numpy()
            train_valid = ~np.isnan(y_train_full)
            if train_valid.sum() < 100:
                continue
            model = HistGradientBoostingRegressor(
                max_iter=300,
                learning_rate=0.05,
                max_leaf_nodes=31,
                max_depth=None,
                min_samples_leaf=20,
                verbose=0,
                random_state=42,
            )
            model.fit(X_train[train_valid], y_train_full[train_valid])
            preds = model.predict(X_test_slice)

            for i, ts in enumerate(slice_data.index):
                idx = ts_to_idx.get(ts)
                if idx is not None:
                    pred_data[f"pred_{h}h"][idx] = preds[i]
                    actual_val = slice_data[label_col].iloc[i]
                    actual_data[f"actual_{h}h"][idx] = actual_val
        n_retrains_done += 1
        if verbose and ri % max(1, len(retrain_dates) // 12) == 0:
            print(f"[wf]   retrain {ri+1}/{len(retrain_dates)} @ {retrain_ts} done in {time.time()-t0:.1f}s, train_n={len(train_data)}")

    # Build predictions DataFrame
    pred_df = pd.DataFrame(pred_data, index=test_ts)
    actual_df = pd.DataFrame(actual_data, index=test_ts)
    combined = pred_df.join(actual_df)

    # Metrics per horizon
    metrics = {}
    for h in horizons_hours:
        m = _evaluate(actual_df[f"actual_{h}h"].to_numpy(), pred_df[f"pred_{h}h"].to_numpy())
        metrics[f"{h}h"] = m
        if verbose:
            print(f"[wf] H={h}h: MAE={m['mae']:.3f}%, RMSE={m['rmse']:.3f}%, dir_acc={m['dir_acc']:.3f}, N={m['n_samples']}")

    return WalkForwardResult(
        predictions=combined,
        metrics=metrics,
        n_retrains=n_retrains_done,
        train_window_days=train_window_days,
        retrain_freq_days=retrain_freq_days,
    )
