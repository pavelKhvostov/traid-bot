"""Volatility regime + calendar features.

Volatility: ATR ratios across TFs, BB width — all HONEST closed bars.
Calendar: hour, day of week, day of month, month, week_of_month.
"""
from __future__ import annotations
import numpy as np
from datetime import datetime, timezone

from ._common import TF_SPECS


def _atr_at_closed(bars: np.ndarray, closed_idx: int, period: int = 14) -> float:
    if closed_idx < period: return np.nan
    highs = bars[:, 2]; lows = bars[:, 3]; closes = bars[:, 4]
    start = closed_idx - period + 1
    tr_vals = []
    for j in range(start, closed_idx + 1):
        if j == 0:
            tr = highs[j] - lows[j]
        else:
            tr = max(highs[j] - lows[j],
                     abs(highs[j] - closes[j-1]),
                     abs(lows[j] - closes[j-1]))
        tr_vals.append(tr)
    return float(np.mean(tr_vals))


def _bb_width_at_closed(bars: np.ndarray, closed_idx: int, period: int = 20) -> float:
    if closed_idx < period - 1: return np.nan
    closes = bars[:, 4]
    window = closes[closed_idx - period + 1:closed_idx + 1]
    mean = float(np.mean(window))
    std = float(np.std(window))
    if mean < 1e-9: return np.nan
    return (4 * std) / mean * 100   # 2σ × 2 = full width, in %


def build_volatility_features(bars: dict[str, np.ndarray],
                                entry_ms_array: np.ndarray) -> dict[str, np.ndarray]:
    n_events = len(entry_ms_array)
    out: dict[str, np.ndarray] = {}
    valid_event = entry_ms_array > 0

    selected_tfs = ["15m", "1h", "4h", "1d", "3d"]

    atr_per_tf = {}
    bb_per_tf = {}

    for tf in selected_tfs:
        if tf not in bars: continue
        bar_arr = bars[tf]
        tf_ms = TF_SPECS[tf]
        ts_arr = bar_arr[:, 0].astype(np.int64)
        closes = bar_arr[:, 4]

        # Closed idx per event (honest)
        closed_idx = np.full(n_events, -1, dtype=np.int64)
        if valid_event.any():
            cutoff = entry_ms_array[valid_event] - tf_ms
            closed_idx[valid_event] = np.searchsorted(ts_arr, cutoff, side="right") - 1
        valid = (closed_idx >= 0) & valid_event

        atr_arr = np.full(n_events, np.nan)
        bb_arr = np.full(n_events, np.nan)
        atr_pct = np.full(n_events, np.nan)

        for i in np.where(valid)[0]:
            ci = int(closed_idx[i])
            atr_v = _atr_at_closed(bar_arr, ci, period=14)
            bb_v = _bb_width_at_closed(bar_arr, ci, period=20)
            atr_arr[i] = atr_v
            bb_arr[i] = bb_v
            if not np.isnan(atr_v) and closes[ci] > 1e-9:
                atr_pct[i] = atr_v / closes[ci] * 100

        out[f"vol_{tf}_atr14_pct"] = atr_pct
        out[f"vol_{tf}_bb20_width_pct"] = bb_arr
        atr_per_tf[tf] = atr_pct

    # Cross-TF ATR ratios (regime detection)
    if "1h" in atr_per_tf and "1d" in atr_per_tf:
        with np.errstate(divide="ignore", invalid="ignore"):
            out["vol_atr_ratio_1h_1d"] = np.where(
                atr_per_tf["1d"] > 1e-9,
                atr_per_tf["1h"] / atr_per_tf["1d"], np.nan)
    if "4h" in atr_per_tf and "1d" in atr_per_tf:
        with np.errstate(divide="ignore", invalid="ignore"):
            out["vol_atr_ratio_4h_1d"] = np.where(
                atr_per_tf["1d"] > 1e-9,
                atr_per_tf["4h"] / atr_per_tf["1d"], np.nan)
    if "1h" in atr_per_tf and "4h" in atr_per_tf:
        with np.errstate(divide="ignore", invalid="ignore"):
            out["vol_atr_ratio_1h_4h"] = np.where(
                atr_per_tf["4h"] > 1e-9,
                atr_per_tf["1h"] / atr_per_tf["4h"], np.nan)

    return out


def build_calendar_features(entry_ms_array: np.ndarray) -> dict[str, np.ndarray]:
    n = len(entry_ms_array)
    hour = np.full(n, np.nan)
    day_of_week = np.full(n, np.nan)
    day_of_month = np.full(n, np.nan)
    month = np.full(n, np.nan)
    week_of_month = np.full(n, np.nan)

    for i, t in enumerate(entry_ms_array):
        if t <= 0: continue
        dt = datetime.fromtimestamp(t / 1000, tz=timezone.utc)
        hour[i] = dt.hour
        day_of_week[i] = dt.weekday()
        day_of_month[i] = dt.day
        month[i] = dt.month
        week_of_month[i] = (dt.day - 1) // 7

    return {
        "cal_hour": hour,
        "cal_day_of_week": day_of_week,
        "cal_day_of_month": day_of_month,
        "cal_month": month,
        "cal_week_of_month": week_of_month,
    }
