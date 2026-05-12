"""Этап 35: Forensic-анализ Strategy 1.1.1 — почему 53.8% WR / +20R.

Берём 446 deduped setups из etap_34, для каждого считаем фичи на signal_time:
  - Hull MA trend (HMA len=78) на 1d / 4h / 1h
  - ASVK Custom RSI ema_3 zone на 1h: red/yellow_OB/neutral/yellow_OS/green
  - Money Hands bw2 color на 1h: green/grey-from-green/red/grey-from-red
  - Pro-trend filter: close vs EMA200 на entry_tf (15m), c2_tf (1h)
  - ICT: hour-of-day (UTC), weekday, daily-open premium/discount

Затем сегментируем wins vs losses по каждой фиче; ищем паттерны
которые отделяют победителей.

Финал — собираем filter из топ-фич, re-backtest 1.1.1 + filter
и сравниваем с baseline (RR=1.0 +20R, RR=1.5 -35R).
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

from pathlib import Path
import time
import numpy as np
import pandas as pd

from data_manager import load_df
from strategies.strategy_1_1_1 import detect_ob_pair, detect_fvg

SYMBOL = "BTCUSDT"
START_DATE = "2020-01-01"
MIN_SL_PCT = 1.0
SL_BUF_ATR = 0.3
ENTRY_PCT = 0.5
RR_BASE = 1.0  # for trade outcomes
RR_TARGET = 1.5  # for filter validation (need to rescue this)

LIFE_DAYS = {"1d": 14, "12h": 7, "4h": 3, "6h": 4,
              "1h": 1, "2h": 1.5, "15m": 0.5, "20m": 0.5}
TF_HOURS = {"1d": 24, "12h": 12, "6h": 6, "4h": 4,
             "2h": 2, "1h": 1, "20m": 1/3, "15m": 0.25}

OUT_DIR = Path("research/elements_study/output")


# ---------- math primitives ----------

def compute_atr(df, period=14):
    high = df["high"]; low = df["low"]; pc = df["close"].shift(1)
    tr = pd.concat([(high-low),(high-pc).abs(),(low-pc).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def wma_fast(arr: np.ndarray, period: int) -> np.ndarray:
    """Convolution-based WMA. weights = 1, 2, ..., period."""
    period = max(int(period), 1)
    weights = np.arange(1, period + 1, dtype=float)
    weights /= weights.sum()
    out = np.full_like(arr, np.nan, dtype=float)
    if len(arr) < period:
        return out
    valid = np.convolve(arr, weights[::-1], mode="valid")
    out[period - 1:] = valid
    return out


def ema_fast(arr: np.ndarray, period: int) -> np.ndarray:
    period = max(int(period), 1)
    return pd.Series(arr).ewm(span=period, adjust=False).mean().to_numpy()


def hull_ma(close: pd.Series, length: int) -> pd.Series:
    """HMA = WMA(2*WMA(close, n/2) - WMA(close, n), round(sqrt(n)))."""
    arr = close.to_numpy(dtype=float)
    half = max(int(length / 2), 1)
    sqrt_len = max(int(round(np.sqrt(length))), 1)
    raw = 2.0 * wma_fast(arr, half) - wma_fast(arr, length)
    hull = wma_fast(np.where(np.isnan(raw), 0.0, raw), sqrt_len)
    hull[:length + sqrt_len] = np.nan
    return pd.Series(hull, index=close.index)


def rsi_wilder(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def asvk_adjusted_rsi(close: pd.Series) -> pd.Series:
    rsi = rsi_wilder(close, 14)
    ema_for_coef = rsi.ewm(span=5, adjust=False).mean()
    coef = pd.Series(np.where(rsi >= 50, 1.2, 0.8), index=rsi.index)
    coefficient = (rsi * coef) / ema_for_coef.replace(0, np.nan)
    adj = rsi * coefficient
    return adj.ewm(span=5, adjust=False).mean()


def asvk_dynamic_levels(ema_3: pd.Series, lookback: int = 200):
    """Vectorized dynamic above/below levels."""
    n = len(ema_3)
    above = np.full(n, np.nan)
    below = np.full(n, np.nan)
    arr = ema_3.to_numpy()
    for i in range(lookback - 1, n):
        win = arr[i - lookback + 1: i + 1]
        win = win[~np.isnan(win)]
        if len(win) < 10: continue
        # above
        m = win > 50
        z = m.sum()
        if z > 0:
            y = win[m].mean()
            c1 = 100 / y; c2 = 50 / y; c3 = c1 - c2
            c4 = (c3 / lookback) * z; c5 = c4 + c3
            above[i] = c5 * y
        # below
        m = win < 50
        z = m.sum()
        if z > 0:
            y = win[m].mean()
            c1 = 50 / y; c2 = 1 / y; c3 = c1 - c2
            c4 = (c3 / lookback) * z; c5 = c4 + c3
            below[i] = 100 - (c5 * y)
    return (pd.Series(above, index=ema_3.index),
            pd.Series(below, index=ema_3.index))


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


def money_hands_bw2(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Возвращает bw2, bw2_sma14."""
    hlc3 = (df["high"] + df["low"] + df["close"]) / 3
    esa = hlc3.ewm(span=9, adjust=False).mean()
    d = (hlc3 - esa).abs().ewm(span=9, adjust=False).mean()
    ci = (hlc3 - esa) / (0.015 * d.replace(0, np.nan))
    wt1 = ci.ewm(span=12, adjust=False).mean()
    wt2 = wt1.rolling(4, min_periods=4).mean()
    sma14 = wt2.rolling(14, min_periods=14).mean()
    return wt2, sma14


