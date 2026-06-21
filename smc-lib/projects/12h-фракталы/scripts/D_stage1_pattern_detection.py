"""STAGE 1 — Pattern Detection (D-layer, 19 Bulkowski detectors).

Trained on RAW chart (no Basket dependency). Output: per-bar fires + walk-forward outcome.

Tiers:
    Tier 1 — LONG base (12h): big_w, db_eve_eve, hs_bottom, v_bottom, barr_bottom
    Tier 2 — SHORT base (12h): big_m, hs_top, v_top, barr_top, diamond_top
    Tier 3 — W-projected: horn_bottom_w, pipe_top_w
    Tier 4 — Busted features: hs_top_busted, triple_top_busted, rect_bottom_busted, sym_triangle_busted
    Tier 5 — Smooth D/W: cup_handle_d, rounding_bottom_w, hs_complex_d

Each detector — pure function. Williams n=2 components (no lookahead).
Breakout = `close[i]` crosses confirmation line first time.

Walk-forward outcome (Bulkowski-style):
    Track favor for up to 240 bars (120 days) или до 20% counter-move от peak.
    Metrics: ult_move, max_adverse, busted, reached_target, reached_half_target.
"""
from __future__ import annotations
import pathlib
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from _lib import load_12h, load_htf_bars, OUT_DIR, TF_HTF

OUTCOME_BARS = 240        # walk-forward horizon
COUNTER_PCT = 20          # 20% counter-move от peak terminates outcome
RANDOM_SEED = 42

# ─── Load 12h bars ─────────────────────────────────────────────
print("Loading 12h bars (raw)...")
bars = load_12h()
n12 = bars["n"]
o12, h12, l12, c12, t12 = bars["o"], bars["h"], bars["l"], bars["c"], bars["t"]
print(f"  12h bars: {n12}")

# ─── Williams n=2 helpers (right-confirmed at j+2) ────────────
def fh_at(j: int) -> bool:
    """High fractal at index j confirmed (knowing j+2)."""
    if j < 2 or j + 2 >= n12: return False
    return (h12[j] > h12[j-1] and h12[j] > h12[j-2] and
            h12[j] > h12[j+1] and h12[j] > h12[j+2])

def fl_at(j: int) -> bool:
    if j < 2 or j + 2 >= n12: return False
    return (l12[j] < l12[j-1] and l12[j] < l12[j-2] and
            l12[j] < l12[j+1] and l12[j] < l12[j+2])


def find_recent_fl(i: int, lookback: int, min_apart: int = 5) -> list[int]:
    """All FL fractals j ∈ [i-lookback, i-2] (confirmed before i)."""
    out = []
    for j in range(max(2, i - lookback), i - 1):
        if fl_at(j):
            if not out or (j - out[-1]) >= min_apart:
                out.append(j)
            elif l12[j] < l12[out[-1]]:
                out[-1] = j
    return out


def find_recent_fh(i: int, lookback: int, min_apart: int = 5) -> list[int]:
    out = []
    for j in range(max(2, i - lookback), i - 1):
        if fh_at(j):
            if not out or (j - out[-1]) >= min_apart:
                out.append(j)
            elif h12[j] > h12[out[-1]]:
                out[-1] = j
    return out


def already_broken_above(level: float, since: int, until: int) -> bool:
    """Has close ever crossed `level` UP in [since, until-1]?"""
    return bool(np.any(c12[since:until] > level))

def already_broken_below(level: float, since: int, until: int) -> bool:
    return bool(np.any(c12[since:until] < level))


# ═══════════════ TIER 1 — LONG base ═════════════════════════════

