"""Wait-window summary features — describe chart segment [born_ms → entry_fill_ms].

КРИТИЧНО: wait_touched_sl_before_entry — invalidates setup, ML must learn to skip.

Features:
  fill_delay_min                   minutes from born to entry_touch
  fill_delay_bars_2h               same in 2h-bar count
  wait_max_high_pct                (max_high_in_window - entry) / entry × 100
  wait_min_low_pct                 (min_low_in_window - entry) / entry × 100
  wait_touched_sl_before_entry     ⚠ bool: did price reach SL before entry
  wait_atr_change_pct              ATR at entry / ATR at born
  wait_volume_total                sum of volume in window
  wait_volume_spike_occurred       bool: z>2 spike in window
  wait_directional_efficiency      |net_move| / sum_abs_changes
  wait_net_move_pct                (close_at_entry - close_at_born) / close_at_born
  wait_bars_count_15m, _1h, _4h    how many bars formed during wait
  wait_aligned_200_change          aligned_count_200 (at entry) - (at born)
  wait_above_200_changes_count     for HMA-200, how many TFs flipped above/below status
"""
from __future__ import annotations
import numpy as np

from ._common import TF_SPECS


def build_wait_window_features(rows_1m: np.ndarray,
                                  born_ms_array: np.ndarray,
                                  entry_ms_array: np.ndarray,
                                  sl_levels: np.ndarray,
                                  entry_levels: np.ndarray,
                                  directions: np.ndarray) -> dict[str, np.ndarray]:
    """For each event with valid entry_ms, compute wait-window stats.

    Events without fill (entry_ms <= 0): features = NaN.
    """
    n_events = len(born_ms_array)
    ts_1m = rows_1m[:, 0].astype(np.int64)
    h_1m = rows_1m[:, 2]
    l_1m = rows_1m[:, 3]
    c_1m = rows_1m[:, 4]
    v_1m = rows_1m[:, 5]

    out = {
        "fill_delay_min": np.full(n_events, np.nan),
        "wait_max_high_pct": np.full(n_events, np.nan),
        "wait_min_low_pct": np.full(n_events, np.nan),
        "wait_touched_sl_before_entry": np.full(n_events, np.nan),
        "wait_volume_total": np.full(n_events, np.nan),
        "wait_directional_efficiency": np.full(n_events, np.nan),
        "wait_net_move_pct": np.full(n_events, np.nan),
        "wait_bars_count_15m": np.full(n_events, np.nan),
        "wait_bars_count_1h": np.full(n_events, np.nan),
        "wait_bars_count_4h": np.full(n_events, np.nan),
        "wait_volatility_change_pct": np.full(n_events, np.nan),
    }

    for i, (b_ms, e_ms, sl, entry, direction) in enumerate(zip(
            born_ms_array, entry_ms_array, sl_levels, entry_levels, directions)):
        if e_ms <= 0 or e_ms <= b_ms:
            continue
        fill_delay_min = (e_ms - b_ms) / 60_000
        out["fill_delay_min"][i] = fill_delay_min

        # Slice 1m window [born, entry] — INCLUDE touch bar for overshoot detection
        i_start = int(np.searchsorted(ts_1m, b_ms, side="left"))
        i_end = int(np.searchsorted(ts_1m, e_ms, side="right"))
        if i_end <= i_start:
            continue
        win_h = h_1m[i_start:i_end]
        win_l = l_1m[i_start:i_end]
        win_c = c_1m[i_start:i_end]
        win_v = v_1m[i_start:i_end]

        if entry > 1e-9:
            out["wait_max_high_pct"][i] = (win_h.max() - entry) / entry * 100
            out["wait_min_low_pct"][i] = (win_l.min() - entry) / entry * 100

        # CRITICAL: did price spike to SL during wait (direction-aware)
        # LONG: SL below entry. Spike means low <= SL (price grabbed deep)
        # SHORT: SL above entry. Spike means high >= SL (price spiked up)
        if direction == "long":
            out["wait_touched_sl_before_entry"][i] = float((win_l <= sl).any())
        else:  # short
            out["wait_touched_sl_before_entry"][i] = float((win_h >= sl).any())

        out["wait_volume_total"][i] = float(win_v.sum())

        # Directional efficiency
        diffs = np.diff(win_c)
        total_abs_move = np.abs(diffs).sum()
        net_move = win_c[-1] - win_c[0]
        if total_abs_move > 1e-9:
            out["wait_directional_efficiency"][i] = abs(net_move) / total_abs_move
        if win_c[0] > 1e-9:
            out["wait_net_move_pct"][i] = net_move / win_c[0] * 100

        # Bar counts (1m bars converted to TF-count proxy)
        bars_count_1m = i_end - i_start
        out["wait_bars_count_15m"][i] = bars_count_1m / 15
        out["wait_bars_count_1h"][i] = bars_count_1m / 60
        out["wait_bars_count_4h"][i] = bars_count_1m / 240

        # Volatility change (range of last 30 1m bars at entry vs range at born)
        if i_start + 30 < len(ts_1m) and i_end + 30 < len(ts_1m):
            rng_born = (h_1m[i_start:i_start+30].max() - l_1m[i_start:i_start+30].min())
            rng_entry = (h_1m[max(0, i_end-30):i_end].max() - l_1m[max(0, i_end-30):i_end].min())
            if rng_born > 1e-9:
                out["wait_volatility_change_pct"][i] = (rng_entry - rng_born) / rng_born * 100

    return out