def money_flow_ha(df: pd.DataFrame) -> pd.Series:
    ha_o, ha_h, ha_l, ha_c = heikin_ashi(df["open"], df["high"], df["low"], df["close"])
    rng = (ha_h - ha_l).replace(0, np.nan)
    raw = ((ha_c - ha_o) / rng) * 200
    return raw.rolling(60, min_periods=60).mean() - 2.25


# ---------- 1.1.1 detector (same as etap_34) ----------

class FastSim:
    def __init__(self, df_1m):
        self.ts = df_1m.index.values
        self.high = df_1m["high"].to_numpy(dtype=float)
        self.low = df_1m["low"].to_numpy(dtype=float)

    def simulate(self, direction, entry, sl, tp, start_time, timeout_days):
        end_time = start_time + pd.Timedelta(days=timeout_days)
        i0 = np.searchsorted(self.ts, np.datetime64(
            start_time.tz_localize(None) if start_time.tz else start_time))
        i1 = np.searchsorted(self.ts, np.datetime64(
            end_time.tz_localize(None) if end_time.tz else end_time))
        if i1 <= i0: return ("no_data", 0.0)
        h = self.high[i0:i1]; l = self.low[i0:i1]
        risk = abs(entry - sl)
        if risk <= 0: return ("invalid", 0.0)
        if direction == "LONG":
            act_mask = l <= entry
            if not act_mask.any(): return ("not_filled", 0.0)
            act_idx = int(np.argmax(act_mask))
            h2 = h[act_idx:]; l2 = l[act_idx:]
            sl_hits = l2 <= sl; tp_hits = h2 >= tp
            sl_idx = int(np.argmax(sl_hits)) if sl_hits.any() else len(h2)
            tp_idx = int(np.argmax(tp_hits)) if tp_hits.any() else len(h2)
            if sl_idx == len(h2) and tp_idx == len(h2): return ("open", 0.0)
            if sl_idx <= tp_idx: return ("loss", -1.0)
            return ("win", (tp - entry) / risk)
        else:
            act_mask = h >= entry
            if not act_mask.any(): return ("not_filled", 0.0)
            act_idx = int(np.argmax(act_mask))
            h2 = h[act_idx:]; l2 = l[act_idx:]
            sl_hits = h2 >= sl; tp_hits = l2 <= tp
            sl_idx = int(np.argmax(sl_hits)) if sl_hits.any() else len(h2)
            tp_idx = int(np.argmax(tp_hits)) if tp_hits.any() else len(h2)
            if sl_idx == len(h2) and tp_idx == len(h2): return ("open", 0.0)
            if sl_idx <= tp_idx: return ("loss", -1.0)
            return ("win", (entry - tp) / risk)