def detect_big_w(i: int, lookback: int = 60) -> dict | None:
    """Twin bottom with tall left side. Two FL ±3%, peak between ≥3%, close > peak."""
    fls = find_recent_fl(i, lookback)
    if len(fls) < 2: return None
    # Take two most recent
    j1, j2 = fls[-2], fls[-1]
    if (j2 - j1) < 5: return None
    p1, p2 = l12[j1], l12[j2]
    if abs(p1 - p2) / min(p1, p2) > 0.03: return None  # ±3%
    # Peak between
    peak_idx = j1 + 1 + int(np.argmax(h12[j1+1:j2]))
    if peak_idx >= j2: return None
    peak = h12[peak_idx]
    avg_low = (p1 + p2) / 2
    height = (peak - avg_low) / avg_low
    if height < 0.03: return None
    # Tall left: left side rise into pattern ≥ height
    left_low = l12[max(0, j1-10):j1].min() if j1 >= 5 else avg_low
    left_rise = (h12[j1] - left_low) / avg_low if left_low > 0 else 0
    if left_rise < height: return None
    # Breakout first time
    if c12[i] <= peak: return None
    if already_broken_above(peak, j2 + 1, i): return None
    return _meta("big_w", "long", i, j1, j2, p1, peak, height)


def detect_db_eve_eve(i: int, lookback: int = 60) -> dict | None:
    """Двойное дно с rounded valleys (body/range < 0.6)."""
    fls = find_recent_fl(i, lookback)
    if len(fls) < 2: return None
    j1, j2 = fls[-2], fls[-1]
    if (j2 - j1) < 5: return None
    # Rounded: avg body/range на 3 окрестных свечах ≤ 0.6
    def rounded(j):
        sub = slice(max(0, j-2), min(n12, j+3))
        rng = h12[sub] - l12[sub]
        body = np.abs(c12[sub] - o12[sub])
        return (body / np.where(rng > 0, rng, 1)).mean() < 0.6
    if not (rounded(j1) and rounded(j2)): return None
    p1, p2 = l12[j1], l12[j2]
    if abs(p1 - p2) / min(p1, p2) > 0.03: return None
    peak = h12[j1:j2].max()
    avg_low = (p1 + p2) / 2
    height = (peak - avg_low) / avg_low
    if height < 0.03: return None
    if c12[i] <= peak: return None
    if already_broken_above(peak, j2 + 1, i): return None
    return _meta("db_eve_eve", "long", i, j1, j2, p1, peak, height)


def detect_hs_bottom(i: int, lookback: int = 60) -> dict | None:
    """3 valleys: middle deepest. Shoulders ±6%."""
    fls = find_recent_fl(i, lookback)
    if len(fls) < 3: return None
    j1, j2, j3 = fls[-3], fls[-2], fls[-1]
    s1, head, s2 = l12[j1], l12[j2], l12[j3]
    if not (head < s1 and head < s2): return None
    if abs(s1 - s2) / min(s1, s2) > 0.06: return None  # symmetric shoulders
    # Neckline = max peak between
    peak_l = h12[j1:j2].max()
    peak_r = h12[j2:j3].max()
    neckline = max(peak_l, peak_r)
    height = (neckline - head) / head
    if height < 0.03: return None
    if c12[i] <= neckline: return None
    if already_broken_above(neckline, j3 + 1, i): return None
    return _meta("hs_bottom", "long", i, j1, j3, head, neckline, height)


def detect_v_bottom(i: int, lookback: int = 20) -> dict | None:
    """Sharp drop ≥8% + sharp rebound ≥50% drop."""
    # Find lowest low in last lookback
    if i - lookback < 0: return None
    low_idx = i - lookback + int(np.argmin(l12[i-lookback:i]))
    if low_idx >= i - 1: return None
    low = l12[low_idx]
    # Drop from prior high
    prior_high_idx = i - lookback + int(np.argmax(h12[i-lookback:low_idx+1]))
    prior_high = h12[prior_high_idx]
    drop = (prior_high - low) / prior_high
    if drop < 0.08: return None
    # Rebound
    rebound = (c12[i] - low) / (prior_high - low)
    if rebound < 0.50: return None
    midpoint = low + 0.5 * (prior_high - low)
    if c12[i] <= midpoint: return None
    if already_broken_above(midpoint, low_idx + 1, i): return None
    return _meta("v_bottom", "long", i, prior_high_idx, low_idx, low, midpoint, drop)


