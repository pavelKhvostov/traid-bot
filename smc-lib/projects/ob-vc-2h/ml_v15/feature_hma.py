"""Rich HMA feature pack — numpy-vectorized.

For each event (born_ms, asset):
  - HMA values on 10 TFs × 14 lengths = 140 raw values
  - Derived per (TF, length): above_hma, dist_pct, slope_5, slope_20, slope_z
  - Per-TF aggregates: fan_pct, stack_above, stack_below
  - Cross-TF: aligned_count_200, aligned_count_78, slope_coherence

Total feature count: ~700 per asset event.
"""
from __future__ import annotations
import math
import pathlib
import csv
from datetime import datetime, timezone

import numpy as np
import pandas as pd

# TF specs
TF_SPECS = {
    "15m":  15 * 60_000,
    "1h":   60 * 60_000,
    "2h":  120 * 60_000,
    "4h":  240 * 60_000,
    "6h":  360 * 60_000,
    "12h": 720 * 60_000,
    "1d":  1440 * 60_000,
    "2d":  2880 * 60_000,
    "3d":  4320 * 60_000,
    "w":   7 * 1440 * 60_000,
}
HMA_LENS = [9, 14, 21, 34, 50, 55, 78, 89, 100, 144, 200, 233, 365, 500]
MONDAY_ANCHOR_MS = 96 * 3600 * 1000


# ─── 1m loaders ─────────────────────────────────────────────
START_MS = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)


def load_1m(symbol: str) -> np.ndarray:
    """Return (N, 5) array: [ts_ms, open, high, low, close]."""
    path = pathlib.Path.home() / f"traid-bot/data/{symbol}_1m_vic_vadim.csv"
    rows = []
    with path.open() as f:
        rd = csv.reader(f); next(rd)
        for r in rd:
            t = int(datetime.fromisoformat(r[0]).timestamp() * 1000)
            if t < START_MS: continue
            rows.append((t, float(r[1]), float(r[2]), float(r[3]), float(r[4])))
    return np.array(rows, dtype=np.float64)


def aggregate(rows_1m: np.ndarray, tf_ms: int, anchor: int = 0) -> np.ndarray:
    """Aggregate to TF. Return (N, 5) = [open_ms, o, h, l, c]."""
    ts = rows_1m[:, 0].astype(np.int64)
    bucket = ts - ((ts - anchor) % tf_ms)
    # Find bucket boundaries
    diff = np.diff(bucket, prepend=bucket[0] - 1)
    starts = np.where(diff != 0)[0]
    ends = np.append(starts[1:], len(bucket))
    n = len(starts)
    out = np.empty((n, 5))
    out[:, 0] = bucket[starts]
    out[:, 1] = rows_1m[starts, 1]                          # open
    # h, l, c per bucket — use np.maximum.reduceat / minimum.reduceat
    out[:, 2] = np.maximum.reduceat(rows_1m[:, 2], starts)  # high
    out[:, 3] = np.minimum.reduceat(rows_1m[:, 3], starts)  # low
    out[:, 4] = rows_1m[ends - 1, 4]                        # close
    return out


# ─── Vectorized HMA (numpy) ────────────────────────────────
def wma_np(x: np.ndarray, n: int) -> np.ndarray:
    """Weighted MA over array x with linear weights (1..n)."""
    if n < 1 or len(x) < n:
        return np.full(len(x), np.nan)
    weights = np.arange(1, n + 1, dtype=np.float64)
    weight_sum = weights.sum()
    # Convolve: weighted moving sum
    # numpy convolve uses reversed weights → use weights[::-1] for forward-rolling
    rolling = np.convolve(x, weights[::-1], mode="valid") / weight_sum
    out = np.full(len(x), np.nan)
    out[n - 1:] = rolling
    return out


