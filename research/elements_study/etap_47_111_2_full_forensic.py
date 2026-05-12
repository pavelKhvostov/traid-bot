"""Этап 47: полный forensic 1.1.2 с поиском разделяющих фич.

Цель: понять, что ОТЛИЧАЕТ winning trades от losing на 1.1.2 baseline RR=1.8,
и можно ли это использовать как фильтр.

Подход:
  Phase A: SAFE baseline RR=1.8 (с not_filled check) → 616 closed trades
  Phase B: для каждого closed trade считаем 30+ фич at signal_time:
    - Hull-MA на 1h/4h/12h/1d, длины 49/78/100/160
    - ASVK ema_3 zone на 1h, 4h
    - MH bw2 color, MF sign на 1h, 4h
    - Pro-trend EMA200 на 1h, 4h, 1d
    - Время (hour, weekday, session)
    - FVG width, OB depth, distance signal→entry в %
  Phase C: per-feature segment — какие values winners/losers разделяют?
  Phase D: parameter sweep — Hull length sensitivity
  Phase E: combo tests — top 15 промежуточных и в combination
  Phase F: best filter year-by-year + CSV для inspection

ВАЖНО: используется SAFE simulator с not_filled check (etap_46 fix).
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
DAYS_BACK = 2313
ENTRY_PCT = 0.70
USER_SL_LONG = 0.35
USER_SL_SHORT = 0.65
RR = 1.8
MIN_SL_PCT = 1.0

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


def hull_ma(close, length):
    arr = close.to_numpy(dtype=float)
    half = max(int(length / 2), 1)
    sqrt_len = max(int(round(np.sqrt(length))), 1)
    raw = 2.0 * wma_fast(arr, half) - wma_fast(arr, length)
    hull = wma_fast(np.where(np.isnan(raw), 0.0, raw), sqrt_len)
    hull[:length + sqrt_len] = np.nan
    return pd.Series(hull, index=close.index)


def hull_label_series(close, hull):
    """SAFE label: close[i] > hull[i-2], known at bar close i."""
    n = len(close); out = []
    for i in range(n):
        if i < 2:
            out.append("na"); continue
        c = close.iloc[i]; h2 = hull.iloc[i - 2]
        if pd.isna(c) or pd.isna(h2): out.append("na")
        else: out.append("up" if c > h2 else "down")
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


def compute_atr(df, period=14):
    high = df["high"]; low = df["low"]; pc = df["close"].shift(1)
    tr = pd.concat([(high-low),(high-pc).abs(),(low-pc).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


# ---------- 1.1.2 pipeline ----------

def precompute(sig):
    fvg_b, fvg_t = sig["fvg_zone"]
    obh_b, obh_t = sig["ob_htf_zone"]
    direction = sig["direction"]
    tf_minutes = 15 if sig["fvg_tf"] == "15m" else 20
    return {
        "direction": direction,
        "fvg_b": float(fvg_b), "fvg_t": float(fvg_t),
        "obh_b": float(obh_b), "obh_t": float(obh_t),
        "signal_time": sig["signal_time"],
        "year": pd.Timestamp(sig["signal_time"]).year,
        "tf_minutes": tf_minutes,
    }


def build_orders(s):
    direction = s["direction"]
    fw = s["fvg_t"] - s["fvg_b"]
    if direction == "LONG":
        entry = s["fvg_b"] + ENTRY_PCT * fw
        sl_lo = s["obh_b"]; sl_hi = s["fvg_b"]
        sl = sl_lo + USER_SL_LONG * (sl_hi - sl_lo)
        if MIN_SL_PCT > 0:
            sl = min(sl, entry - entry * MIN_SL_PCT / 100)
        if sl >= entry: return None
    else:
        entry = s["fvg_t"] - ENTRY_PCT * fw
        sl_hi = s["obh_t"]; sl_lo = s["fvg_t"]
        sl = sl_hi - USER_SL_SHORT * (sl_hi - sl_lo)
        if MIN_SL_PCT > 0:
            sl = max(sl, entry + entry * MIN_SL_PCT / 100)
        if sl <= entry: return None
    return entry, sl


def simulate_safe(s, entry, sl, tp, df_1m, max_hold_days=7):
    """SAFE fixed-RR simulator with not_filled check (= etap_45 V3 logic)."""
    direction = s["direction"]
    risk = abs(entry - sl)
    if risk <= 0: return ("invalid", 0.0)
    tf_min = s["tf_minutes"]
    entry_window_start = s["signal_time"] + pd.Timedelta(minutes=tf_min)
    end_time = entry_window_start + pd.Timedelta(days=max_hold_days)
    et64 = np.datetime64(entry_window_start.tz_localize(None)
                          if entry_window_start.tz else entry_window_start)
    ee64 = np.datetime64(end_time.tz_localize(None)
                          if end_time.tz else end_time)
    i0 = np.searchsorted(df_1m.index.values, et64)
    i1 = np.searchsorted(df_1m.index.values, ee64)
    if i1 <= i0: return ("no_data", 0.0)
    h = df_1m["high"].values[i0:i1].astype(np.float64)
    l = df_1m["low"].values[i0:i1].astype(np.float64)
    if direction == "LONG":
        ent_idxs = np.where(l <= entry)[0]
        tp_pre_idxs = np.where(h >= tp)[0]
    else:
        ent_idxs = np.where(h >= entry)[0]
        tp_pre_idxs = np.where(l <= tp)[0]
    ent_idx = int(ent_idxs[0]) if ent_idxs.size else len(h) + 1
    tp_pre = int(tp_pre_idxs[0]) if tp_pre_idxs.size else len(h) + 1
    # no_entry: TP achieved before entry → cancel
    if tp_pre < ent_idx:
        return ("no_entry", 0.0)
    if ent_idx >= len(h): return ("not_filled", 0.0)
    post_h = h[ent_idx:]; post_l = l[ent_idx:]
    if direction == "LONG":
        sl_m = post_l <= sl; tp_m = post_h >= tp
    else:
        sl_m = post_h >= sl; tp_m = post_l <= tp
    sl_first = int(np.argmax(sl_m)) if sl_m.any() else -1
    tp_first = int(np.argmax(tp_m)) if tp_m.any() else -1
    if sl_first == -1 and tp_first == -1: return ("open", 0.0)
    if sl_first == -1: return ("win", RR)
    if tp_first == -1: return ("loss", -1.0)
    return ("win", RR) if tp_first < sl_first else ("loss", -1.0)


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


# ---------- safe lookup helpers ----------

def safe_label(label_series, ts):
    """Last CLOSED bar's label."""
    idx = label_series.index.searchsorted(ts, side="right") - 1
    if idx < 1: return "na"
    return label_series.iloc[idx - 1]