def detect_barr_bottom(i: int, lookback: int = 40) -> dict | None:
    """Lead-in downtrend (slope<0), bump (steeper slope), close > lead-in line."""
    if i - lookback < 0: return None
    half = lookback // 2
    seg_lead = c12[i-lookback:i-half]
    seg_bump = c12[i-half:i]
    x_lead = np.arange(len(seg_lead))
    x_bump = np.arange(len(seg_bump))
    slope_lead = np.polyfit(x_lead, seg_lead, 1)[0]
    slope_bump = np.polyfit(x_bump, seg_bump, 1)[0]
    if slope_lead >= 0: return None      # lead-in must downtrend
    if slope_bump >= slope_lead * 0.5: return None   # bump steeper down
    # Lead-in line extended to i
    lead_intercept = c12[i-lookback]
    lead_line_now = lead_intercept + slope_lead * lookback
    if c12[i] <= lead_line_now: return None
    low_idx = i - lookback + int(np.argmin(l12[i-lookback:i]))
    height = (c12[i] - l12[low_idx]) / l12[low_idx]
    if already_broken_above(lead_line_now, low_idx + 1, i): return None
    return _meta("barr_bottom", "long", i, i-lookback, low_idx,
                 l12[low_idx], lead_line_now, height)


# ═══════════════ TIER 2 — SHORT base ════════════════════════════

def detect_big_m(i: int, lookback: int = 60) -> dict | None:
    """Mirror big_w."""
    fhs = find_recent_fh(i, lookback)
    if len(fhs) < 2: return None
    j1, j2 = fhs[-2], fhs[-1]
    if (j2 - j1) < 5: return None
    p1, p2 = h12[j1], h12[j2]
    if abs(p1 - p2) / max(p1, p2) > 0.03: return None
    valley_idx = j1 + 1 + int(np.argmin(l12[j1+1:j2]))
    valley = l12[valley_idx]
    avg_high = (p1 + p2) / 2
    height = (avg_high - valley) / avg_high
    if height < 0.03: return None
    left_high = h12[max(0, j1-10):j1].max() if j1 >= 5 else avg_high
    left_drop = (left_high - l12[j1]) / avg_high if left_high > 0 else 0
    if left_drop < height: return None
    if c12[i] >= valley: return None
    if already_broken_below(valley, j2 + 1, i): return None
    return _meta("big_m", "short", i, j1, j2, p1, valley, height)


def detect_hs_top(i: int, lookback: int = 60) -> dict | None:
    """Mirror hs_bottom."""
    fhs = find_recent_fh(i, lookback)
    if len(fhs) < 3: return None
    j1, j2, j3 = fhs[-3], fhs[-2], fhs[-1]
    s1, head, s2 = h12[j1], h12[j2], h12[j3]
    if not (head > s1 and head > s2): return None
    if abs(s1 - s2) / max(s1, s2) > 0.06: return None
    valley_l = l12[j1:j2].min()
    valley_r = l12[j2:j3].min()
    neckline = min(valley_l, valley_r)
    height = (head - neckline) / head
    if height < 0.03: return None
    if c12[i] >= neckline: return None
    if already_broken_below(neckline, j3 + 1, i): return None
    return _meta("hs_top", "short", i, j1, j3, head, neckline, height)


def detect_v_top(i: int, lookback: int = 20) -> dict | None:
    """Mirror v_bottom."""
    if i - lookback < 0: return None
    high_idx = i - lookback + int(np.argmax(h12[i-lookback:i]))
    if high_idx >= i - 1: return None
    high = h12[high_idx]
    prior_low_idx = i - lookback + int(np.argmin(l12[i-lookback:high_idx+1]))
    prior_low = l12[prior_low_idx]
    rise = (high - prior_low) / prior_low
    if rise < 0.08: return None
    drop = (high - c12[i]) / (high - prior_low)
    if drop < 0.50: return None
    midpoint = high - 0.5 * (high - prior_low)
    if c12[i] >= midpoint: return None
    if already_broken_below(midpoint, high_idx + 1, i): return None
    return _meta("v_top", "short", i, prior_low_idx, high_idx, high, midpoint, rise)


