"""Quasi-sequence snapshot extraction.

For each channel time series, vectorized "snapshot at born_ms - offset" lookup
for batch of events. Uses numpy searchsorted for O(N log M) total.
"""
from __future__ import annotations
import numpy as np
import pandas as pd


# Offsets (in ms) for the 5 quasi-sequence snapshots
OFFSETS_MS = {
    "T":     0,
    "T_6h":  6 * 3600 * 1000,
    "T_1d":  24 * 3600 * 1000,
    "T_3d":  3 * 24 * 3600 * 1000,
    "T_1w":  7 * 24 * 3600 * 1000,
}


def snapshot_vectorized(
    series_df: pd.DataFrame,
    ts_col: str,
    value_cols: list[str],
    born_ms_array: np.ndarray,
    offset_ms: int = 0,
) -> dict[str, np.ndarray]:
    """For each born_ms - offset_ms, return last available value per value_col.

    Vectorized via searchsorted. Returns dict {value_col: numpy_array(len events)}.
    Missing = NaN.
    """
    if series_df.empty:
        return {c: np.full(len(born_ms_array), np.nan) for c in value_cols}

    ts = series_df[ts_col].to_numpy()
    targets = born_ms_array.astype(np.int64) - offset_ms
    # For each target, find largest idx where ts[idx] <= target
    idx = np.searchsorted(ts, targets, side="right") - 1
    valid = idx >= 0

    result = {}
    for c in value_cols:
        vals = series_df[c].to_numpy(dtype=np.float64)
        out = np.full(len(born_ms_array), np.nan)
        out[valid] = vals[idx[valid]]
        result[c] = out
    return result


def quasi_seq_features(
    series_df: pd.DataFrame,
    ts_col: str,
    value_cols: list[str],
    born_ms_array: np.ndarray,
    channel_prefix: str = "ch",
) -> dict[str, np.ndarray]:
    """Build features per channel: snapshots @ T/T-6h/T-1d/T-3d/T-1w + derivatives.

    Naming convention:
      {prefix}_{value_col}_T              raw snapshot at born_ms
      {prefix}_{value_col}_T_6h           snapshot 6h before born
      ...
      {prefix}_{value_col}_d6h            delta = T - T_6h
      {prefix}_{value_col}_d1d, d3d, d1w
      {prefix}_{value_col}_pct6h          (T-T_6h) / T_6h
      ...
      {prefix}_{value_col}_z30            z-score of T vs 30-day window
      {prefix}_{value_col}_z90            z-score vs 90-day
      {prefix}_{value_col}_above_ma30     T > 30d mean (boolean as 0/1)
    """
    out = {}
    # 1. Raw snapshots
    snaps = {}  # offset_label -> {value_col: array}
    for lbl, off in OFFSETS_MS.items():
        snaps[lbl] = snapshot_vectorized(series_df, ts_col, value_cols, born_ms_array, off)
        for vc in value_cols:
            out[f"{channel_prefix}_{vc}_{lbl}"] = snaps[lbl][vc]

    # 2. Deltas (T - T_offset)
    for off_lbl in ("T_6h", "T_1d", "T_3d", "T_1w"):
        suffix = off_lbl.split("_")[1]
        for vc in value_cols:
            t_val = snaps["T"][vc]
            o_val = snaps[off_lbl][vc]
            out[f"{channel_prefix}_{vc}_d{suffix}"] = t_val - o_val
            # pct change (safe div)
            with np.errstate(divide="ignore", invalid="ignore"):
                pct = np.where(np.abs(o_val) > 1e-12,
                                (t_val - o_val) / o_val,
                                np.nan)
            out[f"{channel_prefix}_{vc}_pct{suffix}"] = pct

    # 3. Rolling stats: z-score vs 30/90 day window
    if not series_df.empty:
        ts_arr = series_df[ts_col].to_numpy()
        for window_days, lbl in ((30, "z30"), (90, "z90")):
            window_ms = window_days * 86400 * 1000
            for vc in value_cols:
                vals = series_df[vc].to_numpy(dtype=np.float64)
                z_out = np.full(len(born_ms_array), np.nan)
                t_now = snaps["T"][vc]
                # For each event, slice [born - window, born] from series
                for i, b in enumerate(born_ms_array):
                    if np.isnan(t_now[i]):
                        continue
                    lo = np.searchsorted(ts_arr, b - window_ms, side="left")
                    hi = np.searchsorted(ts_arr, b, side="right")
                    if hi - lo < 5:  # need min sample
                        continue
                    win = vals[lo:hi]
                    mean = np.nanmean(win)
                    std = np.nanstd(win)
                    if std > 1e-12:
                        z_out[i] = (t_now[i] - mean) / std
                out[f"{channel_prefix}_{vc}_{lbl}"] = z_out

    return out
