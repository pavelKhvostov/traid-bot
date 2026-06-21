"""
Feature engineering для force-model v3.

Базовые feature blocks (наследуется от v2) + НОВОЕ: liquidity_count_in_region.

Per-element feature lists:

FVG (10): age_bucket, first_touch, fill_state, size_bucket,
          direction_match, htf_trend_match,
          candle_body_atr, candle_range_atr, candle_direction,
          liq_count_region

fractal (10): age_bucket, failed_attempts, wick_size_atr,
              direction_match, htf_trend_match,
              candle_body_atr, candle_range_atr, candle_direction, prior_n_bars_trend,
              liq_count_region

OB (10): age_bucket, has_vc, size_bucket,
         direction_match, htf_trend_match,
         candle_body_atr, candle_range_atr, candle_direction, prior_n_bars_trend,
         liq_count_region

block_orders (9): age_bucket, size_bucket,
                  direction_match, htf_trend_match,
                  candle_body_atr, candle_range_atr, candle_direction, prior_n_bars_trend,
                  liq_count_region

RDRB (9): идентично block_orders

Liquidity feature semantics:
  Per row (candle, zone in region), `liq_count_region` = суммарное количество
  active liquidity levels (backward HH/LL chain) в region зоны across 6 TFs
  (4h, 6h, 12h, 1d, 2d, 3d). Эта фича одинаковая для всех zone-rows одной (candle, region).
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
from resample import tf_to_timedelta  # noqa: E402

from zones import ActiveZone  # noqa: E402


ATR_PERIOD = 14
HMA_PERIOD = 78
PRIOR_TREND_BARS = 20

AGE_FVG_YOUNG = 5
AGE_FVG_OLD = 30
AGE_OTHER_OLD = 20
SIZE_ATR_RATIO = 0.5
WICK_ATR_RATIO = 1.0
APPROACH_PCT = 0.5

LIQ_TFS = ("4h", "6h", "12h", "1d", "2d", "3d")  # 6 TFs для liquidity


# ─────────────────────────────────────────────────────────────
# Per-TF preprocessing (reused from v2)
# ─────────────────────────────────────────────────────────────

def compute_atr(df_tf: pd.DataFrame, period: int = ATR_PERIOD) -> pd.Series:
    high, low, close = df_tf["high"], df_tf["low"], df_tf["close"]
    pc = close.shift(1)
    tr = pd.concat([high - low, (high - pc).abs(), (low - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=period).mean()


def compute_hma_slope(df_tf: pd.DataFrame, period: int = HMA_PERIOD) -> pd.Series:
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
    closes = df_12h["close"]
    out = np.full(len(closes), np.nan)
    x = np.arange(n_bars, dtype=float)
    for i in range(n_bars, len(closes)):
        y = closes.iloc[i - n_bars: i].to_numpy()
        slope = np.polyfit(x, y, 1)[0]
        mean_y = float(np.mean(y))
        out[i] = slope / mean_y if mean_y > 0 else 0.0
    return pd.Series(out, index=closes.index)


# ─────────────────────────────────────────────────────────────
# Per-zone temporal features
# ─────────────────────────────────────────────────────────────

def _df_slice_between(df_tf: pd.DataFrame, born_ts: pd.Timestamp, cut_off_ts: pd.Timestamp) -> pd.DataFrame:
    return df_tf.loc[(df_tf.index > born_ts) & (df_tf.index < cut_off_ts)]


def fractal_failed_attempts(zone: ActiveZone, df_tf: pd.DataFrame, cut_off_ts: pd.Timestamp) -> int:
    level = zone.level
    if level is None:
        return 0
    df = _df_slice_between(df_tf, zone.born_ts, cut_off_ts)
    if df.empty:
        return 0
    tol = level * APPROACH_PCT / 100.0
    if zone.direction == "high":
        approached = ((df["high"] >= level - tol) & (df["high"] < level)).any()
    else:
        approached = ((df["low"] <= level + tol) & (df["low"] > level)).any()
    return int(bool(approached))


def fvg_fill_state(zone: ActiveZone, df_tf: pd.DataFrame, cut_off_ts: pd.Timestamp) -> int:
    df = _df_slice_between(df_tf, zone.born_ts, cut_off_ts)
    if df.empty:
        return 0
    return int(bool(((df["close"] >= zone.lo) & (df["close"] <= zone.hi)).any()))


def fvg_first_touch(zone: ActiveZone, df_tf: pd.DataFrame, cut_off_ts: pd.Timestamp, original_width: float) -> int:
    cw = zone.hi - zone.lo
    eps = 1e-6 * max(original_width, 1.0)
    return int(cw >= original_width - eps)


def fractal_wick_size_at_birth(df_tf: pd.DataFrame, center_idx: int, atr_at_birth: float) -> float:
    row = df_tf.iloc[center_idx]
    body_high = max(row["open"], row["close"])
    body_low = min(row["open"], row["close"])
    upper_wick = row["high"] - body_high
    lower_wick = body_low - row["low"]
    wick = max(upper_wick, lower_wick)
    return float(wick / atr_at_birth) if atr_at_birth > 0 else 0.0


# ─────────────────────────────────────────────────────────────
# Encoders
# ─────────────────────────────────────────────────────────────

def encode_age_fvg(age_bars: int) -> int:
    if age_bars < AGE_FVG_YOUNG:
        return 1
    if age_bars < AGE_FVG_OLD:
        return 2
    return 3


def encode_age_other(age_bars: int) -> int:
    return 1 if age_bars < AGE_OTHER_OLD else 2


def encode_size(width: float, atr: float) -> int:
    if atr <= 0:
        return 0
    return int(width >= SIZE_ATR_RATIO * atr)


def encode_direction_match(zone: ActiveZone, candle_is_bull: bool) -> int:
    if zone.side == "inside":
        return 0
    if zone.side == "above" and candle_is_bull:
        return 1
    if zone.side == "below" and not candle_is_bull:
        return 1
    return 0


def encode_htf_trend_match(zone: ActiveZone, hma_slope: float) -> int:
    direction = zone.direction
    if direction in ("long", "bottom", "low"):
        return int(hma_slope > 0)
    if direction in ("short", "top", "high"):
        return int(hma_slope < 0)
    return 0


# ─────────────────────────────────────────────────────────────
# NEW: Liquidity backward HH/LL chain в region
# ─────────────────────────────────────────────────────────────

def liquidity_count_in_region_short(
    resampled: dict[str, pd.DataFrame],
    cut_off_ts: pd.Timestamp,
    region_lo: float,
    region_hi: float,
    tfs: tuple = LIQ_TFS,
    max_lvls_per_tf: int = 20,
) -> int:
    """Backward higher-highs chain в каждом TF; считаем только level в [region_lo, region_hi]."""
    total = 0
    for tf in tfs:
        df_tf = resampled.get(tf)
        if df_tf is None or df_tf.empty:
            continue
        tf_td = tf_to_timedelta(tf)
        closed = df_tf.loc[(df_tf.index + tf_td) <= cut_off_ts]
        highs = closed["high"].to_numpy()
        n_in = 0
        pointer = -float("inf")
        for i in range(len(highs) - 1, -1, -1):
            h = highs[i]
            if h > pointer:
                pointer = h
                if region_lo <= h <= region_hi:
                    n_in += 1
                    if n_in >= max_lvls_per_tf:
                        break
                elif h > region_hi:
                    break
        total += n_in
    return total


def liquidity_count_in_region_long(
    resampled: dict[str, pd.DataFrame],
    cut_off_ts: pd.Timestamp,
    region_lo: float,
    region_hi: float,
    tfs: tuple = LIQ_TFS,
    max_lvls_per_tf: int = 20,
) -> int:
    """Backward lower-lows chain в каждом TF; считаем level в [region_lo, region_hi]."""
    total = 0
    for tf in tfs:
        df_tf = resampled.get(tf)
        if df_tf is None or df_tf.empty:
            continue
        tf_td = tf_to_timedelta(tf)
        closed = df_tf.loc[(df_tf.index + tf_td) <= cut_off_ts]
        lows = closed["low"].to_numpy()
        n_in = 0
        pointer = float("inf")
        for i in range(len(lows) - 1, -1, -1):
            l = lows[i]
            if l < pointer:
                pointer = l
                if region_lo <= l <= region_hi:
                    n_in += 1
                    if n_in >= max_lvls_per_tf:
                        break
                elif l < region_lo:
                    break
        total += n_in
    return total
