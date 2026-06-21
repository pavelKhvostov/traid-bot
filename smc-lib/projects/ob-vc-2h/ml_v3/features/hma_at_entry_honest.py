"""HMA features (HONEST INTRADAY) — fixes lookahead bug from hma_at_entry.py.

ЧТО:    same 590 features per asset event (5 derivs per (TF, L) + aggregates)
ГДЕ:    11 TFs × 10 lengths (HMA_LENS)
КОГДА:  entry_fill_ms anchor — uses PARTIAL-BAR update at this moment

LIVE logic (как PineScript показывает индикаторы в реальном времени):
  1. Find LAST FULLY CLOSED HTF bar (open + tf_ms <= entry_ms)
  2. Current 1m close at entry_ms = "partial-bar close" of in-progress bar
  3. HMA series = [closed_bar_closes, partial_close]
  4. dist_pct = (partial_close - hma_at_virtual_end) / hma * 100

This NEVER peeks into future bar closes — all data is known at entry_ms.

Slope features use HMA at (closed_idx - N) which uses ONLY closed bars (honest).
Cross/cascade features same logic.
"""
from __future__ import annotations
import math
import numpy as np

from ._common import TF_SPECS, HMA_LENS, hma_np, wma_np


def hma_value_at_virtual_partial(closes_arr: np.ndarray,
                                   closed_idx: int,
                                   partial_close: float,
                                   L: int) -> float:
    """Compute HMA-L value at virtual position (closed_idx + 1) where last
    "close" is partial_close (current 1m price for in-progress bar).

    O(L) per call — only computes the last necessary diff values.
    """
    if L < 2 or closed_idx < L - 1:
        return np.nan
    n = L
    half = max(1, n // 2)
    sqrt_n = max(1, int(round(math.sqrt(n))))

    # Need at least closed_idx >= n + sqrt_n - 2 for valid HMA
    if closed_idx < n + sqrt_n - 2:
        return np.nan

    weights_half = np.arange(1, half + 1, dtype=np.float64)
    weights_full = np.arange(1, n + 1, dtype=np.float64)
    weights_sqrt = np.arange(1, sqrt_n + 1, dtype=np.float64)
    w_half_sum = weights_half.sum()
    w_full_sum = weights_full.sum()
    w_sqrt_sum = weights_sqrt.sum()

    # virtual WMA_half: window of last `half` values ending with partial_close
    half_window = np.concatenate([
        closes_arr[closed_idx - half + 2:closed_idx + 1], [partial_close]])
    virtual_wma_half = float(np.dot(half_window, weights_half) / w_half_sum)

    # virtual WMA_full
    full_window = np.concatenate([
        closes_arr[closed_idx - n + 2:closed_idx + 1], [partial_close]])
    virtual_wma_full = float(np.dot(full_window, weights_full) / w_full_sum)

    virtual_diff = 2.0 * virtual_wma_half - virtual_wma_full

    # Need previous (sqrt_n - 1) diff values from CLOSED bars only
    diffs = np.zeros(sqrt_n, dtype=np.float64)
    for k in range(sqrt_n - 1):
        idx_in_closed = closed_idx - sqrt_n + 2 + k
        if idx_in_closed < n - 1:
            return np.nan
        # WMA_half at this closed idx
        wma_h = float(np.dot(
            closes_arr[idx_in_closed - half + 1:idx_in_closed + 1],
            weights_half) / w_half_sum)
        wma_f = float(np.dot(
            closes_arr[idx_in_closed - n + 1:idx_in_closed + 1],
            weights_full) / w_full_sum)
        diffs[k] = 2.0 * wma_h - wma_f
    diffs[sqrt_n - 1] = virtual_diff

    hma = float(np.dot(diffs, weights_sqrt) / w_sqrt_sum)
    return hma


def bars_since_cross(short_arr: np.ndarray, long_arr: np.ndarray,
                       idx: int, lookback: int = 200) -> int:
    lo = max(0, idx - lookback)
    diff = short_arr[lo:idx+1] - long_arr[lo:idx+1]
    sign_changes = np.diff(np.sign(diff))
    if (sign_changes != 0).any():
        last_change_rel = int(np.where(sign_changes != 0)[0][-1])
        return (idx - lo) - last_change_rel - 1
    return -1


def count_crosses(short_arr: np.ndarray, long_arr: np.ndarray,
                    idx: int, lookback: int = 90) -> int:
    lo = max(0, idx - lookback)
    diff = short_arr[lo:idx+1] - long_arr[lo:idx+1]
    sign_changes = np.diff(np.sign(diff))
    return int((sign_changes != 0).sum())


def build_hma_features_at_entry_honest(bars: dict[str, np.ndarray],
                                          rows_1m: np.ndarray,
                                          entry_ms_array: np.ndarray) -> dict[str, np.ndarray]:
    """HONEST INTRADAY version — uses partial-bar update at entry_ms.

    Args:
      bars: per-TF aggregates {tf_name: (N,6) array (ts, o, h, l, c, v)}
      rows_1m: 1m bars (M, 6) for 1m close lookup at entry_ms
      entry_ms_array: (n_events,) entry_fill_ms per event (-1 if no fill)
    """
    n_events = len(entry_ms_array)
    out: dict[str, np.ndarray] = {}

    ts_1m = rows_1m[:, 0].astype(np.int64)
    close_1m = rows_1m[:, 4]

    # Pre-compute closed-bar HMA series for every (tf, L)
    hma_series: dict[tuple[str, int], np.ndarray] = {}
    ts_per_tf: dict[str, np.ndarray] = {}
    close_per_tf: dict[str, np.ndarray] = {}
    for tf, bar_arr in bars.items():
        closes = bar_arr[:, 4]
        ts_arr = bar_arr[:, 0].astype(np.int64)
        ts_per_tf[tf] = ts_arr
        close_per_tf[tf] = closes
        for L in HMA_LENS:
            if L >= len(closes):
                continue
            hma_series[(tf, L)] = hma_np(closes, L)

    # ─── Step 1: 1m current price per event ────
    valid_event = entry_ms_array > 0
    price_now = np.full(n_events, np.nan)
    if valid_event.any():
        idx_1m = np.searchsorted(ts_1m, entry_ms_array[valid_event], side="right") - 1
        valid_1m = idx_1m >= 0
        event_indices = np.where(valid_event)[0]
        for ei, i1m, ok in zip(event_indices, idx_1m, valid_1m):
            if ok:
                price_now[ei] = close_1m[i1m]

    # ─── Step 2: Per-TF closed_idx (HONEST: open + tf_ms <= entry_ms) ───
    closed_idx_per_tf: dict[str, np.ndarray] = {}
    for tf, ts_arr in ts_per_tf.items():
        tf_ms = TF_SPECS[tf]
        ci = np.full(n_events, -1, dtype=np.int64)
        if valid_event.any():
            cutoff = entry_ms_array[valid_event] - tf_ms
            ci[valid_event] = np.searchsorted(ts_arr, cutoff, side="right") - 1
        closed_idx_per_tf[tf] = ci

    # ─── Step 3: Per-TF, per-length virtual partial HMA ────
    for tf, bar_arr in bars.items():
        ts_arr = ts_per_tf[tf]
        closes = close_per_tf[tf]
        closed_idx = closed_idx_per_tf[tf]
        valid = (closed_idx >= 0) & valid_event & (~np.isnan(price_now))

        for L in HMA_LENS:
            key = (tf, L)
            if key not in hma_series:
                continue
            hma_arr_closed = hma_series[key]

            # virtual HMA per event
            hma_virtual = np.full(n_events, np.nan)
            for i in np.where(valid)[0]:
                ci = int(closed_idx[i])
                pp = float(price_now[i])
                hma_virtual[i] = hma_value_at_virtual_partial(closes, ci, pp, L)

            with np.errstate(divide="ignore", invalid="ignore"):
                dist_pct = np.where(np.abs(hma_virtual) > 1e-9,
                                     (price_now - hma_virtual) / hma_virtual * 100, np.nan)

            above = np.full(n_events, np.nan)
            m_ab = ~(np.isnan(price_now) | np.isnan(hma_virtual))
            above[m_ab] = (price_now[m_ab] > hma_virtual[m_ab]).astype(np.float64)

            # Slopes: HMA_virtual - HMA_at(closed_idx - 4)/(-19) — honest closed-bar values
            slope_5 = np.full(n_events, np.nan)
            m5 = valid & (closed_idx >= 5)
            ci5 = closed_idx[m5] - 4
            slope_5[m5] = hma_virtual[m5] - hma_arr_closed[ci5]
            slope_5_pct = np.where(np.abs(hma_virtual) > 1e-9,
                                    slope_5 / hma_virtual * 100, np.nan)

            slope_20 = np.full(n_events, np.nan)
            m20 = valid & (closed_idx >= 20)
            ci20 = closed_idx[m20] - 19
            slope_20[m20] = hma_virtual[m20] - hma_arr_closed[ci20]
            slope_20_pct = np.where(np.abs(hma_virtual) > 1e-9,
                                      slope_20 / hma_virtual * 100, np.nan)

            slope_accel = slope_5_pct - slope_20_pct

            prefix = f"hma_{tf}_{L}"
            out[f"{prefix}_above"] = above
            out[f"{prefix}_dist_pct"] = dist_pct
            out[f"{prefix}_slope5_pct"] = slope_5_pct
            out[f"{prefix}_slope20_pct"] = slope_20_pct
            out[f"{prefix}_slope_accel"] = slope_accel

    # ─── Step 4: Per-TF aggregates (cross + fan) using CLOSED idx ────
    for tf, bar_arr in bars.items():
        closes = close_per_tf[tf]
        closed_idx = closed_idx_per_tf[tf]

        k78 = (tf, 78); k200 = (tf, 200)
        bsc = np.full(n_events, np.nan)
        cc90 = np.full(n_events, np.nan)
        fan_compr = np.full(n_events, np.nan)
        if k78 in hma_series and k200 in hma_series:
            for i, idx in enumerate(closed_idx):
                if idx < 200: continue
                bsc_v = bars_since_cross(hma_series[k78], hma_series[k200], idx, lookback=200)
                bsc[i] = bsc_v if bsc_v >= 0 else 200
                cc90[i] = count_crosses(hma_series[k78], hma_series[k200], idx, lookback=90)

        k9 = (tf, 9); k500 = (tf, 500)
        if k9 in hma_series and k500 in hma_series:
            for i, idx in enumerate(closed_idx):
                if idx < 0: continue
                v9 = hma_series[k9][idx]
                v500 = hma_series[k500][idx]
                cl = closes[idx] if idx < len(closes) else np.nan
                if not np.isnan(v9) and not np.isnan(v500) and not np.isnan(cl) and cl > 1e-9:
                    fan_compr[i] = (v9 - v500) / cl * 100

        out[f"hma_{tf}_bars_since_78_200"] = bsc
        out[f"hma_{tf}_cross_count_90"] = cc90
        out[f"hma_{tf}_fan_compression"] = fan_compr

    # ─── Step 5: Cross-TF aggregates ───
    for hma_L, suffix in ((200, "200"), (78, "78")):
        cnt = np.zeros(n_events); valid_cnt = np.zeros(n_events, dtype=np.int32)
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

    cascade = np.full(n_events, np.inf)
    for tf in bars.keys():
        key = f"hma_{tf}_bars_since_78_200"
        if key in out:
            arr = out[key]
            mask = ~np.isnan(arr)
            cascade[mask] = np.minimum(cascade[mask], arr[mask])
    cascade = np.where(np.isinf(cascade), np.nan, cascade)
    out["cascade_freshness_min_bars"] = cascade

    bull_count = np.zeros(n_events); valid_cnt = np.zeros(n_events, dtype=np.int32)
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
