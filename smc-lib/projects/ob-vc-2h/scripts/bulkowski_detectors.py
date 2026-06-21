"""Bulkowski pattern detectors — MVP set for ob_vc 2h ML decision layer.

Provides detect_*(candles) -> list of (i_end, direction, meta_dict)
where i_end = bar index where pattern is FULLY FORMED (no lookahead).

All detectors are CAUSAL: data ≤ i_end only.

Patterns:
  - Bullish/Bearish Engulfing (candlestick, 2-bar)
  - Hammer / Inverted Hammer (candlestick, 1-bar after downtrend)
  - Double Bottom / Double Top (ZigZag-based)
  - Busted Bear / Bull Flag (proxy via failed breakdown)

Returns events with:
  - i_end: bar index where pattern formed
  - ts_ms: open_time of i_end bar
  - direction: 'long' or 'short' (which direction the pattern signals)
  - meta: pattern-specific params (depth, duration, etc.)
"""
from __future__ import annotations
import numpy as np


# ─── Candlestick patterns (1-2 bar) ──────────────────────────

def detect_engulfing(cans, min_body_pct: float = 0.005):
    """Bullish/Bearish Engulfing on given TF.

    Bullish: prev bearish, cur bullish; cur.body fully contains prev.body
             AND cur.body_size ≥ min_body_pct of cur.open.
    Bearish: mirror.

    Returns list of (i, direction, {'prev_body': float, 'cur_body': float}).
    """
    out = []
    for i in range(1, len(cans)):
        prev = cans[i-1]; cur = cans[i]
        pb_lo, pb_hi = min(prev.open, prev.close), max(prev.open, prev.close)
        cb_lo, cb_hi = min(cur.open, cur.close), max(cur.open, cur.close)
        prev_bear = prev.close < prev.open
        prev_bull = prev.close > prev.open
        cur_bull = cur.close > cur.open
        cur_bear = cur.close < cur.open
        cur_body_pct = (cb_hi - cb_lo) / cur.open

        if prev_bear and cur_bull and cb_lo <= pb_lo and cb_hi >= pb_hi and cur_body_pct >= min_body_pct:
            out.append((i, "long", {"cur_body_pct": cur_body_pct}))
        elif prev_bull and cur_bear and cb_lo <= pb_lo and cb_hi >= pb_hi and cur_body_pct >= min_body_pct:
            out.append((i, "short", {"cur_body_pct": cur_body_pct}))
    return out


def detect_hammer(cans, lower_wick_ratio: float = 2.0, upper_wick_max: float = 0.1,
                  downtrend_lookback: int = 5, downtrend_pct: float = 0.01):
    """Hammer (LONG) / Hanging Man+Shooting Star (SHORT, inverted hammer after uptrend).

    Hammer (LONG):
      - lower_wick ≥ lower_wick_ratio × body
      - upper_wick ≤ upper_wick_max × range
      - prior downtrend ≥ downtrend_pct over downtrend_lookback bars
    Shooting Star (SHORT):
      - upper_wick ≥ lower_wick_ratio × body
      - lower_wick ≤ upper_wick_max × range
      - prior uptrend
    """
    out = []
    for i in range(downtrend_lookback, len(cans)):
        c = cans[i]; rng = c.high - c.low
        if rng <= 0: continue
        body = abs(c.close - c.open)
        body_hi = max(c.open, c.close); body_lo = min(c.open, c.close)
        upper_wick = c.high - body_hi
        lower_wick = body_lo - c.low

        prior_start = cans[i - downtrend_lookback].close
        trend_pct = (c.close - prior_start) / prior_start

        # Hammer LONG
        if (body > 0 and lower_wick >= lower_wick_ratio * body
                and upper_wick <= upper_wick_max * rng
                and trend_pct <= -downtrend_pct):
            out.append((i, "long", {"lower_wick_ratio": lower_wick/body if body > 0 else 0}))
        # Shooting Star SHORT
        if (body > 0 and upper_wick >= lower_wick_ratio * body
                and lower_wick <= upper_wick_max * rng
                and trend_pct >= downtrend_pct):
            out.append((i, "short", {"upper_wick_ratio": upper_wick/body if body > 0 else 0}))
    return out


