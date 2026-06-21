"""Cross-TF HMA cross features — HONEST INTRADAY live values.

15 hand-picked pairs (tf_A, L_A) × (tf_B, L_B). For each pair, 4 features:
  1. cross_above            — current sign(HMA_A_live - HMA_B_live) > 0
  2. cross_dist_pct         — (HMA_A_live - HMA_B_live) / HMA_B_live * 100
  3. cross_hours_since_flip — hours since last sign flip of (A − B) on 1h grid
  4. cross_count_30d        — number of sign flips in last 30 days (720 × 1h bars)

All HMA values are HONEST:
  - Live "now" values use INTRADAY partial-bar (closed HTF closes + 1m partial)
  - Historical sign flip detection uses only CLOSED HTF bars (no future peek)
"""
from __future__ import annotations
import math
import numpy as np

from ._common import TF_SPECS, hma_np
from .hma_at_entry_honest import hma_value_at_virtual_partial


# 15 pairs designed for cascade momentum signals
CROSS_PAIRS: list[tuple[str, int, str, int]] = [
    # Step-up (LTF slow vs HTF fast)
    ("15m", 21, "1h", 9),
    ("20m", 21, "90m", 9),
    ("1h", 21, "2h", 9),
    ("2h", 21, "4h", 9),     # canonical example
    ("4h", 21, "12h", 9),
    ("12h", 21, "1d", 9),
    ("1d", 21, "3d", 9),
    # Same-length cross-TF
    ("15m", 9, "1h", 9),
    ("1h", 9, "4h", 9),
    ("4h", 9, "1d", 9),
    ("1d", 9, "3d", 9),
    # Wide gap
    ("15m", 9, "1d", 21),
    ("1h", 9, "3d", 21),
    ("2h", 14, "12h", 78),
    ("4h", 21, "1d", 200),
]

GRID_MS = 60 * 60 * 1000          # 1h grid for sign-change detection
LOOKBACK_30D_BARS = 30 * 24       # 30 days × 24h = 720 1h bars