def detect_barr_top(i: int, lookback: int = 40) -> dict | None:
    if i - lookback < 0: return None
    half = lookback // 2
    seg_lead = c12[i-lookback:i-half]
    seg_bump = c12[i-half:i]
    x_lead = np.arange(len(seg_lead))
    x_bump = np.arange(len(seg_bump))
    slope_lead = np.polyfit(x_lead, seg_lead, 1)[0]
    slope_bump = np.polyfit(x_bump, seg_bump, 1)[0]
    if slope_lead <= 0: return None
    if slope_bump <= slope_lead * 0.5: return None
    lead_intercept = c12[i-lookback]
    lead_line_now = lead_intercept + slope_lead * lookback
    if c12[i] >= lead_line_now: return None
    high_idx = i - lookback + int(np.argmax(h12[i-lookback:i]))
    height = (h12[high_idx] - c12[i]) / h12[high_idx]
    if already_broken_below(lead_line_now, high_idx + 1, i): return None
    return _meta("barr_top", "short", i, i-lookback, high_idx,
                 h12[high_idx], lead_line_now, height)


def detect_diamond_top(i: int, lookback: int = 40) -> dict | None:
    """Range expanding then contracting (broadening → narrowing)."""
    if i - lookback < 0: return None
    half = lookback // 2
    seg_l = slice(i - lookback, i - half)
    seg_r = slice(i - half, i)
    range_l = h12[seg_l] - l12[seg_l]
    range_r = h12[seg_r] - l12[seg_r]
    x_l = np.arange(len(range_l))
    x_r = np.arange(len(range_r))
    slope_l = np.polyfit(x_l, range_l, 1)[0]
    slope_r = np.polyfit(x_r, range_r, 1)[0]
    if slope_l <= 0 or slope_r >= 0: return None
    last_low = l12[seg_r].min()
    high = h12[seg_l].max()
    height = (high - last_low) / high
    if height < 0.03: return None
    if c12[i] >= last_low: return None
    if already_broken_below(last_low, i - half, i): return None
    return _meta("diamond_top", "short", i, i-lookback, i-half,
                 high, last_low, height)


# ═══════════════ TIER 3 — W-projected ═══════════════════════════

def _build_W_bars():
    """Load weekly bars + arrays."""
    bars_w = load_htf_bars("W")
    return {
        "t": np.array([b[0] for b in bars_w], dtype=np.int64),
        "o": np.array([b[1] for b in bars_w]),
        "h": np.array([b[2] for b in bars_w]),
        "l": np.array([b[3] for b in bars_w]),
        "c": np.array([b[4] for b in bars_w]),
        "n": len(bars_w),
    }

W = _build_W_bars()
TFW = TF_HTF["W"]


def detect_horn_bottom_w_for_12h(i_12h: int) -> dict | None:
    """Horn Bottom on W: 3 consecutive weekly bars где middle = deepest low (W fractal n=1).
    Projection: fire at 12h bar i_12h if W pattern just confirmed на close last W ≤ open(i_12h+1).
    """
    open_next_12h = int(t12[i_12h] + 12 * 60 * 60 * 1000) if i_12h + 1 < n12 else int(t12[i_12h])
    j = int(np.searchsorted(W["t"], open_next_12h, side="right")) - 1
    if j < 2 or j >= W["n"]: return None
    # Horn = middle of 3 consecutive W bars has lowest low
    if not (W["l"][j-1] < W["l"][j-2] and W["l"][j-1] < W["l"][j]): return None
    # Tall horns: both outer wicks small relative to body? skip simplification; check breakout
    horn_low = W["l"][j-1]
    horn_high = max(W["h"][j-2], W["h"][j-1], W["h"][j])
    # Breakout: 12h close > horn_high
    if c12[i_12h] <= horn_high: return None
    # First time check on 12h window since W close
    w_close_ms = int(W["t"][j] + TFW)
    since = int(np.searchsorted(t12, w_close_ms, side="left"))
    if since < 0 or since >= i_12h: return None
    if already_broken_above(horn_high, since, i_12h): return None
    height = (horn_high - horn_low) / horn_low
    return _meta("horn_bottom_w", "long", i_12h, since, since, horn_low, horn_high, height)


