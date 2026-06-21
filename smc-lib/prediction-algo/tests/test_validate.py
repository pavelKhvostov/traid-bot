"""Тесты для validate.py."""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from validate import reliability_bins, walk_forward


def test_reliability_bins_basic():
    preds = np.array([0.05, 0.15, 0.55, 0.85, 0.95])
    actuals = np.array([0, 0, 1, 1, 1])
    rel = reliability_bins(preds, actuals, n_bins=10)
    # каждый pred в свой bin
    assert len(rel) == 5
    assert all(rel["n"] == 1)


def test_reliability_pred_1_is_in_last_bin():
    preds = np.array([1.0])
    actuals = np.array([1])
    rel = reliability_bins(preds, actuals, n_bins=10)
    assert len(rel) == 1
    assert rel.iloc[0]["bin_lo"] == 0.9


def _synthetic_dataset(n_cuts: int = 60) -> pd.DataFrame:
    """Сгенерим простой dataset: 100 зон на cut-off, hit_D зависит от distance_pct."""
    np.random.seed(0)
    rows = []
    start = pd.Timestamp("2024-01-01", tz="UTC")
    for c in range(n_cuts):
        cut = start + pd.Timedelta(hours=12 * c)
        for k in range(100):
            dist = np.random.exponential(3.0)
            # hit_D ∝ exp(-dist); small dist → high hit
            hit_D = bool(np.random.random() < np.exp(-dist))
            hit_12h = bool(hit_D and np.random.random() < 0.6)
            side = "above" if k % 2 == 0 else "below"
            rows.append({
                "cut_off_ts": cut,
                "tf": "1h", "type": "OB", "side": side,
                "distance_pct": dist, "age_bars": 0,
                "hit_12h": hit_12h, "hit_D": hit_D,
                "direction": "long", "lo": 100, "hi": 101, "level": float("nan"),
                "width": 1.0, "mitigation_model": "wick-fill", "born_ts": cut,
                "time_to_hit_minutes": -1, "first_hit_horizon": "none",
                "first_hit_above": False, "first_hit_below": False,
            })
    return pd.DataFrame(rows)


def test_walk_forward_synthetic_beats_baseline():
    ds = _synthetic_dataset(n_cuts=120)
    # train на первой половине, test на второй
    test_start = pd.Timestamp("2024-01-30", tz="UTC")
    test_end = pd.Timestamp("2024-02-29", tz="UTC")
    r = walk_forward(
        ds,
        test_start=test_start, test_end=test_end,
        train_window_days=30, retrain_freq_days=14,
        min_count=5, alpha=1.0, verbose=False,
    )
    assert r.n_test_records > 0
    # модель должна быть лучше базы по Brier
    assert r.brier_D < r.brier_D_baseline
    # top-5 должны заметно превышать random
    assert r.top5_hit_D_mean > r.random5_hit_D_mean