def collect_obs(df, atr_series, tf_label):
    out = []
    for idx in range(2, len(df) - 1):
        ob = detect_ob_pair(df, idx)
        if ob is None: continue
        atr = float(atr_series.iloc[idx])
        if pd.isna(atr) or atr <= 0: continue
        out.append({"kind":"OB","tf":tf_label,"direction":ob.direction,
                    "bottom":ob.bottom,"top":ob.top,"atr":atr,
                    "time":ob.cur_time,"idx":idx})
    return out


def collect_fvgs(df, atr_series, tf_label):
    out = []
    for idx in range(2, len(df) - 1):
        f = detect_fvg(df, idx)
        if f is None: continue
        atr = float(atr_series.iloc[idx])
        if pd.isna(atr) or atr <= 0: continue
        out.append({"kind":"FVG","tf":tf_label,"direction":f.direction,
                    "bottom":f.bottom,"top":f.top,"atr":atr,
                    "time":f.c2_time,"idx":idx})
    return out


def zones_overlap(b1,t1,b2,t2):
    return not (t1 < b2 or t2 < b1)


def build_setup(trig, entry_pct, sl_buf, min_sl_pct, rr):
    zb=trig["bottom"]; zt=trig["top"]; atr=trig["atr"]
    direction=trig["direction"]; size = zt - zb
    if direction == "LONG":
        entry = zb + entry_pct * size
        atr_sl = zb - sl_buf * atr
        sl = min(atr_sl, entry - entry * min_sl_pct / 100)
    else:
        entry = zt - entry_pct * size
        atr_sl = zt + sl_buf * atr
        sl = max(atr_sl, entry + entry * min_sl_pct / 100)
    risk = abs(entry - sl)
    if risk <= 0: return None
    if direction == "LONG":
        tp = entry + rr * risk
    else:
        tp = entry - rr * risk
    return entry, sl, tp


def detect_111_chain_setups(obs_top, fvgs_macro, obs_mid, fvgs_entry,
                             top_tf, macro_tf, mid_tf, entry_tf):
    setups = []
    top_tf_td = pd.Timedelta(hours=TF_HOURS[top_tf])
    macro_tf_td = pd.Timedelta(hours=TF_HOURS[macro_tf])
    mid_tf_td = pd.Timedelta(hours=TF_HOURS[mid_tf])
    top_life = pd.Timedelta(days=LIFE_DAYS[top_tf])
    macro_life = pd.Timedelta(days=LIFE_DAYS[macro_tf])
    mid_life = pd.Timedelta(days=LIFE_DAYS[mid_tf])

    fvgs_macro_sorted = sorted(fvgs_macro, key=lambda x: x["time"])
    obs_mid_sorted = sorted(obs_mid, key=lambda x: x["time"])
    fvgs_entry_sorted = sorted(fvgs_entry, key=lambda x: x["time"])

    fvgs_macro_times = np.array([np.datetime64(
        z["time"].tz_localize(None) if z["time"].tz else z["time"])
        for z in fvgs_macro_sorted])
    obs_mid_times = np.array([np.datetime64(
        z["time"].tz_localize(None) if z["time"].tz else z["time"])
        for z in obs_mid_sorted])
    fvgs_entry_times = np.array([np.datetime64(
        z["time"].tz_localize(None) if z["time"].tz else z["time"])
        for z in fvgs_entry_sorted])

    for ob_top in obs_top:
        l1_confirm = ob_top["time"] + top_tf_td
        l1_end = ob_top["time"] + top_life
        if l1_end <= l1_confirm: continue
        i0 = np.searchsorted(fvgs_macro_times, np.datetime64(
            l1_confirm.tz_localize(None) if l1_confirm.tz else l1_confirm),
            side="right")
        i1 = np.searchsorted(fvgs_macro_times, np.datetime64(
            l1_end.tz_localize(None) if l1_end.tz else l1_end),
            side="right")
        for mi in range(i0, i1):
            f_macro = fvgs_macro_sorted[mi]
            if f_macro["direction"] != ob_top["direction"]: continue
            if not zones_overlap(f_macro["bottom"], f_macro["top"],
                                  ob_top["bottom"], ob_top["top"]): continue
            l2_confirm = f_macro["time"] + macro_tf_td
            l2_end = f_macro["time"] + macro_life
            if l2_end <= l2_confirm: continue
            j0 = np.searchsorted(obs_mid_times, np.datetime64(
                l2_confirm.tz_localize(None) if l2_confirm.tz else l2_confirm),
                side="right")
            j1 = np.searchsorted(obs_mid_times, np.datetime64(
                l2_end.tz_localize(None) if l2_end.tz else l2_end), side="right")
            ob_mid_found = None
            for oj in range(j0, j1):
                ob_mid = obs_mid_sorted[oj]
                if ob_mid["direction"] != ob_top["direction"]: continue
                if not zones_overlap(ob_mid["bottom"], ob_mid["top"],
                                      ob_top["bottom"], ob_top["top"]): continue
                if not zones_overlap(ob_mid["bottom"], ob_mid["top"],
                                      f_macro["bottom"], f_macro["top"]): continue
                ob_mid_found = ob_mid; break
            if ob_mid_found is None: continue
            l3_confirm = ob_mid_found["time"] + mid_tf_td
            l3_end = ob_mid_found["time"] + mid_life
            if l3_end <= l3_confirm: continue
            k0 = np.searchsorted(fvgs_entry_times, np.datetime64(
                l3_confirm.tz_localize(None) if l3_confirm.tz else l3_confirm),
                side="right")
            k1 = np.searchsorted(fvgs_entry_times, np.datetime64(
                l3_end.tz_localize(None) if l3_end.tz else l3_end), side="right")
            fvg_entry_found = None
            for ek in range(k0, k1):
                f_entry = fvgs_entry_sorted[ek]
                if f_entry["direction"] != ob_top["direction"]: continue
                if not zones_overlap(f_entry["bottom"], f_entry["top"],
                                      ob_mid_found["bottom"],
                                      ob_mid_found["top"]): continue
                fvg_entry_found = f_entry; break
            if fvg_entry_found is None: continue
            setups.append({
                "anchor_time": ob_top["time"],
                "anchor_tf": top_tf,
                "macro_tf": macro_tf,
                "mid_tf": mid_tf,
                "trigger_time": fvg_entry_found["time"],
                "trigger": fvg_entry_found,
                "year": fvg_entry_found["time"].year,
            })
            break
    return setups