def detect_pipe_top_w_for_12h(i_12h: int) -> dict | None:
    """Pipe Top on W: parallel twin tall wicks at top."""
    open_next_12h = int(t12[i_12h] + 12 * 60 * 60 * 1000) if i_12h + 1 < n12 else int(t12[i_12h])
    j = int(np.searchsorted(W["t"], open_next_12h, side="right")) - 1
    if j < 1 or j >= W["n"]: return None
    # Two adjacent weeks: both have high near same level, body small relative to wick
    if abs(W["h"][j] - W["h"][j-1]) / max(W["h"][j], W["h"][j-1]) > 0.02: return None
    wick1 = W["h"][j-1] - max(W["o"][j-1], W["c"][j-1])
    wick0 = W["h"][j] - max(W["o"][j], W["c"][j])
    body1 = abs(W["c"][j-1] - W["o"][j-1])
    body0 = abs(W["c"][j] - W["o"][j])
    if wick1 < body1 * 0.5 or wick0 < body0 * 0.5: return None
    pipe_top = max(W["h"][j], W["h"][j-1])
    pipe_bottom = min(W["l"][j], W["l"][j-1])
    # 12h breakout below body lows
    body_low = min(W["c"][j], W["c"][j-1])
    if c12[i_12h] >= body_low: return None
    w_close_ms = int(W["t"][j] + TFW)
    since = int(np.searchsorted(t12, w_close_ms, side="left"))
    if since < 0 or since >= i_12h: return None
    if already_broken_below(body_low, since, i_12h): return None
    height = (pipe_top - pipe_bottom) / pipe_bottom
    return _meta("pipe_top_w", "short", i_12h, since, since, pipe_top, body_low, height)


# ═══════════════ TIER 4 — Busted features ══════════════════════
# Busted = base pattern fired but failed (<10% favor) AND price crossed opposite side.
# Detect at the BAR of bust (not at original fire).

def detect_busted(base_detector, fires_base: dict, name: str, side_busted: str):
    """For each base fire, scan forward up to 30 bars; if peak_favor < 10% AND
    price crosses original entry side → fire busted signal at bust bar.
    """
    busted_fires = []
    for fire in fires_base:
        start = fire["breakout_idx"] + 1
        side = fire["side"]
        ref = fire["breakout_price"]
        peak_favor_pct = 0
        for k in range(start, min(start + 30, n12)):
            if side == "long":
                favor = (h12[k] - ref) / ref * 100
                if favor > peak_favor_pct: peak_favor_pct = favor
                if peak_favor_pct < 10 and c12[k] < fire["low_price"]:
                    busted_fires.append({**fire,
                        "pattern": name, "side": side_busted,
                        "breakout_idx": k,
                        "breakout_price": c12[k],
                        "peak_favor_before_bust": peak_favor_pct,
                    })
                    break
            else:  # short
                favor = (ref - l12[k]) / ref * 100
                if favor > peak_favor_pct: peak_favor_pct = favor
                if peak_favor_pct < 10 and c12[k] > fire["high_price"]:
                    busted_fires.append({**fire,
                        "pattern": name, "side": side_busted,
                        "breakout_idx": k,
                        "breakout_price": c12[k],
                        "peak_favor_before_bust": peak_favor_pct,
                    })
                    break
    return busted_fires


# ═══════════════ TIER 5 — D/W smooth ═══════════════════════════

D = _build_W_bars()  # placeholder, used below

def _build_D_bars():
    bars_d = load_htf_bars("D")
    return {
        "t": np.array([b[0] for b in bars_d], dtype=np.int64),
        "o": np.array([b[1] for b in bars_d]),
        "h": np.array([b[2] for b in bars_d]),
        "l": np.array([b[3] for b in bars_d]),
        "c": np.array([b[4] for b in bars_d]),
        "n": len(bars_d),
    }
