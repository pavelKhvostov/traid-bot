"""Shared utilities for OB-VC project scripts.

Centralized: 1m data loading, TF aggregation, project paths.
"""
from __future__ import annotations
import csv
import pathlib
from datetime import datetime, timezone
import numpy as np

# ─── Paths ──────────────────────────────────────────────────
ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CHARTS_DIR = ROOT / "charts"
DATA_DIR.mkdir(exist_ok=True)
CHARTS_DIR.mkdir(exist_ok=True)

CSV_1M = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"

# ─── TF constants ───────────────────────────────────────────
MS = 60_000
TFS_MS = {
    "15m":  15 * MS,
    "20m":  20 * MS,
    "1h":   60 * MS,
    "90m":  90 * MS,
    "2h":  120 * MS,
    "4h":  240 * MS,
    "6h":  360 * MS,
    "12h": 720 * MS,
    "1d": 1440 * MS,
}

# 3D / 2D / 1W нужны особые anchors (per memory [[feedback-3d-resample-monday-reset]] /
# [[weekly-tf-anchor-monday]]). Standard epoch-anchor для них некорректен.
# Будут реализованы отдельной функцией agg_weekly_anchor.

# Canon HTF → LTF mapping (~/smc-lib/elements/ob_vc/code.py)
HTF_TO_LTF: dict[str, tuple[str, ...]] = {
    "3d": ("12h",),
    "2d": ("12h",),
    "1d": ("4h", "6h"),
    "12h": ("4h", "6h"),
    "6h": ("1h", "90m", "2h"),
    "4h": ("1h", "90m", "2h"),
    "2h": ("15m", "20m"),
    "1h": ("15m", "20m"),
}

ALL_HTFS = list(HTF_TO_LTF.keys())
ALL_LTFS = sorted({ltf for ltfs in HTF_TO_LTF.values() for ltf in ltfs})
N_FRACTAL = 2  # canon Williams N

START_MS = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)


def load_1m(start_ms: int = START_MS, end_ms: int | None = None) -> list[tuple]:
    """Return list of (t_ms, o, h, l, c) for 1m bars in window."""
    if end_ms is None:
        end_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
    rows = []
    with CSV_1M.open() as f:
        rd = csv.reader(f); next(rd)
        for r in rd:
            t = int(datetime.fromisoformat(r[0]).timestamp() * 1000)
            if t < start_ms or t > end_ms: continue
            rows.append((t, float(r[1]), float(r[2]), float(r[3]), float(r[4])))
    return rows


def agg(rs, tf_ms: int, anchor: int = 0):
    """Epoch-anchored aggregation. Returns list[(t_open_ms, o, h, l, c)].

    anchor: epoch offset for bar boundaries (t - anchor) % tf_ms == 0.
    """
    out = []; cb = None; o = h = l = c = 0.0
    for t, oo, hh, ll, cc in rs:
        b = t - ((t - anchor) % tf_ms)
        if b != cb:
            if cb is not None: out.append((cb, o, h, l, c))
            cb = b; o, h, l, c = oo, hh, ll, cc
        else:
            h = max(h, hh); l = min(l, ll); c = cc
    if cb is not None: out.append((cb, o, h, l, c))
    return out


# ─── Anchors ──────────────────────────────────────────────
# Binance/UTC standard: anchor = 0 (UTC midnight = 03:00 МСК).
# 12h opens 03:00/15:00 МСК; 1D opens 03:00 МСК.
USER_HTF_ANCHOR_MS = 0
# Monday UTC midnight: epoch was Thu UTC 00:00. First Mon UTC 00:00 = epoch + 4d = 96h.
MONDAY_USER_ANCHOR_MS = 96 * 3600 * 1000


def aggregate_all_tfs(rows_1m) -> dict[str, list[tuple]]:
    """Aggregate 1m to all standard TFs.

    Per [[feedback-htf-anchor-global-rule]] и [[feedback-3d-resample-monday-reset]]:
      - 2h, 3h, 4h, 6h, 8h, 12h, 1d, 2d, 3d: anchor=0 UTC (Binance standard,
        03:00 МСК / 15:00 МСК). 2D / 3D continuous 72h/48h от epoch (Thu 1970).
      - W: Monday at 00:00 UTC = 03:00 МСК (MONDAY_USER_ANCHOR_MS)
      - 15m, 20m, 30m, 1h, 90m: anchor-neutral (anchor=0 OK)
    """
    bars = {}
    for tf, tfm in TFS_MS.items():
        bars[tf] = agg(rows_1m, tfm, anchor=0)
    # 2D / 3D — continuous from epoch (anchor=0), НЕ Mon-reset
    bars["2d"] = agg(rows_1m, 2 * 1440 * MS, anchor=0)
    bars["3d"] = agg(rows_1m, 3 * 1440 * MS, anchor=0)
    # Future: bars["w"] = agg(rows_1m, 7 * 1440 * MS, anchor=MONDAY_USER_ANCHOR_MS)
    return bars


def to_candles(bars_list):
    """Convert [(t,o,h,l,c)] to list[Candle]."""
    import sys as _sys
    _sys.path.insert(0, str(pathlib.Path.home() / "smc-lib"))
    from candle import Candle  # noqa
    return [Candle(open=x[1], high=x[2], low=x[3], close=x[4], open_time=x[0]) for x in bars_list]


def detect_williams_n2(cans, n: int = 2):
    """Williams N=n fractals: strict center > / < all 2n neighbors.
    Returns (FH list[(i, level, ts_ms)], FL list[(i, level, ts_ms)]).
    """
    fhs, fls = [], []
    if len(cans) < 2 * n + 1:
        return fhs, fls
    arr_h = np.array([c.high for c in cans])
    arr_l = np.array([c.low for c in cans])
    arr_t = np.array([c.open_time for c in cans], dtype=np.int64)
    for i in range(n, len(cans) - n):
        ch, cl, ct = arr_h[i], arr_l[i], arr_t[i]
        if all(ch > arr_h[i-k] and ch > arr_h[i+k] for k in range(1, n+1)):
            fhs.append((i, float(ch), int(ct)))
        if all(cl < arr_l[i-k] and cl < arr_l[i+k] for k in range(1, n+1)):
            fls.append((i, float(cl), int(ct)))
    return fhs, fls