# ---------- feature lookup ----------

def asof_value(s: pd.Series, ts: pd.Timestamp):
    """Last non-NaN value at or before ts. Returns NaN if no data."""
    if s.empty: return np.nan
    idx = s.index.searchsorted(ts, side="right") - 1
    if idx < 0: return np.nan
    val = s.iloc[idx]
    return float(val) if pd.notna(val) else np.nan


def asvk_zone_label(ema_3, above, below, ts):
    e = asof_value(ema_3, ts)
    a = asof_value(above, ts)
    b = asof_value(below, ts)
    if np.isnan(e) or np.isnan(a) or np.isnan(b): return "na"
    if e > a: return "red"          # OB extension
    if e > 50 + (a - 50) * 0.5: return "yellow_OB"  # near OB
    if e < b: return "green"        # OS extension
    if e < 50 - (50 - b) * 0.5: return "yellow_OS"
    return "neutral"


def mh_color_label(bw2, sma14, ts):
    v = asof_value(bw2, ts)
    s = asof_value(sma14, ts)
    if np.isnan(v) or np.isnan(s): return "na"
    if v > 0:
        return "green" if v >= s else "grey_from_green"
    if v < 0:
        return "red" if v <= s else "grey_from_red"
    return "neutral"


def hull_trend(close, hull, ts):
    """close > hull[-2] → up, иначе down."""
    c = asof_value(close, ts)
    # Pine SHULL = HULL[2] — on bar `i` сравниваем close[i] vs hull[i-2]
    idx = hull.index.searchsorted(ts, side="right") - 1
    if idx < 2 or np.isnan(c): return "na"
    h2 = hull.iloc[idx - 2]
    if pd.isna(h2): return "na"
    return "up" if c > h2 else "down"


def ema_trend(close, ema_s, ts):
    c = asof_value(close, ts); e = asof_value(ema_s, ts)
    if np.isnan(c) or np.isnan(e): return "na"
    return "above" if c > e else "below"