D = _build_D_bars()
TFD = TF_HTF["D"]


def detect_cup_handle_d_for_12h(i_12h: int) -> dict | None:
    """Cup with Handle на D: U-shape min ~20-60 days, handle 3-15 days retrace ≤50%."""
    open_next_12h = int(t12[i_12h] + 12 * 60 * 60 * 1000) if i_12h + 1 < n12 else int(t12[i_12h])
    j_now = int(np.searchsorted(D["t"], open_next_12h, side="right")) - 1
    if j_now < 30: return None
    # Look for cup in last 60 days
    cup_start = max(0, j_now - 60)
    cup_window = slice(cup_start, j_now + 1)
    closes = D["c"][cup_window]
    if len(closes) < 30: return None
    # Find lowest point (cup bottom)
    bot_idx_local = int(np.argmin(closes))
    if bot_idx_local < 10 or bot_idx_local > len(closes) - 10: return None
    bot_d = cup_start + bot_idx_local
    cup_bot = closes[bot_idx_local]
    # Cup rims: highs of first 5 and last 5 days symmetric ±5%
    left_rim = D["h"][cup_start:cup_start+5].max()
    right_rim = D["h"][bot_d+1:bot_d+6].max() if bot_d + 6 < D["n"] else 0
    if right_rim == 0: return None
    if abs(left_rim - right_rim) / max(left_rim, right_rim) > 0.06: return None
    cup_height = (left_rim - cup_bot) / cup_bot
    if cup_height < 0.05: return None
    # Handle: from right rim down ≤ 50% cup, within last 15 days
    handle_start = bot_d + 5
    handle_low = D["l"][handle_start:j_now+1].min() if handle_start < j_now else cup_bot
    handle_retrace = (right_rim - handle_low) / (right_rim - cup_bot)
    if not (0.0 < handle_retrace < 0.5): return None
    # 12h breakout above right_rim
    if c12[i_12h] <= right_rim: return None
    d_close_ms = int(D["t"][j_now] + TFD)
    since = int(np.searchsorted(t12, d_close_ms, side="left"))
    if since < 0 or since >= i_12h: return None
    if already_broken_above(right_rim, since, i_12h): return None
    return _meta("cup_handle_d", "long", i_12h, since, since, cup_bot, right_rim, cup_height)


def detect_rounding_bottom_w_for_12h(i_12h: int) -> dict | None:
    """Rounding Bottom на W: U-shape over 8-26 weeks."""
    open_next_12h = int(t12[i_12h] + 12 * 60 * 60 * 1000) if i_12h + 1 < n12 else int(t12[i_12h])
    j_now = int(np.searchsorted(W["t"], open_next_12h, side="right")) - 1
    if j_now < 8: return None
    win = slice(max(0, j_now - 20), j_now + 1)
    closes = W["c"][win]
    if len(closes) < 8: return None
    bot_local = int(np.argmin(closes))
    if bot_local < 2 or bot_local > len(closes) - 2: return None
    # Check rounding: parabolic fit y = a x² + b x + c, a > 0
    x = np.arange(len(closes))
    coef = np.polyfit(x, closes, 2)
    if coef[0] <= 0: return None
    rim_left = closes[:bot_local].max() if bot_local > 0 else closes[0]
    rim_right = closes[bot_local:].max()
    if abs(rim_left - rim_right) / max(rim_left, rim_right) > 0.10: return None
    bot_price = closes[bot_local]
    height = (max(rim_left, rim_right) - bot_price) / bot_price
    if height < 0.10: return None
    breakout_level = rim_right
    if c12[i_12h] <= breakout_level: return None
    w_close_ms = int(W["t"][j_now] + TFW)
    since = int(np.searchsorted(t12, w_close_ms, side="left"))
    if since < 0 or since >= i_12h: return None
    if already_broken_above(breakout_level, since, i_12h): return None
    return _meta("rounding_bottom_w", "long", i_12h, since, since,
                 bot_price, breakout_level, height)