def build_cross_tf_features(bars: dict[str, np.ndarray],
                              rows_1m: np.ndarray,
                              entry_ms_array: np.ndarray) -> dict[str, np.ndarray]:
    """Honest live cross-TF cross features at entry_fill_ms."""
    n_events = len(entry_ms_array)
    out: dict[str, np.ndarray] = {}

    ts_1m = rows_1m[:, 0].astype(np.int64)
    close_1m = rows_1m[:, 4]

    # Precompute HMA series on closed bars + ts arrays per (tf, L)
    hma_series: dict[tuple[str, int], np.ndarray] = {}
    closes_per_tf: dict[str, np.ndarray] = {}
    ts_per_tf: dict[str, np.ndarray] = {}
    needed_keys = set()
    for tf_A, L_A, tf_B, L_B in CROSS_PAIRS:
        needed_keys.add((tf_A, L_A))
        needed_keys.add((tf_B, L_B))
    for tf in {k[0] for k in needed_keys}:
        bar_arr = bars[tf]
        closes = bar_arr[:, 4]
        ts_arr = bar_arr[:, 0].astype(np.int64)
        closes_per_tf[tf] = closes
        ts_per_tf[tf] = ts_arr
    for (tf, L) in needed_keys:
        closes = closes_per_tf[tf]
        if L < len(closes):
            hma_series[(tf, L)] = hma_np(closes, L)

    # 1m current price per event
    valid_event = entry_ms_array > 0
    price_now = np.full(n_events, np.nan)
    if valid_event.any():
        idx_1m = np.searchsorted(ts_1m, entry_ms_array[valid_event], side="right") - 1
        for ei, i1m in zip(np.where(valid_event)[0], idx_1m):
            if i1m >= 0:
                price_now[ei] = close_1m[i1m]

    # Build common 1h grid covering data
    grid_start = int(min(ts_per_tf[tf][0] for tf in closes_per_tf))
    grid_start = grid_start - (grid_start % GRID_MS) + GRID_MS
    grid_end = int(max(ts_per_tf[tf][-1] + TF_SPECS[tf] for tf in closes_per_tf))
    grid_ts = np.arange(grid_start, grid_end, GRID_MS, dtype=np.int64)
    n_grid = len(grid_ts)

    # For each pair: compute 1h-grid resampled HMA values from CLOSED bars
    # then sign-change vector for the pair
    pair_diff_sign_grid: dict[int, np.ndarray] = {}  # idx → sign array on grid

    for pair_idx, (tf_A, L_A, tf_B, L_B) in enumerate(CROSS_PAIRS):
        hma_A = hma_series.get((tf_A, L_A))
        hma_B = hma_series.get((tf_B, L_B))
        if hma_A is None or hma_B is None:
            pair_diff_sign_grid[pair_idx] = np.full(n_grid, 0, dtype=np.int8)
            continue

        ts_A = ts_per_tf[tf_A]
        ts_B = ts_per_tf[tf_B]
        tf_ms_A = TF_SPECS[tf_A]
        tf_ms_B = TF_SPECS[tf_B]

        # At each grid time t, find last CLOSED bar of TF_A: open + tf_ms_A <= t
        # ⟺ open <= t - tf_ms_A
        cutoff_A = grid_ts - tf_ms_A
        idx_A = np.searchsorted(ts_A, cutoff_A, side="right") - 1
        cutoff_B = grid_ts - tf_ms_B
        idx_B = np.searchsorted(ts_B, cutoff_B, side="right") - 1

        valid = (idx_A >= 0) & (idx_B >= 0)
        valid &= (idx_A < len(hma_A)) & (idx_B < len(hma_B))

        diff_grid = np.full(n_grid, np.nan)
        if valid.any():
            a_vals = hma_A[idx_A[valid]]
            b_vals = hma_B[idx_B[valid]]
            diff_grid[valid] = a_vals - b_vals

        # Sign: 1 if positive, -1 if negative, 0 if nan
        sign_grid = np.where(
            np.isnan(diff_grid), 0,
            np.where(diff_grid > 0, 1, -1)
        ).astype(np.int8)
        pair_diff_sign_grid[pair_idx] = sign_grid

    # For each event, compute features for each pair
    for pair_idx, (tf_A, L_A, tf_B, L_B) in enumerate(CROSS_PAIRS):
        sign_grid = pair_diff_sign_grid[pair_idx]
        # Pre-compute sign-change positions for the grid
        diff_sign = np.diff(sign_grid.astype(np.int16))
        change_grid = (diff_sign != 0) & (sign_grid[:-1] != 0) & (sign_grid[1:] != 0)
        change_idx_grid = np.where(change_grid)[0]  # positions where flip just happened
        change_set_sorted = change_idx_grid  # already sorted

        feat_above = np.full(n_events, np.nan)
        feat_dist = np.full(n_events, np.nan)
        feat_hsf = np.full(n_events, np.nan)
        feat_c30 = np.full(n_events, np.nan)

        for ei in np.where(valid_event)[0]:
            pp = price_now[ei]
            if np.isnan(pp): continue
            t_event = int(entry_ms_array[ei])

            # LIVE HMA values at entry_ms (intraday partial)
            ts_A = ts_per_tf[tf_A]; tf_ms_A = TF_SPECS[tf_A]
            ts_B = ts_per_tf[tf_B]; tf_ms_B = TF_SPECS[tf_B]
            closes_A = closes_per_tf[tf_A]
            closes_B = closes_per_tf[tf_B]
            ci_A = int(np.searchsorted(ts_A, t_event - tf_ms_A, side="right") - 1)
            ci_B = int(np.searchsorted(ts_B, t_event - tf_ms_B, side="right") - 1)
            if ci_A < L_A - 1 or ci_B < L_B - 1: continue

            hma_A_live = hma_value_at_virtual_partial(closes_A, ci_A, pp, L_A)
            hma_B_live = hma_value_at_virtual_partial(closes_B, ci_B, pp, L_B)
            if np.isnan(hma_A_live) or np.isnan(hma_B_live): continue

            diff_live = hma_A_live - hma_B_live
            feat_above[ei] = 1.0 if diff_live > 0 else 0.0
            if abs(hma_B_live) > 1e-9:
                feat_dist[ei] = diff_live / hma_B_live * 100

            # hours_since_flip + count_30d using 1h grid (CLOSED-bar based)
            grid_idx_event = int(np.searchsorted(grid_ts, t_event, side="right") - 1)
            if grid_idx_event < 1: continue
            # last flip before or at grid_idx_event
            insert_pos = np.searchsorted(change_set_sorted, grid_idx_event, side="right")
            if insert_pos == 0:
                feat_hsf[ei] = float(grid_idx_event)  # no flip detected yet
            else:
                last_change_idx = int(change_set_sorted[insert_pos - 1])
                feat_hsf[ei] = float(grid_idx_event - last_change_idx)
            # count flips in last 720 hours
            lo = grid_idx_event - LOOKBACK_30D_BARS
            in_window = (change_set_sorted >= max(0, lo)) & (change_set_sorted <= grid_idx_event)
            feat_c30[ei] = float(in_window.sum())

        name = f"cross_{tf_A}_{L_A}__{tf_B}_{L_B}"
        out[f"{name}_above"] = feat_above
        out[f"{name}_dist_pct"] = feat_dist
        out[f"{name}_hours_since_flip"] = feat_hsf
        out[f"{name}_count_30d"] = feat_c30

    return out
