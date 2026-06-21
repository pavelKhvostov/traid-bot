"""Phase 2 Step 3 PoC — build subset top-10 Andrey features on 1h cadence (BTC).

Goal: verify pipeline architecture works at 1h cadence before full porting.
Subset of features (from etap_171 importance ranking):
  1. sweep_BSL_mag_24h_pct, sweep_BSL_failed_24h
  2. sweep_SSL_mag_24h_pct, sweep_SSL_failed_24h
  3. candle_close_pos_in_range
  4. candle_range_vs_atr, candle_upper_wick_pct, candle_lower_wick_pct
  5. rsi_14_1h
  6. hull_78_slope_pct_1h
  7. atr_pct_1h, vol_zscore_20_1h
  8. ema_200_dist_pct_1h
  9. lopez_parkinson_1h
  10. day_of_week, hour_utc

Train + holdout per spec lock (2020-2024 train, 2025-2026.05 holdout).
Output: data/features_poc_1h.parquet

Test idea: train on y_long_3pct_24h (positive ~27%), verify AUC > 0.55 baseline.
If AUC > 0.65 → pipeline architecture is sound, scale to full port.
"""
from __future__ import annotations
import time
from pathlib import Path

import numpy as np
import pandas as pd

# ─── Paths ──────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
PHASE1_DATA = ROOT / "phase1_reproduce" / "data"
OUT_PATH = DATA_DIR / "features_poc_1h.parquet"


def load_1h() -> pd.DataFrame:
    src = PHASE1_DATA / "BTCUSDT_1h.csv"
    df = pd.read_csv(src)
    df["open_time"] = pd.to_datetime(df["open_time"], utc=True)
    df = df.set_index("open_time").sort_index()
    return df


# ─── Indicator helpers (from etap_171, adapted) ──────────────────
def rsi_wilder(series: pd.Series, length: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _wma(values: pd.Series, length: int) -> pd.Series:
    w = np.arange(1, length + 1, dtype=float)
    return values.rolling(length).apply(lambda x: np.dot(x, w) / w.sum(), raw=True)


def hull_ma(series: pd.Series, length: int = 78) -> pd.Series:
    half = length // 2
    sqrtl = int(np.sqrt(length))
    return _wma(2 * _wma(series, half) - _wma(series, length), sqrtl)


def ema(series: pd.Series, length: int = 200) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()


def atr_pct(df: pd.DataFrame, length: int = 14) -> pd.Series:
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / length, min_periods=length, adjust=False).mean() / close * 100


def parkinson_vol(df: pd.DataFrame, window: int = 14) -> pd.Series:
    """Parkinson volatility estimator (HL-only). σ = √(1/(4 ln 2) * mean(ln(H/L)²))."""
    log_hl = np.log(df["high"] / df["low"])
    return np.sqrt(log_hl.pow(2).rolling(window).mean() / (4 * np.log(2)))


# ─── Sweep features (key — top-1 importance) ─────────
def build_sweep_24h(df: pd.DataFrame) -> pd.DataFrame:
    """Compute sweep BSL/SSL features on 1h cadence within 24h backward window.

    For each 1h bar i (look back at last 24 bars including i):
      prev_window = bars[i-23..i-1] (23 bars)
      prev_hi = prev_window['high'].max()
      prev_lo = prev_window['low'].min()
      sweep_BSL = (high[i] > prev_hi) — пробитие предыдущего high
      sweep_BSL_mag_pct = (high[i] - prev_hi) / close[i] * 100, if sweep else 0
      sweep_BSL_failed = sweep AND (close[i] <= prev_hi) — фитиль пробил, close не пробил
    SSL mirror.
    """
    n = len(df)
    high = df["high"].to_numpy()
    low = df["low"].to_numpy()
    close = df["close"].to_numpy()

    sweep_BSL = np.zeros(n, dtype=bool)
    sweep_SSL = np.zeros(n, dtype=bool)
    sweep_BSL_mag_pct = np.zeros(n)
    sweep_SSL_mag_pct = np.zeros(n)
    sweep_BSL_failed = np.zeros(n, dtype=bool)
    sweep_SSL_failed = np.zeros(n, dtype=bool)

    WIN = 24
    for i in range(WIN, n):
        prev_lo_i = max(0, i - WIN + 1)
        # prev window = bars[prev_lo_i .. i-1] (does NOT include i)
        if i - prev_lo_i < 5:
            continue
        prev_hi = high[prev_lo_i:i].max()
        prev_lo = low[prev_lo_i:i].min()
        if high[i] > prev_hi:
            sweep_BSL[i] = True
            sweep_BSL_mag_pct[i] = (high[i] - prev_hi) / close[i] * 100
            sweep_BSL_failed[i] = close[i] <= prev_hi
        if low[i] < prev_lo:
            sweep_SSL[i] = True
            sweep_SSL_mag_pct[i] = (prev_lo - low[i]) / close[i] * 100
            sweep_SSL_failed[i] = close[i] >= prev_lo

    return pd.DataFrame(
        {
            "sweep_BSL_24h": sweep_BSL.astype("int8"),
            "sweep_SSL_24h": sweep_SSL.astype("int8"),
            "sweep_BSL_mag_24h_pct": sweep_BSL_mag_pct,
            "sweep_SSL_mag_24h_pct": sweep_SSL_mag_pct,
            "sweep_BSL_failed_24h": sweep_BSL_failed.astype("int8"),
            "sweep_SSL_failed_24h": sweep_SSL_failed.astype("int8"),
        },
        index=df.index,
    )