def detect_hs_complex_d_for_12h(i_12h: int) -> dict | None:
    """H&S Complex на D: 5 valleys, deepest in middle."""
    open_next_12h = int(t12[i_12h] + 12 * 60 * 60 * 1000) if i_12h + 1 < n12 else int(t12[i_12h])
    j_now = int(np.searchsorted(D["t"], open_next_12h, side="right")) - 1
    if j_now < 40: return None
    # D-level fractal n=2 valleys in last 40 D bars
    valleys = []
    for jj in range(max(2, j_now - 40), j_now - 1):
        if (jj + 2 >= D["n"]): continue
        if (D["l"][jj] < D["l"][jj-1] and D["l"][jj] < D["l"][jj-2] and
            D["l"][jj] < D["l"][jj+1] and D["l"][jj] < D["l"][jj+2]):
            valleys.append(jj)
    if len(valleys) < 5: return None
    v = valleys[-5:]
    head_idx = v[2]
    head = D["l"][head_idx]
    if not all(D["l"][k] > head for k in [v[0], v[1], v[3], v[4]]): return None
    # Neckline = max peak between v[1] and v[3]
    neckline = D["h"][v[1]:v[3]+1].max()
    height = (neckline - head) / head
    if height < 0.05: return None
    if c12[i_12h] <= neckline: return None
    d_close_ms = int(D["t"][j_now] + TFD)
    since = int(np.searchsorted(t12, d_close_ms, side="left"))
    if since < 0 or since >= i_12h: return None
    if already_broken_above(neckline, since, i_12h): return None
    return _meta("hs_complex_d", "long", i_12h, since, since, head, neckline, height)


# ═══════════════ Helper: meta-dict ═════════════════════════════
def _meta(name, side, i, low_idx, high_idx, low_price, neck_price, height_pct):
    return {
        "pattern": name, "side": side,
        "breakout_idx": int(i), "breakout_price": float(c12[i]),
        "low_idx": int(low_idx), "high_idx": int(high_idx),
        "low_price": float(low_price), "high_price": float(neck_price),
        "neck_price": float(neck_price),
        "height_pct": float(height_pct),
        "ts_ms": int(t12[i]),
    }


# ═══════════════ MAIN LOOP — detect all 19 ═════════════════════
print("\nRunning 19 detectors on full 12h chart...")

DETECTORS_12H = [
    ("big_w", detect_big_w),
    ("db_eve_eve", detect_db_eve_eve),
    ("hs_bottom", detect_hs_bottom),
    ("v_bottom", detect_v_bottom),
    ("barr_bottom", detect_barr_bottom),
    ("big_m", detect_big_m),
    ("hs_top", detect_hs_top),
    ("v_top", detect_v_top),
    ("barr_top", detect_barr_top),
    ("diamond_top", detect_diamond_top),
]
DETECTORS_HTF = [
    ("horn_bottom_w", detect_horn_bottom_w_for_12h),
    ("pipe_top_w", detect_pipe_top_w_for_12h),
    ("cup_handle_d", detect_cup_handle_d_for_12h),
    ("rounding_bottom_w", detect_rounding_bottom_w_for_12h),
    ("hs_complex_d", detect_hs_complex_d_for_12h),
]

all_fires = []
for name, fn in DETECTORS_12H + DETECTORS_HTF:
    fires = []
    for i in range(30, n12):
        sig = fn(i)
        if sig is not None:
            fires.append(sig)
    print(f"  {name:<25} → {len(fires):>3} fires")
    all_fires.extend(fires)

# Busted features
print("\nDetecting busted features...")
base_fires_by_pattern = {}
for f in all_fires:
    base_fires_by_pattern.setdefault(f["pattern"], []).append(f)

