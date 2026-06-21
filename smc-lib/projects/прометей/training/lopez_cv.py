"""Lopez de Prado Purged K-Fold + embargo (canon for time-series ML).

Reference: «Advances in Financial Machine Learning» Ch. 7.

Why standard K-Fold leaks:
  - Samples близко по времени имеют overlapping features (e.g. lagged price).
  - Test-period samples могут сидеть в train-period features → leak.

Solution:
  - PURGE: drop train samples whose target horizon overlaps test period.
  - EMBARGO: drop train samples within `h` periods AFTER test (to absorb
    forward-induced correlation).

This implementation is t0-based (each sample has scalar t0_unix), assumes
horizon=H bars per sample, and applies symmetric purge+embargo.
"""
from __future__ import annotations

import numpy as np


def purged_kfold_splits(
    t0_unix: np.ndarray,
    n_splits: int = 5,
    horizon_seconds: int = 24 * 3600,
    embargo_seconds: int = 24 * 3600,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Yield (train_idx, test_idx) per fold.

    Args:
        t0_unix: shape (N,) — cutoff timestamps in seconds (sorted ascending).
        n_splits: K folds (chronological blocks).
        horizon_seconds: target lookahead per sample (used for purge).
        embargo_seconds: extra purge after test end.

    Returns:
        List of (train_idx, test_idx) numpy arrays per fold.
    """
    N = len(t0_unix)
    assert np.all(np.diff(t0_unix) >= 0), "t0_unix must be sorted ascending"

    # Test blocks = K equal chronological chunks
    fold_size = N // n_splits
    splits: list[tuple[np.ndarray, np.ndarray]] = []
    for k in range(n_splits):
        test_start = k * fold_size
        test_end = (k + 1) * fold_size if k < n_splits - 1 else N
        test_idx = np.arange(test_start, test_end)

        test_t_min = t0_unix[test_idx[0]]
        test_t_max = t0_unix[test_idx[-1]]

        # Purge any train sample whose horizon overlaps [test_t_min, test_t_max]:
        #   sample t covers [t, t + horizon]. Overlaps test ↔
        #     t + horizon ≥ test_t_min AND t ≤ test_t_max
        # Embargo: train sample t > test_t_max but within `embargo` → drop
        purge_lo = test_t_min - horizon_seconds  # earliest train t whose horizon enters test
        embargo_hi = test_t_max + embargo_seconds  # latest train t to embargo

        train_mask = np.ones(N, dtype=bool)
        train_mask[test_idx] = False
        # Purge before-test
        in_purge = (t0_unix >= purge_lo) & (t0_unix < test_t_min)
        train_mask &= ~in_purge
        # Embargo after-test
        in_embargo = (t0_unix > test_t_max) & (t0_unix <= embargo_hi)
        train_mask &= ~in_embargo

        train_idx = np.where(train_mask)[0]
        splits.append((train_idx, test_idx))
    return splits


def time_decay_weights(
    t0_unix: np.ndarray,
    half_life_seconds: int = 90 * 24 * 3600,
) -> np.ndarray:
    """Exponential decay weights: newer samples get higher weight.

    weight = exp(-(t_max - t) * ln(2) / half_life)
    weight=1 для самых новых, weight=0.5 для half_life-старых.
    """
    t_max = t0_unix.max()
    decay_const = np.log(2) / half_life_seconds
    w = np.exp(-(t_max - t0_unix) * decay_const)
    return w