def safe_value(series, ts):
    idx = series.index.searchsorted(ts, side="right") - 1
    if idx < 1: return np.nan
    v = series.iloc[idx - 1]
    return float(v) if pd.notna(v) else np.nan


# ---------- forensic features ----------

def aligned(direction, label, up="up", down="down"):
    if label == "na": return None
    if direction == "LONG":
        return label == up
    return label == down


def extract_features(s, entry, hull_lbls, ema200_lbls, asvk_zones,
                       mh_colors, mh_mfs, atr_series, df_1d):
    """Extract all features for one setup at signal_time."""
    ts = s["signal_time"]
    direction = s["direction"]
    fb, ft = s["fvg_b"], s["fvg_t"]
    obb, obt = s["obh_b"], s["obh_t"]

    f = {}
    # Hull aligned (multiple TFs × lengths)
    for tf, lbl in hull_lbls.items():
        a = aligned(direction, safe_label(lbl, ts))
        f[f"hull_{tf}_align"] = "aligned" if a else ("counter" if a is False else "na")

    # EMA200 align на разных TF
    for tf, lbl in ema200_lbls.items():
        a = aligned(direction, safe_label(lbl, ts), "above", "below")
        f[f"ema200_{tf}_align"] = "aligned" if a else ("counter" if a is False else "na")

    # ASVK zone
    for tf, zlbl in asvk_zones.items():
        f[f"asvk_{tf}_zone"] = safe_label(zlbl, ts)

    # MH color
    for tf, clbl in mh_colors.items():
        col = safe_label(clbl, ts)
        f[f"mh_{tf}_color"] = col
        bullish = col in ("green", "grey_from_red")
        bearish = col in ("red", "grey_from_green")
        if direction == "LONG":
            f[f"mh_{tf}_color_align"] = "aligned" if bullish else ("counter" if bearish else "neutral")
        else:
            f[f"mh_{tf}_color_align"] = "aligned" if bearish else ("counter" if bullish else "neutral")

    # MH MF sign aligned
    for tf, mfs in mh_mfs.items():
        v = safe_value(mfs, ts)
        if np.isnan(v):
            f[f"mh_{tf}_mf_align"] = "na"
        else:
            pos = v > 0
            if direction == "LONG":
                f[f"mh_{tf}_mf_align"] = "aligned" if pos else "counter"
            else:
                f[f"mh_{tf}_mf_align"] = "aligned" if not pos else "counter"

    # Time-based
    h = ts.hour
    f["hour"] = h
    f["weekday"] = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"][ts.weekday()]
    f["session"] = ("asia" if h < 7 else "london" if h < 12
                     else "ny" if h < 17 else "off")

    # FVG geometry
    fvg_w = ft - fb
    fvg_w_pct = fvg_w / fb * 100  # FVG width as % of price
    f["fvg_w_pct"] = round(fvg_w_pct, 3)
    f["fvg_w_bin"] = "small" if fvg_w_pct < 0.5 else \
                     "medium" if fvg_w_pct < 1.5 else "large"

    # OB depth
    ob_depth_pct = (obt - obb) / obb * 100
    f["ob_depth_bin"] = "small" if ob_depth_pct < 1 else \
                         "medium" if ob_depth_pct < 3 else "large"

    # Distance from signal-time price to entry (as % of FVG width)
    # Need close at signal_time on 1h or similar — use ema200_1h's parent close
    # Approximation: use last 1h close close to signal_time
    # We'll use atr_series['1h'] index to find close at ts
    # Actually, just measure where entry sits in FVG (always 0.7 — fixed)

    # Daily-open premium/discount
    idx_d = df_1d.index.searchsorted(ts, side="right") - 1
    if idx_d >= 0:
        do = df_1d["open"].iloc[idx_d]
        if entry > do: do_label = "premium"
        elif entry < do: do_label = "discount"
        else: do_label = "mid"
    else:
        do_label = "na"
    if direction == "LONG":
        f["do_match"] = "aligned" if do_label == "discount" else \
                         ("counter" if do_label == "premium" else "na")
    else:
        f["do_match"] = "aligned" if do_label == "premium" else \
                         ("counter" if do_label == "discount" else "na")

    # ATR ratio: 1h ATR / 4h ATR (volatility regime)
    atr_1h = safe_value(atr_series["1h"], ts)
    atr_4h = safe_value(atr_series["4h"], ts)
    if not np.isnan(atr_1h) and not np.isnan(atr_4h) and atr_4h > 0:
        ratio = atr_1h / atr_4h
        f["atr_ratio_bin"] = "low" if ratio < 0.4 else \
                              "med" if ratio < 0.6 else "high"
    else:
        f["atr_ratio_bin"] = "na"

    return f