def hma_np(x: np.ndarray, n: int) -> np.ndarray:
    """Hull MA = WMA(2 * WMA(x, n/2) - WMA(x, n), sqrt(n))."""
    if n < 2 or len(x) < n:
        return np.full(len(x), np.nan)
    half = max(1, n // 2)
    sqrt_n = max(1, int(round(math.sqrt(n))))
    w_half = wma_np(x, half)
    w_full = wma_np(x, n)
    diff = 2 * w_half - w_full
    # Replace NaN with 0 for next WMA convolution, then mask out
    diff_safe = np.where(np.isnan(diff), 0.0, diff)
    result = wma_np(diff_safe, sqrt_n)
    # Cutoff: result valid only where diff is valid for the last sqrt_n samples
    cutoff = n - 1 + sqrt_n - 1
    out = np.full(len(x), np.nan)
    out[cutoff:] = result[cutoff:]
    return out


# ─── HMA snapshot at born_ms ───────────────────────────────
def hma_snapshot_for_events(
    bars: dict[str, np.ndarray],      # tf -> (N, 5) array
    born_ms_array: np.ndarray,
) -> dict[str, np.ndarray]:
    """For each event born_ms, return dict of HMA values per (tf, length).

    Keys: hma_{tf}_{L}_value, above_hma_{tf}_{L}, dist_pct_{tf}_{L},
          slope5_hma_{tf}_{L}, slope20_hma_{tf}_{L}
    """
    out = {}
    n_events = len(born_ms_array)

    # Pre-compute HMA series for every (tf, L)
    hma_series = {}    # (tf, L) -> array of HMA values aligned with bars[tf]
    for tf, bar_arr in bars.items():
        closes = bar_arr[:, 4]
        for L in HMA_LENS:
            if L >= len(closes):
                continue
            hma_series[(tf, L)] = hma_np(closes, L)

    # For each event, lookup HMA at born_ms
    # find last bar <= born_ms per TF
    for tf, bar_arr in bars.items():
        ts = bar_arr[:, 0].astype(np.int64)
        closes = bar_arr[:, 4]
        # For each event find idx
        idx = np.searchsorted(ts, born_ms_array, side="right") - 1
        valid = idx >= 0

        # Also get current close at that bar (close is the most recent bar's close at born)
        close_at_event = np.full(n_events, np.nan)
        close_at_event[valid] = closes[idx[valid]]

        for L in HMA_LENS:
            key = (tf, L)
            if key not in hma_series:
                continue
            hma_arr = hma_series[key]
            # value
            val_now = np.full(n_events, np.nan)
            val_now[valid] = hma_arr[idx[valid]]

            # slope_5: hma[idx] - hma[idx-5]
            slope_5 = np.full(n_events, np.nan)
            sl_mask = valid & (idx >= 5)
            slope_5[sl_mask] = hma_arr[idx[sl_mask]] - hma_arr[idx[sl_mask] - 5]
            # as %
            with np.errstate(divide="ignore", invalid="ignore"):
                slope_5_pct = np.where(np.abs(val_now) > 1e-9,
                                        slope_5 / val_now * 100,
                                        np.nan)

            # slope_20
            slope_20 = np.full(n_events, np.nan)
            sl_mask2 = valid & (idx >= 20)
            slope_20[sl_mask2] = hma_arr[idx[sl_mask2]] - hma_arr[idx[sl_mask2] - 20]
            with np.errstate(divide="ignore", invalid="ignore"):
                slope_20_pct = np.where(np.abs(val_now) > 1e-9,
                                         slope_20 / val_now * 100,
                                         np.nan)

            # above / dist_pct
            above = (close_at_event > val_now).astype(np.float64)
            above[np.isnan(val_now) | np.isnan(close_at_event)] = np.nan
            with np.errstate(divide="ignore", invalid="ignore"):
                dist_pct = np.where(np.abs(val_now) > 1e-9,
                                     (close_at_event - val_now) / val_now * 100,
                                     np.nan)

            prefix = f"hma_{tf}_{L}"
            out[f"{prefix}_value"] = val_now
            out[f"{prefix}_above"] = above
            out[f"{prefix}_dist_pct"] = dist_pct
            out[f"{prefix}_slope5_pct"] = slope_5_pct
            out[f"{prefix}_slope20_pct"] = slope_20_pct

    # ─── Cross-TF aggregates ─────────────────────────────
    # aligned_count_200: how many TFs has close > HMA-200
    aligned_200 = np.zeros(n_events, dtype=np.float64)
    valid_count_200 = np.zeros(n_events, dtype=np.int32)
    for tf in bars.keys():
        key = f"hma_{tf}_200_above"
        if key in out:
            arr = out[key]
            v = ~np.isnan(arr)
            aligned_200[v] += arr[v]
            valid_count_200[v] += 1
    aligned_200 = np.where(valid_count_200 > 0, aligned_200, np.nan)
    out["aligned_count_200"] = aligned_200
    out["aligned_count_200_pct"] = np.where(valid_count_200 > 0,
                                              aligned_200 / valid_count_200, np.nan)

    # aligned_count_78
    aligned_78 = np.zeros(n_events, dtype=np.float64)
    valid_count_78 = np.zeros(n_events, dtype=np.int32)
    for tf in bars.keys():
        key = f"hma_{tf}_78_above"
        if key in out:
            arr = out[key]
            v = ~np.isnan(arr)
            aligned_78[v] += arr[v]
            valid_count_78[v] += 1
    aligned_78 = np.where(valid_count_78 > 0, aligned_78, np.nan)
    out["aligned_count_78"] = aligned_78
    out["aligned_count_78_pct"] = np.where(valid_count_78 > 0,
                                             aligned_78 / valid_count_78, np.nan)

    # slope coherence: count of TFs where slope_200 sign is bull (slope > 0)
    bull_slope_200 = np.zeros(n_events, dtype=np.float64)
    valid_slope_200 = np.zeros(n_events, dtype=np.int32)
    for tf in bars.keys():
        key = f"hma_{tf}_200_slope5_pct"
        if key in out:
            arr = out[key]
            v = ~np.isnan(arr)
            bull_slope_200[v] += (arr[v] > 0).astype(np.float64)
            valid_slope_200[v] += 1
    out["slope_coherence_200_bull_count"] = np.where(valid_slope_200 > 0,
                                                       bull_slope_200, np.nan)
    out["slope_coherence_200_bull_pct"] = np.where(valid_slope_200 > 0,
                                                     bull_slope_200 / valid_slope_200,
                                                     np.nan)

    return out


def build_hma_features(events: pd.DataFrame) -> pd.DataFrame:
    """events must have asset, born_ms columns."""
    print("[hma] loading 1m for assets and aggregating...")
    feat_per_asset = {}

    for asset in ("BTC", "ETH"):
        mask = (events["asset"].values == asset)
        if mask.sum() == 0:
            continue
        born_subset = events.loc[mask, "born_ms"].to_numpy(dtype=np.int64)
        print(f"  [{asset}] loading 1m...")
        sym = f"{asset}USDT"
        rows_1m = load_1m(sym)
        print(f"  [{asset}] 1m bars: {len(rows_1m):,}")
        print(f"  [{asset}] aggregating to {len(TF_SPECS)} TFs...")
        bars = {}
        for tf, tf_ms in TF_SPECS.items():
            anchor = MONDAY_ANCHOR_MS if tf == "w" else 0
            bars[tf] = aggregate(rows_1m, tf_ms, anchor)
        print(f"  [{asset}] computing HMA snapshots for {mask.sum():,} events...")
        hma_feat = hma_snapshot_for_events(bars, born_subset)
        # Expand to full event index, NaN for other asset
        for k, v in hma_feat.items():
            full = np.full(len(events), np.nan)
            full[mask] = v
            if k in feat_per_asset:
                # Merge from other asset
                existing = feat_per_asset[k]
                existing[mask] = v
            else:
                feat_per_asset[k] = full
        print(f"  [{asset}] HMA features: {len(hma_feat)}")

    df_feat = pd.DataFrame(feat_per_asset, index=events.index)
    return df_feat


if __name__ == "__main__":
    # smoke test
    events = pd.DataFrame({
        "asset": ["BTC", "ETH"],
        "born_ms": [1780696800000, 1780696800000],
    })
    df_feat = build_hma_features(events)
    print(f"\nHMA features: {df_feat.shape[1]}")
    print(df_feat.iloc[0, :10].to_string())
