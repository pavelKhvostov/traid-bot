"""Этап 53: 1.1.4 STRICT-L1 + SWEPT + полный forensic.

Baseline: STRICT-L1 RR=1.8 (etap_52) — +19.8R / 375 closed / 2 bad years.

Подход:
  Phase A: SWEPT filter (на OB-mid L3, как в 1.1.1/1.1.2)
  Phase B: feature extraction per closed trade
  Phase C: per-feature segmentation — что разделяет winners/losers
  Phase D: top single filters
  Phase E: combos
  Phase F: verdict
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
from strategies.strategy_1_1_1 import detect_ob_pair, detect_fvg

SYMBOL = "BTCUSDT"
START_DATE = "2020-01-01"
ENTRY_PCT = 0.70
USER_SL_LONG = 0.35
USER_SL_SHORT = 0.65
RR = 1.8
MIN_SL_PCT = 1.0

LIFE_DAYS = {"1d": 14, "12h": 7, "6h": 4, "4h": 3,
              "2h": 1.5, "1h": 1, "15m": 0.5}
TF_HOURS = {"1d": 24, "12h": 12, "6h": 6, "4h": 4,
             "2h": 2, "1h": 1, "15m": 0.25}

OUT_DIR = Path("research/elements_study/output")


def compute_atr(df, period=14):
    high = df["high"]; low = df["low"]; pc = df["close"].shift(1)
    tr = pd.concat([(high-low),(high-pc).abs(),(low-pc).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


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
        if pd.isna(e) or pd.isna(a) or pd.isna(b): out.append("na")
        elif e > a: out.append("red")
        elif e < b: out.append("green")
        else: out.append("neutral")
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


def collect_obs(df, atr, tf):
    out = []
    for idx in range(2, len(df) - 1):
        ob = detect_ob_pair(df, idx)
        if ob is None: continue
        a = float(atr.iloc[idx])
        if pd.isna(a) or a <= 0: continue
        out.append({"kind": "OB", "tf": tf, "direction": ob.direction,
                     "bottom": ob.bottom, "top": ob.top, "atr": a,
                     "time": ob.cur_time, "idx": idx,
                     "prev_time": ob.prev_time})
    return out


def collect_fvgs(df, atr, tf):
    out = []
    for idx in range(2, len(df) - 1):
        f = detect_fvg(df, idx)
        if f is None: continue
        a = float(atr.iloc[idx])
        if pd.isna(a) or a <= 0: continue
        out.append({"kind": "FVG", "tf": tf, "direction": f.direction,
                     "bottom": f.bottom, "top": f.top, "atr": a,
                     "time": f.c2_time, "idx": idx})
    return out


def zones_overlap(b1, t1, b2, t2):
    return not (t1 < b2 or t2 < b1)


# STRICT-L1 detection (from etap_52)
def detect_114_strict(fvgs_top, obs_macro, obs_mid, fvgs_entry,
                       top_tf, macro_tf, mid_tf, entry_tf):
    setups = []
    top_td = pd.Timedelta(hours=TF_HOURS[top_tf])
    macro_td = pd.Timedelta(hours=TF_HOURS[macro_tf])
    mid_td = pd.Timedelta(hours=TF_HOURS[mid_tf])
    top_life = pd.Timedelta(days=LIFE_DAYS[top_tf])
    macro_life = pd.Timedelta(days=LIFE_DAYS[macro_tf])
    mid_life = pd.Timedelta(days=LIFE_DAYS[mid_tf])

    obs_macro_sorted = sorted(obs_macro, key=lambda x: x["time"])
    obs_mid_sorted = sorted(obs_mid, key=lambda x: x["time"])
    fvgs_entry_sorted = sorted(fvgs_entry, key=lambda x: x["time"])
    obs_macro_times = np.array([np.datetime64(z["time"].tz_localize(None) if z["time"].tz else z["time"])
                                  for z in obs_macro_sorted])
    obs_mid_times = np.array([np.datetime64(z["time"].tz_localize(None) if z["time"].tz else z["time"])
                                for z in obs_mid_sorted])
    fvgs_entry_times = np.array([np.datetime64(z["time"].tz_localize(None) if z["time"].tz else z["time"])
                                   for z in fvgs_entry_sorted])

    for fvg_top in fvgs_top:
        l1_confirm = fvg_top["time"] + top_td
        l1_end = fvg_top["time"] + top_life
        if l1_end <= l1_confirm: continue
        i0 = np.searchsorted(obs_macro_times, np.datetime64(
            l1_confirm.tz_localize(None) if l1_confirm.tz else l1_confirm), side="right")
        i1 = np.searchsorted(obs_macro_times, np.datetime64(
            l1_end.tz_localize(None) if l1_end.tz else l1_end), side="right")

        for mi in range(i0, i1):
            ob_macro = obs_macro_sorted[mi]
            if ob_macro["direction"] != fvg_top["direction"]: continue
            if not zones_overlap(ob_macro["bottom"], ob_macro["top"],
                                  fvg_top["bottom"], fvg_top["top"]): continue
            l2_confirm = ob_macro["time"] + macro_td
            l2_end = ob_macro["time"] + macro_life
            if l2_end <= l2_confirm: continue

            j0 = np.searchsorted(obs_mid_times, np.datetime64(
                l2_confirm.tz_localize(None) if l2_confirm.tz else l2_confirm), side="right")
            j1 = np.searchsorted(obs_mid_times, np.datetime64(
                l2_end.tz_localize(None) if l2_end.tz else l2_end), side="right")
            ob_mid_found = None
            for oj in range(j0, j1):
                ob_mid = obs_mid_sorted[oj]
                if ob_mid["direction"] != fvg_top["direction"]: continue
                if not zones_overlap(ob_mid["bottom"], ob_mid["top"],
                                      fvg_top["bottom"], fvg_top["top"]): continue
                if not zones_overlap(ob_mid["bottom"], ob_mid["top"],
                                      ob_macro["bottom"], ob_macro["top"]): continue
                ob_mid_found = ob_mid; break
            if ob_mid_found is None: continue

            l3_confirm = ob_mid_found["time"] + mid_td
            l3_end = ob_mid_found["time"] + mid_life
            if l3_end <= l3_confirm: continue
            k0 = np.searchsorted(fvgs_entry_times, np.datetime64(
                l3_confirm.tz_localize(None) if l3_confirm.tz else l3_confirm), side="right")
            k1 = np.searchsorted(fvgs_entry_times, np.datetime64(
                l3_end.tz_localize(None) if l3_end.tz else l3_end), side="right")
            fvg_entry_found = None
            for ek in range(k0, k1):
                f_entry = fvgs_entry_sorted[ek]
                if f_entry["direction"] != fvg_top["direction"]: continue
                if not zones_overlap(f_entry["bottom"], f_entry["top"],
                                      ob_mid_found["bottom"], ob_mid_found["top"]): continue
                # STRICT-L1
                if not zones_overlap(f_entry["bottom"], f_entry["top"],
                                      fvg_top["bottom"], fvg_top["top"]): continue
                fvg_entry_found = f_entry; break
            if fvg_entry_found is None: continue

            tf_minutes = 15
            setups.append({
                "anchor_time": fvg_top["time"],
                "trigger_time": fvg_entry_found["time"],
                "ob_mid": ob_mid_found,
                "fvg_b": fvg_entry_found["bottom"],
                "fvg_t": fvg_entry_found["top"],
                "obh_b": ob_mid_found["bottom"],
                "obh_t": ob_mid_found["top"],
                "tf_minutes": tf_minutes,
                "year": fvg_entry_found["time"].year,
                "direction": fvg_entry_found["direction"],
                "signal_time": fvg_entry_found["time"],
                "ob_htf_tf": mid_tf,
                "ob_htf_cur_time": ob_mid_found["time"],
                "ob_htf_prev_time": ob_mid_found["prev_time"],
                "macro_tf": macro_tf, "top_tf": top_tf,
            })
            break
    return setups


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


def build_orders(s):
    direction = s["direction"]
    fb, ft = s["fvg_b"], s["fvg_t"]
    obb, obt = s["obh_b"], s["obh_t"]
    fw = ft - fb
    if direction == "LONG":
        entry = fb + ENTRY_PCT * fw
        sl_lo = obb; sl_hi = fb
        sl = sl_lo + USER_SL_LONG * (sl_hi - sl_lo)
        if MIN_SL_PCT > 0:
            sl = min(sl, entry - entry * MIN_SL_PCT / 100)
        if sl >= entry: return None
    else:
        entry = ft - ENTRY_PCT * fw
        sl_hi = obt; sl_lo = ft
        sl = sl_hi - USER_SL_SHORT * (sl_hi - sl_lo)
        if MIN_SL_PCT > 0:
            sl = max(sl, entry + entry * MIN_SL_PCT / 100)
        if sl <= entry: return None
    return entry, sl


def simulate_safe(s, entry, sl, tp, df_1m, max_hold_days=7):
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
    if sl_first == -1: return ("win", abs(tp - entry) / risk)
    if tp_first == -1: return ("loss", -1.0)
    if tp_first < sl_first:
        return ("win", abs(tp - entry) / risk)
    return ("loss", -1.0)


def evaluate(setups, rr, df_1m):
    rows = []
    for s in setups:
        tup = build_orders(s)
        if tup is None: continue
        entry, sl = tup
        risk = abs(entry - sl)
        tp = entry + rr * risk if s["direction"] == "LONG" else entry - rr * risk
        outcome, R = simulate_safe(s, entry, sl, tp, df_1m)
        rows.append({**s, "entry": entry, "sl": sl, "tp": tp,
                      "outcome": outcome, "R": R})
    return pd.DataFrame(rows)


def report(label, df):
    cl = df[df["outcome"].isin(["win", "loss"])]
    n_total = len(df)
    if cl.empty:
        print(f"  {label}: no closed (n={n_total})"); return None
    nc = len(cl); wins = (cl["R"] > 0).sum()
    wr = wins/nc*100; tot = cl["R"].sum(); rt = cl["R"].mean()
    yr = cl.groupby("year")["R"].sum()
    bad = (yr < 0).sum()
    print(f"  {label}")
    print(f"    n_total={n_total}, closed={nc}, WR={wr:.1f}%  total={tot:+.1f}R  R/tr={rt:+.3f}  bad={bad}/{len(yr)}")
    return tot, wr, nc, bad


def safe_label(label_series, ts):
    idx = label_series.index.searchsorted(ts, side="right") - 1
    if idx < 1: return "na"
    return label_series.iloc[idx - 1]


def safe_value(series, ts):
    idx = series.index.searchsorted(ts, side="right") - 1
    if idx < 1: return np.nan
    v = series.iloc[idx - 1]
    return float(v) if pd.notna(v) else np.nan


def aligned(direction, label, up="up", down="down"):
    if label == "na": return None
    if direction == "LONG": return label == up
    return label == down


def extract_features(s, entry, hull_lbls, ema200_lbls, asvk_zones,
                       mh_colors, mh_mfs, df_1d):
    ts = s["signal_time"]
    direction = s["direction"]
    fb, ft = s["fvg_b"], s["fvg_t"]
    obb, obt = s["obh_b"], s["obh_t"]
    f = {}
    for tf, lbl in hull_lbls.items():
        a = aligned(direction, safe_label(lbl, ts))
        f[f"hull_{tf}_align"] = "aligned" if a else ("counter" if a is False else "na")
    for tf, lbl in ema200_lbls.items():
        a = aligned(direction, safe_label(lbl, ts), "above", "below")
        f[f"ema200_{tf}_align"] = "aligned" if a else ("counter" if a is False else "na")
    for tf, zlbl in asvk_zones.items():
        f[f"asvk_{tf}_zone"] = safe_label(zlbl, ts)
    for tf, clbl in mh_colors.items():
        col = safe_label(clbl, ts)
        f[f"mh_{tf}_color"] = col
        bullish = col in ("green", "grey_from_red")
        bearish = col in ("red", "grey_from_green")
        if direction == "LONG":
            f[f"mh_{tf}_color_align"] = "aligned" if bullish else ("counter" if bearish else "neutral")
        else:
            f[f"mh_{tf}_color_align"] = "aligned" if bearish else ("counter" if bullish else "neutral")
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
    h = ts.hour
    f["hour"] = h
    f["weekday"] = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"][ts.weekday()]
    f["session"] = ("asia" if h < 7 else "london" if h < 12
                     else "ny" if h < 17 else "off")
    fvg_w_pct = (ft - fb) / fb * 100
    f["fvg_w_pct"] = round(fvg_w_pct, 3)
    f["fvg_w_bin"] = "small" if fvg_w_pct < 0.5 else \
                     "medium" if fvg_w_pct < 1.5 else "large"
    ob_depth_pct = (obt - obb) / obb * 100
    f["ob_depth_bin"] = "small" if ob_depth_pct < 1 else \
                         "medium" if ob_depth_pct < 3 else "large"
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
    return f


def report_segment(closed_df, feature, baseline_wr, baseline_R, min_n=20):
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
    print(f"  {mask_label} (n={len(sub)})  WR={wr:.1f}% (d={wr-baseline_wr:+.1f}pp)  "
          f"total={tot:+.1f}R  R/tr={rt:+.3f}  bad={bad}/{len(yr)}")
    return {"name": mask_label, "n": len(sub), "wr": wr,
             "total_R": tot, "rt": rt, "bad_yrs": bad, "n_yrs": len(yr)}


def main():
    t0 = time.time()
    print("[INFO] load data")
    df_1d = load_df(SYMBOL, "1d")
    df_4h = load_df(SYMBOL, "4h")
    df_1h = load_df(SYMBOL, "1h")
    df_12h = compose_from_base(df_1h, "12h")
    df_6h = compose_from_base(df_1h, "6h")
    df_2h = compose_from_base(df_1h, "2h")
    df_1m = load_df(SYMBOL, "1m")
    # FIX (etap_55 audit): native 15m CSV has 2022 data gap (only 1 bar).
    # Compose 15m from 1m which was fixed in etap_27.
    df_15m = compose_from_base(df_1m, "15m")

    cutoff = pd.Timestamp(START_DATE, tz="UTC")
    df_1d = df_1d[df_1d.index >= cutoff].copy()
    df_4h = df_4h[df_4h.index >= cutoff].copy()
    df_1h = df_1h[df_1h.index >= cutoff].copy()
    df_12h = df_12h[df_12h.index >= cutoff].copy()
    df_6h = df_6h[df_6h.index >= cutoff].copy()
    df_2h = df_2h[df_2h.index >= cutoff].copy()
    df_15m = df_15m[df_15m.index >= cutoff].copy()
    df_1m = df_1m[df_1m.index >= cutoff]

    for tf, df in [("1d", df_1d), ("12h", df_12h), ("6h", df_6h),
                    ("4h", df_4h), ("2h", df_2h), ("1h", df_1h),
                    ("15m", df_15m)]:
        df["atr14"] = compute_atr(df, 14)

    print("[INFO] indicators")
    HULL_LENGTHS = [49, 78, 100, 160]
    HULL_TFS = {"1h": df_1h, "4h": df_4h, "12h": df_12h, "1d": df_1d}
    hull_lbls = {}
    for tf, df in HULL_TFS.items():
        for L in HULL_LENGTHS:
            h = hull_ma(df["close"], L)
            hull_lbls[f"{tf}_L{L}"] = hull_label_series(df["close"], h)
    EMA200_TFS = {"15m": df_15m, "1h": df_1h, "4h": df_4h, "1d": df_1d}
    ema200_lbls = {}
    for tf, df in EMA200_TFS.items():
        ema = df["close"].ewm(span=200, adjust=False).mean()
        out = []
        for c, e in zip(df["close"], ema):
            if pd.isna(c) or pd.isna(e): out.append("na")
            else: out.append("above" if c > e else "below")
        ema200_lbls[tf] = pd.Series(out, index=df.index)
    asvk_zones = {}
    for tf, df in [("1h", df_1h), ("4h", df_4h)]:
        e3 = asvk_adjusted_rsi(df["close"])
        ab, bl = asvk_dynamic_levels(e3, 200)
        asvk_zones[tf] = asvk_zone_label(e3, ab, bl)
    mh_colors = {}; mh_mfs = {}
    for tf, df in [("1h", df_1h), ("4h", df_4h)]:
        bw2, sma14 = mh_bw2(df)
        mh_colors[tf] = mh_color_label(bw2, sma14)
        mh_mfs[tf] = money_flow_ha(df)

    print("[INFO] collect zones")
    fvgs_1d = collect_fvgs(df_1d, df_1d["atr14"], "1d")
    fvgs_12h = collect_fvgs(df_12h, df_12h["atr14"], "12h")
    obs_6h = collect_obs(df_6h, df_6h["atr14"], "6h")
    obs_4h = collect_obs(df_4h, df_4h["atr14"], "4h")
    obs_2h = collect_obs(df_2h, df_2h["atr14"], "2h")
    obs_1h = collect_obs(df_1h, df_1h["atr14"], "1h")
    fvgs_15m = collect_fvgs(df_15m, df_15m["atr14"], "15m")

    print("[INFO] STRICT-L1 detect 1.1.4 (8 chains)")
    all_setups = []
    for top_tf, top_zones in [("1d", fvgs_1d), ("12h", fvgs_12h)]:
        for macro_tf, macro_zones in [("4h", obs_4h), ("6h", obs_6h)]:
            for mid_tf, mid_zones in [("1h", obs_1h), ("2h", obs_2h)]:
                chains = detect_114_strict(top_zones, macro_zones, mid_zones,
                                            fvgs_15m, top_tf, macro_tf, mid_tf, "15m")
                all_setups.extend(chains)
    seen = set(); unique = []
    for s in all_setups:
        key = (s["signal_time"], s["direction"], round(s["fvg_b"], 2), round(s["fvg_t"], 2))
        if key in seen: continue
        seen.add(key); unique.append(s)
    print(f"  total chains: {len(all_setups)}, deduped: {len(unique)}")

    swept_setups = []
    for s in unique:
        sw = check_swept(s, df_1h, df_2h)
        if sw is None: continue
        if sw: swept_setups.append(s)
    print(f"  SWEPT-filtered: {len(swept_setups)} ({len(swept_setups)/max(len(unique),1)*100:.0f}%)")

    # ============================================================
    print(f"\n{'='*70}\nPHASE A: BASELINES (RR=1.8)")
    print(f"{'='*70}")
    print("\n  ALL (no SWEPT):")
    df_all = evaluate(unique, RR, df_1m)
    base_all = report("ALL", df_all)
    print("\n  SWEPT:")
    df_swept = evaluate(swept_setups, RR, df_1m)
    base_swept = report("SWEPT", df_swept)

    print("\n  SWEPT, RR sweep:")
    swept_rr_results = {}
    for rr in [1.0, 1.5, 1.8, 2.0, 2.5]:
        df_e = evaluate(swept_setups, rr, df_1m)
        r = report(f"SWEPT RR={rr}", df_e)
        if r: swept_rr_results[rr] = r

    # use better baseline (SWEPT vs ALL)
    if base_swept and base_all and base_swept[0] >= base_all[0]:
        cache = swept_setups
        df_base = df_swept
        base_label = "SWEPT"
    else:
        cache = unique
        df_base = df_all
        base_label = "ALL"
    closed = df_base[df_base["outcome"].isin(["win", "loss"])].copy()
    base_wr = (closed["R"] > 0).mean() * 100 if len(closed) else 0
    base_R = closed["R"].sum()
    print(f"\n  -> USE {base_label} for forensic: WR={base_wr:.1f}%  total={base_R:+.1f}R  n={len(closed)}")

    # ============================================================
    print(f"\n[PHASE B] features for {len(closed)} closed trades")
    feat_rows = []
    for _, r in closed.iterrows():
        sd = {"signal_time": r["signal_time"], "direction": r["direction"],
               "fvg_b": r["fvg_b"], "fvg_t": r["fvg_t"],
               "obh_b": r["obh_b"], "obh_t": r["obh_t"]}
        f = extract_features(sd, r["entry"], hull_lbls, ema200_lbls,
                              asvk_zones, mh_colors, mh_mfs, df_1d)
        feat_rows.append(f)
    feats = pd.DataFrame(feat_rows, index=closed.index)
    closed = pd.concat([closed, feats], axis=1)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_out = OUT_DIR / f"etap53_114_strict_{base_label}_features.csv"
    closed.to_csv(csv_out, index=False, encoding="utf-8-sig")
    print(f"  CSV: {csv_out}")

    # ============================================================
    print(f"\n{'='*70}\nPHASE C: PER-FEATURE SEGMENTS  (baseline {base_wr:.1f}% / {base_R:+.1f}R)")
    print(f"{'='*70}")
    for feat_col in ["direction", "session", "weekday",
                       "ema200_15m_align", "ema200_1h_align",
                       "ema200_4h_align", "ema200_1d_align",
                       "asvk_1h_zone", "asvk_4h_zone",
                       "mh_1h_color_align", "mh_4h_color_align",
                       "mh_1h_mf_align", "mh_4h_mf_align",
                       "do_match", "fvg_w_bin", "ob_depth_bin"]:
        report_segment(closed, feat_col, base_wr, base_R)

    print(f"\n--- Hull sweep ---")
    for hull_key in sorted(hull_lbls.keys()):
        report_segment(closed, f"hull_{hull_key}_align", base_wr, base_R)

    # ============================================================
    print(f"\n{'='*70}\nPHASE D: TOP SINGLE FILTERS")
    print(f"{'='*70}\n")
    candidate_filters = []
    # Hull all variants
    for k in sorted(hull_lbls.keys()):
        candidate_filters.append((f"hull_{k} aligned", closed[f"hull_{k}_align"] == "aligned"))
    candidate_filters += [
        ("ema200_15m aligned", closed["ema200_15m_align"] == "aligned"),
        ("ema200_1h aligned", closed["ema200_1h_align"] == "aligned"),
        ("ema200_4h aligned", closed["ema200_4h_align"] == "aligned"),
        ("ema200_1d aligned", closed["ema200_1d_align"] == "aligned"),
        ("mh_1h color aligned", closed["mh_1h_color_align"] == "aligned"),
        ("mh_4h color aligned", closed["mh_4h_color_align"] == "aligned"),
        ("mh_4h MF aligned", closed["mh_4h_mf_align"] == "aligned"),
        ("session london+ny", closed["session"].isin(["london", "ny"])),
        ("session ny only", closed["session"] == "ny"),
        ("exclude Sunday", closed["weekday"] != "Sun"),
        ("exclude Friday", closed["weekday"] != "Fri"),
        ("LONG only", closed["direction"] == "LONG"),
        ("SHORT only", closed["direction"] == "SHORT"),
        ("OB depth medium", closed["ob_depth_bin"] == "medium"),
        ("OB depth small", closed["ob_depth_bin"] == "small"),
        ("FVG w small", closed["fvg_w_bin"] == "small"),
        ("asvk_1h not red", closed["asvk_1h_zone"] != "red"),
        ("asvk_4h not extreme", ~closed["asvk_4h_zone"].isin(["red", "green"])),
        ("do_match aligned", closed["do_match"] == "aligned"),
    ]
    results = []
    for name, mask in candidate_filters:
        r = evaluate_filter(closed, name, mask, base_wr, base_R)
        if r: results.append(r)

    print(f"\n--- TOP by total_R (winners beating baseline {base_R:+.1f}R) ---")
    sorted_r = sorted(results, key=lambda x: x["total_R"], reverse=True)
    for r in sorted_r[:12]:
        flag = "" if r["bad_yrs"] == 0 else f" (bad={r['bad_yrs']})"
        beats = " WIN" if r["total_R"] > base_R else ""
        print(f"  {r['name']:<32} n={r['n']:>4} WR={r['wr']:5.1f}% "
              f"total={r['total_R']:+6.1f}R R/tr={r['rt']:+.3f}{flag}{beats}")

    # ============================================================
    print(f"\n{'='*70}\nPHASE E: COMBOS")
    print(f"{'='*70}\n")
    combo_filters = [
        ("LONG + ema200_4h aligned",
            (closed["direction"] == "LONG") & (closed["ema200_4h_align"] == "aligned")),
        ("LONG + hull_4h_L78 aligned",
            (closed["direction"] == "LONG") & (closed["hull_4h_L78_align"] == "aligned")),
        ("LONG + hull_12h_L78 aligned",
            (closed["direction"] == "LONG") & (closed["hull_12h_L78_align"] == "aligned")),
        ("LONG + ema200_1h + ema200_4h",
            (closed["direction"] == "LONG") &
            (closed["ema200_1h_align"] == "aligned") &
            (closed["ema200_4h_align"] == "aligned")),
        ("hull_4h_L78 + ema200_4h",
            (closed["hull_4h_L78_align"] == "aligned") &
            (closed["ema200_4h_align"] == "aligned")),
        ("hull_12h_L78 + ema200_4h",
            (closed["hull_12h_L78_align"] == "aligned") &
            (closed["ema200_4h_align"] == "aligned")),
        ("LONG + hull_4h_L78 + ema200_4h",
            (closed["direction"] == "LONG") &
            (closed["hull_4h_L78_align"] == "aligned") &
            (closed["ema200_4h_align"] == "aligned")),
        ("- Sunday + ema200_4h aligned",
            (closed["weekday"] != "Sun") &
            (closed["ema200_4h_align"] == "aligned")),
        ("LONG + session NY",
            (closed["direction"] == "LONG") & (closed["session"] == "ny")),
    ]
    combo_results = []
    for name, mask in combo_filters:
        r = evaluate_filter(closed, name, mask, base_wr, base_R)
        if r: combo_results.append(r)

    print(f"\n--- BEST combos sorted by total_R ---")
    all_r = sorted(combo_results + results, key=lambda x: x["total_R"], reverse=True)
    for r in all_r[:8]:
        flag = "" if r["bad_yrs"] == 0 else f" (bad={r['bad_yrs']}/{r['n_yrs']})"
        print(f"  {r['name']:<40} n={r['n']:>4} WR={r['wr']:5.1f}% "
              f"total={r['total_R']:+6.1f}R{flag}")

    # ============================================================
    print(f"\n{'='*70}\nFINAL: variants beating baseline AND 0 bad years")
    print(f"{'='*70}")
    print(f"\n  Baseline: {base_label} RR={RR} -> {base_R:+.1f}R, WR={base_wr:.1f}%, n={len(closed)}\n")
    winners = [r for r in (results + combo_results)
                if r["total_R"] > base_R and r["bad_yrs"] == 0]
    if winners:
        for r in sorted(winners, key=lambda x: x["total_R"], reverse=True):
            print(f"  {r['name']:<40} n={r['n']:>4} total={r['total_R']:+.1f}R "
                  f"(d={r['total_R']-base_R:+.1f})")
    else:
        print(f"  NONE - baseline already optimal")

    print(f"\n[TIME] {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
