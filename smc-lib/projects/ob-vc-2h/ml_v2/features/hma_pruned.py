"""HMA pruned + evolution features.

Per-TF × per-length:
  - above       (close > HMA bool)
  - dist_pct    (close - HMA) / HMA × 100
  - slope5_pct  (HMA[i] - HMA[i-5]) / HMA × 100
  - slope20_pct (HMA[i] - HMA[i-20]) / HMA × 100
  - slope_accel (slope5 - slope20) — anticipatory signal

Per-TF evolution:
  - bars_since_cross_78_200  (recency of fast/slow cross)
  - cross_count_90           (chop vs trend, in last 90 bars)
  - fan_compression          (HMA_9 - HMA_500) / close × 100
  - fan_compression_z30      (compression z-score over 30 bars)

Cross-TF aggregates:
  - aligned_count_200  (TFs where close > HMA-200)
  - aligned_count_78
  - slope_coherence_200_bull_pct
  - cascade_freshness  (min bars_since_cross_78_200 across TFs)
"""
from __future__ import annotations
import numpy as np
import pandas as pd

from ._common import TF_SPECS, HMA_LENS, hma_np, find_idx_at_or_before


def bars_since_cross(short_arr: np.ndarray, long_arr: np.ndarray, idx: int, lookback: int = 200) -> int:
    """Find idx of most recent cross between short and long HMA arrays, walking back from idx."""
    lo = max(0, idx - lookback)
    diff = short_arr[lo:idx+1] - long_arr[lo:idx+1]
    sign_changes = np.diff(np.sign(diff))
    if (sign_changes != 0).any():
        # Last sign change
        last_change_rel = int(np.where(sign_changes != 0)[0][-1])
        return (idx - lo) - last_change_rel - 1
    return -1  # no cross in window


def count_crosses(short_arr: np.ndarray, long_arr: np.ndarray, idx: int, lookback: int = 90) -> int:
    """Count zero-crossings of (short - long) in last lookback bars."""
    lo = max(0, idx - lookback)
    diff = short_arr[lo:idx+1] - long_arr[lo:idx+1]
    sign_changes = np.diff(np.sign(diff))
    return int((sign_changes != 0).sum())