def daily_open_pos(df_1d, ts, entry_price):
    """premium / discount / mid relative to current daily open."""
    idx = df_1d.index.searchsorted(ts, side="right") - 1
    if idx < 0: return "na"
    do = df_1d["open"].iloc[idx]
    dh = df_1d["high"].iloc[idx]; dl = df_1d["low"].iloc[idx]
    if dh == dl: return "na"
    pos = (entry_price - dl) / (dh - dl)
    if entry_price > do:
        return "premium"
    elif entry_price < do:
        return "discount"
    return "mid"


# ---------- analysis ----------

def segment(trades_df: pd.DataFrame, feature: str):
    g = trades_df.groupby(feature).agg(
        n=("R", "size"),
        wins=("outcome", lambda x: (x == "win").sum()),
        total_R=("R", "sum"),
        avg_R=("R", "mean"),
    )
    g["WR"] = g["wins"] / g["n"] * 100
    g = g.sort_values("WR", ascending=False)
    return g


def report_segment(label, trades_df, feature, baseline_wr, baseline_R):
    print(f"\n=== Feature: {feature} ===")
    g = segment(trades_df, feature)
    print(f"  baseline (all): WR={baseline_wr:.1f}%, total={baseline_R:+.1f}R, n={len(trades_df)}")
    for cat, row in g.iterrows():
        delta_wr = row["WR"] - baseline_wr
        flag = " ***" if (row["WR"] - baseline_wr >= 5 and row["n"] >= 30) else ""
        flag += " !" if (row["WR"] - baseline_wr <= -5 and row["n"] >= 30) else ""
        print(f"  {cat!s:<25} n={int(row['n']):>4} WR={row['WR']:5.1f}% (d={delta_wr:+5.1f}pp) "
                f"total={row['total_R']:+6.1f}R  avg_R={row['avg_R']:+.3f}{flag}")


