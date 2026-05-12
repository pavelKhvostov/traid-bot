"""Этап 45: исследование Strategy 1.1.2 + индикаторные фильтры + smart trail.

Стратегия 1.1.2 — макро-OB вместо макро-FVG (vs 1.1.1).
Cascade: OB-{1d,12h} -> OB-{4h,6h} -> OB-{1h,2h} -> FVG-{15m,20m}.

USER параметры (Stage 3):
  - entry = 0.70 of FVG (deep entry)
  - sl_pct_long = 0.35  (LONG: SL = OB.bot + 0.35 * (FVG.bot - OB.bot))
  - sl_pct_short = 0.65 (SHORT asymmetric)
  - RR = 1.8

ЭКСПЕРИМЕНТЫ:

  V1 REPRO:    3y orig (DAYS_BACK=1095, sl=0.35 sym, RR=2.2) - воспроизвести +101R
  V2 USER 6y:  6.33y user params (entry=0.70, sl=0.35/0.65 asym, RR=1.8)
  V3 USER+min:  + min_sl=1% (futures-realistic)
  V4 SWEPT:    + SWEPT filter (как в 1.1.1)
  V5 ALT_RR:   user params, vary RR в [1.0, 1.5, 1.8, 2.0, 2.5, 3.0]

  Filters (поверх V4 SWEPT, sl=0.35/0.65, min_sl=1%, RR=1.8):
    F1: Hull-4h aligned
    F2: Hull-1d aligned
    F3: Hull-1h aligned
    F4: MH bw2 color aligned
    F5: MH MF sign aligned
    F6: ASVK zone NOT yellow_OB / NOT yellow_OS (counter-extreme exit)
    F7: ICT session in (london, ny)
    F8: Friday excluded
    F9: DO premium/discount match
    Combos: F1+F4, F1+F7, F1+F4+F7

  Smart Trail (поверх V3, без RR fixed):
    M0 baseline:         RR=1.8 fixed
    M1 Hull-1h flip:     exit на close vs Hull[2] flip
    M2 Hull-4h flip:     то же на 4h
    M3 MH color flip:    exit on color away
    M8 Hull-1h confirm-2: 2-bar confirmation
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
from strategies.strategy_1_1_2 import detect_strategy_1_1_2_signals

SYMBOL = "BTCUSDT"
ENTRY_PCT = 0.70   # USER param
USER_SL_LONG = 0.35
USER_SL_SHORT = 0.65
USER_RR = 1.8
MAX_HOLD_DAYS = 7

OUT_DIR = Path("research/elements_study/output")


# ---------- math primitives ----------

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


def hull_label_series(close, hull):
    n = len(close); out = []
    for i in range(n):
        if i < 2:
            out.append("na"); continue
        c = close.iloc[i]; h2 = hull.iloc[i - 2]
        if pd.isna(c) or pd.isna(h2):
            out.append("na")
        else:
            out.append("up" if c > h2 else "down")
    return pd.Series(out, index=close.index)


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


def asvk_zone_label(ema_3, above, below):
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


def mh_color_label(bw2, sma14):
    out = []
    for v, s in zip(bw2, sma14):
        if pd.isna(v) or pd.isna(s): out.append("na")
        elif v > 0:
            out.append("green" if v >= s else "grey_from_green")
        elif v < 0:
            out.append("red" if v <= s else "grey_from_red")
        else: out.append("na")
    return pd.Series(out, index=bw2.index)


def money_flow_ha(df):
    ha_o, ha_h, ha_l, ha_c = heikin_ashi(df["open"], df["high"], df["low"], df["close"])
    rng = (ha_h - ha_l).replace(0, np.nan)
    raw = ((ha_c - ha_o) / rng) * 200
    return raw.rolling(60, min_periods=60).mean() - 2.25


# ---------- 1.1.2 pipeline ----------

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


def precompute(sig, df_1m):
    fvg_b, fvg_t = sig["fvg_zone"]
    obh_b, obh_t = sig["ob_htf_zone"]
    direction = sig["direction"]
    tf_minutes = 15 if sig["fvg_tf"] == "15m" else 20
    forward = df_1m[df_1m.index >= sig["signal_time"] + pd.Timedelta(minutes=tf_minutes)]
    if forward.empty: return None
    return {
        "direction": direction,
        "fvg_b": float(fvg_b), "fvg_t": float(fvg_t),
        "obh_b": float(obh_b), "obh_t": float(obh_t),
        "highs": forward["high"].values.astype(np.float64),
        "lows": forward["low"].values.astype(np.float64),
        "signal_time": sig["signal_time"],
        "year": pd.Timestamp(sig["signal_time"]).year,
        "tf_minutes": tf_minutes,
    }


def simulate_fixed(s, entry, sl, tp, no_entry=True):
    """Simulate fixed RR (no trail) — return outcome string."""
    highs, lows = s["highs"], s["lows"]
    n = len(highs)
    if s["direction"] == "LONG":
        ent_idxs = np.where(lows <= entry)[0]
        tp_pre_idxs = np.where(highs >= tp)[0]
    else:
        ent_idxs = np.where(highs >= entry)[0]
        tp_pre_idxs = np.where(lows <= tp)[0]
    ent_idx = int(ent_idxs[0]) if ent_idxs.size else n + 1
    tp_pre = int(tp_pre_idxs[0]) if tp_pre_idxs.size else n + 1
    if no_entry and tp_pre < ent_idx:
        return "no_entry"
    if ent_idx >= n: return "not_filled"
    post_l = lows[ent_idx:]; post_h = highs[ent_idx:]
    if s["direction"] == "LONG":
        sl_m = post_l <= sl; tp_m = post_h >= tp
    else:
        sl_m = post_h >= sl; tp_m = post_l <= tp
    sl_first = int(np.argmax(sl_m)) if sl_m.any() else -1
    tp_first = int(np.argmax(tp_m)) if tp_m.any() else -1
    if sl_first == -1 and tp_first == -1: return "open"
    if sl_first == -1: return "win"
    if tp_first == -1: return "loss"
    return "win" if tp_first < sl_first else "loss"


def build_sl(s, sl_long, sl_short, min_sl_pct):
    direction = s["direction"]
    fw = s["fvg_t"] - s["fvg_b"]
    if direction == "LONG":
        entry = s["fvg_b"] + ENTRY_PCT * fw
        sl_lo = s["obh_b"]; sl_hi = s["fvg_b"]
        sl = sl_lo + sl_long * (sl_hi - sl_lo)
        if min_sl_pct > 0:
            min_sl = entry * min_sl_pct / 100
            sl = min(sl, entry - min_sl)
        if sl >= entry: return None
    else:
        entry = s["fvg_t"] - ENTRY_PCT * fw
        sl_hi = s["obh_t"]; sl_lo = s["fvg_t"]
        sl = sl_hi - sl_short * (sl_hi - sl_lo)
        if min_sl_pct > 0:
            min_sl = entry * min_sl_pct / 100
            sl = max(sl, entry + min_sl)
        if sl <= entry: return None
    return entry, sl


def evaluate(setups, sl_long, sl_short, rr, min_sl_pct=0.0, no_entry=True):
    rows = []
    for s in setups:
        tup = build_sl(s, sl_long, sl_short, min_sl_pct)
        if tup is None: continue
        entry, sl = tup
        risk = abs(entry - sl)
        tp = entry + rr * risk if s["direction"] == "LONG" else entry - rr * risk
        outcome = simulate_fixed(s, entry, sl, tp, no_entry=no_entry)
        if outcome == "win":
            R = rr
        elif outcome == "loss":
            R = -1.0
        else:
            R = 0.0
        rows.append({"outcome": outcome, "R": R, "year": s["year"],
                      "direction": s["direction"]})
    return pd.DataFrame(rows)


def report(label, df_e):
    cl = df_e[df_e["outcome"].isin(["win", "loss"])]
    if cl.empty:
        print(f"  {label}: no closed"); return
    n_total = len(df_e); n_closed = len(cl)
    no_ent = (df_e["outcome"] == "no_entry").sum()
    not_filled = (df_e["outcome"] == "not_filled").sum()
    wr = (cl["outcome"] == "win").mean() * 100
    tot = cl["R"].sum()
    rt = cl["R"].mean()
    yr = cl.groupby("year")["R"].sum()
    bad = (yr < 0).sum()
    print(f"  {label}")
    print(f"    n={n_total}, no_entry={no_ent}, not_filled={not_filled}, closed={n_closed}")
    print(f"    WR={wr:.1f}%  R/tr={rt:+.3f}  total={tot:+.1f}R  bad_yrs={bad}/{len(yr)}")


# ---------- safe lookups ----------

def hull_aligned_safe(close_series, hull_series, ts, direction):
    idx = hull_series.index.searchsorted(ts, side="right") - 1
    if idx < 3: return False
    last_closed = idx - 1
    c = close_series.iloc[last_closed]; h2 = hull_series.iloc[last_closed - 2]
    if pd.isna(c) or pd.isna(h2): return False
    up = c > h2
    return up if direction == "LONG" else (not up)


def asof_label_safe(label_series, ts):
    idx = label_series.index.searchsorted(ts, side="right") - 1
    if idx < 1: return "na"
    return label_series.iloc[idx - 1]


def mh_aligned(direction, color):
    if color == "na": return False
    bullish = color in ("green", "grey_from_red")
    bearish = color in ("red", "grey_from_green")
    if direction == "LONG":
        return bullish
    return bearish


def asvk_not_extreme(direction, zone):
    """LONG не в красной (extension), SHORT не в зелёной."""
    if zone == "na": return True
    if direction == "LONG" and zone == "red":
        return False
    if direction == "SHORT" and zone == "green":
        return False
    return True


def in_session(ts, sessions):
    h = pd.Timestamp(ts).hour
    if "asia" in sessions and h < 7: return True
    if "london" in sessions and 7 <= h < 12: return True
    if "ny" in sessions and 12 <= h < 17: return True
    if "off" in sessions and h >= 17: return True
    return False


def do_pos(df_1d, ts, entry):
    idx = df_1d.index.searchsorted(ts, side="right") - 1
    if idx < 0: return "na"
    do = df_1d["open"].iloc[idx]
    if entry > do: return "premium"
    if entry < do: return "discount"
    return "mid"


def do_match(direction, pos):
    if pos == "na": return False
    return ((direction == "LONG" and pos == "discount") or
            (direction == "SHORT" and pos == "premium"))


# ---------- smart trail M8 ----------

def simulate_M8_trail(s, entry, sl, df_1m, df_1h, hull_1h_lbl,
                       max_hold_days=MAX_HOLD_DAYS):
    """Hull-1h flip with 2-bar confirmation."""
    direction = s["direction"]
    risk = abs(entry - sl)
    if risk <= 0: return None
    tf_min = s["tf_minutes"]
    entry_time = s["signal_time"] + pd.Timedelta(minutes=tf_min)
    end_time = entry_time + pd.Timedelta(days=max_hold_days)
    et64 = np.datetime64(entry_time.tz_localize(None) if entry_time.tz else entry_time)
    ee64 = np.datetime64(end_time.tz_localize(None) if end_time.tz else end_time)

    i0 = np.searchsorted(df_1m.index.values, et64)
    i1 = np.searchsorted(df_1m.index.values, ee64)
    if i1 <= i0: return None

    highs_1m = df_1m["high"].values[i0:i1].astype(np.float64)
    lows_1m = df_1m["low"].values[i0:i1].astype(np.float64)
    times_1m = df_1m.index.values[i0:i1]

    h0 = df_1h.index.searchsorted(entry_time, side="right")
    h1 = df_1h.index.searchsorted(end_time, side="right")
    if h0 >= h1: return None
    checkpoints = df_1h.index[h0:h1]
    closes_1h = df_1h["close"].values

    flip_count = 0
    prev_idx_1m = 0
    for cp in checkpoints:
        cp64 = np.datetime64(cp.tz_localize(None) if cp.tz else cp)
        cur_idx_1m = np.searchsorted(times_1m, cp64)
        if cur_idx_1m > prev_idx_1m:
            wh = highs_1m[prev_idx_1m:cur_idx_1m]
            wl = lows_1m[prev_idx_1m:cur_idx_1m]
            if direction == "LONG" and (wl <= sl).any():
                return ("loss", -1.0)
            elif direction == "SHORT" and (wh >= sl).any():
                return ("loss", -1.0)
        prev_idx_1m = cur_idx_1m

        cp_close_idx = df_1h.index.searchsorted(cp, side="right") - 2
        if cp_close_idx < 0: continue
        cur_close = closes_1h[cp_close_idx]

        hl_idx = hull_1h_lbl.index.searchsorted(cp, side="right") - 1
        target = hl_idx - 1
        if target < 0: continue
        hl = hull_1h_lbl.iloc[target]

        if direction == "LONG" and hl == "down":
            flip_count += 1
        elif direction == "SHORT" and hl == "up":
            flip_count += 1
        else:
            flip_count = 0

        if flip_count >= 2:
            R = (cur_close - entry) / risk if direction == "LONG" \
                else (entry - cur_close) / risk
            return ("exit", R)

    if len(checkpoints) > 0:
        last_cp = checkpoints[-1]
        cp_close_idx = df_1h.index.searchsorted(last_cp, side="right") - 2
        if cp_close_idx >= 0:
            cur_close = closes_1h[cp_close_idx]
            R = (cur_close - entry) / risk if direction == "LONG" \
                else (entry - cur_close) / risk
            return ("max_hold", R)
    return None


def evaluate_trail(setups, sl_long, sl_short, min_sl_pct, df_1m, df_1h, hull_1h_lbl):
    rows = []
    for s in setups:
        tup = build_sl(s, sl_long, sl_short, min_sl_pct)
        if tup is None: continue
        entry, sl = tup
        r = simulate_M8_trail(s, entry, sl, df_1m, df_1h, hull_1h_lbl)
        if r is None: continue
        outcome, R = r
        rows.append({"outcome": "win" if R > 0 else ("loss" if R < 0 else "flat"),
                      "exit_reason": outcome,
                      "R": R, "year": s["year"]})
    return pd.DataFrame(rows)


# ---------- main ----------

def main():
    t0 = time.time()
    print("[INFO] загружаем данные")
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

    print("[INFO] вычисляем индикаторы")
    hull_4h = hull_ma(df_4h["close"], 78)
    hull_4h_lbl = hull_label_series(df_4h["close"], hull_4h)
    hull_1d = hull_ma(df_1d["close"], 78)
    hull_1d_lbl = hull_label_series(df_1d["close"], hull_1d)
    hull_1h = hull_ma(df_1h["close"], 78)
    hull_1h_lbl = hull_label_series(df_1h["close"], hull_1h)
    bw2_1h, sma14_1h = mh_bw2(df_1h)
    mh_color = mh_color_label(bw2_1h, sma14_1h)
    mh_mf = money_flow_ha(df_1h)
    asvk_ema3 = asvk_adjusted_rsi(df_1h["close"])
    asvk_above, asvk_below = asvk_dynamic_levels(asvk_ema3, 200)
    asvk_zone = asvk_zone_label(asvk_ema3, asvk_above, asvk_below)

    def build_signals(days_back):
        cutoff = today - pd.Timedelta(days=days_back)
        df_1d_f = df_1d[df_1d.index >= cutoff]
        raw = detect_strategy_1_1_2_signals(
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
        all_reps = [paths[0]["sig"] for paths in groups.values()]
        cache_swept = [c for c in (precompute(s, df_1m) for s in swept_reps) if c]
        cache_all = [c for c in (precompute(s, df_1m) for s in all_reps) if c]
        return cache_swept, cache_all

    # ============================================================
    print(f"\n{'='*70}\nV1 REPRO: 3y, sl=0.35 sym, RR=2.2 (CLAUDE.md '+101.4R')")
    print(f"{'='*70}")
    cache_3y_swept, cache_3y_all = build_signals(1095)
    print(f"  cache: SWEPT={len(cache_3y_swept)}, ALL={len(cache_3y_all)}")
    for rr in [1.0, 1.8, 2.0, 2.2, 2.5]:
        df_e = evaluate(cache_3y_all, 0.35, 0.35, rr,
                          min_sl_pct=0.0, no_entry=True)
        report(f"V1 3y ALL sl=0.35 RR={rr}", df_e)
    print()
    for rr in [1.0, 1.8, 2.2]:
        df_e = evaluate(cache_3y_swept, 0.35, 0.35, rr,
                          min_sl_pct=0.0, no_entry=True)
        report(f"V1 3y SWEPT sl=0.35 RR={rr}", df_e)

    # ============================================================
    print(f"\n{'='*70}\nV2 USER on 6.33y: entry=0.70, sl=0.35L/0.65S, RR=1.8, no min_sl")
    print(f"{'='*70}")
    cache_6y_swept, cache_6y_all = build_signals(2313)
    print(f"  cache: SWEPT={len(cache_6y_swept)}, ALL={len(cache_6y_all)}")

    for rr in [1.0, 1.5, 1.8, 2.0, 2.5]:
        df_e = evaluate(cache_6y_all, USER_SL_LONG, USER_SL_SHORT, rr,
                          min_sl_pct=0.0, no_entry=True)
        report(f"V2 6.33y ALL sl=0.35L/0.65S RR={rr}", df_e)

    # ============================================================
    print(f"\n{'='*70}\nV3 USER + min_sl=1% (futures-realistic)")
    print(f"{'='*70}")
    for rr in [1.0, 1.5, 1.8, 2.0, 2.5]:
        df_e = evaluate(cache_6y_all, USER_SL_LONG, USER_SL_SHORT, rr,
                          min_sl_pct=1.0, no_entry=True)
        report(f"V3 6.33y ALL sl=0.35L/0.65S min_sl=1% RR={rr}", df_e)

    # ============================================================
    print(f"\n{'='*70}\nV4 USER + SWEPT (6.33y)")
    print(f"{'='*70}")
    for rr in [1.0, 1.5, 1.8, 2.0, 2.5]:
        df_e = evaluate(cache_6y_swept, USER_SL_LONG, USER_SL_SHORT, rr,
                          min_sl_pct=1.0, no_entry=True)
        report(f"V4 6.33y SWEPT sl=0.35L/0.65S min_sl=1% RR={rr}", df_e)

    # ============================================================
    # FILTERS
    # ============================================================
    print(f"\n{'='*70}\nFILTERS поверх V3 (6.33y ALL, sl=0.35/0.65, min_sl=1%, RR=1.8)")
    print(f"{'='*70}")

    def apply_filter(cache, predicate):
        return [s for s in cache if predicate(s)]

    def f_hull4h(s): return hull_aligned_safe(df_4h["close"], hull_4h, s["signal_time"], s["direction"])
    def f_hull1d(s): return hull_aligned_safe(df_1d["close"], hull_1d, s["signal_time"], s["direction"])
    def f_hull1h(s): return hull_aligned_safe(df_1h["close"], hull_1h, s["signal_time"], s["direction"])
    def f_mh_color(s): return mh_aligned(s["direction"], asof_label_safe(mh_color, s["signal_time"]))
    def f_mh_mf(s):
        idx = mh_mf.index.searchsorted(s["signal_time"], side="right") - 1
        if idx < 1: return False
        v = mh_mf.iloc[idx - 1]
        if pd.isna(v): return False
        if s["direction"] == "LONG": return v > 0
        return v < 0
    def f_asvk_not_extreme(s):
        return asvk_not_extreme(s["direction"], asof_label_safe(asvk_zone, s["signal_time"]))
    def f_ict_lon_ny(s): return in_session(s["signal_time"], ["london", "ny"])
    def f_no_friday(s): return pd.Timestamp(s["signal_time"]).weekday() != 4
    def f_do_match(s):
        # We need entry price for DO comparison - approximate as midline of FVG
        fb, ft = s["fvg_b"], s["fvg_t"]
        entry_approx = fb + ENTRY_PCT * (ft - fb) if s["direction"] == "LONG" \
                        else ft - ENTRY_PCT * (ft - fb)
        return do_match(s["direction"], do_pos(df_1d, s["signal_time"], entry_approx))

    filters = {
        "F1 Hull-4h aligned":   f_hull4h,
        "F2 Hull-1d aligned":   f_hull1d,
        "F3 Hull-1h aligned":   f_hull1h,
        "F4 MH color aligned":  f_mh_color,
        "F5 MH MF aligned":     f_mh_mf,
        "F6 ASVK not extreme":  f_asvk_not_extreme,
        "F7 ICT london|ny":     f_ict_lon_ny,
        "F8 exclude Friday":    f_no_friday,
        "F9 DO match":          f_do_match,
    }
    for name, pred in filters.items():
        sub = apply_filter(cache_6y_all, pred)
        df_e = evaluate(sub, USER_SL_LONG, USER_SL_SHORT, USER_RR,
                          min_sl_pct=1.0, no_entry=True)
        report(f"{name} (n={len(sub)})", df_e)

    # ============================================================
    # COMBOS
    # ============================================================
    print(f"\n{'='*70}\nCOMBOS поверх V3 (RR=1.8)")
    print(f"{'='*70}")
    combos = {
        "F1+F4 Hull-4h + MH color":   lambda s: f_hull4h(s) and f_mh_color(s),
        "F1+F7 Hull-4h + ICT":        lambda s: f_hull4h(s) and f_ict_lon_ny(s),
        "F1+F5 Hull-4h + MH MF":      lambda s: f_hull4h(s) and f_mh_mf(s),
        "F1+F8 Hull-4h + no Friday":  lambda s: f_hull4h(s) and f_no_friday(s),
        "F1+F4+F7 triple":            lambda s: f_hull4h(s) and f_mh_color(s) and f_ict_lon_ny(s),
        "F2+F1 Hull-1d + Hull-4h":    lambda s: f_hull1d(s) and f_hull4h(s),
        "Score>=3 of (F1,F4,F7,F8,F9)": lambda s: (
            int(f_hull4h(s)) + int(f_mh_color(s)) + int(f_ict_lon_ny(s)) +
            int(f_no_friday(s)) + int(f_do_match(s))) >= 3,
    }
    for name, pred in combos.items():
        sub = apply_filter(cache_6y_all, pred)
        df_e = evaluate(sub, USER_SL_LONG, USER_SL_SHORT, USER_RR,
                          min_sl_pct=1.0, no_entry=True)
        report(f"{name} (n={len(sub)})", df_e)

    # ============================================================
    # SMART TRAIL
    # ============================================================
    print(f"\n{'='*70}\nSMART TRAIL поверх V3 (6.33y ALL, sl=0.35/0.65, min_sl=1%)")
    print(f"{'='*70}")

    print("  M0 baseline RR=1.8:")
    df_e = evaluate(cache_6y_all, USER_SL_LONG, USER_SL_SHORT, USER_RR,
                      min_sl_pct=1.0, no_entry=True)
    report("    M0", df_e)

    print("\n  M8 Hull-1h confirm-2:")
    df_e = evaluate_trail(cache_6y_all, USER_SL_LONG, USER_SL_SHORT, 1.0,
                           df_1m, df_1h, hull_1h_lbl)
    report("    M8 Hull-1h x2", df_e)

    # M8 на SWEPT-cache
    print("\n  M8 + SWEPT cache:")
    df_e = evaluate_trail(cache_6y_swept, USER_SL_LONG, USER_SL_SHORT, 1.0,
                           df_1m, df_1h, hull_1h_lbl)
    report("    M8 + SWEPT", df_e)

    # M8 + Hull-4h aligned (best filter combo from above)
    cache_hull4h = apply_filter(cache_6y_all, f_hull4h)
    print(f"\n  M8 + Hull-4h aligned filter (n={len(cache_hull4h)}):")
    df_e = evaluate_trail(cache_hull4h, USER_SL_LONG, USER_SL_SHORT, 1.0,
                           df_1m, df_1h, hull_1h_lbl)
    report("    M8 + Hull4h", df_e)

    print(f"\n[TIME] {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