# ─── Candle anatomy ──────────────────────────────────
def build_candle_anatomy(df: pd.DataFrame) -> pd.DataFrame:
    rng = df["high"] - df["low"]
    body = (df["close"] - df["open"]).abs()
    upper_wick = df["high"] - df[["open", "close"]].max(axis=1)
    lower_wick = df[["open", "close"]].min(axis=1) - df["low"]
    atr_1h = atr_pct(df, 14) * df["close"] / 100  # back to absolute ATR

    out = pd.DataFrame(
        {
            "candle_body_pct": (body / rng).replace([np.inf, -np.inf], 0).fillna(0),
            "candle_range_vs_atr": (rng / atr_1h).replace([np.inf, -np.inf], 1).fillna(1),
            "candle_upper_wick_pct": (upper_wick / rng).replace([np.inf, -np.inf], 0).fillna(0),
            "candle_lower_wick_pct": (lower_wick / rng).replace([np.inf, -np.inf], 0).fillna(0),
            "candle_close_pos_in_range": ((df["close"] - df["low"]) / rng).replace([np.inf, -np.inf], 0.5).fillna(0.5),
            "candle_is_bull": (df["close"] > df["open"]).astype("int8"),
        },
        index=df.index,
    )
    return out


# ─── Time features ───────────────────────────────────
def build_time_features(df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "hour_utc": df.index.hour.astype("int8"),
            "day_of_week": df.index.dayofweek.astype("int8"),
            "is_weekend": (df.index.dayofweek >= 5).astype("int8"),
        },
        index=df.index,
    )


# ─── Indicators on 1h ────────────────────────────────
def build_1h_indicators(df: pd.DataFrame) -> pd.DataFrame:
    close = df["close"]
    rsi = rsi_wilder(close, 14)
    hma78 = hull_ma(close, 78)
    ema200 = ema(close, 200)
    park = parkinson_vol(df, 14)
    vol_ma = df["volume"].rolling(20).mean()
    vol_std = df["volume"].rolling(20).std()
    vol_z = (df["volume"] - vol_ma) / vol_std.replace(0, np.nan)

    hma_slope = (hma78 - hma78.shift(3)) / hma78.shift(3).replace(0, np.nan) * 100

    return pd.DataFrame(
        {
            "rsi_14_1h": rsi.fillna(50),
            "hull_78_slope_pct_1h": hma_slope.fillna(0),
            "ema_200_dist_pct_1h": ((close - ema200) / close).fillna(0) * 100,
            "atr_pct_1h": atr_pct(df, 14).fillna(0),
            "vol_zscore_20_1h": vol_z.fillna(0),
            "lopez_parkinson_1h": park.fillna(0),
        },
        index=df.index,
    )


# ─── Main ────────────────────────────────────────────
def main() -> None:
    t0 = time.time()
    df = load_1h()
    print(f"Loaded {len(df):,} 1h bars from {df.index[0]} to {df.index[-1]}")

    # Build feature blocks
    print("Building sweep features...")
    sweep = build_sweep_24h(df)

    print("Building candle anatomy...")
    anatomy = build_candle_anatomy(df)

    print("Building time features...")
    time_f = build_time_features(df)

    print("Building 1h indicators...")
    indicators = build_1h_indicators(df)

    feats = pd.concat([sweep, anatomy, time_f, indicators], axis=1)
    feats.index.name = "open_time"
    # Snapshot timestamp = close of bar = open_time + 1h
    feats["snapshot_close_time"] = feats.index + pd.Timedelta(hours=1)
    feats = feats.set_index("snapshot_close_time")

    print(f"\nTotal feature count: {len(feats.columns)}  rows: {len(feats):,}")
    print(f"Feature head:")
    print(feats.head(3).to_string())

    print(f"\nNaN counts per feature:")
    print(feats.isna().sum())

    DATA_DIR.mkdir(exist_ok=True)
    feats.to_parquet(OUT_PATH)
    print(f"\n→ Saved: {OUT_PATH}")
    print(f"Total elapsed: {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
