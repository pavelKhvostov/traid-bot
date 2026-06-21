"""MH multi-TF feature engineering v2 — расширенный набор ~1290 features.

13 групп features per TF + cross-TF aggregates + 2 parameter variants (R, S):
  A. Base values (bw2, mf, rsi, stc) × 8 TFs
  B. Sign features
  C. Slopes (4 indicators × 5 windows)
  D. Acceleration (bw2, mf × 3 windows)
  E. Distance from levels
  F. Cross-line features (mf-bw2, etc)
  G. Time-since events
  H. Statistical rollings (mean, std, percentile_rank × 2 windows)
  I. Direction binary (rising_streak, vs[-N])
  J. Concordance flags
  K. Recent crossings
  M. Count aggregates (cross-TF)
  N. Mean/std across TFs
  O. HTF/LTF alignment
  P. Diff between TFs
  Q. Cascade timing
  R. bw2 EMA(7) variant
  S. bw2 EMA(13) variant

Output: ~1200-1300 features per 15m timestamp.
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

from resample import resample_one, tf_to_timedelta  # noqa: E402


TFS_8: tuple[str, ...] = ("15m", "30m", "1h", "2h", "4h", "8h", "16h", "32h")
COLOR_CATS: tuple[str, ...] = ("green", "white_weak_bull", "red", "white_weak_bear")

OB_LEVEL = 60.0
OS_LEVEL = -60.0


# ─── Parametric MH calculation ───────────────────────────────────────

def _ema_np(values: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(values), np.nan)
    if len(values) < n:
        return out
    alpha = 2.0 / (n + 1)
    init = np.nanmean(values[:n])
    if np.isnan(init):
        return out
    out[n - 1] = init
    for i in range(n, len(values)):
        v = values[i]
        if np.isnan(v):
            out[i] = out[i - 1]
        else:
            out[i] = alpha * v + (1 - alpha) * out[i - 1]
    return out


def _sma_np(values: np.ndarray, n: int) -> np.ndarray:
    s = pd.Series(values).rolling(n, min_periods=n).mean()
    return s.to_numpy()


def compute_mh_parametric(
    o: np.ndarray, h: np.ndarray, l: np.ndarray, c: np.ndarray,
    n1: int = 9, n2: int = 9, n3: int = 12, n4: int = 4,
    sma_compare: int = 14, mf_sma: int = 60,
    stoch_fast: int = 40, stoch_slow: int = 81,
) -> dict:
    """Parametric Money Hands. Default = canon (9,9,12,4,14,60,40,81)."""
    n = len(o)
    ap = (h + l + c) / 3.0
    esa = _ema_np(ap, n1)
    abs_diff = np.where(np.isnan(esa), np.nan, np.abs(ap - esa))
    d = _ema_np(np.where(np.isnan(abs_diff), 0.0, abs_diff), n2)
    d = np.where(np.isnan(abs_diff), np.nan, d)
    ci = np.where((np.isnan(esa)) | (np.isnan(d)) | (d == 0), np.nan, (ap - esa) / (0.015 * d))
    wt1 = _ema_np(np.where(np.isnan(ci), 0.0, ci), n3)
    wt1 = np.where(np.isnan(ci), np.nan, wt1)
    bw2 = _sma_np(wt1, n4)
    bw2_sma = _sma_np(bw2, sma_compare)

    # MF (HA-based)
    ha_open = np.zeros(n); ha_close = np.zeros(n); ha_high = np.zeros(n); ha_low = np.zeros(n)
    if n > 0:
        ha_close[0] = (o[0] + h[0] + l[0] + c[0]) / 4
        ha_open[0] = (o[0] + c[0]) / 2
        ha_high[0] = max(h[0], ha_open[0], ha_close[0])
        ha_low[0] = min(l[0], ha_open[0], ha_close[0])
        for i in range(1, n):
            ha_close[i] = (o[i] + h[i] + l[i] + c[i]) / 4
            ha_open[i] = (ha_open[i - 1] + ha_close[i - 1]) / 2
            ha_high[i] = max(h[i], ha_open[i], ha_close[i])
            ha_low[i] = min(l[i], ha_open[i], ha_close[i])
    rng = ha_high - ha_low
    raw = np.where(rng > 0, (ha_close - ha_open) / rng * 200, 0.0)
    mf = _sma_np(raw, mf_sma) - 2.25

    # Stochastic
    def stoch(window: int) -> np.ndarray:
        out = np.full(n, np.nan)
        for i in range(window - 1, n):
            hh = np.max(h[i - window + 1:i + 1])
            ll = np.min(l[i - window + 1:i + 1])
            if hh > ll:
                out[i] = 100 * (c[i] - ll) / (hh - ll)
            else:
                out[i] = 50.0
        return out
    rsi_mod = _sma_np(stoch(stoch_fast), 2)
    stc_rsi_mod = _sma_np(stoch(stoch_slow), 2)

    return {
        "bw2": bw2, "bw2_sma": bw2_sma,
        "mf": mf,
        "rsi_mod": rsi_mod, "stc_rsi_mod": stc_rsi_mod,
    }


# ─── Helper feature generators per TF ────────────────────────────────

def _color_state(bw2: np.ndarray, bw2_sma: np.ndarray) -> np.ndarray:
    """Return color state per bar as int code: 0=green, 1=ww_bull, 2=red, 3=ww_bear, -1=none."""
    out = np.full(len(bw2), -1, dtype=np.int8)
    for i in range(len(bw2)):
        if np.isnan(bw2[i]) or np.isnan(bw2_sma[i]):
            continue
        if bw2[i] > 0:
            out[i] = 0 if bw2[i] >= bw2_sma[i] else 1
        elif bw2[i] < 0:
            out[i] = 2 if bw2[i] <= bw2_sma[i] else 3
    return out


def _bars_since_event(bool_arr: np.ndarray) -> np.ndarray:
    """For each bar, bars since last True event. -1 if never."""
    n = len(bool_arr)
    out = np.full(n, -1, dtype=np.int32)
    last = -1
    for i in range(n):
        if bool_arr[i]:
            last = i
            out[i] = 0
        elif last >= 0:
            out[i] = i - last
    return out


def _bars_since_sign_flip(arr: np.ndarray) -> np.ndarray:
    n = len(arr)
    out = np.zeros(n, dtype=np.int32)
    sign = np.sign(np.nan_to_num(arr, nan=0.0))
    last_sign = 0
    cnt = 0
    for i in range(n):
        s = sign[i]
        if s != 0 and last_sign != 0 and s != last_sign:
            cnt = 0
        cnt += 1
        out[i] = cnt
        if s != 0:
            last_sign = s
    return out


def _build_per_tf_features(mh: dict, prefix: str = "") -> pd.DataFrame:
    """Build all per-TF feature groups for one MH-snapshot DataFrame.
    `prefix` = optional prefix (e.g. "v_fast_") для variants R/S.
    """
    bw2 = mh["bw2"]
    bw2_sma = mh["bw2_sma"]
    mf = mh["mf"]
    rsi = mh["rsi_mod"]
    stc = mh["stc_rsi_mod"]
    n = len(bw2)

    out: dict[str, np.ndarray] = {}
    P = prefix

    # ── A. Base values
    out[f"{P}bw2"] = bw2
    out[f"{P}mf"] = mf
    out[f"{P}rsi"] = rsi
    out[f"{P}stc"] = stc

    # ── B. Signs
    out[f"{P}sign_bw2"] = np.sign(bw2)
    out[f"{P}sign_mf"] = np.sign(mf)
    out[f"{P}sign_rsi_50"] = np.sign(rsi - 50)
    out[f"{P}sign_stc_50"] = np.sign(stc - 50)
    out[f"{P}sign_rsi_stc"] = np.sign(rsi - stc)

    # ── C. Slopes (4 indicators × 5 windows = 20 features)
    series_map = {"bw2": bw2, "mf": mf, "rsi": rsi, "stc": stc}
    for name, arr in series_map.items():
        s = pd.Series(arr)
        for w in (1, 3, 5, 10, 20):
            out[f"{P}slope_{name}_{w}"] = (s.diff(w) / w).to_numpy()

    # ── D. Acceleration (bw2, mf × 3 windows = 6)
    for name, arr in [("bw2", bw2), ("mf", mf)]:
        s = pd.Series(arr)
        for w in (3, 5, 10):
            slope = s.diff(w) / w
            out[f"{P}accel_{name}_{w}"] = slope.diff(w).to_numpy() / w

    # ── E. Distance from levels (11 features)
    out[f"{P}dist_bw2_0"] = np.abs(bw2)
    out[f"{P}dist_bw2_60"] = np.abs(bw2 - 60)
    out[f"{P}dist_bw2_75"] = np.abs(bw2 - 75)
    out[f"{P}dist_bw2_n60"] = np.abs(bw2 + 60)
    out[f"{P}dist_bw2_n75"] = np.abs(bw2 + 75)
    out[f"{P}dist_mf_0"] = np.abs(mf)
    out[f"{P}dist_mf_30"] = np.abs(mf - 30)
    out[f"{P}dist_mf_n30"] = np.abs(mf + 30)
    out[f"{P}dist_rsi_50"] = np.abs(rsi - 50)
    out[f"{P}dist_rsi_75"] = np.abs(rsi - 75)
    out[f"{P}dist_rsi_25"] = np.abs(rsi - 25)

    # ── F. Cross-line (4)
    out[f"{P}cross_mf_bw2"] = mf - bw2
    out[f"{P}cross_mf_sma14"] = mf - bw2_sma  # mf vs sma14(bw2)
    out[f"{P}cross_rsi_stc"] = rsi - stc
    out[f"{P}cross_bw2_sma14"] = bw2 - bw2_sma

    # ── G. Time-since events (11)
    out[f"{P}bars_since_bw2_zero"] = _bars_since_sign_flip(bw2)
    out[f"{P}bars_since_mf_zero"] = _bars_since_sign_flip(mf)
    bw2_in_ob = bw2 >= OB_LEVEL
    bw2_in_os = bw2 <= OS_LEVEL
    rsi_in_ob = rsi >= 75
    rsi_in_os = rsi <= 25
    stc_in_ob = stc >= 75
    stc_in_os = stc <= 25
    color = _color_state(bw2, bw2_sma)
    color_flip = np.concatenate([[False], (color[1:] != color[:-1]) & (color[:-1] != -1)])
    out[f"{P}bars_since_bw2_ob_enter"] = _bars_since_event(
        np.concatenate([[False], (~bw2_in_ob[:-1]) & bw2_in_ob[1:]])
    )
    out[f"{P}bars_since_bw2_os_enter"] = _bars_since_event(
        np.concatenate([[False], (~bw2_in_os[:-1]) & bw2_in_os[1:]])
    )
    out[f"{P}bars_since_bw2_ob_exit"] = _bars_since_event(
        np.concatenate([[False], bw2_in_ob[:-1] & (~bw2_in_ob[1:])])
    )
    out[f"{P}bars_since_bw2_os_exit"] = _bars_since_event(
        np.concatenate([[False], bw2_in_os[:-1] & (~bw2_in_os[1:])])
    )
    out[f"{P}bars_since_rsi_ob_exit"] = _bars_since_event(
        np.concatenate([[False], rsi_in_ob[:-1] & (~rsi_in_ob[1:])])
    )
    out[f"{P}bars_since_rsi_os_exit"] = _bars_since_event(
        np.concatenate([[False], rsi_in_os[:-1] & (~rsi_in_os[1:])])
    )
    out[f"{P}bars_since_stc_ob_exit"] = _bars_since_event(
        np.concatenate([[False], stc_in_ob[:-1] & (~stc_in_ob[1:])])
    )
    out[f"{P}bars_since_stc_os_exit"] = _bars_since_event(
        np.concatenate([[False], stc_in_os[:-1] & (~stc_in_os[1:])])
    )
    out[f"{P}bars_since_color_flip"] = _bars_since_event(color_flip)

    # ── H. Statistical rollings (4 indicators × 3 stats × 2 windows = 24)
    for name, arr in series_map.items():
        s = pd.Series(arr)
        for w in (20, 50):
            out[f"{P}roll_mean_{name}_{w}"] = s.rolling(w, min_periods=max(5, w // 4)).mean().to_numpy()
            out[f"{P}roll_std_{name}_{w}"] = s.rolling(w, min_periods=max(5, w // 4)).std().to_numpy()
            # Percentile rank (where current is in last W bars)
            out[f"{P}roll_pctrank_{name}_{w}"] = s.rolling(w, min_periods=max(5, w // 4)).apply(
                lambda x: (x.iloc[-1] > x).mean(), raw=False
            ).to_numpy()

    # ── I. Direction binary (4 indicators × 4 = 16)
    for name, arr in series_map.items():
        s = pd.Series(arr)
        out[f"{P}rising_{name}_1"] = (s.diff(1) > 0).astype("int8").to_numpy()
        out[f"{P}rising_{name}_3"] = (s.diff(3) > 0).astype("int8").to_numpy()
        out[f"{P}rising_{name}_5"] = (s.diff(5) > 0).astype("int8").to_numpy()
        # Streak: how many consecutive bars rising
        rising = (s.diff(1) > 0).astype("int8").to_numpy()
        streak = np.zeros(n, dtype=np.int32)
        cnt = 0
        for i in range(n):
            if rising[i] == 1:
                cnt += 1
            else:
                cnt = 0
            streak[i] = cnt
        out[f"{P}streak_{name}_rising"] = streak

    # ── J. Concordance flags (5)
    out[f"{P}conc_bw2_mf_sign"] = (np.sign(bw2) == np.sign(mf)).astype("int8")
    bw2_rising = pd.Series(bw2).diff(1).to_numpy() > 0
    mf_rising = pd.Series(mf).diff(1).to_numpy() > 0
    out[f"{P}conc_bw2_mf_rising"] = (bw2_rising & mf_rising).astype("int8")
    out[f"{P}conc_double_ob"] = (bw2_in_ob & rsi_in_ob).astype("int8")
    out[f"{P}conc_double_os"] = (bw2_in_os & rsi_in_os).astype("int8")
    out[f"{P}conc_all4_bull"] = (
        (bw2 > 0) & (mf > 0) & (rsi > 50) & (stc > 50)
    ).astype("int8")

    # ── K. Recent crossings (6 events × 3 lookbacks = 18)
    bw2_zero_cross = np.concatenate([[False], np.sign(bw2[1:]) != np.sign(bw2[:-1])])
    mf_zero_cross = np.concatenate([[False], np.sign(mf[1:]) != np.sign(mf[:-1])])
    bw2_60_cross = np.concatenate([[False], ((bw2[:-1] < 60) & (bw2[1:] >= 60)) | ((bw2[:-1] > 60) & (bw2[1:] <= 60))])
    bw2_n60_cross = np.concatenate([[False], ((bw2[:-1] > -60) & (bw2[1:] <= -60)) | ((bw2[:-1] < -60) & (bw2[1:] >= -60))])
    rsi_50_cross = np.concatenate([[False], np.sign(rsi[1:] - 50) != np.sign(rsi[:-1] - 50)])
    stc_50_cross = np.concatenate([[False], np.sign(stc[1:] - 50) != np.sign(stc[:-1] - 50)])
    events = {
        "bw2_zero": bw2_zero_cross, "mf_zero": mf_zero_cross,
        "bw2_60": bw2_60_cross, "bw2_n60": bw2_n60_cross,
        "rsi_50": rsi_50_cross, "stc_50": stc_50_cross,
    }
    for ename, ev in events.items():
        # Rolling sum: events in last 1, 3, 5 bars
        ser = pd.Series(ev.astype("int8"))
        for w in (1, 3, 5):
            out[f"{P}cross_{ename}_in_{w}"] = ser.rolling(w, min_periods=1).sum().astype("int8").to_numpy()

    return pd.DataFrame(out)


def _compute_mh_per_tf_v2(df_1m: pd.DataFrame, tf: str, end_ts: pd.Timestamp) -> pd.DataFrame:
    """Compute default MH per TF + return DataFrame with all per-TF features."""
    df_tf = resample_one(df_1m, tf, end_ts)
    o = df_tf["open"].to_numpy()
    h = df_tf["high"].to_numpy()
    l = df_tf["low"].to_numpy()
    c = df_tf["close"].to_numpy()
    mh = compute_mh_parametric(o, h, l, c)
    features = _build_per_tf_features(mh, prefix="")
    features.index = df_tf.index
    return features


def _compute_mh_variant_per_tf(df_1m: pd.DataFrame, tf: str, end_ts: pd.Timestamp,
                                params: dict, prefix: str) -> pd.DataFrame:
    """Compute MH per TF with custom params + return per-TF features with prefix."""
    df_tf = resample_one(df_1m, tf, end_ts)
    o = df_tf["open"].to_numpy(); h = df_tf["high"].to_numpy()
    l = df_tf["low"].to_numpy(); c = df_tf["close"].to_numpy()
    mh = compute_mh_parametric(o, h, l, c, **params)
    features = _build_per_tf_features(mh, prefix=prefix)
    features.index = df_tf.index
    return features


def _reindex_to_target(per_tf_df: pd.DataFrame, target_idx: pd.DatetimeIndex, tf: str) -> pd.DataFrame:
    tf_td = tf_to_timedelta(tf)
    closed = per_tf_df.copy()
    closed["close_ts"] = closed.index + tf_td
    closed = closed.reset_index(drop=False).rename(columns={"open_time": "open_ts"})
    target = pd.DataFrame({"ts": target_idx})
    merged = pd.merge_asof(
        target.sort_values("ts"),
        closed.sort_values("close_ts"),
        left_on="ts", right_on="close_ts",
        direction="backward",
    )
    merged = merged.set_index("ts")
    return merged.drop(columns=["open_ts", "close_ts"])


def build_features_v2(
    df_1m: pd.DataFrame,
    tfs: Iterable[str] = TFS_8,
    target_freq: str = "15m",
    include_variants: bool = True,
) -> pd.DataFrame:
    """Build expanded feature matrix v2 (~1100-1290 features).

    Args:
        include_variants: если True, добавляем R (EMA7 fast) и S (EMA13 slow) variants of bw2.
    """
    end_ts = df_1m.index[-1] + pd.Timedelta(minutes=1)
    grid = resample_one(df_1m, target_freq, end_ts).index

    feat_parts = []
    for tf in tfs:
        per_tf = _compute_mh_per_tf_v2(df_1m, tf, end_ts)
        aligned = _reindex_to_target(per_tf, grid, tf)
        aligned = aligned.add_suffix(f"_{tf}")
        feat_parts.append(aligned)

    # Variants R, S
    if include_variants:
        for tf in tfs:
            # R: fast EMA(7)
            per_tf_r = _compute_mh_variant_per_tf(
                df_1m, tf, end_ts,
                params=dict(n1=7, n2=7, n3=8, n4=4),
                prefix="vfast_",
            )
            aligned_r = _reindex_to_target(per_tf_r, grid, tf).add_suffix(f"_{tf}")
            feat_parts.append(aligned_r)
            # S: slow EMA(13)
            per_tf_s = _compute_mh_variant_per_tf(
                df_1m, tf, end_ts,
                params=dict(n1=13, n2=13, n3=16, n4=4),
                prefix="vslow_",
            )
            aligned_s = _reindex_to_target(per_tf_s, grid, tf).add_suffix(f"_{tf}")
            feat_parts.append(aligned_s)

    features = pd.concat(feat_parts, axis=1)

    # ── Cross-TF aggregates ──
    tfs_list = list(tfs)
    bw2_cols = [f"bw2_{tf}" for tf in tfs_list]
    mf_cols = [f"mf_{tf}" for tf in tfs_list]
    rsi_cols = [f"rsi_{tf}" for tf in tfs_list]
    stc_cols = [f"stc_{tf}" for tf in tfs_list]
    sign_bw2_cols = [f"sign_bw2_{tf}" for tf in tfs_list]
    sign_mf_cols = [f"sign_mf_{tf}" for tf in tfs_list]
    rising_bw2_1_cols = [f"rising_bw2_1_{tf}" for tf in tfs_list]
    rising_mf_1_cols = [f"rising_mf_1_{tf}" for tf in tfs_list]

    # M. Counts
    features["n_TFs_bw2_above_0"] = (features[bw2_cols] > 0).sum(axis=1)
    features["n_TFs_mf_above_0"] = (features[mf_cols] > 0).sum(axis=1)
    features["n_TFs_rsi_OB"] = (features[rsi_cols] >= 75).sum(axis=1)
    features["n_TFs_rsi_OS"] = (features[rsi_cols] <= 25).sum(axis=1)
    features["n_TFs_stc_OB"] = (features[stc_cols] >= 75).sum(axis=1)
    features["n_TFs_stc_OS"] = (features[stc_cols] <= 25).sum(axis=1)
    features["n_TFs_bw2_OB"] = (features[bw2_cols] >= 60).sum(axis=1)
    features["n_TFs_bw2_OS"] = (features[bw2_cols] <= -60).sum(axis=1)
    features["bw2_consensus"] = features[sign_bw2_cols].sum(axis=1)
    features["mf_consensus"] = features[sign_mf_cols].sum(axis=1)
    features["n_TFs_bw2_rising"] = features[rising_bw2_1_cols].sum(axis=1)
    features["n_TFs_mf_rising"] = features[rising_mf_1_cols].sum(axis=1)

    # N. Mean/std across TFs
    for name, cols in [("bw2", bw2_cols), ("mf", mf_cols), ("rsi", rsi_cols), ("stc", stc_cols)]:
        features[f"agg_mean_{name}"] = features[cols].mean(axis=1)
        features[f"agg_std_{name}"] = features[cols].std(axis=1)

    # O. HTF/LTF alignment (selected pairs)
    pairs = [
        ("15m", "1h"), ("15m", "4h"), ("15m", "16h"), ("15m", "32h"),
        ("30m", "2h"), ("30m", "8h"),
        ("1h", "4h"), ("1h", "16h"),
        ("2h", "8h"), ("2h", "32h"),
        ("4h", "16h"), ("4h", "32h"),
        ("8h", "32h"),
    ]
    for ltf, htf in pairs:
        for ind in ["bw2", "mf", "rsi", "stc"]:
            features[f"aligned_{ind}_{ltf}_{htf}"] = (
                np.sign(features[f"{ind}_{ltf}"]) == np.sign(features[f"{ind}_{htf}"])
            ).astype("int8")

    # P. Diffs between selected TF pairs
    diff_pairs = [("15m", "32h"), ("15m", "8h"), ("30m", "16h"), ("1h", "8h"), ("4h", "32h")]
    for ltf, htf in diff_pairs:
        for ind in ["bw2", "mf"]:
            features[f"diff_{ind}_{ltf}_{htf}"] = features[f"{ind}_{ltf}"] - features[f"{ind}_{htf}"]

    # Q. Cascade timing per TF (already есть bars_since_*; добавим cascade min)
    bsc_bw2_cols = [f"bars_since_bw2_zero_{tf}" for tf in tfs_list]
    bsc_mf_cols = [f"bars_since_mf_zero_{tf}" for tf in tfs_list]
    tf_minutes = {"15m": 15, "30m": 30, "1h": 60, "2h": 120, "4h": 240,
                  "8h": 480, "16h": 960, "32h": 1920}
    # Convert each bars_since to hours
    bw2_freshness_h = pd.DataFrame()
    mf_freshness_h = pd.DataFrame()
    for tf in tfs_list:
        m = tf_minutes[tf] / 60.0
        bw2_freshness_h[tf] = features[f"bars_since_bw2_zero_{tf}"].astype("float64") * m
        mf_freshness_h[tf] = features[f"bars_since_mf_zero_{tf}"].astype("float64") * m
    features["cascade_bw2_zero_min_h"] = bw2_freshness_h.min(axis=1)
    features["cascade_bw2_zero_mean_h"] = bw2_freshness_h.mean(axis=1)
    features["cascade_mf_zero_min_h"] = mf_freshness_h.min(axis=1)
    features["cascade_mf_zero_mean_h"] = mf_freshness_h.mean(axis=1)
    # Separately for bull/bear cascade
    cascade_bull = pd.DataFrame()
    cascade_bear = pd.DataFrame()
    for tf in tfs_list:
        m = tf_minutes[tf] / 60.0
        sign = features[f"sign_bw2_{tf}"]
        bsc = features[f"bars_since_bw2_zero_{tf}"].astype("float64") * m
        cascade_bull[tf] = bsc.where(sign > 0, np.inf)
        cascade_bear[tf] = bsc.where(sign < 0, np.inf)
    features["cascade_bw2_bull_freshness_h"] = cascade_bull.min(axis=1).replace(np.inf, 9999.0)
    features["cascade_bw2_bear_freshness_h"] = cascade_bear.min(axis=1).replace(np.inf, 9999.0)

    # De-fragment DataFrame (улучшает производительность последующих операций)
    return features.copy()