def report_segment(closed_df, feature, baseline_wr, baseline_R, min_n=30):
    g = closed_df.groupby(feature).agg(
        n=("R", "size"),
        wins=("outcome", lambda x: (x == "win").sum()),
        total_R=("R", "sum"),
        avg_R=("R", "mean"),
    )
    g["WR"] = g["wins"] / g["n"] * 100
    g = g.sort_values("WR", ascending=False)
    print(f"\n=== {feature} ===  (baseline {baseline_wr:.1f}% / {baseline_R:+.1f}R)")
    for cat, row in g.iterrows():
        d_wr = row["WR"] - baseline_wr
        flag = ""
        if row["n"] >= min_n:
            if d_wr >= 5: flag = " ***"
            elif d_wr <= -5: flag = " !"
        print(f"  {cat!s:<22} n={int(row['n']):>4} WR={row['WR']:5.1f}% "
              f"(d={d_wr:+5.1f}pp) total={row['total_R']:+6.1f}R "
              f"R/tr={row['avg_R']:+.3f}{flag}")


def evaluate_filter(closed_df, mask_label, mask, baseline_wr, baseline_R):
    sub = closed_df[mask]
    if len(sub) < 20:
        print(f"  {mask_label}: n={len(sub)} - skip"); return None
    wr = (sub["outcome"] == "win").mean() * 100
    tot = sub["R"].sum()
    rt = sub["R"].mean()
    yr = sub.groupby("year")["R"].sum()
    bad = (yr < 0).sum()
    d_wr = wr - baseline_wr
    print(f"  {mask_label} (n={len(sub)})")
    print(f"    WR={wr:.1f}% (d={d_wr:+.1f}pp) total={tot:+.1f}R R/tr={rt:+.3f} bad_yrs={bad}/{len(yr)}")
    return {"n": len(sub), "wr": wr, "total_R": tot, "rt": rt,
            "bad_yrs": bad, "n_yrs": len(yr)}


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
    cutoff = today - pd.Timedelta(days=DAYS_BACK)
    df_1d_f = df_1d[df_1d.index >= cutoff]

    # Pre-compute indicators for multiple TFs and Hull lengths
    print("[INFO] вычисляем все индикаторы")
    HULL_LENGTHS = [49, 78, 100, 160]
    HULL_TFS = {"1h": df_1h, "4h": df_4h, "12h": df_12h, "1d": df_1d}
    MH_TFS = {"1h": df_1h, "4h": df_4h}
    ASVK_TFS = {"1h": df_1h, "4h": df_4h}
    EMA200_TFS = {"15m": df_15m, "1h": df_1h, "4h": df_4h, "1d": df_1d}

    hull_lbls = {}
    for tf, df in HULL_TFS.items():
        for L in HULL_LENGTHS:
            h = hull_ma(df["close"], L)
            hull_lbls[f"{tf}_L{L}"] = hull_label_series(df["close"], h)

    ema200_lbls = {}
    for tf, df in EMA200_TFS.items():
        ema = df["close"].ewm(span=200, adjust=False).mean()
        out = []
        for c, e in zip(df["close"], ema):
            if pd.isna(c) or pd.isna(e):
                out.append("na")
            else:
                out.append("above" if c > e else "below")
        ema200_lbls[tf] = pd.Series(out, index=df.index)

    asvk_zones = {}
    for tf, df in ASVK_TFS.items():
        e3 = asvk_adjusted_rsi(df["close"])
        ab, bl = asvk_dynamic_levels(e3, 200)
        asvk_zones[tf] = asvk_zone_label(e3, ab, bl)

    mh_colors = {}
    mh_mfs = {}
    for tf, df in MH_TFS.items():
        bw2, sma14 = mh_bw2(df)
        mh_colors[tf] = mh_color_label(bw2, sma14)
        mh_mfs[tf] = money_flow_ha(df)

    atr_series = {
        "1h": compute_atr(df_1h, 14),
        "4h": compute_atr(df_4h, 14),
    }
    print(f"  Hull labels: {len(hull_lbls)} variants")
    print(f"  ASVK on {len(asvk_zones)} TFs, MH on {len(mh_colors)} TFs")

    # Detect 1.1.2 setups
    print("[INFO] детектируем 1.1.2 setups")
    raw = detect_strategy_1_1_2_signals(
        df_1d_f, df_12h, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m,
        verbose=False)
    groups = defaultdict(list)
    for s in raw:
        key = (s["signal_time"], s["direction"], round(float(s["entry"]), 2))
        sw = check_swept(s, df_1h, df_2h)
        if sw is None: continue
        groups[key].append({"sig": s, "swept": sw})
    all_reps = [paths[0]["sig"] for paths in groups.values()]
    cache = [precompute(s) for s in all_reps]
    print(f"  total signals (deduped): {len(cache)}")

    # Build orders
    setups = []
    for s in cache:
        tup = build_orders(s)
        if tup is None: continue
        entry, sl = tup
        risk = abs(entry - sl)
        tp = entry + RR * risk if s["direction"] == "LONG" else entry - RR * risk
        setups.append({**s, "entry": entry, "sl": sl, "tp": tp})
    print(f"  setups: {len(setups)}")

    # Simulate (SAFE)
    print("[INFO] симулируем SAFE RR=1.8")
    rows = []
    for s in setups:
        outcome, R = simulate_safe(s, s["entry"], s["sl"], s["tp"], df_1m)
        rows.append({**s, "outcome": outcome, "R": R})
    df_full = pd.DataFrame(rows)
    closed = df_full[df_full["outcome"].isin(["win", "loss"])].copy()
    n_total = len(df_full)
    n_no_entry = (df_full["outcome"] == "no_entry").sum()
    n_not_filled = (df_full["outcome"] == "not_filled").sum()
    nc = len(closed)
    wins = (closed["R"] > 0).sum()
    losses = (closed["R"] < 0).sum()
    base_wr = wins / nc * 100
    base_R = closed["R"].sum()
    print(f"  n_total={n_total}, no_entry={n_no_entry}, not_filled={n_not_filled}, closed={nc}")
    print(f"  BASELINE: WR={base_wr:.1f}%  total={base_R:+.1f}R  R/tr={closed['R'].mean():+.3f}")
    yr = closed.groupby("year")["R"].sum()
    bad = (yr < 0).sum()
    print(f"  bad_yrs={bad}/{len(yr)}")

    # ============================================================
    # PHASE B: Extract features per closed trade
    # ============================================================
    print(f"\n[PHASE B] извлекаем фичи для {len(closed)} closed trades")
    feat_rows = []
    for _, r in closed.iterrows():
        s = {"signal_time": r["signal_time"], "direction": r["direction"],
              "fvg_b": r["fvg_b"], "fvg_t": r["fvg_t"],
              "obh_b": r["obh_b"], "obh_t": r["obh_t"]}
        f = extract_features(s, r["entry"], hull_lbls, ema200_lbls,
                              asvk_zones, mh_colors, mh_mfs, atr_series, df_1d)
        feat_rows.append(f)
    feats = pd.DataFrame(feat_rows, index=closed.index)
    closed = pd.concat([closed, feats], axis=1)

    # Save full CSV
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_out = OUT_DIR / "etap47_closed_trades_features.csv"
    closed.to_csv(csv_out, index=False, encoding="utf-8-sig")
    print(f"  trades CSV: {csv_out}")

    # ============================================================
    # PHASE C: Per-feature segmentation
    # ============================================================
    print(f"\n{'='*70}")
    print(f"PHASE C: PER-FEATURE SEGMENTATION  (baseline {base_wr:.1f}% / {base_R:+.1f}R)")
    print(f"{'='*70}")

    # Standard set
    for feat_col in [
        "direction", "session", "weekday",
        "ema200_15m_align", "ema200_1h_align", "ema200_4h_align", "ema200_1d_align",
        "asvk_1h_zone", "asvk_4h_zone",
        "mh_1h_color_align", "mh_4h_color_align",
        "mh_1h_mf_align", "mh_4h_mf_align",
        "do_match", "fvg_w_bin", "ob_depth_bin", "atr_ratio_bin",
    ]:
        report_segment(closed, feat_col, base_wr, base_R)

    # Hull labels (parameter sweep)
    print(f"\n{'='*70}")
    print(f"HULL parameter sweep (TF x Length)")
    print(f"{'='*70}")
    for hull_key in sorted(hull_lbls.keys()):
        col = f"hull_{hull_key}_align"
        report_segment(closed, col, base_wr, base_R, min_n=50)

    # ============================================================
    # PHASE D: Single-feature filter test
    # ============================================================
    print(f"\n{'='*70}")
    print(f"PHASE D: TOP single-feature filters (MIN n=80)")
    print(f"{'='*70}")
    print(f"baseline: {base_wr:.1f}% / {base_R:+.1f}R / 0 bad yrs (1.1.2 RR=1.8 SAFE)\n")

    candidate_filters = [
        ("hull_1h_L49 aligned", closed["hull_1h_L49_align"] == "aligned"),
        ("hull_1h_L78 aligned", closed["hull_1h_L78_align"] == "aligned"),
        ("hull_1h_L100 aligned", closed["hull_1h_L100_align"] == "aligned"),
        ("hull_1h_L160 aligned", closed["hull_1h_L160_align"] == "aligned"),
        ("hull_4h_L49 aligned", closed["hull_4h_L49_align"] == "aligned"),
        ("hull_4h_L78 aligned", closed["hull_4h_L78_align"] == "aligned"),
        ("hull_4h_L100 aligned", closed["hull_4h_L100_align"] == "aligned"),
        ("hull_4h_L160 aligned", closed["hull_4h_L160_align"] == "aligned"),
        ("hull_12h_L78 aligned", closed["hull_12h_L78_align"] == "aligned"),
        ("hull_12h_L160 aligned", closed["hull_12h_L160_align"] == "aligned"),
        ("hull_1d_L49 aligned", closed["hull_1d_L49_align"] == "aligned"),
        ("hull_1d_L78 aligned", closed["hull_1d_L78_align"] == "aligned"),
        ("ema200_1h aligned", closed["ema200_1h_align"] == "aligned"),
        ("ema200_4h aligned", closed["ema200_4h_align"] == "aligned"),
        ("ema200_1d aligned", closed["ema200_1d_align"] == "aligned"),
        ("mh_1h color aligned", closed["mh_1h_color_align"] == "aligned"),
        ("mh_4h color aligned", closed["mh_4h_color_align"] == "aligned"),
        ("mh_1h MF aligned", closed["mh_1h_mf_align"] == "aligned"),
        ("session london+ny", closed["session"].isin(["london", "ny"])),
        ("exclude Friday", closed["weekday"] != "Fri"),
        ("do_match aligned", closed["do_match"] == "aligned"),
        ("asvk_1h not red", closed["asvk_1h_zone"] != "red"),
        ("asvk_4h not extreme", ~closed["asvk_4h_zone"].isin(["red", "green"])),
        ("FVG width medium+small", closed["fvg_w_bin"].isin(["small", "medium"])),
    ]
    results = []
    for name, mask in candidate_filters:
        r = evaluate_filter(closed, name, mask, base_wr, base_R)
        if r:
            r["name"] = name
            results.append(r)

    # Sort by total_R (best gain)
    print(f"\n--- РЕЙТИНГ по total_R ---")
    sorted_r = sorted(results, key=lambda x: x["total_R"], reverse=True)
    for r in sorted_r[:8]:
        print(f"  {r['name']:<32} n={r['n']:>4} WR={r['wr']:5.1f}% "
              f"total={r['total_R']:+6.1f}R R/tr={r['rt']:+.3f} bad={r['bad_yrs']}/{r['n_yrs']}")

    print(f"\n--- РЕЙТИНГ по R/tr (лучший edge на сделку) ---")
    sorted_rt = sorted(results, key=lambda x: x["rt"], reverse=True)
    for r in sorted_rt[:8]:
        print(f"  {r['name']:<32} n={r['n']:>4} WR={r['wr']:5.1f}% "
              f"total={r['total_R']:+6.1f}R R/tr={r['rt']:+.3f} bad={r['bad_yrs']}/{r['n_yrs']}")

    # ============================================================
    # PHASE E: Combos
    # ============================================================
    print(f"\n{'='*70}")
    print(f"PHASE E: COMBOS (top single combined)")
    print(f"{'='*70}")

    # Find top 2 single-features by R/tr (with n >= 200 to ensure stability)
    stable_top = [r for r in sorted_rt if r["n"] >= 200][:5]
    print(f"\nTop-5 stable filters (n>=200) for combo testing:")
    for r in stable_top:
        print(f"  {r['name']}  R/tr={r['rt']:+.3f} total={r['total_R']:+.1f}R")

    # Manual combos based on findings
    combo_filters = [
        ("hull_1h_L78 + ema200_1h",
            (closed["hull_1h_L78_align"] == "aligned") &
            (closed["ema200_1h_align"] == "aligned")),
        ("hull_1h_L78 + asvk_1h not red",
            (closed["hull_1h_L78_align"] == "aligned") &
            (closed["asvk_1h_zone"] != "red")),
        ("hull_1h_L100 + exclude Friday",
            (closed["hull_1h_L100_align"] == "aligned") &
            (closed["weekday"] != "Fri")),
        ("hull_1h_L160 + ema200_4h",
            (closed["hull_1h_L160_align"] == "aligned") &
            (closed["ema200_4h_align"] == "aligned")),
        ("hull_4h_L78 + ICT lon+ny",
            (closed["hull_4h_L78_align"] == "aligned") &
            (closed["session"].isin(["london", "ny"]))),
        ("hull_1h_L78 + MH MF aligned",
            (closed["hull_1h_L78_align"] == "aligned") &
            (closed["mh_1h_mf_align"] == "aligned")),
        ("hull_4h_L78 + hull_1d_L78",
            (closed["hull_4h_L78_align"] == "aligned") &
            (closed["hull_1d_L78_align"] == "aligned")),
        ("ema200_1h + ema200_4h aligned",
            (closed["ema200_1h_align"] == "aligned") &
            (closed["ema200_4h_align"] == "aligned")),
    ]
    print()
    combo_results = []
    for name, mask in combo_filters:
        r = evaluate_filter(closed, name, mask, base_wr, base_R)
        if r:
            r["name"] = name
            combo_results.append(r)

    # Score-based composite
    print(f"\n--- SCORE-based composite (5 features) ---")
    score = (
        (closed["hull_1h_L78_align"] == "aligned").astype(int) +
        (closed["ema200_1h_align"] == "aligned").astype(int) +
        (closed["mh_1h_color_align"] == "aligned").astype(int) +
        (closed["weekday"] != "Fri").astype(int) +
        (closed["session"].isin(["london", "ny"])).astype(int)
    )
    closed["score"] = score
    print(f"  Score distribution:")
    for sc in sorted(closed["score"].unique()):
        sub = closed[closed["score"] == sc]
        wr = (sub["outcome"] == "win").mean() * 100 if len(sub) else 0
        tot = sub["R"].sum()
        print(f"    score={sc}: n={len(sub):>4} WR={wr:5.1f}% total={tot:+6.1f}R")
    evaluate_filter(closed, "score>=2", closed["score"] >= 2, base_wr, base_R)
    evaluate_filter(closed, "score>=3", closed["score"] >= 3, base_wr, base_R)
    evaluate_filter(closed, "score>=4", closed["score"] >= 4, base_wr, base_R)

    # ============================================================
    # PHASE F: Best combo year-by-year
    # ============================================================
    if combo_results:
        best = max(combo_results, key=lambda x: x["total_R"])
        # find the mask
        for name, mask in combo_filters:
            if name == best["name"]:
                print(f"\n{'='*70}")
                print(f"PHASE F: BEST COMBO YEAR-BY-YEAR  ({best['name']})")
                print(f"{'='*70}")
                sub = closed[mask]
                yr = sub.groupby("year").agg(
                    n=("R", "size"),
                    wins=("outcome", lambda x: (x == "win").sum()),
                    total_R=("R", "sum"))
                yr["WR"] = yr["wins"] / yr["n"] * 100
                yr["R_tr"] = yr["total_R"] / yr["n"]
                for y, r in yr.iterrows():
                    flag = "  !" if r["total_R"] < 0 else ""
                    print(f"  {int(y)}: n={int(r['n']):>3} WR={r['WR']:5.1f}% "
                          f"total={r['total_R']:+5.1f}R R/tr={r['R_tr']:+.3f}{flag}")
                break

    print(f"\n[TIME] {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
