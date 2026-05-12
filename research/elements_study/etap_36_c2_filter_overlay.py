"""Этап 36: применение топ-фильтров etap_35 на C2 (текущий #1).

C2 baseline (etap_15 v7, после 2022 fix):
  OB-6h x FVG-2h pro-trend, entry=mid, min_sl=1%, RR=1.0
  → 178 setups, WR 55.3%, +70R, R/tr 0.105, 0 минусовых лет

Тестируем:
  - Hull MA(78) на 4h aligned with direction (top finding из etap_35: +13.6pp на 1.1.1)
  - EMA200 на 15m aligned (на 1.1.1: +6.9pp)
  - HA Money Flow sign aligned (на 1.1.1: +9.8pp)
  - Daily-open discount/premium ICT (на 1.1.1: +7.3pp)
  - ICT NY session (12-17 UTC) (на 1.1.1: +9.2pp)
  - Score-based composite

Главный вопрос: C2 уже использует EMA200(2h) pro-trend gate. Дают ли
эти 5 фич ДОПОЛНИТЕЛЬНЫЙ edge поверх, или C2 уже optimal?
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
RR_BASE = 1.0
RR_TEST = [1.0, 1.5, 2.0]

TF_LIFE_DAYS = {"1d": 30, "12h": 14, "6h": 10, "4h": 5,
                 "2h": 3, "1h": 2, "15m": 1}

OUT_DIR = Path("research/elements_study/output")


# ---------- math primitives (same as etap_35) ----------

def compute_atr(df, period=14):
    high = df["high"]; low = df["low"]; pc = df["close"].shift(1)
    tr = pd.concat([(high-low),(high-pc).abs(),(low-pc).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def wma_fast(arr: np.ndarray, period: int) -> np.ndarray:
    period = max(int(period), 1)
    weights = np.arange(1, period + 1, dtype=float)
    weights /= weights.sum()
    out = np.full_like(arr, np.nan, dtype=float)
    if len(arr) < period: return out
    valid = np.convolve(arr, weights[::-1], mode="valid")
    out[period - 1:] = valid
    return out


def hull_ma(close: pd.Series, length: int) -> pd.Series:
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


def money_flow_ha(df: pd.DataFrame) -> pd.Series:
    ha_o, ha_h, ha_l, ha_c = heikin_ashi(df["open"], df["high"], df["low"], df["close"])
    rng = (ha_h - ha_l).replace(0, np.nan)
    raw = ((ha_c - ha_o) / rng) * 200
    return raw.rolling(60, min_periods=60).mean() - 2.25


# ---------- C2 detection (from etap_15) ----------

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
        out.append({"time": ob.cur_time, "direction": ob.direction,
                     "bottom": ob.bottom, "top": ob.top, "atr": atr,
                     "tf": tf_label, "idx": idx})
    return out


def collect_fvgs(df, atr_series, tf_label):
    out = []
    for idx in range(2, len(df) - 1):
        f = detect_fvg(df, idx)
        if f is None: continue
        atr = float(atr_series.iloc[idx])
        if pd.isna(atr) or atr <= 0: continue
        out.append({"time": f.c2_time, "direction": f.direction,
                     "bottom": f.bottom, "top": f.top, "atr": atr,
                     "tf": tf_label, "idx": idx})
    return out


def zones_overlap(b1, t1, b2, t2):
    return not (t1 < b2 or t2 < b1)


def build_c2_setups(obs_6h, fvgs_2h, df_2h, anchor_tf="6h", trigger_tf="2h"):
    """C2: OB-6h × FVG-2h pro-trend, dedup first."""
    a_tf_td = pd.Timedelta(anchor_tf)
    a_life = pd.Timedelta(days=TF_LIFE_DAYS[anchor_tf])
    t_sorted = sorted(fvgs_2h, key=lambda x: x["time"])
    t_times = np.array([np.datetime64(t["time"].tz_localize(None) if t["time"].tz else t["time"])
                         for t in t_sorted])
    ema_arr = df_2h["ema200"].to_numpy()
    close_arr = df_2h["close"].to_numpy()
    setups = []
    for a in obs_6h:
        a_start = a["time"] + a_tf_td  # cur_close
        a_end = a["time"] + a_life
        if a_end <= a_start: continue
        i_start = np.searchsorted(t_times, np.datetime64(
            a_start.tz_localize(None) if a_start.tz else a_start), side="right")
        i_end = np.searchsorted(t_times, np.datetime64(
            a_end.tz_localize(None) if a_end.tz else a_end), side="right")
        for ti in range(i_start, i_end):
            t = t_sorted[ti]
            if t["direction"] != a["direction"]: continue
            if not zones_overlap(t["bottom"], t["top"], a["bottom"], a["top"]):
                continue
            em = float(ema_arr[t["idx"]]); cl = float(close_arr[t["idx"]])
            pro = ((t["direction"] == "LONG" and cl > em) or
                   (t["direction"] == "SHORT" and cl < em))
            if not pro: continue  # C2 уже требует pro-trend
            setups.append({"anchor_time": a["time"], "trigger_time": t["time"],
                            "direction": t["direction"],
                            "fvg_bottom": t["bottom"], "fvg_top": t["top"],
                            "fvg_atr": t["atr"], "year": t["time"].year})
            break
    return setups


def evaluate_c2(setups, sim, trigger_tf, rr):
    rows = []
    for s in setups:
        direction = s["direction"]
        entry = (s["fvg_bottom"] + s["fvg_top"]) / 2
        atr = s["fvg_atr"]
        if direction == "LONG":
            atr_sl = s["fvg_bottom"] - SL_BUF_ATR * atr
            min_dist = entry * MIN_SL_PCT / 100
            sl = min(atr_sl, entry - min_dist)
        else:
            atr_sl = s["fvg_top"] + SL_BUF_ATR * atr
            min_dist = entry * MIN_SL_PCT / 100
            sl = max(atr_sl, entry + min_dist)
        risk = abs(entry - sl)
        if risk <= 0: continue
        tp = entry + rr * risk if direction == "LONG" else entry - rr * risk
        start = s["trigger_time"] + pd.Timedelta(trigger_tf)
        outcome, R = sim.simulate(direction, entry, sl, tp, start,
                                    TF_LIFE_DAYS[trigger_tf])
        rows.append({**s, "entry": entry, "sl": sl, "tp": tp,
                      "outcome": outcome, "R": R})
    return pd.DataFrame(rows)


# ---------- feature lookup ----------

def asof_value(s, ts):
    if s.empty: return np.nan
    idx = s.index.searchsorted(ts, side="right") - 1
    if idx < 0: return np.nan
    val = s.iloc[idx]
    return float(val) if pd.notna(val) else np.nan


def hull_trend_label(close, hull, ts):
    c = asof_value(close, ts)
    idx = hull.index.searchsorted(ts, side="right") - 1
    if idx < 2 or np.isnan(c): return "na"
    h2 = hull.iloc[idx - 2]
    if pd.isna(h2): return "na"
    return "up" if c > h2 else "down"


def ema_trend_label(close, ema_s, ts):
    c = asof_value(close, ts); e = asof_value(ema_s, ts)
    if np.isnan(c) or np.isnan(e): return "na"
    return "above" if c > e else "below"


def daily_open_pos(df_1d, ts, entry_price):
    idx = df_1d.index.searchsorted(ts, side="right") - 1
    if idx < 0: return "na"
    do = df_1d["open"].iloc[idx]
    if entry_price > do: return "premium"
    if entry_price < do: return "discount"
    return "mid"


def aligned(direction, label, up="up", down="down"):
    if label == "na": return "na"
    if direction == "LONG":
        return "aligned" if label == up else "counter"
    return "aligned" if label == down else "counter"


# ---------- analysis ----------

def report_segment(label, trades_df, feature, baseline_wr, baseline_R):
    g = trades_df.groupby(feature).agg(
        n=("R", "size"),
        wins=("outcome", lambda x: (x == "win").sum()),
        total_R=("R", "sum"),
        avg_R=("R", "mean"),
    )
    g["WR"] = g["wins"] / g["n"] * 100
    g = g.sort_values("WR", ascending=False)
    print(f"\n=== {feature} ===")
    print(f"  baseline: WR={baseline_wr:.1f}%, total={baseline_R:+.1f}R, n={len(trades_df)}")
    for cat, row in g.iterrows():
        d_wr = row["WR"] - baseline_wr
        flag = " ***" if (d_wr >= 5 and row["n"] >= 20) else ""
        flag += " !" if (d_wr <= -5 and row["n"] >= 20) else ""
        print(f"  {cat!s:<25} n={int(row['n']):>4} WR={row['WR']:5.1f}% "
              f"(d={d_wr:+5.1f}pp) total={row['total_R']:+6.1f}R "
              f"avg_R={row['avg_R']:+.3f}{flag}")


def evaluate_filter(name, closed, mask, unique_setups, sim, base_wr, base_R, rr_test):
    kept = closed[mask].copy()
    if len(kept) < 20:
        print(f"  {name}: only n={len(kept)} - skip"); return
    kept_wr = (kept["outcome"] == "win").mean() * 100
    kept_R = kept["R"].sum()
    print(f"\n  Filter: {name}")
    print(f"    keep n={len(kept)}/{len(closed)} ({len(kept)/len(closed)*100:.0f}%)"
          f"  RR=1.0: WR={kept_wr:.1f}% (d={kept_wr-base_wr:+.1f}pp) total={kept_R:+.1f}R "
          f"R/tr={kept['R'].mean():+.3f}")
    # Re-evaluate at higher RR
    keep_keys = set(zip(kept["trigger_time"], kept["direction"]))
    for rr in rr_test[1:]:
        df_re = evaluate_c2(
            [s for s in unique_setups
             if (s["trigger_time"], s["direction"]) in keep_keys],
            sim, "2h", rr)
        cl_re = df_re[df_re["outcome"].isin(["win", "loss"])]
        if cl_re.empty: continue
        wr_re = (cl_re["outcome"] == "win").mean() * 100
        print(f"    RR={rr}: closed={len(cl_re)} WR={wr_re:.1f}% "
              f"total={cl_re['R'].sum():+.1f}R R/tr={cl_re['R'].mean():+.3f}")


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
    hull_4h = hull_ma(dfs["4h"]["close"], 78)
    hull_1d = hull_ma(dfs["1d"]["close"], 78)
    mh_mf_1h = money_flow_ha(dfs["1h"])
    print("  Hull(78) on 1d/4h, MH-MF on 1h done")

    print("\n[INFO] collecting C2 zones")
    obs_6h = collect_obs(dfs["6h"], dfs["6h"]["atr14"], "6h")
    fvgs_2h = collect_fvgs(dfs["2h"], dfs["2h"]["atr14"], "2h")
    print(f"  OB-6h: {len(obs_6h)}, FVG-2h: {len(fvgs_2h)}")

    setups = build_c2_setups(obs_6h, fvgs_2h, dfs["2h"])
    print(f"  C2 setups: {len(setups)}")

    print(f"\n[INFO] evaluating C2 baseline @ RR={RR_BASE}")
    trades = evaluate_c2(setups, sim, "2h", RR_BASE)
    closed = trades[trades["outcome"].isin(["win", "loss"])].copy()
    base_wr = (closed["outcome"] == "win").mean() * 100
    base_R = closed["R"].sum()
    print(f"  C2 baseline: total={len(trades)}, closed={len(closed)}, "
          f"WR={base_wr:.1f}%, total_R={base_R:+.1f}, R/tr={closed['R'].mean():+.3f}")

    # Higher RR baselines for reference
    print(f"\n[INFO] C2 at RR=1.5, 2.0 (no filter):")
    for rr in [1.5, 2.0]:
        df_e = evaluate_c2(setups, sim, "2h", rr)
        cl = df_e[df_e["outcome"].isin(["win", "loss"])]
        wr = (cl["outcome"] == "win").mean() * 100 if len(cl) else 0
        print(f"  RR={rr}: closed={len(cl)} WR={wr:.1f}% "
              f"total={cl['R'].sum():+.1f}R R/tr={cl['R'].mean():+.3f}")

    print(f"\n[INFO] computing features per closed trade")
    feats = []
    df_1h = dfs["1h"]; df_4h = dfs["4h"]; df_1d = dfs["1d"]
    df_15m = dfs["15m"]
    for _, r in closed.iterrows():
        ts = r["trigger_time"]
        f = {
            "hull_4h": hull_trend_label(df_4h["close"], hull_4h, ts),
            "hull_1d": hull_trend_label(df_1d["close"], hull_1d, ts),
            "ema200_1h": ema_trend_label(df_1h["close"], df_1h["ema200"], ts),
            "ema200_15m": ema_trend_label(df_15m["close"], df_15m["ema200"], ts),
            "ema200_4h": ema_trend_label(df_4h["close"], df_4h["ema200"], ts),
            "mh_mf_sign": "pos" if asof_value(mh_mf_1h, ts) > 0 else "neg",
            "do_pos": daily_open_pos(df_1d, ts, r["entry"]),
            "hour": int(ts.hour),
            "weekday": ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"][ts.weekday()],
            "ict_session": ("asia" if ts.hour < 7
                            else "london" if ts.hour < 12
                            else "ny" if ts.hour < 17
                            else "off-hours"),
        }
        feats.append(f)
    feats_df = pd.DataFrame(feats, index=closed.index)
    closed = pd.concat([closed, feats_df], axis=1)

    # Aligned columns
    closed["hull_4h_align"] = closed.apply(
        lambda r: aligned(r["direction"], r["hull_4h"]), axis=1)
    closed["hull_1d_align"] = closed.apply(
        lambda r: aligned(r["direction"], r["hull_1d"]), axis=1)
    closed["ema200_15m_align"] = closed.apply(
        lambda r: aligned(r["direction"], r["ema200_15m"], "above", "below"), axis=1)
    closed["ema200_1h_align"] = closed.apply(
        lambda r: aligned(r["direction"], r["ema200_1h"], "above", "below"), axis=1)
    closed["ema200_4h_align"] = closed.apply(
        lambda r: aligned(r["direction"], r["ema200_4h"], "above", "below"), axis=1)
    closed["mh_mf_align"] = closed.apply(
        lambda r: aligned(r["direction"], r["mh_mf_sign"], "pos", "neg"), axis=1)
    closed["do_match"] = closed.apply(
        lambda r: "discount" if (
            (r["direction"] == "LONG" and r["do_pos"] == "discount") or
            (r["direction"] == "SHORT" and r["do_pos"] == "premium"))
        else "premium" if (
            (r["direction"] == "LONG" and r["do_pos"] == "premium") or
            (r["direction"] == "SHORT" and r["do_pos"] == "discount"))
        else "na", axis=1)

    # Save trades CSV
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_csv = OUT_DIR / "etap36_trades_c2_features.csv"
    closed.to_csv(out_csv, index=False)
    print(f"  trades CSV: {out_csv}")

    # ----- single-feature segments (only those that worked on 1.1.1) -----
    print(f"\n{'='*70}\nSEGMENTATION on C2 ({base_wr:.1f}% / {base_R:+.1f}R)")
    print(f"{'='*70}")
    for feat in [
        "direction", "year",
        "hull_4h_align", "hull_1d_align",
        "ema200_4h_align", "ema200_1h_align", "ema200_15m_align",
        "mh_mf_align", "do_match",
        "weekday", "ict_session",
    ]:
        report_segment("", closed, feat, base_wr, base_R)

    # ----- filter combinations -----
    print(f"\n{'='*70}\nFILTER OVERLAYS on C2")
    print(f"{'='*70}")

    evaluate_filter("hull_4h aligned", closed,
                    closed["hull_4h_align"] == "aligned",
                    setups, sim, base_wr, base_R, RR_TEST)
    evaluate_filter("hull_1d aligned", closed,
                    closed["hull_1d_align"] == "aligned",
                    setups, sim, base_wr, base_R, RR_TEST)
    evaluate_filter("ema200_15m aligned", closed,
                    closed["ema200_15m_align"] == "aligned",
                    setups, sim, base_wr, base_R, RR_TEST)
    evaluate_filter("mh_mf aligned", closed,
                    closed["mh_mf_align"] == "aligned",
                    setups, sim, base_wr, base_R, RR_TEST)
    evaluate_filter("do_match == discount", closed,
                    closed["do_match"] == "discount",
                    setups, sim, base_wr, base_R, RR_TEST)
    evaluate_filter("ict in (london, ny)", closed,
                    closed["ict_session"].isin(["london", "ny"]),
                    setups, sim, base_wr, base_R, RR_TEST)
    evaluate_filter("exclude Friday", closed,
                    closed["weekday"] != "Fri",
                    setups, sim, base_wr, base_R, RR_TEST)

    print(f"\n--- 2-feature combos ---")
    evaluate_filter("hull_4h + ema200_15m", closed,
                    (closed["hull_4h_align"] == "aligned") &
                    (closed["ema200_15m_align"] == "aligned"),
                    setups, sim, base_wr, base_R, RR_TEST)
    evaluate_filter("hull_4h + mh_mf", closed,
                    (closed["hull_4h_align"] == "aligned") &
                    (closed["mh_mf_align"] == "aligned"),
                    setups, sim, base_wr, base_R, RR_TEST)
    evaluate_filter("hull_4h + do_match==discount", closed,
                    (closed["hull_4h_align"] == "aligned") &
                    (closed["do_match"] == "discount"),
                    setups, sim, base_wr, base_R, RR_TEST)
    evaluate_filter("hull_4h + hull_1d", closed,
                    (closed["hull_4h_align"] == "aligned") &
                    (closed["hull_1d_align"] == "aligned"),
                    setups, sim, base_wr, base_R, RR_TEST)
    evaluate_filter("hull_4h + exclude Friday", closed,
                    (closed["hull_4h_align"] == "aligned") &
                    (closed["weekday"] != "Fri"),
                    setups, sim, base_wr, base_R, RR_TEST)

    # Score-based composite (5 features)
    closed["score"] = (
        (closed["hull_4h_align"] == "aligned").astype(int) +
        (closed["do_match"] == "discount").astype(int) +
        (closed["ict_session"].isin(["london", "ny"])).astype(int) +
        (closed["mh_mf_align"] == "aligned").astype(int) +
        (closed["ema200_15m_align"] == "aligned").astype(int)
    )
    print(f"\n  Score distribution (5 features, max=5):")
    for sc in sorted(closed["score"].unique()):
        sub = closed[closed["score"] == sc]
        wr = (sub["outcome"] == "win").mean() * 100 if len(sub) else 0
        print(f"    score={sc}: n={len(sub):>3} WR={wr:5.1f}% total={sub['R'].sum():+6.1f}R")
    evaluate_filter("score >= 3", closed, closed["score"] >= 3,
                    setups, sim, base_wr, base_R, RR_TEST)
    evaluate_filter("score >= 4", closed, closed["score"] >= 4,
                    setups, sim, base_wr, base_R, RR_TEST)

    # year-by-year for THE winner (hull_1d aligned) at RR=1.0/1.5/2.0
    print(f"\n{'='*70}\nWINNER: C2 + hull_1d aligned — full year-by-year breakdown")
    print(f"{'='*70}")
    keep_keys_1d = set(zip(
        closed[closed["hull_1d_align"] == "aligned"]["trigger_time"],
        closed[closed["hull_1d_align"] == "aligned"]["direction"]))
    setups_filtered = [s for s in setups
                        if (s["trigger_time"], s["direction"]) in keep_keys_1d]
    print(f"  filtered setups: {len(setups_filtered)}/{len(setups)}")
    for rr in RR_TEST:
        df_e = evaluate_c2(setups_filtered, sim, "2h", rr)
        cl = df_e[df_e["outcome"].isin(["win", "loss"])]
        if cl.empty: continue
        wr = (cl["outcome"] == "win").mean() * 100
        print(f"\n  --- RR={rr}: closed={len(cl)} WR={wr:.1f}% "
              f"total={cl['R'].sum():+.1f}R R/tr={cl['R'].mean():+.3f} "
              f"freq={len(df_e)/years/52:.2f}/wk ---")
        yr = cl.groupby("year").agg(
            n=("R", "size"),
            wins=("outcome", lambda x: (x == "win").sum()),
            total_R=("R", "sum"))
        yr["WR"] = yr["wins"]/yr["n"]*100
        for y, r in yr.iterrows():
            flag = " !" if r["total_R"] < 0 else ""
            print(f"    {int(y)}: n={int(r['n']):>3} WR={r['WR']:5.1f}% "
                  f"total={r['total_R']:+5.1f}R R/tr={r['total_R']/r['n']:+.3f}{flag}")

    # also check hull_1d + hull_4h (combined) year-by-year
    print(f"\n--- C2 + hull_1d + hull_4h (both aligned), year-by-year ---")
    both = closed[(closed["hull_1d_align"] == "aligned") &
                   (closed["hull_4h_align"] == "aligned")]
    keep_keys_both = set(zip(both["trigger_time"], both["direction"]))
    setups_both = [s for s in setups
                    if (s["trigger_time"], s["direction"]) in keep_keys_both]
    for rr in RR_TEST:
        df_e = evaluate_c2(setups_both, sim, "2h", rr)
        cl = df_e[df_e["outcome"].isin(["win", "loss"])]
        if cl.empty: continue
        wr = (cl["outcome"] == "win").mean() * 100
        print(f"\n  --- RR={rr}: closed={len(cl)} WR={wr:.1f}% "
              f"total={cl['R'].sum():+.1f}R R/tr={cl['R'].mean():+.3f} "
              f"freq={len(df_e)/years/52:.2f}/wk ---")
        yr = cl.groupby("year").agg(
            n=("R", "size"),
            wins=("outcome", lambda x: (x == "win").sum()),
            total_R=("R", "sum"))
        yr["WR"] = yr["wins"]/yr["n"]*100
        for y, r in yr.iterrows():
            flag = " !" if r["total_R"] < 0 else ""
            print(f"    {int(y)}: n={int(r['n']):>3} WR={r['WR']:5.1f}% "
                  f"total={r['total_R']:+5.1f}R{flag}")

    print(f"\n[TIME] {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