busted_specs = [
    ("hs_top_busted", "hs_top", "long"),
    ("triple_top_busted", "diamond_top", "long"),  # use diamond as triple proxy
    ("rect_bottom_busted", "v_bottom", "short"),   # placeholder mirror
    ("sym_triangle_busted", "barr_top", "long"),   # proxy
]
for new_name, base_name, flip_side in busted_specs:
    if base_name not in base_fires_by_pattern:
        print(f"  {new_name:<25} → 0 (no base {base_name})")
        continue
    bf = detect_busted(None, base_fires_by_pattern[base_name], new_name, flip_side)
    print(f"  {new_name:<25} → {len(bf):>3} fires (from {len(base_fires_by_pattern[base_name])} base)")
    all_fires.extend(bf)

# Sort
all_fires.sort(key=lambda f: (f["breakout_idx"], f["pattern"]))
print(f"\nTotal fires: {len(all_fires)}")

# ─── Walk-forward outcome (Bulkowski-style) ──────────────────
print("\nComputing walk-forward outcomes...")

def outcome(fire):
    i = fire["breakout_idx"]
    side = fire["side"]
    ref = fire["breakout_price"]
    height = fire["height_pct"]
    if i + OUTCOME_BARS >= n12:
        end = n12
    else:
        end = i + OUTCOME_BARS + 1
    peak_favor = 0.0
    peak_idx = i
    max_adverse = 0.0
    for k in range(i + 1, end):
        if side == "long":
            favor = (h12[k] - ref) / ref
            adverse = (ref - l12[k]) / ref
        else:
            favor = (ref - l12[k]) / ref
            adverse = (h12[k] - ref) / ref
        if favor > peak_favor:
            peak_favor = favor; peak_idx = k
        if adverse > max_adverse:
            max_adverse = adverse
        # 20% counter-move от peak terminates outcome
        if peak_favor > 0 and (peak_favor - favor) / peak_favor >= 0.20:
            break
    return {
        "ult_move_pct": peak_favor * 100,
        "max_adverse_pct": max_adverse * 100,
        "bars_to_extreme": peak_idx - i,
        "busted": int(peak_favor < 0.10 and max_adverse >= peak_favor * 2),
        "reached_target": int(peak_favor >= height),
        "reached_half_target": int(peak_favor >= height / 2),
    }

for f in all_fires:
    f.update(outcome(f))

# ─── Save fires + per-pattern stats ───────────────────────────
fires_df = pd.DataFrame(all_fires)
out_path = OUT_DIR / "D_stage1_fires.parquet"
fires_df.to_parquet(out_path, index=False)
print(f"\nSaved fires: {out_path}")

print("\n" + "=" * 90)
print("PER-PATTERN STATS (Bulkowski-style)")
print("=" * 90)
stats = fires_df.groupby("pattern").agg(
    n=("ult_move_pct", "count"),
    ult_move_mean=("ult_move_pct", "mean"),
    ult_move_med=("ult_move_pct", "median"),
    fail_rate=("busted", "mean"),
    reached_tgt=("reached_target", "mean"),
    half_tgt=("reached_half_target", "mean"),
).round(3).sort_values("ult_move_mean", ascending=False)
stats["fail_rate"] = (stats["fail_rate"] * 100).round(1)
stats["reached_tgt"] = (stats["reached_tgt"] * 100).round(1)
stats["half_tgt"] = (stats["half_tgt"] * 100).round(1)
print(stats.to_string())

# ─── Regime-cohorted (join D regime) ──────────────────────────
print("\n" + "=" * 90)
print("REGIME-COHORTED STATS")
print("=" * 90)
regime_df = pd.read_parquet(OUT_DIR / "D_regime_states.parquet")
fires_with_regime = fires_df.merge(
    regime_df[["bar_idx", "regime_state"]],
    left_on="breakout_idx", right_on="bar_idx", how="left")

cohort = fires_with_regime.groupby(["pattern", "regime_state"]).agg(
    n=("ult_move_pct", "count"),
    ult_mean=("ult_move_pct", "mean"),
    fail=("busted", "mean"),
).round(3)
cohort["fail"] = (cohort["fail"] * 100).round(1)
print(cohort.head(40).to_string())

print(f"\nSaved: {out_path}")
print(f"Total fires: {len(all_fires)}, unique patterns: {fires_df['pattern'].nunique()}")
