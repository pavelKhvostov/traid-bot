"""Shared utilities for v3 (entry_fill anchor) feature builders."""
from __future__ import annotations
import csv
import math
import pathlib
from datetime import datetime, timezone

import numpy as np


START_MS = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)

# Per req #4: TFs ≤ 3D (no W)
TF_SPECS = {
    "15m":  15 * 60_000,
    "20m":  20 * 60_000,
    "1h":   60 * 60_000,
    "90m":  90 * 60_000,
    "2h":  120 * 60_000,
    "4h":  240 * 60_000,
    "6h":  360 * 60_000,
    "12h": 720 * 60_000,
    "1d":  1440 * 60_000,
    "2d":  2880 * 60_000,
    "3d":  4320 * 60_000,
}

HMA_LENS = [9, 14, 21, 34, 50, 78, 100, 200, 365, 500]


def load_1m_full(symbol: str) -> np.ndarray:
    """Return (N, 6) array: [ts_ms, open, high, low, close, volume]."""
    path = pathlib.Path.home() / f"traid-bot/data/{symbol}_1m_vic_vadim.csv"
    rows = []
    with path.open() as f:
        rd = csv.reader(f); next(rd)
        for r in rd:
            t = int(datetime.fromisoformat(r[0]).timestamp() * 1000)
            if t < START_MS: continue
            rows.append((t, float(r[1]), float(r[2]), float(r[3]),
                          float(r[4]), float(r[5])))
    return np.array(rows, dtype=np.float64)


def aggregate(rows_1m: np.ndarray, tf_ms: int, anchor: int = 0) -> np.ndarray:
    """Aggregate 1m to TF. Returns (N, 6)."""
    ts = rows_1m[:, 0].astype(np.int64)
    bucket = ts - ((ts - anchor) % tf_ms)
    diff = np.diff(bucket, prepend=bucket[0] - 1)
    starts = np.where(diff != 0)[0]
    ends = np.append(starts[1:], len(bucket))
    n = len(starts)
    out = np.empty((n, 6))
    out[:, 0] = bucket[starts]
    out[:, 1] = rows_1m[starts, 1]
    out[:, 2] = np.maximum.reduceat(rows_1m[:, 2], starts)
    out[:, 3] = np.minimum.reduceat(rows_1m[:, 3], starts)
    out[:, 4] = rows_1m[ends - 1, 4]
    out[:, 5] = np.add.reduceat(rows_1m[:, 5], starts)
    return out


def aggregate_all_tfs(rows_1m: np.ndarray) -> dict[str, np.ndarray]:
    return {tf: aggregate(rows_1m, tf_ms, anchor=0) for tf, tf_ms in TF_SPECS.items()}


def wma_np(x: np.ndarray, n: int) -> np.ndarray:
    if n < 1 or len(x) < n:
        return np.full(len(x), np.nan)
    weights = np.arange(1, n + 1, dtype=np.float64)
    rolling = np.convolve(x, weights[::-1], mode="valid") / weights.sum()
    out = np.full(len(x), np.nan)
    out[n - 1:] = rolling
    return out


def hma_np(x: np.ndarray, n: int) -> np.ndarray:
    if n < 2 or len(x) < n:
        return np.full(len(x), np.nan)
    half = max(1, n // 2)
    sqrt_n = max(1, int(round(math.sqrt(n))))
    w_half = wma_np(x, half)
    w_full = wma_np(x, n)
    diff = 2 * w_half - w_full
    diff_safe = np.where(np.isnan(diff), 0.0, diff)
    result = wma_np(diff_safe, sqrt_n)
    cutoff = n - 1 + sqrt_n - 1
    out = np.full(len(x), np.nan)
    out[cutoff:] = result[cutoff:]
    return out