def main():
    t0 = time.time()
    print(f"[INFO] loading data {START_DATE}+")
    tfs = ["1d", "12h", "6h", "4h", "2h", "1h", "15m"]
    dfs = {}
    for tf in tfs:
        df = load_df(SYMBOL, tf)
        df = df[df.index >= pd.Timestamp(START_DATE, tz="UTC")].copy()
        df["atr14"] = compute_atr(df, 14)
        df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
        dfs[tf] = df
    df_1m = load_df(SYMBOL, "1m")
    df_1m = df_1m[df_1m.index >= pd.Timestamp(START_DATE, tz="UTC")]
    sim = FastSim(df_1m)
    years = (dfs["1d"].index[-1] - dfs["1d"].index[0]).days / 365
    print(f"  years: {years:.2f}")

    print("\n[INFO] computing indicators")
    # Hull MA(78) on 1d, 4h, 1h
    hull = {}
    for tf in ["1d", "4h", "1h"]:
        hull[tf] = hull_ma(dfs[tf]["close"], 78)
    # ASVK on 1h
    rsi_1h = asvk_adjusted_rsi(dfs["1h"]["close"])
    above_1h, below_1h = asvk_dynamic_levels(rsi_1h, 200)
    # Money Hands on 1h
    mh_bw2_1h, mh_sma14_1h = money_hands_bw2(dfs["1h"])
    mh_mf_1h = money_flow_ha(dfs["1h"])
    print(f"  Hull on 1d/4h/1h, ASVK on 1h, MH on 1h done")

    print("\n[INFO] collecting zones")
    obs = {}; fvgs = {}
    for tf in ["1d", "12h", "2h", "1h"]:
        obs[tf] = collect_obs(dfs[tf], dfs[tf]["atr14"], tf)
    for tf in ["6h", "4h", "15m"]:
        fvgs[tf] = collect_fvgs(dfs[tf], dfs[tf]["atr14"], tf)

    # detect 1.1.1 chains
    print("\n[INFO] building 1.1.1 chains")
    all_setups = []
    for top_tf in ["1d", "12h"]:
        for macro_tf in ["4h", "6h"]:
            for mid_tf in ["1h", "2h"]:
                setups = detect_111_chain_setups(
                    obs[top_tf], fvgs[macro_tf], obs[mid_tf], fvgs["15m"],
                    top_tf, macro_tf, mid_tf, "15m")
                all_setups.extend(setups)
    seen = set(); unique = []
    for s in all_setups:
        key = (s["anchor_time"], s["trigger_time"], s["trigger"]["direction"])
        if key in seen: continue
        seen.add(key); unique.append(s)
    print(f"  setups: {len(unique)}")

    # evaluate at RR=1.0 to get outcomes
    print(f"\n[INFO] evaluating at RR={RR_BASE}")
    rows = []
    for s in unique:
        t = s["trigger"]
        tup = build_setup(t, ENTRY_PCT, SL_BUF_ATR, MIN_SL_PCT, RR_BASE)
        if tup is None: continue
        entry, sl, tp = tup
        start = t["time"] + pd.Timedelta(hours=TF_HOURS["15m"])
        outcome, R = sim.simulate(t["direction"], entry, sl, tp, start,
                                    timeout_days=LIFE_DAYS["15m"])
        rows.append({
            "trigger_time": t["time"], "direction": t["direction"],
            "entry": entry, "sl": sl, "tp": tp,
            "outcome": outcome, "R": R,
            "year": s["year"],
            "anchor_tf": s["anchor_tf"], "macro_tf": s["macro_tf"],
            "mid_tf": s["mid_tf"],
        })
    trades = pd.DataFrame(rows)
    closed = trades[trades["outcome"].isin(["win", "loss"])].copy()
    base_wr = (closed["outcome"] == "win").mean() * 100
    base_R = closed["R"].sum()
    print(f"  total: {len(trades)}, closed: {len(closed)}, "
          f"WR={base_wr:.1f}%, total_R={base_R:+.1f}")

    # ----- compute features for each closed trade -----
    print(f"\n[INFO] computing features per trade")
    feats = []
    df_1h = dfs["1h"]; df_4h = dfs["4h"]; df_1d = dfs["1d"]
    df_15m = dfs["15m"]
    for _, r in closed.iterrows():
        ts = r["trigger_time"]
        f = {
            # Hull trend on multiple TFs
            "hull_1d": hull_trend(df_1d["close"], hull["1d"], ts),
            "hull_4h": hull_trend(df_4h["close"], hull["4h"], ts),
            "hull_1h": hull_trend(df_1h["close"], hull["1h"], ts),
            # ASVK RSI zone on 1h
            "asvk_zone": asvk_zone_label(rsi_1h, above_1h, below_1h, ts),
            # MH bw2 color on 1h
            "mh_color": mh_color_label(mh_bw2_1h, mh_sma14_1h, ts),
            "mh_mf_sign": "pos" if asof_value(mh_mf_1h, ts) > 0 else "neg",
            # Pro-trend EMA200 on entry_tf and 1h
            "ema200_1h": ema_trend(df_1h["close"], df_1h["ema200"], ts),
            "ema200_15m": ema_trend(df_15m["close"], df_15m["ema200"], ts),
            "ema200_4h": ema_trend(df_4h["close"], df_4h["ema200"], ts),
            # ICT
            "hour": int(ts.hour),
            "weekday": ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"][ts.weekday()],
            "is_weekend": "weekend" if ts.weekday() >= 5 else "weekday",
            "ict_session": ("asia" if ts.hour < 7
                            else "london" if ts.hour < 12
                            else "ny" if ts.hour < 17
                            else "off-hours"),
            "do_pos": daily_open_pos(df_1d, ts, r["entry"]),
        }
        feats.append(f)
    feats_df = pd.DataFrame(feats, index=closed.index)
    closed = pd.concat([closed, feats_df], axis=1)

    # add aligned-with-direction flags
    def aligned(direction, trend_label, up_label="up", down_label="down"):
        if trend_label == "na": return "na"
        if direction == "LONG":
            return "aligned" if trend_label == up_label else "counter"
        else:
            return "aligned" if trend_label == down_label else "counter"

    closed["hull_1d_align"] = closed.apply(
        lambda r: aligned(r["direction"], r["hull_1d"]), axis=1)
    closed["hull_4h_align"] = closed.apply(
        lambda r: aligned(r["direction"], r["hull_4h"]), axis=1)
    closed["hull_1h_align"] = closed.apply(
        lambda r: aligned(r["direction"], r["hull_1h"]), axis=1)
    closed["ema200_1h_align"] = closed.apply(
        lambda r: aligned(r["direction"], r["ema200_1h"], "above", "below"), axis=1)
    closed["ema200_15m_align"] = closed.apply(
        lambda r: aligned(r["direction"], r["ema200_15m"], "above", "below"), axis=1)
    closed["ema200_4h_align"] = closed.apply(
        lambda r: aligned(r["direction"], r["ema200_4h"], "above", "below"), axis=1)
    # MH color → bullish/bearish/neutral relative to direction
    def mh_aligned(direction, color):
        if color == "na": return "na"
        bullish = color in ("green", "grey_from_red")
        bearish = color in ("red", "grey_from_green")
        if direction == "LONG":
            if bullish: return "aligned"
            if bearish: return "counter"
        else:
            if bearish: return "aligned"
            if bullish: return "counter"
        return "neutral"
    closed["mh_align"] = closed.apply(
        lambda r: mh_aligned(r["direction"], r["mh_color"]), axis=1)
    # MH MF sign aligned
    closed["mh_mf_align"] = closed.apply(
        lambda r: aligned(r["direction"], r["mh_mf_sign"], "pos", "neg"), axis=1)

    # Save full trades CSV
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_csv = OUT_DIR / "etap35_trades_111_features.csv"
    closed.to_csv(out_csv, index=False)
    print(f"  trades CSV: {out_csv}")

    # ----- SEGMENT REPORT -----
    print(f"\n{'='*70}\nSEGMENTATION (RR={RR_BASE} baseline {base_wr:.1f}% / {base_R:+.1f}R)")
    print(f"{'='*70}")
    for feature in [
        "direction", "year", "anchor_tf", "macro_tf", "mid_tf",
        "hull_1d_align", "hull_4h_align", "hull_1h_align",
        "ema200_4h_align", "ema200_1h_align", "ema200_15m_align",
        "asvk_zone", "mh_align", "mh_mf_align",
        "hour", "weekday", "is_weekend", "ict_session", "do_pos",
    ]:
        report_segment("", closed, feature, base_wr, base_R)

    # ----- FILTER VALIDATION -----
    print(f"\n{'='*70}\nFILTER CANDIDATES")
    print(f"{'='*70}")

    def evaluate_filter(name, mask, rr_test=[1.0, 1.5, 2.0]):
        kept_closed = closed[mask].copy()
        if len(kept_closed) < 30:
            print(f"  {name}: only n={len(kept_closed)} — skip"); return
        kept_wr = (kept_closed["outcome"] == "win").mean() * 100
        kept_R = kept_closed["R"].sum()
        print(f"\n  Filter: {name}")
        print(f"    keep n={len(kept_closed)}/{len(closed)} ({len(kept_closed)/len(closed)*100:.0f}%)"
              f"  RR=1.0: WR={kept_wr:.1f}% (d={kept_wr-base_wr:+.1f}pp)  total={kept_R:+.1f}R")
        # Re-evaluate at higher RR (need re-sim from setups, not from baseline trades!)
        for rr in rr_test[1:]:
            kept_re = []
            kept_keys = set(zip(kept_closed["trigger_time"], kept_closed["direction"]))
            for s in unique:
                t = s["trigger"]
                key = (t["time"], t["direction"])
                if key not in kept_keys: continue
                tup = build_setup(t, ENTRY_PCT, SL_BUF_ATR, MIN_SL_PCT, rr)
                if tup is None: continue
                entry, sl, tp = tup
                start = t["time"] + pd.Timedelta(hours=TF_HOURS["15m"])
                out, R = sim.simulate(t["direction"], entry, sl, tp, start,
                                        timeout_days=LIFE_DAYS["15m"])
                kept_re.append({"outcome": out, "R": R})
            df_re = pd.DataFrame(kept_re)
            cl_re = df_re[df_re["outcome"].isin(["win", "loss"])]
            if cl_re.empty: continue
            wr_re = (cl_re["outcome"] == "win").mean() * 100
            R_re = cl_re["R"].sum()
            print(f"    RR={rr}: closed={len(cl_re)} WR={wr_re:.1f}% total={R_re:+.1f}R "
                  f"R/tr={cl_re['R'].mean():+.3f}")

    # Best single-feature filters
    evaluate_filter("hull_4h_align == aligned",
                    closed["hull_4h_align"] == "aligned")
    evaluate_filter("hull_1d_align == aligned",
                    closed["hull_1d_align"] == "aligned")
    evaluate_filter("ema200_15m_align == aligned",
                    closed["ema200_15m_align"] == "aligned")
    evaluate_filter("mh_align == aligned",
                    closed["mh_align"] == "aligned")
    evaluate_filter("ict_session in (london, ny)",
                    closed["ict_session"].isin(["london", "ny"]))

    # Combined: all 3 trend filters aligned
    evaluate_filter("hull_4h + hull_1d + ema200_15m (all aligned)",
                    (closed["hull_4h_align"] == "aligned") &
                    (closed["hull_1d_align"] == "aligned") &
                    (closed["ema200_15m_align"] == "aligned"))
    # Hull_4h + MH
    evaluate_filter("hull_4h + mh_align (both aligned)",
                    (closed["hull_4h_align"] == "aligned") &
                    (closed["mh_align"] == "aligned"))
    # Trend + ICT session
    evaluate_filter("hull_4h + ict (london|ny)",
                    (closed["hull_4h_align"] == "aligned") &
                    (closed["ict_session"].isin(["london", "ny"])))
    # Best practical combo
    evaluate_filter("hull_1d + hull_4h + mh (all aligned)",
                    (closed["hull_1d_align"] == "aligned") &
                    (closed["hull_4h_align"] == "aligned") &
                    (closed["mh_align"] == "aligned"))

    # Refined filter exploration after first-pass insights
    print(f"\n{'='*70}\nREFINED FILTER EXPLORATION")
    print(f"{'='*70}")
    evaluate_filter("hull_4h + do_pos == discount",
                    (closed["hull_4h_align"] == "aligned") &
                    (closed["do_pos"] == "discount"))
    evaluate_filter("hull_4h + ema200_15m (both aligned)",
                    (closed["hull_4h_align"] == "aligned") &
                    (closed["ema200_15m_align"] == "aligned"))
    evaluate_filter("hull_4h + mh_mf_align (both aligned)",
                    (closed["hull_4h_align"] == "aligned") &
                    (closed["mh_mf_align"] == "aligned"))
    evaluate_filter("hull_4h + exclude Friday",
                    (closed["hull_4h_align"] == "aligned") &
                    (closed["weekday"] != "Fri"))
    evaluate_filter("hull_4h + asvk_zone NOT yellow_OB",
                    (closed["hull_4h_align"] == "aligned") &
                    (closed["asvk_zone"] != "yellow_OB"))
    # KILLER: hull_4h + ny session (only)
    evaluate_filter("hull_4h + ict==ny",
                    (closed["hull_4h_align"] == "aligned") &
                    (closed["ict_session"] == "ny"))
    # Triple top-features
    evaluate_filter("hull_4h + do_pos==discount + ict in (london, ny)",
                    (closed["hull_4h_align"] == "aligned") &
                    (closed["do_pos"] == "discount") &
                    (closed["ict_session"].isin(["london", "ny"])))
    # Less restrictive: ANY 2 of top features
    closed["score"] = (
        (closed["hull_4h_align"] == "aligned").astype(int) +
        (closed["do_pos"] == "discount").astype(int) +
        (closed["ict_session"].isin(["london", "ny"])).astype(int) +
        (closed["mh_mf_align"] == "aligned").astype(int) +
        (closed["ema200_15m_align"] == "aligned").astype(int)
    )
    print(f"\n  Score distribution (hull_4h+discount+ict+mh_mf+ema200_15m, max=5):")
    for sc in sorted(closed["score"].unique()):
        mask = closed["score"] == sc
        sub = closed[mask]
        wins = (sub["outcome"] == "win").sum()
        wr = wins/len(sub)*100 if len(sub) else 0
        tot = sub["R"].sum()
        print(f"    score={sc}: n={len(sub):>3} WR={wr:5.1f}% total={tot:+6.1f}R")
    evaluate_filter("score >= 3 of top 5 features", closed["score"] >= 3)
    evaluate_filter("score >= 4 of top 5 features", closed["score"] >= 4)

    print(f"\n[TIME] {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
