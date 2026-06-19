"""Shared utilities for 12h-fractal-new B-class filter scripts.

Загружает 1m данные, агрегирует в multi-TF, биндит к A4-baseline.
Strict causality: только bars ≤ pivot i. Per [[feedback-b-series-strict-causal-i]].

Usage:
    from _lib import *
    bars12 = load_12h()
    pivots = load_baseline()
    pmap = match_pivots(bars12, pivots)
    ...
"""
from __future__ import annotations
import csv, pathlib, sys
from datetime import datetime, timezone
import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path.home() / "smc-lib"))

# ─── Paths ─────────────────────────────────────────────────────
CSV_1M = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
BASELINE = pathlib.Path.home() / "Desktop/pred12h_baseline_v2.parquet"
OUT_DIR = pathlib.Path.home() / "Desktop/12h-fractal-new-out"
OUT_DIR.mkdir(exist_ok=True)

# ─── Constants ─────────────────────────────────────────────────
MS_M = 60_000
TF12 = 12 * 60 * MS_M
TFD = 24 * 60 * MS_M
TF2D = 2 * TFD
TF3D = 3 * TFD
TFW = 7 * TFD
TF_HTF = {"12h": TF12, "D": TFD, "2D": TF2D, "3D": TF3D, "W": TFW}
# Binance/UTC standard: anchor = 0 (UTC midnight = 03:00 МСК)
# 12h bars open 03:00 / 15:00 МСК; 1D opens 03:00 МСК
MON_ANCHOR = int(datetime(2017, 1, 2, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
START_MS = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)


# ─── Data loading ──────────────────────────────────────────────
_rows_cache = None
def load_1m(start: int = START_MS, end: int | None = None) -> list[tuple]:
    """Load BTC 1m candles in window. Cached on first call."""
    global _rows_cache
    if _rows_cache is not None:
        return _rows_cache
    end = end if end is not None else int(datetime.now(tz=timezone.utc).timestamp() * 1000)
    rows = []
    with CSV_1M.open() as f:
        rd = csv.reader(f); next(rd)
        for r in rd:
            t = int(datetime.fromisoformat(r[0]).timestamp() * 1000)
            if t < start or t > end: continue
            rows.append((t, float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
    _rows_cache = rows
    return rows


def aggregate(rows, tfms: int, anchor: int = 0):
    """Aggregate 1m rows to higher TF. anchor: 0 = epoch, MON_ANCHOR for W."""
    out = []
    cb = None; o = h = l = c = v = 0.0
    for ts, oo, hh, ll, cc, vv in rows:
        b = ts - ((ts - anchor) % tfms)
        if b != cb:
            if cb is not None: out.append((cb, o, h, l, c, v))
            cb = b; o, h, l, c, v = oo, hh, ll, cc, vv
        else:
            h = max(h, hh); l = min(l, ll); c = cc; v += vv
    if cb is not None: out.append((cb, o, h, l, c, v))
    return out


def load_12h():
    """Returns dict with arrays: t, o, h, l, c, v (all numpy).
    Anchor = 0 (UTC midnight = 03:00 МСК / 15:00 МСК bars).
    """
    rows = load_1m()
    bars = aggregate(rows, TF12)
    return {
        "t": np.array([b[0] for b in bars], dtype=np.int64),
        "o": np.array([b[1] for b in bars]),
        "h": np.array([b[2] for b in bars]),
        "l": np.array([b[3] for b in bars]),
        "c": np.array([b[4] for b in bars]),
        "v": np.array([b[5] for b in bars]),
        "n": len(bars),
    }


def load_htf_bars(tf: str):
    """Load aggregated bars for given TF. Returns list of (ts, o, h, l, c, v).
    Anchor=0 (UTC midnight); W uses MON_ANCHOR.
    """
    rows = load_1m()
    anchor = MON_ANCHOR if tf == "W" else 0
    return aggregate(rows, TF_HTF[tf], anchor)


# ─── Technicals ────────────────────────────────────────────────
def atr(h: np.ndarray, l: np.ndarray, c: np.ndarray, n: int = 14) -> np.ndarray:
    """Simple ATR — past-only causal."""
    tr = np.zeros(len(h))
    for i in range(1, len(h)):
        tr[i] = max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1]))
    out = np.zeros(len(h))
    for i in range(n, len(h)):
        out[i] = tr[i-n+1:i+1].mean()
    return out


# ─── Baseline matching ─────────────────────────────────────────
def load_baseline() -> pd.DataFrame:
    """Load A4 cascade output (1356 pivots)."""
    return pd.read_parquet(BASELINE)


def match_pivots(bars12: dict, baseline: pd.DataFrame) -> dict:
    """Build pivot_map: (k, zone_direction) → (confirmed, pivot_direction, ts_ms).

    zone_direction = direction of zone that would fire at this pivot:
        FH pivot (high) → matches "short" zones (sweep upward)
        FL pivot (low)  → matches "long"  zones (sweep downward)
    """
    ts_to_idx = {int(t): k for k, t in enumerate(bars12["t"])}
    pmap = {}
    for _, p in baseline.iterrows():
        ts_ms = int(p["pivot_open_ts_ms"])
        if ts_ms not in ts_to_idx: continue
        k = ts_to_idx[ts_ms]
        zone_dir = "short" if p["direction"] == "high" else "long"
        pmap[(k, zone_dir)] = (bool(p["confirmed"]), p["direction"], ts_ms)
    return pmap


def stats(fires: set, pmap: dict) -> tuple[int, int, float]:
    """Return (n, conf, WR%) for fire set vs baseline pivot map."""
    matched = [pmap[(k, d)] for (k, d) in fires if (k, d) in pmap]
    n = len(matched)
    conf = sum(1 for c, _, _ in matched if c)
    return n, conf, (100 * conf / n if n else 0.0)


def report(code: str, name: str, fires: set, pmap: dict, baseline_wr: float = 48.60):
    """Print one-line summary for a B-script."""
    n, conf, wr = stats(fires, pmap)
    delta = wr - baseline_wr
    print(f"  {code:<6} {name:<28}  n = {n:>4}   conf = {conf:>4}   WR = {wr:>5.2f}%   Δ = {delta:+5.2f} pp")
    return n, conf, wr


def save_fires(code: str, fires: set, bars12: dict):
    """Save fire-set to parquet: pivot_open_ts_ms, direction, bar_idx."""
    rows = []
    for k, direction in fires:
        rows.append({
            "pivot_open_ts_ms": int(bars12["t"][k]),
            "zone_direction": direction,
            "bar_idx": int(k),
        })
    df = pd.DataFrame(rows)
    out = OUT_DIR / f"{code}_fires.parquet"
    df.to_parquet(out, index=False)
    return out
