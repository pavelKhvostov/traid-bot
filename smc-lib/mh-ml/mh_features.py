"""MH multi-TF feature engineering.

Для каждого 15m timestamp вычисляем ~90-D feature vector:
- Per TF (8 TFs): bw2, bw2_sign, bw2_vs_sma14, color (one-hot 4), MF, mf_sign,
                  in_OB, in_OS, bars_since_zero_cross  → 10 features × 8 TFs = 80
- Cross-TF: resonance, bw2_consensus, cascade_bull/bear_freshness,
            htf_ltf_alignment, n_OB, n_OS, ... → ~10 features

Output: pd.DataFrame indexed by 15m timestamps (UTC).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

SMC_LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SMC_LIB))
sys.path.insert(0, str(SMC_LIB / "prediction-algo"))

from indicators.money_hands_asvk import money_hands  # noqa: E402
from resample import resample_one, tf_to_timedelta  # noqa: E402


# Canon 8 TFs (геометрическая ×2 прогрессия)
TFS_8: tuple[str, ...] = ("15m", "30m", "1h", "2h", "4h", "8h", "16h", "32h")

# Color → one-hot (4 categories)
COLOR_CATS: tuple[str, ...] = ("green", "white_weak_bull", "red", "white_weak_bear")

# OB/OS thresholds (canon)
OB_LEVEL = 60.0
OS_LEVEL = -60.0


def _compute_mh_per_tf(df_1m: pd.DataFrame, tf: str, end_ts: pd.Timestamp) -> pd.DataFrame:
    """Resample 1m → TF, compute MH (все 4 канон-фактора), return DataFrame."""
    df_tf = resample_one(df_1m, tf, end_ts)
    bars = list(zip(df_tf["open"], df_tf["high"], df_tf["low"], df_tf["close"], df_tf["volume"]))
    mh = money_hands(bars)
    n = len(df_tf)
    bw2 = pd.Series(mh["bw2"], index=df_tf.index, dtype="float64")
    mf = pd.Series(mh["mf"], index=df_tf.index, dtype="float64")
    color = pd.Series(mh["color"], index=df_tf.index, dtype="object")
    rsi_mod = pd.Series(mh["rsi_mod"], index=df_tf.index, dtype="float64")
    stc_rsi_mod = pd.Series(mh["stc_rsi_mod"], index=df_tf.index, dtype="float64")
    sma14 = bw2.rolling(14).mean()
    # bars_since_zero_cross — для каждого бара, сколько TF-баров прошло с последнего пересечения 0
    sign = np.sign(bw2.fillna(0).to_numpy())
    bars_since = np.zeros(n, dtype="int32")
    cnt = 0
    last_sign = 0
    for i in range(n):
        s = sign[i]
        if s != 0 and s != last_sign and last_sign != 0:
            cnt = 0
        cnt += 1
        bars_since[i] = cnt
        if s != 0:
            last_sign = s
    return pd.DataFrame({
        # Factor 1 — bw2 (WaveTrend)
        "bw2": bw2,
        "bw2_sign": np.sign(bw2),
        "bw2_vs_sma14": bw2 - sma14,
        "in_OB": (bw2 >= OB_LEVEL).astype("int8"),
        "in_OS": (bw2 <= OS_LEVEL).astype("int8"),
        "bars_since_zero_cross": bars_since,
        # Factor 2 — color state
        "color": color,
        # Factor 3 — Heikin Ashi Money Flow
        "mf": mf,
        "mf_sign": np.sign(mf),
        # Factor 4 — двойной Stochastic
        "rsi_mod": rsi_mod,
        "stc_rsi_mod": stc_rsi_mod,
        "rsi_in_OB": (rsi_mod >= 75).astype("int8"),
        "rsi_in_OS": (rsi_mod <= 25).astype("int8"),
        "stc_in_OB": (stc_rsi_mod >= 75).astype("int8"),
        "stc_in_OS": (stc_rsi_mod <= 25).astype("int8"),
        "rsi_above_stc": (rsi_mod > stc_rsi_mod).astype("int8"),
    }, index=df_tf.index)


def _reindex_to_15m(per_tf_df: pd.DataFrame, target_idx: pd.DatetimeIndex, tf: str) -> pd.DataFrame:
    """Для каждого 15m timestamp взять самое свежее ЗАКРЫТОЕ значение TF.
    "Закрытое" = bar.open_time + tf_duration <= 15m_timestamp.

    Использует pd.merge_asof с tolerance.
    """
    tf_td = tf_to_timedelta(tf)
    # close_ts = bar.open_time + tf_duration; для merge_asof берём close_ts как ключ
    closed = per_tf_df.copy()
    closed["close_ts"] = closed.index + tf_td
    closed = closed.reset_index(drop=False).rename(columns={"open_time": "open_ts"})
    target = pd.DataFrame({"ts": target_idx})
    merged = pd.merge_asof(
        target.sort_values("ts"),
        closed.sort_values("close_ts"),
        left_on="ts",
        right_on="close_ts",
        direction="backward",
    )
    merged = merged.set_index("ts")
    cols_out = ["bw2", "bw2_sign", "bw2_vs_sma14", "in_OB", "in_OS", "bars_since_zero_cross",
                "color",
                "mf", "mf_sign",
                "rsi_mod", "stc_rsi_mod", "rsi_in_OB", "rsi_in_OS",
                "stc_in_OB", "stc_in_OS", "rsi_above_stc"]
    return merged[cols_out]


def _color_one_hot(color: pd.Series) -> pd.DataFrame:
    out = pd.DataFrame(index=color.index)
    for cat in COLOR_CATS:
        out[f"color_{cat}"] = (color == cat).astype("int8")
    return out


def build_features(
    df_1m: pd.DataFrame,
    tfs: Iterable[str] = TFS_8,
    target_freq: str = "15m",
) -> pd.DataFrame:
    """Главный API — построить multi-TF feature matrix по 15m sampling.

    Args:
        df_1m: 1m OHLCV (DatetimeIndex UTC).
        tfs: список TFs для MH (default 8 канонических).
        target_freq: sampling frequency для feature matrix (default 15m).

    Returns:
        DataFrame indexed by 15m timestamps, ~90 columns.
    """
    end_ts = df_1m.index[-1] + pd.Timedelta(minutes=1)
    # 15m grid (target sampling)
    grid = resample_one(df_1m, target_freq, end_ts).index

    feat_parts = []
    color_parts = []
    for tf in tfs:
        per_tf = _compute_mh_per_tf(df_1m, tf, end_ts)
        aligned = _reindex_to_15m(per_tf, grid, tf)
        # Rename columns with TF suffix (except color which we one-hot below)
        non_color = aligned.drop(columns=["color"]).add_suffix(f"_{tf}")
        feat_parts.append(non_color)
        color_oh = _color_one_hot(aligned["color"]).add_suffix(f"_{tf}")
        color_parts.append(color_oh)

    features = pd.concat(feat_parts + color_parts, axis=1)

    # Cross-TF aggregates
    bw2_cols = [f"bw2_{tf}" for tf in tfs]
    mf_cols = [f"mf_{tf}" for tf in tfs]
    in_ob_cols = [f"in_OB_{tf}" for tf in tfs]
    in_os_cols = [f"in_OS_{tf}" for tf in tfs]
    sign_cols = [f"bw2_sign_{tf}" for tf in tfs]

    features["bw2_consensus"] = features[sign_cols].sum(axis=1)            # ∈ [-8, +8]
    features["n_TFs_in_OB"] = features[in_ob_cols].sum(axis=1)
    features["n_TFs_in_OS"] = features[in_os_cols].sum(axis=1)
    features["bw2_mean"] = features[bw2_cols].mean(axis=1)
    features["mf_mean"] = features[mf_cols].mean(axis=1)
    # Resonance score — сколько TFs совпадает по знаку bw2 и MF
    bw2_signs = np.sign(features[bw2_cols].to_numpy())
    mf_signs = np.sign(features[mf_cols].to_numpy())
    features["bw2_mf_alignment"] = (bw2_signs == mf_signs).sum(axis=1).astype("int8")  # ∈ [0, 8]
    # Stochastic cross-TF aggregates
    rsi_cols = [f"rsi_mod_{tf}" for tf in tfs]
    stc_cols = [f"stc_rsi_mod_{tf}" for tf in tfs]
    rsi_above_stc_cols = [f"rsi_above_stc_{tf}" for tf in tfs]
    rsi_ob_cols = [f"rsi_in_OB_{tf}" for tf in tfs]
    rsi_os_cols = [f"rsi_in_OS_{tf}" for tf in tfs]
    features["rsi_mod_mean"] = features[rsi_cols].mean(axis=1)
    features["stc_rsi_mod_mean"] = features[stc_cols].mean(axis=1)
    features["n_TFs_rsi_above_stc"] = features[rsi_above_stc_cols].sum(axis=1)  # ∈ [0, 8]
    features["n_TFs_rsi_OB"] = features[rsi_ob_cols].sum(axis=1)
    features["n_TFs_rsi_OS"] = features[rsi_os_cols].sum(axis=1)
    # Bull/bear cascade freshness — для каждого TF берём bars_since_zero_cross, конвертим в часы
    # и берём минимум по «свежим bear» (sign=-1) и «свежим bull» (sign=+1)
    bsc_cols = [f"bars_since_zero_cross_{tf}" for tf in tfs]
    # Convert bars to hours per TF
    tf_minutes = {"15m": 15, "30m": 30, "1h": 60, "2h": 120, "4h": 240,
                  "8h": 480, "16h": 960, "32h": 1920}
    cascade_bull_h = np.full(len(features), np.inf)
    cascade_bear_h = np.full(len(features), np.inf)
    for tf in tfs:
        bsc = features[f"bars_since_zero_cross_{tf}"].to_numpy()
        sign = features[f"bw2_sign_{tf}"].to_numpy()
        hours = bsc * tf_minutes[tf] / 60.0
        cascade_bull_h = np.where((sign > 0) & (hours < cascade_bull_h), hours, cascade_bull_h)
        cascade_bear_h = np.where((sign < 0) & (hours < cascade_bear_h), hours, cascade_bear_h)
    features["cascade_bull_freshness_h"] = np.where(np.isinf(cascade_bull_h), 9999.0, cascade_bull_h)
    features["cascade_bear_freshness_h"] = np.where(np.isinf(cascade_bear_h), 9999.0, cascade_bear_h)

    return features
