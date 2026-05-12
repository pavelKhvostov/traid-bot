"""Этап 38: re-audit 1.1.1 с safe HTF lookup (после etap_37 находки).

etap_35 forensic использовал buggy hull_trend_label (тот же bug что в
etap_36 для C2v2). Magnitudes inflated.

Здесь:
  1. Воспроизводим 1.1.1 baseline (etap_34 numbers — без HTF lookup'ов)
  2. Re-run filter combinations с SAFE hull lookup
  3. Сравниваем buggy vs safe
  4. Финальная таблица: какой total R для 1.1.1 с лучшим filter
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
RR_TEST = [1.0, 1.5, 2.0, 2.5]

LIFE_DAYS = {"1d": 14, "12h": 7, "4h": 3, "6h": 4,
              "1h": 1, "2h": 1.5, "15m": 0.5}
TF_HOURS = {"1d": 24, "12h": 12, "6h": 6, "4h": 4,
             "2h": 2, "1h": 1, "15m": 0.25}

OUT_DIR = Path("research/elements_study/output")


# ---------- math ----------

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


def money_flow_ha(df):
    ha_o, ha_h, ha_l, ha_c = heikin_ashi(df["open"], df["high"], df["low"], df["close"])
    rng = (ha_h - ha_l).replace(0, np.nan)
    raw = ((ha_c - ha_o) / rng) * 200
    return raw.rolling(60, min_periods=60).mean() - 2.25


# ---------- 1.1.1 detection (same as etap_34/35) ----------

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


def collect_obs(df, atr, tf):
    out = []
    for idx in range(2, len(df) - 1):
        ob = detect_ob_pair(df, idx)
        if ob is None: continue
        a = float(atr.iloc[idx])
        if pd.isna(a) or a <= 0: continue
        out.append({"time": ob.cur_time, "direction": ob.direction,
                     "bottom": ob.bottom, "top": ob.top, "atr": a, "tf": tf, "idx": idx})
    return out


def collect_fvgs(df, atr, tf):
    out = []
    for idx in range(2, len(df) - 1):
        f = detect_fvg(df, idx)
        if f is None: continue
        a = float(atr.iloc[idx])
        if pd.isna(a) or a <= 0: continue
        out.append({"time": f.c2_time, "direction": f.direction,
                     "bottom": f.bottom, "top": f.top, "atr": a, "tf": tf, "idx": idx})
    return out


def zones_overlap(b1, t1, b2, t2):
    return not (t1 < b2 or t2 < b1)


def build_setup(trig, rr):
    zb=trig["bottom"]; zt=trig["top"]; atr=trig["atr"]
    direction=trig["direction"]; size = zt - zb
    if direction == "LONG":
        entry = zb + ENTRY_PCT * size
        atr_sl = zb - SL_BUF_ATR * atr
        sl = min(atr_sl, entry - entry * MIN_SL_PCT / 100)
    else:
        entry = zt - ENTRY_PCT * size
        atr_sl = zt + SL_BUF_ATR * atr
        sl = max(atr_sl, entry + entry * MIN_SL_PCT / 100)
    risk = abs(entry - sl)
    if risk <= 0: return None
    tp = entry + rr * risk if direction == "LONG" else entry - rr * risk
    return entry, sl, tp


def detect_111_chains(obs_top, fvgs_macro, obs_mid, fvgs_entry,
                       top_tf, macro_tf, mid_tf, entry_tf):
    setups = []
    top_td = pd.Timedelta(hours=TF_HOURS[top_tf])
    macro_td = pd.Timedelta(hours=TF_HOURS[macro_tf])
    mid_td = pd.Timedelta(hours=TF_HOURS[mid_tf])
    top_life = pd.Timedelta(days=LIFE_DAYS[top_tf])
    macro_life = pd.Timedelta(days=LIFE_DAYS[macro_tf])
    mid_life = pd.Timedelta(days=LIFE_DAYS[mid_tf])

    fvgs_macro_sorted = sorted(fvgs_macro, key=lambda x: x["time"])
    obs_mid_sorted = sorted(obs_mid, key=lambda x: x["time"])
    fvgs_entry_sorted = sorted(fvgs_entry, key=lambda x: x["time"])
    fm_times = np.array([np.datetime64(z["time"].tz_localize(None) if z["time"].tz else z["time"])
                          for z in fvgs_macro_sorted])
    om_times = np.array([np.datetime64(z["time"].tz_localize(None) if z["time"].tz else z["time"])
                          for z in obs_mid_sorted])
    fe_times = np.array([np.datetime64(z["time"].tz_localize(None) if z["time"].tz else z["time"])
                          for z in fvgs_entry_sorted])

    for ob_top in obs_top:
        l1c = ob_top["time"] + top_td
        l1e = ob_top["time"] + top_life
        if l1e <= l1c: continue
        i0 = np.searchsorted(fm_times, np.datetime64(
            l1c.tz_localize(None) if l1c.tz else l1c), side="right")
        i1 = np.searchsorted(fm_times, np.datetime64(
            l1e.tz_localize(None) if l1e.tz else l1e), side="right")
        for mi in range(i0, i1):
            f_macro = fvgs_macro_sorted[mi]
            if f_macro["direction"] != ob_top["direction"]: continue
            if not zones_overlap(f_macro["bottom"], f_macro["top"],
                                  ob_top["bottom"], ob_top["top"]): continue
            l2c = f_macro["time"] + macro_td
            l2e = f_macro["time"] + macro_life
            if l2e <= l2c: continue
            j0 = np.searchsorted(om_times, np.datetime64(
                l2c.tz_localize(None) if l2c.tz else l2c), side="right")
            j1 = np.searchsorted(om_times, np.datetime64(
                l2e.tz_localize(None) if l2e.tz else l2e), side="right")
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
            l3c = ob_mid_found["time"] + mid_td
            l3e = ob_mid_found["time"] + mid_life
            if l3e <= l3c: continue
            k0 = np.searchsorted(fe_times, np.datetime64(
                l3c.tz_localize(None) if l3c.tz else l3c), side="right")
            k1 = np.searchsorted(fe_times, np.datetime64(
                l3e.tz_localize(None) if l3e.tz else l3e), side="right")
            fvg_entry_found = None
            for ek in range(k0, k1):
                f_entry = fvgs_entry_sorted[ek]
                if f_entry["direction"] != ob_top["direction"]: continue
                if not zones_overlap(f_entry["bottom"], f_entry["top"],
                                      ob_mid_found["bottom"], ob_mid_found["top"]):
                    continue
                fvg_entry_found = f_entry; break
            if fvg_entry_found is None: continue
            setups.append({
                "anchor_time": ob_top["time"],
                "trigger_time": fvg_entry_found["time"],
                "trigger": fvg_entry_found,
                "year": fvg_entry_found["time"].year,
            })
            break
    return setups


def evaluate(setups, sim, rr):
    rows = []
    for s in setups:
        t = s["trigger"]
        tup = build_setup(t, rr)
        if tup is None: continue
        entry, sl, tp = tup
        start = t["time"] + pd.Timedelta(hours=TF_HOURS["15m"])
        outcome, R = sim.simulate(t["direction"], entry, sl, tp, start,
                                    timeout_days=LIFE_DAYS["15m"])
        rows.append({"trigger_time": t["time"], "direction": t["direction"],
                      "entry": entry, "sl": sl, "tp": tp,
                      "outcome": outcome, "R": R, "year": s["year"]})
    return pd.DataFrame(rows)


# ---------- safe lookups ----------

def asof_value(s, ts):
    if s.empty: return np.nan
    idx = s.index.searchsorted(ts, side="right") - 1
    if idx < 0: return np.nan
    val = s.iloc[idx]
    return float(val) if pd.notna(val) else np.nan


def hull_trend_safe(close, hull, ts):
    """SAFE: use last CLOSED bar (idx-1) and HULL[2] from there."""
    idx = hull.index.searchsorted(ts, side="right") - 1
    if idx < 3: return "na"
    last_closed = idx - 1
    c = close.iloc[last_closed]
    h2 = hull.iloc[last_closed - 2]
    if pd.isna(c) or pd.isna(h2): return "na"
    return "up" if c > h2 else "down"


def ema_trend_safe(close, ema_s, ts):
    """SAFE: last closed bar."""
    idx = close.index.searchsorted(ts, side="right") - 1
    if idx < 1: return "na"
    last_closed = idx - 1
    c = close.iloc[last_closed]; e = ema_s.iloc[last_closed]
    if pd.isna(c) or pd.isna(e): return "na"
    return "above" if c > e else "below"


def mh_mf_safe(mh_mf, ts):
    """Last closed 1h bar."""
    idx = mh_mf.index.searchsorted(ts, side="right") - 1
    if idx < 1: return "na"
    v = mh_mf.iloc[idx - 1]
    if pd.isna(v): return "na"
    return "pos" if v > 0 else "neg"


def daily_open_pos_safe(df_1d, ts, entry):
    """Daily open IS known at start of day, no lookahead concern.
    But to be safe, use last CLOSED 1d bar's open... wait, this requires
    rethinking. The CURRENT day's open is indeed available at intraday ts.
    So this is the one feature where idx (forming bar) is correct.
    """
    idx = df_1d.index.searchsorted(ts, side="right") - 1
    if idx < 0: return "na"
    do = df_1d["open"].iloc[idx]  # current day's open IS available
    if pd.isna(do): return "na"
    if entry > do: return "premium"
    if entry < do: return "discount"
    return "mid"


def aligned(direction, label, up="up", down="down"):
    if label == "na": return "na"
    if direction == "LONG":
        return "aligned" if label == up else "counter"
    return "aligned" if label == down else "counter"


# ---------- main ----------

def main():
    t0 = time.time()
    print(f"[INFO] loading data {START_DATE}+")
    tfs = ["1d", "12h", "4h", "2h", "1h", "15m"]
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

    print("[INFO] computing indicators")
    hull_4h = hull_ma(dfs["4h"]["close"], 78)
    hull_1d = hull_ma(dfs["1d"]["close"], 78)
    mh_mf_1h = money_flow_ha(dfs["1h"])

    print("[INFO] collecting zones")
    obs = {}; fvgs = {}
    for tf in ["1d", "12h", "2h", "1h"]:
        obs[tf] = collect_obs(dfs[tf], dfs[tf]["atr14"], tf)
    for tf in ["4h", "15m"]:
        fvgs[tf] = collect_fvgs(dfs[tf], dfs[tf]["atr14"], tf)

    print("[INFO] building 1.1.1 chains")
    all_setups = []
    for top_tf in ["1d", "12h"]:
        for macro_tf in ["4h"]:  # 6h not collected here for simplicity
            for mid_tf in ["1h", "2h"]:
                ss = detect_111_chains(obs[top_tf], fvgs[macro_tf],
                                        obs[mid_tf], fvgs["15m"],
                                        top_tf, macro_tf, mid_tf, "15m")
                all_setups.extend(ss)
    seen = set(); unique = []
    for s in all_setups:
        key = (s["anchor_time"], s["trigger_time"], s["trigger"]["direction"])
        if key in seen: continue
        seen.add(key); unique.append(s)
    print(f"  unique setups (1d/12h x 4h x 1h/2h x 15m): {len(unique)}")
    # Note: full etap_35 used 4h+6h, here only 4h to match what we have collected.

    # Baseline (no filter) at all RR
    print(f"\n{'='*70}\n1.1.1 baseline (no filter):")
    baseline = {}
    for rr in RR_TEST:
        df_e = evaluate(unique, sim, rr)
        cl = df_e[df_e["outcome"].isin(["win", "loss"])]
        if cl.empty: continue
        wr = (cl["outcome"] == "win").mean() * 100
        tot = cl["R"].sum()
        baseline[rr] = (len(cl), wr, tot, cl["R"].mean())
        print(f"  RR={rr}: closed={len(cl)} WR={wr:.1f}% total={tot:+.1f}R "
              f"R/tr={cl['R'].mean():+.3f}")

    # Compute features safely for all setups
    print(f"\n[INFO] computing safe features per setup")
    df_1h = dfs["1h"]; df_4h = dfs["4h"]; df_1d = dfs["1d"]; df_15m = dfs["15m"]

    feat_rows = []
    for s in unique:
        ts = s["trigger_time"]
        d = s["trigger"]["direction"]
        # entry needs price info
        tup = build_setup(s["trigger"], 1.0)
        if tup is None:
            feat_rows.append(None)
            continue
        entry = tup[0]
        f = {
            "trigger_time": ts, "direction": d,
            "hull_4h": hull_trend_safe(df_4h["close"], hull_4h, ts),
            "hull_1d": hull_trend_safe(df_1d["close"], hull_1d, ts),
            "ema200_15m": ema_trend_safe(df_15m["close"], df_15m["ema200"], ts),
            "ema200_1h": ema_trend_safe(df_1h["close"], df_1h["ema200"], ts),
            "mh_mf_sign": mh_mf_safe(mh_mf_1h, ts),
            "do_pos": daily_open_pos_safe(df_1d, ts, entry),
            "hour": int(ts.hour),
            "weekday": ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"][ts.weekday()],
            "ict_session": ("asia" if ts.hour < 7
                            else "london" if ts.hour < 12
                            else "ny" if ts.hour < 17
                            else "off-hours"),
        }
        feat_rows.append(f)
    feats = pd.DataFrame([f for f in feat_rows if f is not None])
    feats["hull_4h_align"] = feats.apply(lambda r: aligned(r["direction"], r["hull_4h"]), axis=1)
    feats["hull_1d_align"] = feats.apply(lambda r: aligned(r["direction"], r["hull_1d"]), axis=1)
    feats["ema200_15m_align"] = feats.apply(
        lambda r: aligned(r["direction"], r["ema200_15m"], "above", "below"), axis=1)
    feats["ema200_1h_align"] = feats.apply(
        lambda r: aligned(r["direction"], r["ema200_1h"], "above", "below"), axis=1)
    feats["mh_mf_align"] = feats.apply(
        lambda r: aligned(r["direction"], r["mh_mf_sign"], "pos", "neg"), axis=1)
    feats["do_match"] = feats.apply(
        lambda r: "discount" if (
            (r["direction"] == "LONG" and r["do_pos"] == "discount") or
            (r["direction"] == "SHORT" and r["do_pos"] == "premium"))
        else "premium" if (
            (r["direction"] == "LONG" and r["do_pos"] == "premium") or
            (r["direction"] == "SHORT" and r["do_pos"] == "discount"))
        else "na", axis=1)

    # Helper: filter setups by feature mask, evaluate at all RR
    def test_filter(name, mask):
        keep_keys = set(zip(feats[mask]["trigger_time"], feats[mask]["direction"]))
        kept = [s for s in unique
                if (s["trigger_time"], s["trigger"]["direction"]) in keep_keys]
        if len(kept) < 20:
            print(f"  {name}: only n={len(kept)} - skip")
            return
        result = {}
        for rr in RR_TEST:
            df_e = evaluate(kept, sim, rr)
            cl = df_e[df_e["outcome"].isin(["win", "loss"])]
            if cl.empty: continue
            wr = (cl["outcome"] == "win").mean() * 100
            tot = cl["R"].sum()
            result[rr] = (len(cl), wr, tot, cl["R"].mean())
        print(f"  Filter: {name}  (n_setups={len(kept)})")
        for rr, (n, wr, tot, rt) in result.items():
            print(f"    RR={rr}: closed={n} WR={wr:.1f}% total={tot:+.1f}R R/tr={rt:+.3f}")

    print(f"\n{'='*70}\n1.1.1 + SAFE filters (single-feature):")
    test_filter("hull_4h aligned", feats["hull_4h_align"] == "aligned")
    test_filter("hull_1d aligned", feats["hull_1d_align"] == "aligned")
    test_filter("ema200_15m aligned", feats["ema200_15m_align"] == "aligned")
    test_filter("ema200_1h aligned", feats["ema200_1h_align"] == "aligned")
    test_filter("mh_mf aligned", feats["mh_mf_align"] == "aligned")
    test_filter("do_match == discount", feats["do_match"] == "discount")
    test_filter("ict in (london, ny)", feats["ict_session"].isin(["london", "ny"]))
    test_filter("exclude Friday", feats["weekday"] != "Fri")

    print(f"\n{'='*70}\n1.1.1 + SAFE filters (combo):")
    test_filter("hull_4h + ema200_15m",
                (feats["hull_4h_align"] == "aligned") &
                (feats["ema200_15m_align"] == "aligned"))
    test_filter("hull_4h + ICT(london|ny)",
                (feats["hull_4h_align"] == "aligned") &
                (feats["ict_session"].isin(["london", "ny"])))
    test_filter("hull_4h + do_match==discount",
                (feats["hull_4h_align"] == "aligned") &
                (feats["do_match"] == "discount"))
    test_filter("hull_4h + mh_mf",
                (feats["hull_4h_align"] == "aligned") &
                (feats["mh_mf_align"] == "aligned"))
    test_filter("hull_4h + exclude Friday",
                (feats["hull_4h_align"] == "aligned") &
                (feats["weekday"] != "Fri"))
    # Score-based composite
    feats["score"] = (
        (feats["hull_4h_align"] == "aligned").astype(int) +
        (feats["do_match"] == "discount").astype(int) +
        (feats["ict_session"].isin(["london", "ny"])).astype(int) +
        (feats["mh_mf_align"] == "aligned").astype(int) +
        (feats["ema200_15m_align"] == "aligned").astype(int)
    )
    test_filter("score >= 3", feats["score"] >= 3)
    test_filter("score >= 4", feats["score"] >= 4)

    print(f"\n[TIME] {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