def build_hma_features_for_asset(bars: dict[str, np.ndarray],
                                   born_ms_array: np.ndarray) -> dict[str, np.ndarray]:
    """For each event born_ms, compute pruned HMA + evolution feature dict."""
    n_events = len(born_ms_array)
    out = {}

    # Pre-compute HMA series for every (tf, L)
    hma_series = {}
    ts_per_tf = {}
    close_per_tf = {}
    for tf, bar_arr in bars.items():
        closes = bar_arr[:, 4]
        ts_arr = bar_arr[:, 0].astype(np.int64)
        ts_per_tf[tf] = ts_arr
        close_per_tf[tf] = closes
        for L in HMA_LENS:
            if L >= len(closes):
                continue
            hma_series[(tf, L)] = hma_np(closes, L)

    # ─── Per-TF, per-length features ─────
    for tf, bar_arr in bars.items():
        ts_arr = ts_per_tf[tf]
        closes = close_per_tf[tf]

        # For each event, idx into this TF
        idx_at_event = np.searchsorted(ts_arr, born_ms_array, side="right") - 1
        valid = idx_at_event >= 0

        # Close at event
        close_at_event = np.full(n_events, np.nan)
        close_at_event[valid] = closes[idx_at_event[valid]]

        for L in HMA_LENS:
            key = (tf, L)
            if key not in hma_series:
                continue
            hma_arr = hma_series[key]

            val_now = np.full(n_events, np.nan)
            val_now[valid] = hma_arr[idx_at_event[valid]]

            with np.errstate(divide="ignore", invalid="ignore"):
                # dist_pct
                dist_pct = np.where(np.abs(val_now) > 1e-9,
                                     (close_at_event - val_now) / val_now * 100,
                                     np.nan)
                # above
                above = (close_at_event > val_now).astype(np.float64)
                above[np.isnan(val_now) | np.isnan(close_at_event)] = np.nan

                # slope5_pct
                slope_5 = np.full(n_events, np.nan)
                m5 = valid & (idx_at_event >= 5)
                slope_5[m5] = hma_arr[idx_at_event[m5]] - hma_arr[idx_at_event[m5] - 5]
                slope_5_pct = np.where(np.abs(val_now) > 1e-9,
                                        slope_5 / val_now * 100,
                                        np.nan)

                # slope20_pct
                slope_20 = np.full(n_events, np.nan)
                m20 = valid & (idx_at_event >= 20)
                slope_20[m20] = hma_arr[idx_at_event[m20]] - hma_arr[idx_at_event[m20] - 20]
                slope_20_pct = np.where(np.abs(val_now) > 1e-9,
                                          slope_20 / val_now * 100,
                                          np.nan)

                # slope_accel (anticipatory): slope5 - slope20
                slope_accel = slope_5_pct - slope_20_pct

            prefix = f"hma_{tf}_{L}"
            out[f"{prefix}_above"] = above
            out[f"{prefix}_dist_pct"] = dist_pct
            out[f"{prefix}_slope5_pct"] = slope_5_pct
            out[f"{prefix}_slope20_pct"] = slope_20_pct
            out[f"{prefix}_slope_accel"] = slope_accel

    # ─── Per-TF evolution (cross + fan) ────
    for tf, bar_arr in bars.items():
        ts_arr = ts_per_tf[tf]
        closes = close_per_tf[tf]
        idx_at_event = np.searchsorted(ts_arr, born_ms_array, side="right") - 1

        # bars_since_cross_78_200 and cross_count_90
        k78 = (tf, 78)
        k200 = (tf, 200)
        bsc = np.full(n_events, np.nan)
        cc90 = np.full(n_events, np.nan)
        fan_compr = np.full(n_events, np.nan)
        if k78 in hma_series and k200 in hma_series:
            for i, idx in enumerate(idx_at_event):
                if idx < 200:
                    continue
                bsc_v = bars_since_cross(hma_series[k78], hma_series[k200], idx, lookback=200)
                bsc[i] = bsc_v if bsc_v >= 0 else 200  # clip max
                cc90[i] = count_crosses(hma_series[k78], hma_series[k200], idx, lookback=90)

        # fan_compression: (HMA_9 - HMA_500) at born / close × 100
        k9 = (tf, 9); k500 = (tf, 500)
        if k9 in hma_series and k500 in hma_series:
            for i, idx in enumerate(idx_at_event):
                if idx < 0:
                    continue
                v9 = hma_series[k9][idx]
                v500 = hma_series[k500][idx]
                if not np.isnan(v9) and not np.isnan(v500) and closes[idx] > 1e-9:
                    fan_compr[i] = (v9 - v500) / closes[idx] * 100

        out[f"hma_{tf}_bars_since_78_200"] = bsc
        out[f"hma_{tf}_cross_count_90"] = cc90
        out[f"hma_{tf}_fan_compression"] = fan_compr

    # ─── Cross-TF aggregates ───────────
    for hma_L, suffix in ((200, "200"), (78, "78")):
        cnt = np.zeros(n_events)
        valid_cnt = np.zeros(n_events, dtype=np.int32)
        for tf in bars.keys():
            key = f"hma_{tf}_{hma_L}_above"
            if key in out:
                arr = out[key]
                v = ~np.isnan(arr)
                cnt[v] += arr[v]
                valid_cnt[v] += 1
        cnt = np.where(valid_cnt > 0, cnt, np.nan)
        out[f"aligned_count_{suffix}"] = cnt
        out[f"aligned_count_{suffix}_pct"] = np.where(valid_cnt > 0, cnt / valid_cnt, np.nan)

    # Cascade freshness: min(bars_since_cross_78_200) across TFs
    cascade = np.full(n_events, np.inf)
    for tf in bars.keys():
        key = f"hma_{tf}_bars_since_78_200"
        if key in out:
            arr = out[key]
            mask = ~np.isnan(arr)
            cascade[mask] = np.minimum(cascade[mask], arr[mask])
    cascade = np.where(np.isinf(cascade), np.nan, cascade)
    out["cascade_freshness_min_bars"] = cascade

    # Slope coherence: count of TFs with bull slope on HMA-200
    bull_count = np.zeros(n_events)
    valid_cnt = np.zeros(n_events, dtype=np.int32)
    for tf in bars.keys():
        key = f"hma_{tf}_200_slope5_pct"
        if key in out:
            arr = out[key]
            v = ~np.isnan(arr)
            bull_count[v] += (arr[v] > 0).astype(np.float64)
            valid_cnt[v] += 1
    out["slope_coherence_200_bull_count"] = np.where(valid_cnt > 0, bull_count, np.nan)
    out["slope_coherence_200_bull_pct"] = np.where(valid_cnt > 0, bull_count / valid_cnt, np.nan)

    return out