# ─── ZigZag-based patterns ──────────────────────────────────

def zigzag_pivots(cans, threshold_pct: float = 0.03):
    """Build ZigZag pivots. Returns list of (i, 'H' or 'L', price).

    Causal: each pivot confirmed when price moves threshold_pct opposite.
    """
    if len(cans) < 3: return []
    pivots = []
    last_dir = None  # 'up' or 'down'
    last_pivot_i = 0
    last_pivot_p = cans[0].close
    for i in range(1, len(cans)):
        c = cans[i]
        if last_dir is None:
            # Init: take high vs low movement
            if c.high >= last_pivot_p * (1 + threshold_pct):
                pivots.append((last_pivot_i, "L", cans[last_pivot_i].low))
                last_dir = "up"; last_pivot_i = i; last_pivot_p = c.high
            elif c.low <= last_pivot_p * (1 - threshold_pct):
                pivots.append((last_pivot_i, "H", cans[last_pivot_i].high))
                last_dir = "down"; last_pivot_i = i; last_pivot_p = c.low
        elif last_dir == "up":
            if c.high > last_pivot_p:
                last_pivot_i = i; last_pivot_p = c.high
            elif c.low <= last_pivot_p * (1 - threshold_pct):
                pivots.append((last_pivot_i, "H", last_pivot_p))
                last_dir = "down"; last_pivot_i = i; last_pivot_p = c.low
        else:  # down
            if c.low < last_pivot_p:
                last_pivot_i = i; last_pivot_p = c.low
            elif c.high >= last_pivot_p * (1 + threshold_pct):
                pivots.append((last_pivot_i, "L", last_pivot_p))
                last_dir = "up"; last_pivot_i = i; last_pivot_p = c.high
    return pivots


def detect_double_bottom(cans, threshold_pct: float = 0.03,
                         max_distance_bars: int = 60,
                         max_low_diff_pct: float = 0.03):
    """Double Bottom (LONG signal). Confirmed at neckline breakout.

    Geometry:
      - 2 lows within max_low_diff_pct
      - Separated by ≥1 high (neckline) ≥10% above lows
      - Breakout = close above neckline
    """
    pivots = zigzag_pivots(cans, threshold_pct)
    out = []
    for k in range(2, len(pivots)):
        if pivots[k-2][1] == "L" and pivots[k-1][1] == "H" and pivots[k][1] == "L":
            l1_i, _, l1_p = pivots[k-2]
            h_i, _, h_p = pivots[k-1]
            l2_i, _, l2_p = pivots[k]
            if l2_i - l1_i > max_distance_bars: continue
            low_diff = abs(l1_p - l2_p) / min(l1_p, l2_p)
            if low_diff > max_low_diff_pct: continue
            rise_pct = (h_p - min(l1_p, l2_p)) / min(l1_p, l2_p)
            if rise_pct < 0.10: continue
            # Find neckline breakout (close > h_p)
            for j in range(l2_i + 1, min(l2_i + 30, len(cans))):
                if cans[j].close > h_p:
                    out.append((j, "long", {
                        "depth_pct": rise_pct,
                        "low_diff_pct": low_diff,
                        "duration_bars": l2_i - l1_i,
                    }))
                    break
    return out


def detect_double_top(cans, threshold_pct: float = 0.03,
                      max_distance_bars: int = 60,
                      max_high_diff_pct: float = 0.03):
    """Double Top (SHORT signal). Confirmed at neckline breakdown."""
    pivots = zigzag_pivots(cans, threshold_pct)
    out = []
    for k in range(2, len(pivots)):
        if pivots[k-2][1] == "H" and pivots[k-1][1] == "L" and pivots[k][1] == "H":
            h1_i, _, h1_p = pivots[k-2]
            l_i, _, l_p = pivots[k-1]
            h2_i, _, h2_p = pivots[k]
            if h2_i - h1_i > max_distance_bars: continue
            high_diff = abs(h1_p - h2_p) / max(h1_p, h2_p)
            if high_diff > max_high_diff_pct: continue
            drop_pct = (max(h1_p, h2_p) - l_p) / max(h1_p, h2_p)
            if drop_pct < 0.10: continue
            for j in range(h2_i + 1, min(h2_i + 30, len(cans))):
                if cans[j].close < l_p:
                    out.append((j, "short", {
                        "depth_pct": drop_pct,
                        "high_diff_pct": high_diff,
                        "duration_bars": h2_i - h1_i,
                    }))
                    break
    return out


