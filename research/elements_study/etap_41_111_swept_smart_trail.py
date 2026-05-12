"""Этап 41: 1.1.1 SWEPT с auto-trailing exits на индикаторах.

Идея: вместо fixed RR=N TP, "вести" каждую позицию через индикаторы,
выходя когда тренд разворачивается / momentum иссякает / ASVK extension.

Exit-режимы (initial SL остаётся всегда):

  M0 (FIXED):    fixed RR=2.5 (V3 baseline из etap_40)
  M1 (HULL_1h):  exit когда close_1h vs HULL_1h[2] flip против direction
  M2 (HULL_4h):  то же на 4h (медленнее, дольше держим)
  M3 (MH_COLOR): exit когда MH bw2 color меняется на не-aligned
  M4 (MH_ZERO):  exit когда bw2 пересекает 0 против direction
  M5 (ASVK):     exit когда ASVK ema_3 в extreme opposite zone (red/green)
  M6 (ANY):      exit на ПЕРВОМ из {Hull-1h, MH color, ASVK} flip
  M7 (HULL+CAP): Hull-1h trail + cap RR=5.0 если достигнут раньше
  M8 (HULL_CONFIRM_2): Hull-1h flip с подтверждением 2 бара подряд

Все индикаторы на 1h (или 4h для M2). Lookahead-safe (etap_37 fix):
  все label-функции считают как-of last CLOSED bar.

Простое правило выхода: signal_time = signal_time + 15min (entry of FVG-15m).
Iterate by 1h checkpoints from entry. На каждом checkpoint:
  1. В окне [prev_check, current_check] check 1m bars for SL hit → loss.
  2. На current_check (close 1h bar) lookup indicator labels (precomputed).
  3. Если exit signal triggered → exit at current_check close.
  4. max_hold = 7 дней (TF_LIFE_DAYS["1d"]/2 для 1h trigger).
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

from collections import defaultdict
from pathlib import Path
import time
import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_1 import detect_strategy_1_1_1_signals

SYMBOL = "BTCUSDT"
DAYS_BACK = 2313  # 6.33y
ENTRY_PCT = 0.80
SL_PCT = 0.40
MIN_SL_PCT = 1.0
MAX_HOLD_DAYS = 7
RR_CAP = 5.0  # для M7

OUT_DIR = Path("research/elements_study/output")


# ---------- math ----------

def wma_fast(arr, period):
    period = max(int(period), 1)
    weights = np.arange(1, period + 1, dtype=float)
    weights /= weights.sum()
    out = np.full_like(arr, np.nan, dtype=float)
    if len(arr) < period: return out
    valid = np.convolve(arr, weights[::-1], mode="valid")
    out[period - 1:] = valid
    return out


def hull_ma(close, length=78):
    arr = close.to_numpy(dtype=float)
    half = max(int(length / 2), 1)
    sqrt_len = max(int(round(np.sqrt(length))), 1)
    raw = 2.0 * wma_fast(arr, half) - wma_fast(arr, length)
    hull = wma_fast(np.where(np.isnan(raw), 0.0, raw), sqrt_len)
    hull[:length + sqrt_len] = np.nan
    return pd.Series(hull, index=close.index)


def heikin_ashi(o, h, l, c):
    n = len(c)
    ha_close = (o + h + l + c) / 4
    ha_open = np.zeros(n)
    ha_open[0] = (o.iloc[0] + c.iloc[0]) / 2
    ha_close_arr = ha_close.values
    for i in range(1, n):
        ha_open[i] = (ha_open[i - 1] + ha_close_arr[i - 1]) / 2
    ha_open = pd.Series(ha_open, index=c.index)
    ha_high = pd.concat([h, ha_open, ha_close], axis=1).max(axis=1)
    ha_low = pd.concat([l, ha_open, ha_close], axis=1).min(axis=1)
    return ha_open, ha_high, ha_low, ha_close


def mh_bw2(df):
    hlc3 = (df["high"] + df["low"] + df["close"]) / 3
    esa = hlc3.ewm(span=9, adjust=False).mean()
    d = (hlc3 - esa).abs().ewm(span=9, adjust=False).mean()
    ci = (hlc3 - esa) / (0.015 * d.replace(0, np.nan))
    wt1 = ci.ewm(span=12, adjust=False).mean()
    wt2 = wt1.rolling(4, min_periods=4).mean()
    sma14 = wt2.rolling(14, min_periods=14).mean()
    return wt2, sma14


def mh_color_label_series(bw2, sma14):
    """Return Series of color labels: green / grey_from_green / red /
    grey_from_red / na, indexed same as bw2."""
    out = []
    for v, s in zip(bw2, sma14):
        if pd.isna(v) or pd.isna(s): out.append("na")
        elif v > 0:
            out.append("green" if v >= s else "grey_from_green")
        elif v < 0:
            out.append("red" if v <= s else "grey_from_red")
        else:
            out.append("na")
    return pd.Series(out, index=bw2.index)


def rsi_wilder(close, period=14):
    delta = close.diff()
    gain = delta.clip(lower=0.0); loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def asvk_adjusted_rsi(close):
    rsi = rsi_wilder(close, 14)
    ema_for_coef = rsi.ewm(span=5, adjust=False).mean()
    coef = pd.Series(np.where(rsi >= 50, 1.2, 0.8), index=rsi.index)
    coefficient = (rsi * coef) / ema_for_coef.replace(0, np.nan)
    adj = rsi * coefficient
    return adj.ewm(span=5, adjust=False).mean()


def asvk_dynamic_levels(ema_3, lookback=200):
    n = len(ema_3)
    above = np.full(n, np.nan); below = np.full(n, np.nan)
    arr = ema_3.to_numpy()
    for i in range(lookback - 1, n):
        win = arr[i - lookback + 1: i + 1]
        win = win[~np.isnan(win)]
        if len(win) < 10: continue
        m = win > 50; z = m.sum()
        if z > 0:
            y = win[m].mean()
            c1 = 100/y; c2 = 50/y; c3 = c1-c2
            c5 = (c3/lookback)*z + c3
            above[i] = c5 * y
        m = win < 50; z = m.sum()
        if z > 0:
            y = win[m].mean()
            c1 = 50/y; c2 = 1/y; c3 = c1-c2
            c5 = (c3/lookback)*z + c3
            below[i] = 100 - (c5 * y)
    return pd.Series(above, index=ema_3.index), pd.Series(below, index=ema_3.index)


def asvk_zone_label_series(ema_3, above, below):
    out = []
    for e, a, b in zip(ema_3, above, below):
        if pd.isna(e) or pd.isna(a) or pd.isna(b):
            out.append("na")
        elif e > a:
            out.append("red")
        elif e < b:
            out.append("green")
        else:
            out.append("neutral")
    return pd.Series(out, index=ema_3.index)


def hull_trend_label_series(close, hull):
    """Series of "up"/"down" labels at each bar i:
    (close[i] > hull[i-2]). Computed using ONLY data up to bar i."""
    n = len(close)
    out = []
    for i in range(n):
        if i < 2:
            out.append("na"); continue
        c = close.iloc[i]; h2 = hull.iloc[i - 2]
        if pd.isna(c) or pd.isna(h2):
            out.append("na")
        else:
            out.append("up" if c > h2 else "down")
    return pd.Series(out, index=close.index)


# ---------- 1.1.1 SWEPT pipeline (from etap_40) ----------

def check_swept(sig, df_1h, df_2h):
    df_top = df_1h if sig["ob_htf_tf"] == "1h" else df_2h
    cur_time = pd.Timestamp(sig["ob_htf_cur_time"])
    prev_time = pd.Timestamp(sig["ob_htf_prev_time"])
    if cur_time.tz is None: cur_time = cur_time.tz_localize("UTC")
    if prev_time.tz is None: prev_time = prev_time.tz_localize("UTC")
    if prev_time not in df_top.index or cur_time not in df_top.index:
        return None
    pi = df_top.index.get_loc(prev_time)
    if pi < 2: return None
    ci = df_top.index.get_loc(cur_time)
    c1l = float(df_top.iloc[pi]["low"]); c2l = float(df_top.iloc[ci]["low"])
    c1h = float(df_top.iloc[pi]["high"]); c2h = float(df_top.iloc[ci]["high"])
    n1l = float(df_top.iloc[pi-1]["low"]); n2l = float(df_top.iloc[pi-2]["low"])
    n1h = float(df_top.iloc[pi-1]["high"]); n2h = float(df_top.iloc[pi-2]["high"])
    if sig["direction"] == "LONG":
        return min(c1l, c2l) < min(n1l, n2l)
    return max(c1h, c2h) > max(n1h, n2h)


def build_setup_user(s):
    direction = s["direction"]
    fb, ft = s["fvg_zone"]
    obb, obt = s["ob_htf_zone"]
    fw = ft - fb
    if direction == "LONG":
        entry = fb + ENTRY_PCT * fw
        sl = obb + SL_PCT * (fb - obb)
        if MIN_SL_PCT > 0:
            min_sl = entry * MIN_SL_PCT / 100
            sl = min(sl, entry - min_sl)
        if sl >= entry: return None
    else:
        entry = ft - ENTRY_PCT * fw
        sl = obt - SL_PCT * (obt - ft)
        if MIN_SL_PCT > 0:
            min_sl = entry * MIN_SL_PCT / 100
            sl = max(sl, entry + min_sl)
        if sl <= entry: return None
    return entry, sl


# ---------- smart simulator ----------

def simulate_smart(setup_data, exit_mode, df_1m, df_1h, df_4h,
                    labels, max_hold_days=MAX_HOLD_DAYS, rr_cap=None):
    """
    setup_data = {entry_time, direction, entry, sl}
    labels = {hull_1h, hull_4h, mh_color, asvk_zone}  — все на 1h timestamps
             (hull_4h на 4h timestamps)

    Returns (outcome, R, exit_reason, hold_hours)
    """
    direction = setup_data["direction"]
    entry = setup_data["entry"]; sl = setup_data["sl"]
    entry_time = setup_data["entry_time"]
    risk = abs(entry - sl)
    if risk <= 0: return ("invalid", 0.0, "invalid", 0)

    end_time = entry_time + pd.Timedelta(days=max_hold_days)

    # 1m slice for SL detection
    if entry_time.tz is None: et64 = np.datetime64(entry_time)
    else: et64 = np.datetime64(entry_time.tz_localize(None))
    if end_time.tz is None: ee64 = np.datetime64(end_time)
    else: ee64 = np.datetime64(end_time.tz_localize(None))

    i0 = np.searchsorted(df_1m.index.values, et64)
    i1 = np.searchsorted(df_1m.index.values, ee64)
    if i1 <= i0: return ("no_data", 0.0, "no_data", 0)

    highs_1m = df_1m["high"].values[i0:i1].astype(np.float64)
    lows_1m = df_1m["low"].values[i0:i1].astype(np.float64)
    times_1m = df_1m.index.values[i0:i1]

    # 1h checkpoints inside [entry_time, end_time]
    h0 = df_1h.index.searchsorted(entry_time, side="right")  # first 1h close > entry
    h1 = df_1h.index.searchsorted(end_time, side="right")
    if h0 >= h1:
        return ("no_data", 0.0, "no_data", 0)
    checkpoints = df_1h.index[h0:h1]

    closes_1h = df_1h["close"].values

    # Indicator labels (precomputed, indexed by 1h timestamps)
    hull_1h_lbl = labels["hull_1h"]
    hull_4h_lbl = labels["hull_4h"]
    mh_color = labels["mh_color"]
    asvk_zone = labels["asvk_zone"]

    # Helper: at moment t, get last CLOSED label
    def last_closed_label_1h(series_1h, t):
        # series_1h indexed by 1h timestamps. Last closed bar's label
        # is the bar whose CLOSE timestamp <= t. In our convention:
        # df_1h[idx] open = idx, close = idx + 1h. So bar with close <= t
        # is bar with open <= t - 1h.
        # idx of last closed bar = searchsorted(t, "right") - 1 - 1 = idx2
        # But actually we need: bar at position k where bar's CLOSE
        # has happened. The label series at position k is computed
        # using close[k]. So label[k] is "valid as of close[k]" =
        # available at time t = open[k+1] = open[k] + 1h.
        # If t == checkpoint = open[k+1] (close of bar k), then
        # label[k] is the last available.
        # series_1h.index[k] = open[k]. We need k such that open[k] = t - 1h.
        idx = series_1h.index.searchsorted(t, side="right") - 1
        # idx is the bar containing t. If t == open[idx], bar idx is
        # just opening. We want label of bar idx-1 (already closed).
        # Actually if t = checkpoint = bar idx open, then bar idx-1
        # just closed. label[idx-1] is what we want.
        # However t being a 1h timestamp coincides with bar's open, so
        # searchsorted right gives idx+1 → -1 = idx → idx itself is
        # the bar opening at t. We need idx-1.
        target = idx - 1
        if target < 0: return "na"
        return series_1h.iloc[target]

    def last_closed_label_4h(t):
        # Same logic but on 4h
        idx = hull_4h_lbl.index.searchsorted(t, side="right") - 1
        target = idx - 1
        if target < 0: return "na"
        return hull_4h_lbl.iloc[target]

    # Track exit conditions for confirmation modes
    hull_1h_flip_count = 0  # for M8 (2-bar confirmation)

    prev_check_idx_1m = 0
    for cp in checkpoints:
        # 1. SL detection in [prev_check, cp] window of 1m bars
        cp64 = np.datetime64(cp.tz_localize(None) if cp.tz else cp)
        cur_idx_1m = np.searchsorted(times_1m, cp64)
        if cur_idx_1m > prev_check_idx_1m:
            window_h = highs_1m[prev_check_idx_1m:cur_idx_1m]
            window_l = lows_1m[prev_check_idx_1m:cur_idx_1m]
            if direction == "LONG":
                if (window_l <= sl).any():
                    hold_h = (cp - entry_time).total_seconds() / 3600
                    return ("loss", -1.0, "sl_hit", hold_h)
            else:
                if (window_h >= sl).any():
                    hold_h = (cp - entry_time).total_seconds() / 3600
                    return ("loss", -1.0, "sl_hit", hold_h)
        prev_check_idx_1m = cur_idx_1m

        # 2. Get current 1h close (= price at cp checkpoint)
        # cp is open of next 1h bar = close of previous bar
        cp_close_idx = df_1h.index.searchsorted(cp, side="right") - 2  # bar that just closed
        if cp_close_idx < 0: continue
        cur_close = closes_1h[cp_close_idx]

        # 3. Indicator-based exits
        hull_1h_v = last_closed_label_1h(hull_1h_lbl, cp)
        hull_4h_v = last_closed_label_4h(cp)
        mh_v = last_closed_label_1h(mh_color, cp)
        asvk_v = last_closed_label_1h(asvk_zone, cp)

        exit_now = False
        exit_reason = None

        if exit_mode == "M1_HULL_1h":
            if direction == "LONG" and hull_1h_v == "down":
                exit_now = True; exit_reason = "hull_1h_flip"
            elif direction == "SHORT" and hull_1h_v == "up":
                exit_now = True; exit_reason = "hull_1h_flip"

        elif exit_mode == "M2_HULL_4h":
            if direction == "LONG" and hull_4h_v == "down":
                exit_now = True; exit_reason = "hull_4h_flip"
            elif direction == "SHORT" and hull_4h_v == "up":
                exit_now = True; exit_reason = "hull_4h_flip"

        elif exit_mode == "M3_MH_COLOR":
            # exit when MH color goes from aligned to non-aligned
            if direction == "LONG" and mh_v in ("red", "grey_from_green"):
                exit_now = True; exit_reason = "mh_color_flip"
            elif direction == "SHORT" and mh_v in ("green", "grey_from_red"):
                exit_now = True; exit_reason = "mh_color_flip"

        elif exit_mode == "M5_ASVK":
            # extension exit — opposite direction extreme
            if direction == "LONG" and asvk_v == "red":  # extreme up extension
                exit_now = True; exit_reason = "asvk_extension"
            elif direction == "SHORT" and asvk_v == "green":
                exit_now = True; exit_reason = "asvk_extension"

        elif exit_mode == "M6_ANY":
            # any of Hull-1h / MH color / ASVK
            if direction == "LONG":
                if hull_1h_v == "down":
                    exit_now = True; exit_reason = "hull_1h_flip"
                elif mh_v in ("red", "grey_from_green"):
                    exit_now = True; exit_reason = "mh_color_flip"
                elif asvk_v == "red":
                    exit_now = True; exit_reason = "asvk_extension"
            else:
                if hull_1h_v == "up":
                    exit_now = True; exit_reason = "hull_1h_flip"
                elif mh_v in ("green", "grey_from_red"):
                    exit_now = True; exit_reason = "mh_color_flip"
                elif asvk_v == "green":
                    exit_now = True; exit_reason = "asvk_extension"

        elif exit_mode == "M7_HULL_CAP":
            # Hull-1h trail + RR cap
            R_now = (cur_close - entry) / risk if direction == "LONG" \
                    else (entry - cur_close) / risk
            if rr_cap and R_now >= rr_cap:
                exit_now = True; exit_reason = "rr_cap"
            elif direction == "LONG" and hull_1h_v == "down":
                exit_now = True; exit_reason = "hull_1h_flip"
            elif direction == "SHORT" and hull_1h_v == "up":
                exit_now = True; exit_reason = "hull_1h_flip"

        elif exit_mode == "M8_HULL_CONFIRM":
            # require 2 consecutive bars of opposite Hull
            if direction == "LONG" and hull_1h_v == "down":
                hull_1h_flip_count += 1
            elif direction == "SHORT" and hull_1h_v == "up":
                hull_1h_flip_count += 1
            else:
                hull_1h_flip_count = 0
            if hull_1h_flip_count >= 2:
                exit_now = True; exit_reason = "hull_1h_flip_x2"

        if exit_now:
            R = (cur_close - entry) / risk if direction == "LONG" \
                else (entry - cur_close) / risk
            hold_h = (cp - entry_time).total_seconds() / 3600
            return ("exit", R, exit_reason, hold_h)

    # Max hold reached — close at last checkpoint
    if len(checkpoints) > 0:
        last_cp = checkpoints[-1]
        cp_close_idx = df_1h.index.searchsorted(last_cp, side="right") - 2
        if cp_close_idx >= 0:
            cur_close = closes_1h[cp_close_idx]
            R = (cur_close - entry) / risk if direction == "LONG" \
                else (entry - cur_close) / risk
            hold_h = (last_cp - entry_time).total_seconds() / 3600
            return ("max_hold", R, "max_hold", hold_h)
    return ("open", 0.0, "open", 0)


def simulate_fixed_rr(setup_data, rr, df_1m):
    """M0: fixed RR=N TP."""
    direction = setup_data["direction"]
    entry = setup_data["entry"]; sl = setup_data["sl"]
    entry_time = setup_data["entry_time"]
    risk = abs(entry - sl)
    if risk <= 0: return ("invalid", 0.0, "invalid", 0)
    tp = entry + rr * risk if direction == "LONG" else entry - rr * risk
    end_time = entry_time + pd.Timedelta(days=MAX_HOLD_DAYS)

    if entry_time.tz is None: et64 = np.datetime64(entry_time)
    else: et64 = np.datetime64(entry_time.tz_localize(None))
    if end_time.tz is None: ee64 = np.datetime64(end_time)
    else: ee64 = np.datetime64(end_time.tz_localize(None))

    i0 = np.searchsorted(df_1m.index.values, et64)
    i1 = np.searchsorted(df_1m.index.values, ee64)
    if i1 <= i0: return ("no_data", 0.0, "no_data", 0)

    h = df_1m["high"].values[i0:i1].astype(np.float64)
    l = df_1m["low"].values[i0:i1].astype(np.float64)
    if direction == "LONG":
        sl_hits = l <= sl; tp_hits = h >= tp
    else:
        sl_hits = h >= sl; tp_hits = l <= tp
    sl_idx = int(np.argmax(sl_hits)) if sl_hits.any() else len(h)
    tp_idx = int(np.argmax(tp_hits)) if tp_hits.any() else len(h)
    if sl_idx == len(h) and tp_idx == len(h): return ("open", 0.0, "open", 0)
    if sl_idx <= tp_idx: return ("loss", -1.0, "sl_hit", 0)
    return ("win", rr, "tp_hit", 0)


# ---------- main ----------

def report(label, results):
    df = pd.DataFrame(results)
    closed = df[df["outcome"].isin(["win", "loss", "exit", "max_hold"])]
    if closed.empty:
        print(f"  {label}: no closed"); return
    n = len(df); nc = len(closed)
    wins = (closed["R"] > 0).sum()
    losses = (closed["R"] < 0).sum()
    flat = (closed["R"] == 0).sum()
    wr = wins / nc * 100
    tot = closed["R"].sum()
    rt = closed["R"].mean()
    yr = closed.groupby("year")["R"].sum()
    bad = (yr < 0).sum()
    avg_hold = closed["hold_h"].mean()
    median_hold = closed["hold_h"].median()
    # Exit reasons breakdown
    reasons = closed["reason"].value_counts().to_dict()
    print(f"  {label}")
    print(f"    n={n}, closed={nc}, wins={wins} losses={losses} flat={flat}")
    print(f"    WR={wr:.1f}%  total_R={tot:+.1f}  R/tr={rt:+.3f}  bad_yrs={bad}/{len(yr)}")
    print(f"    hold avg={avg_hold:.0f}h ({avg_hold/24:.1f}d), median={median_hold:.0f}h")
    print(f"    exit reasons: {reasons}")
    yr_sorted = yr.sort_index()
    yrs_str = "  ".join(f"{int(y)}:{r:+.1f}" for y, r in yr_sorted.items())
    print(f"    year-by-year: {yrs_str}")


def main():
    t0 = time.time()
    print("[INFO] loading TFs")
    df_1d = load_df(SYMBOL, "1d")
    df_4h = load_df(SYMBOL, "4h")
    df_1h = load_df(SYMBOL, "1h")
    df_12h = compose_from_base(df_1h, "12h")
    df_6h = compose_from_base(df_1h, "6h")
    df_2h = compose_from_base(df_1h, "2h")
    df_15m = load_df(SYMBOL, "15m")
    df_1m = load_df(SYMBOL, "1m")
    df_20m = compose_from_base(df_1m, "20m")
    today = pd.Timestamp.now(tz="UTC").normalize()
    cutoff = today - pd.Timedelta(days=DAYS_BACK)
    df_1d_f = df_1d[df_1d.index >= cutoff]

    print("[INFO] computing indicators on 1h and 4h")
    hull_1h = hull_ma(df_1h["close"], 78)
    hull_1h_lbl = hull_trend_label_series(df_1h["close"], hull_1h)
    hull_4h = hull_ma(df_4h["close"], 78)
    hull_4h_lbl = hull_trend_label_series(df_4h["close"], hull_4h)
    bw2_1h, sma14_1h = mh_bw2(df_1h)
    mh_color = mh_color_label_series(bw2_1h, sma14_1h)
    asvk_ema3 = asvk_adjusted_rsi(df_1h["close"])
    asvk_above, asvk_below = asvk_dynamic_levels(asvk_ema3, 200)
    asvk_zone = asvk_zone_label_series(asvk_ema3, asvk_above, asvk_below)
    print(f"  Hull-1h: {hull_1h.notna().sum()} valid, "
          f"MH color: {(mh_color != 'na').sum()}, "
          f"ASVK zone: {(asvk_zone != 'na').sum()}")

    labels = {
        "hull_1h": hull_1h_lbl, "hull_4h": hull_4h_lbl,
        "mh_color": mh_color, "asvk_zone": asvk_zone,
    }

    print("[INFO] detecting 1.1.1 signals + SWEPT filter")
    raw = detect_strategy_1_1_1_signals(
        df_1d_f, df_12h, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m,
        verbose=False)
    groups = defaultdict(list)
    for s in raw:
        key = (s["signal_time"], s["direction"], round(float(s["entry"]), 2))
        sw = check_swept(s, df_1h, df_2h)
        if sw is None: continue
        groups[key].append({"sig": s, "swept": sw})
    swept_reps = [next(p["sig"] for p in paths if p["swept"])
                  for key, paths in groups.items()
                  if any(p["swept"] for p in paths)]
    print(f"  SWEPT signals: {len(swept_reps)}")

    # Build setups with USER's entry/SL formula (entry=0.80, sl_pct=0.40, min_sl=1%)
    setups = []
    for s in swept_reps:
        tup = build_setup_user(s)
        if tup is None: continue
        entry, sl = tup
        tf_minutes = 15 if s["fvg_tf"] == "15m" else 20
        entry_time = s["signal_time"] + pd.Timedelta(minutes=tf_minutes)
        setups.append({
            "entry_time": entry_time,
            "direction": s["direction"],
            "entry": entry, "sl": sl,
            "year": pd.Timestamp(s["signal_time"]).year,
        })
    print(f"  setups built: {len(setups)}")

    # ---------- Run each exit mode ----------
    print(f"\n{'='*70}\nFIXED RR baselines:")
    print(f"{'='*70}")
    for rr in [2.0, 2.5, 3.0]:
        results = []
        for s in setups:
            outcome, R, reason, hold_h = simulate_fixed_rr(s, rr, df_1m)
            results.append({"outcome": outcome, "R": R, "reason": reason,
                            "hold_h": hold_h, "year": s["year"]})
        report(f"M0 FIXED RR={rr}", results)

    print(f"\n{'='*70}\nSMART TRAIL exit modes:")
    print(f"{'='*70}")
    for mode_name in ["M1_HULL_1h", "M2_HULL_4h", "M3_MH_COLOR",
                       "M5_ASVK", "M6_ANY", "M8_HULL_CONFIRM"]:
        results = []
        for s in setups:
            outcome, R, reason, hold_h = simulate_smart(
                s, mode_name, df_1m, df_1h, df_4h, labels)
            results.append({"outcome": outcome, "R": R, "reason": reason,
                            "hold_h": hold_h, "year": s["year"]})
        report(mode_name, results)

    # M7 HULL+CAP at different RR caps
    print(f"\n{'='*70}\nM7 Hull-1h trail + RR cap:")
    print(f"{'='*70}")
    for cap in [3.0, 5.0, 8.0]:
        results = []
        for s in setups:
            outcome, R, reason, hold_h = simulate_smart(
                s, "M7_HULL_CAP", df_1m, df_1h, df_4h, labels, rr_cap=cap)
            results.append({"outcome": outcome, "R": R, "reason": reason,
                            "hold_h": hold_h, "year": s["year"]})
        report(f"M7 Hull-1h + cap RR={cap}", results)

    print(f"\n[TIME] {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
