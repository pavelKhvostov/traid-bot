"""
Feature engineering для force-model v2.

Per-element feature lists (заморожено [[force-model-v2-architecture]]):

FVG (9): age_bucket, first_touch, fill_state, size_bucket,
         direction_match, htf_trend_match,
         candle_body_atr, candle_range_atr, candle_direction

fractal (9): age_bucket, failed_attempts, wick_size_atr,
             direction_match, htf_trend_match,
             candle_body_atr, candle_range_atr, candle_direction, prior_n_bars_trend

OB (9): age_bucket, has_vc, size_bucket,
        direction_match, htf_trend_match,
        candle_body_atr, candle_range_atr, candle_direction, prior_n_bars_trend

block_orders (8): age_bucket, size_bucket,
                  direction_match, htf_trend_match,
                  candle_body_atr, candle_range_atr, candle_direction, prior_n_bars_trend

RDRB (8): идентично block_orders

Все features детерминированные (никакого обучения внутри features).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

SMC_LIB = Path(os.environ.get("SMCLIB_ROOT", str(Path.home() / "smc-lib")))
sys.path.insert(0, str(SMC_LIB / "indicators"))
sys.path.insert(0, str(SMC_LIB / "prediction-algo"))

from trend_line_asvk import hma  # noqa: E402

from zones import ActiveZone  # noqa: E402


ATR_PERIOD = 14
HMA_PERIOD = 78
PRIOR_TREND_BARS = 20

# Thresholds (см. force-model-v2-architecture.md)
AGE_FVG_YOUNG = 5      # < 5 bars TF
AGE_FVG_OLD = 30       # ≥ 30 bars TF
AGE_OTHER_OLD = 20     # < 20 new, ≥ 20 old (fractal/OB/block_orders/RDRB)
SIZE_ATR_RATIO = 0.5   # size_bucket: width < 0.5*ATR → small
WICK_ATR_RATIO = 1.0   # wick_size_atr: < 1.0*ATR → small
APPROACH_PCT = 0.5     # для failed_attempts: подход в пределах 0.5%


# ─────────────────────────────────────────────────────────────
# Per-TF preprocessing (ATR, HMA, prior_trend)
# ─────────────────────────────────────────────────────────────

def compute_atr(df_tf: pd.DataFrame, period: int = ATR_PERIOD) -> pd.Series:
    """ATR(period) на TF; используется как нормировка размеров."""
    high = df_tf["high"]
    low = df_tf["low"]
    close = df_tf["close"]
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=period).mean()


def compute_hma_slope(df_tf: pd.DataFrame, period: int = HMA_PERIOD) -> pd.Series:
    """HMA(period) slope sign: +1 rising, -1 falling, 0 flat."""
    closes = df_tf["close"].tolist()
    h = hma(closes, period)
    slope = np.zeros(len(h))
    for i in range(1, len(h)):
        if h[i] is None or h[i - 1] is None:
            continue
        d = h[i] - h[i - 1]
        slope[i] = 1.0 if d > 0 else (-1.0 if d < 0 else 0.0)
    return pd.Series(slope, index=df_tf.index)


def compute_prior_trend_slope(df_12h: pd.DataFrame, n_bars: int = PRIOR_TREND_BARS) -> pd.Series:
    """Slope of close over previous N bars (rolling linregress slope, normalized by mean close)."""
    closes = df_12h["close"]
    out = np.full(len(closes), np.nan)
    x = np.arange(n_bars, dtype=float)
    for i in range(n_bars, len(closes)):
        y = closes.iloc[i - n_bars: i].to_numpy()
        # slope = cov(x,y) / var(x); normalize by mean(y)
        slope = np.polyfit(x, y, 1)[0]
        mean_y = float(np.mean(y))
        out[i] = slope / mean_y if mean_y > 0 else 0.0
    return pd.Series(out, index=closes.index)


# ─────────────────────────────────────────────────────────────
# Per-zone temporal features (нужны bars от born до current cut-off)
# ─────────────────────────────────────────────────────────────

def _df_slice_between(df_tf: pd.DataFrame, born_ts: pd.Timestamp, cut_off_ts: pd.Timestamp) -> pd.DataFrame:
    """Bars из df_tf с born_ts < open_time < cut_off_ts (exclusive обоих)."""
    return df_tf.loc[(df_tf.index > born_ts) & (df_tf.index < cut_off_ts)]


def fractal_failed_attempts(zone: ActiveZone, df_tf: pd.DataFrame, cut_off_ts: pd.Timestamp) -> int:
    """Binary: 1 если был хотя бы один approach (wick в пределах APPROACH_PCT от level, но не sweep), 0 иначе."""
    level = zone.level
    if level is None:
        return 0
    df = _df_slice_between(df_tf, zone.born_ts, cut_off_ts)
    if df.empty:
        return 0
    tol = level * APPROACH_PCT / 100.0
    if zone.direction == "high":
        approached = ((df["high"] >= level - tol) & (df["high"] < level)).any()
    else:  # 'low'
        approached = ((df["low"] <= level + tol) & (df["low"] > level)).any()
    return int(bool(approached))


def fvg_fill_state(zone: ActiveZone, df_tf: pd.DataFrame, cut_off_ts: pd.Timestamp) -> int:
    """1 = complete (был ≥1 close внутри [lo,hi]); 0 = partial (только wick касания)."""
    df = _df_slice_between(df_tf, zone.born_ts, cut_off_ts)
    if df.empty:
        return 0
    closes_inside = ((df["close"] >= zone.lo) & (df["close"] <= zone.hi)).any()
    return int(bool(closes_inside))


def fvg_first_touch(zone: ActiveZone, df_tf: pd.DataFrame, cut_off_ts: pd.Timestamp, original_width: float) -> int:
    """1 = virgin (current width == original ± epsilon); 0 = touched."""
    current_width = zone.hi - zone.lo
    eps = 1e-6 * max(original_width, 1.0)
    return int(current_width >= original_width - eps)


def fractal_wick_size_at_birth(df_tf: pd.DataFrame, center_idx: int, atr_at_birth: float) -> float:
    """Wick size центральной свечи fractal / ATR. Возвращает ratio."""
    row = df_tf.iloc[center_idx]
    body_high = max(row["open"], row["close"])
    body_low = min(row["open"], row["close"])
    upper_wick = row["high"] - body_high
    lower_wick = body_low - row["low"]
    # Берём максимальный wick (sweep direction обычно туда)
    wick = max(upper_wick, lower_wick)
    return float(wick / atr_at_birth) if atr_at_birth > 0 else 0.0


# ─────────────────────────────────────────────────────────────
# Encoders: continuous → ordinal/binary
# ─────────────────────────────────────────────────────────────

def encode_age_fvg(age_bars: int) -> int:
    """3-ordinal: young=1, mid=2, old=3."""
    if age_bars < AGE_FVG_YOUNG:
        return 1
    if age_bars < AGE_FVG_OLD:
        return 2
    return 3


def encode_age_other(age_bars: int) -> int:
    """2-ordinal: new=1, old=2."""
    return 1 if age_bars < AGE_OTHER_OLD else 2


def encode_size(width: float, atr: float) -> int:
    """0 small, 1 large."""
    if atr <= 0:
        return 0
    return int(width >= SIZE_ATR_RATIO * atr)


def encode_direction_match(zone: ActiveZone, candle_is_bull: bool) -> int:
    """1 если зона = противовес направлению свечи, 0 если совпадает / inside."""
    if zone.side == "inside":
        return 0
    if zone.side == "above" and candle_is_bull:
        return 1
    if zone.side == "below" and not candle_is_bull:
        return 1
    return 0


def encode_htf_trend_match(zone: ActiveZone, hma_slope: float) -> int:
    """1 если slope HMA(78) согласуется с logical direction зоны, 0 иначе.

    long zone (support, bounce up) → match positive slope
    short zone (resistance, bounce down) → match negative slope
    fractal high (FH = bearish target after sweep) → match negative slope
    fractal low (FL = bullish target after sweep) → match positive slope
    RB top → short-like; RB bottom → long-like.
    """
    direction = zone.direction
    if direction in ("long", "bottom", "low"):
        return int(hma_slope > 0)
    if direction in ("short", "top", "high"):
        return int(hma_slope < 0)
    return 0
