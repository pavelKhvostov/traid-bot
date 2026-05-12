"""Этап 56: RR sweep для 1.1.4 STRICT + do_match aligned.

Берём STRICT-L1 cache (после bug fix etap_55), фильтруем по do_match=aligned,
варьируем RR в [1.0, 1.5, 1.8, 2.0, 2.5, 3.0].

Цель: найти оптимальный RR для best filter на 1.1.4.
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
MIN_SL_PCT = 1.0

LIFE_DAYS = {"1d": 14, "12h": 7, "6h": 4, "4h": 3,
              "2h": 1.5, "1h": 1, "15m": 0.5}
TF_HOURS = {"1d": 24, "12h": 12, "6h": 6, "4h": 4,
             "2h": 2, "1h": 1, "15m": 0.25}


def compute_atr(df, period=14):
    high = df["high"]; low = df["low"]; pc = df["close"].shift(1)
    tr = pd.concat([(high-low),(high-pc).abs(),(low-pc).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def collect_obs(df, atr, tf):
    out = []
    for idx in range(2, len(df) - 1):
        ob = detect_ob_pair(df, idx)
        if ob is None: continue
        a = float(atr.iloc[idx])
        if pd.isna(a) or a <= 0: continue
        out.append({"tf": tf, "direction": ob.direction,
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
        out.append({"tf": tf, "direction": f.direction,
                     "bottom": f.bottom, "top": f.top, "atr": a,
                     "time": f.c2_time, "idx": idx})
    return out


def zones_overlap(b1, t1, b2, t2):
    return not (t1 < b2 or t2 < b1)


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

            setups.append({
                "anchor_time": fvg_top["time"],
                "trigger_time": fvg_entry_found["time"],
                "fvg_b": fvg_entry_found["bottom"],
                "fvg_t": fvg_entry_found["top"],
                "obh_b": ob_mid_found["bottom"],
                "obh_t": ob_mid_found["top"],
                "tf_minutes": 15,
                "year": fvg_entry_found["time"].year,
                "direction": fvg_entry_found["direction"],
                "signal_time": fvg_entry_found["time"],
            })
            break
    return setups


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
    if tp_pre < ent_idx: return ("no_entry", 0.0)
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


def do_match_aligned(s, entry, df_1d):
    """Returns True if entry on correct side of daily open."""
    ts = s["signal_time"]
    idx_d = df_1d.index.searchsorted(ts, side="right") - 1
    if idx_d < 0: return False
    do = df_1d["open"].iloc[idx_d]
    if pd.isna(do): return False
    if s["direction"] == "LONG":
        return entry < do  # discount
    return entry > do  # premium


def evaluate(setups, rr, df_1m, df_1d, only_dom=False):
    rows = []
    for s in setups:
        tup = build_orders(s)
        if tup is None: continue
        entry, sl = tup
        if only_dom and not do_match_aligned(s, entry, df_1d):
            continue
        risk = abs(entry - sl)
        tp = entry + rr * risk if s["direction"] == "LONG" else entry - rr * risk
        outcome, R = simulate_safe(s, entry, sl, tp, df_1m)
        rows.append({**s, "outcome": outcome, "R": R})
    return pd.DataFrame(rows)


def report(label, df, expected_rr):
    cl = df[df["outcome"].isin(["win", "loss"])]
    if cl.empty:
        print(f"  {label}: no closed"); return None
    n = len(df); nc = len(cl)
    wins = (cl["R"] > 0).sum()
    wr = wins/nc*100
    tot = cl["R"].sum()
    rt = cl["R"].mean()
    yr = cl.groupby("year")["R"].sum()
    bad = (yr < 0).sum()
    # break-even WR for given RR
    be_wr = 1 / (1 + expected_rr) * 100  # WR needed for break-even
    safety_pp = wr - be_wr
    print(f"  {label}")
    print(f"    n_total={n}  closed={nc}  wins={wins}  losses={nc-wins}")
    print(f"    WR={wr:.1f}%  R/tr={rt:+.3f}  total={tot:+.1f}R  bad={bad}/{len(yr)}")
    print(f"    break-even WR @ RR={expected_rr}: {be_wr:.1f}%  -> margin {safety_pp:+.1f}pp")
    return tot


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
    df_15m = compose_from_base(df_1m, "15m")  # composed (avoid native gap)

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

    fvgs_1d = collect_fvgs(df_1d, df_1d["atr14"], "1d")
    fvgs_12h = collect_fvgs(df_12h, df_12h["atr14"], "12h")
    obs_4h = collect_obs(df_4h, df_4h["atr14"], "4h")
    obs_6h = collect_obs(df_6h, df_6h["atr14"], "6h")
    obs_1h = collect_obs(df_1h, df_1h["atr14"], "1h")
    obs_2h = collect_obs(df_2h, df_2h["atr14"], "2h")
    fvgs_15m = collect_fvgs(df_15m, df_15m["atr14"], "15m")

    print("[INFO] STRICT-L1 detect")
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
    print(f"  setups: {len(unique)}")

    # ==========================================================
    print(f"\n{'='*70}\n1.1.4 STRICT-L1 + do_match aligned: RR sweep")
    print(f"{'='*70}\n")
    print(f"  Filter: entry on correct side of daily_open")
    print(f"  USER params: entry=0.7, sl=0.35L/0.65S, min_sl=1%\n")

    results = {}
    for rr in [1.0, 1.2, 1.5, 1.8, 2.0, 2.2, 2.5, 3.0]:
        df_e = evaluate(unique, rr, df_1m, df_1d, only_dom=True)
        tot = report(f"RR={rr}", df_e, rr)
        if tot is not None:
            results[rr] = tot
        print()

    # Summary
    print(f"\n{'='*70}\nSUMMARY: RR vs total R")
    print(f"{'='*70}")
    print(f"  {'RR':<6}  {'Total R':<10}  {'Per yr':<10}")
    for rr, tot in sorted(results.items()):
        per_yr = tot / 6.33
        print(f"  {rr:<6}  {tot:>+7.1f}R   {per_yr:>+5.1f}R/y")

    best_rr = max(results.items(), key=lambda x: x[1])
    print(f"\n  BEST RR={best_rr[0]} -> {best_rr[1]:+.1f}R")

    print(f"\n[TIME] {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