# ─── Busted patterns ────────────────────────────────────────

def detect_busted_double_top(cans, threshold_pct: float = 0.03,
                             max_distance_bars: int = 60,
                             max_high_diff_pct: float = 0.03,
                             max_below_neckline_bars: int = 15):
    """Busted Double Top → LONG signal.

    Failed DT: neckline broken down, BUT price rallied back above middle low (neckline)
    within max_below_neckline_bars.

    Bulkowski edge: busted pattern often gives stronger move than original.
    """
    pivots = zigzag_pivots(cans, threshold_pct)
    out = []
    for k in range(2, len(pivots)):
        if pivots[k-2][1] == "H" and pivots[k-1][1] == "L" and pivots[k][1] == "H":
            h1_i, _, h1_p = pivots[k-2]
            l_i, _, l_p = pivots[k-1]
            h2_i, _, h2_p = pivots[k]
            if h2_i - h1_i > max_distance_bars: continue
            high_diff = abs(h1_p - h2_p) / max(h1_p, h2_p)
            if high_diff > max_high_diff_pct: continue
            drop_pct = (max(h1_p, h2_p) - l_p) / max(h1_p, h2_p)
            if drop_pct < 0.10: continue
            # Find DT breakdown
            breakdown_i = None
            for j in range(h2_i + 1, min(h2_i + 30, len(cans))):
                if cans[j].close < l_p:
                    breakdown_i = j; break
            if breakdown_i is None: continue
            # BUSTED: close > neckline (l_p) within max_below_neckline_bars
            for j in range(breakdown_i + 1, min(breakdown_i + max_below_neckline_bars, len(cans))):
                if cans[j].close > l_p:
                    out.append((j, "long", {
                        "bust_bars": j - breakdown_i,
                        "depth_pct": drop_pct,
                    }))
                    break
    return out


def detect_busted_double_bottom(cans, threshold_pct: float = 0.03,
                                max_distance_bars: int = 60,
                                max_low_diff_pct: float = 0.03,
                                max_above_neckline_bars: int = 15):
    """Busted Double Bottom → SHORT signal."""
    pivots = zigzag_pivots(cans, threshold_pct)
    out = []
    for k in range(2, len(pivots)):
        if pivots[k-2][1] == "L" and pivots[k-1][1] == "H" and pivots[k][1] == "L":
            l1_i, _, l1_p = pivots[k-2]
            h_i, _, h_p = pivots[k-1]
            l2_i, _, l2_p = pivots[k]
            if l2_i - l1_i > max_distance_bars: continue
            low_diff = abs(l1_p - l2_p) / min(l1_p, l2_p)
            if low_diff > max_low_diff_pct: continue
            rise_pct = (h_p - min(l1_p, l2_p)) / min(l1_p, l2_p)
            if rise_pct < 0.10: continue
            breakout_i = None
            for j in range(l2_i + 1, min(l2_i + 30, len(cans))):
                if cans[j].close > h_p:
                    breakout_i = j; break
            if breakout_i is None: continue
            for j in range(breakout_i + 1, min(breakout_i + max_above_neckline_bars, len(cans))):
                if cans[j].close < h_p:
                    out.append((j, "short", {
                        "bust_bars": j - breakout_i,
                        "depth_pct": rise_pct,
                    }))
                    break
    return out


# ─── Helper: events within window ───────────────────────────

def events_within(events, ts_ms: int, lookback_bars_ms: int):
    """Filter events with ts in [ts_ms - lookback_bars_ms, ts_ms)."""
    return [(i, d, m, ets) for (i, d, m, ets) in events
            if ts_ms - lookback_bars_ms <= ets < ts_ms]


def annotate_with_ts(events, cans):
    """Add ts_ms = cans[i_end].open_time to each event tuple."""
    return [(i, d, m, cans[i].open_time) for (i, d, m) in events if i < len(cans)]
