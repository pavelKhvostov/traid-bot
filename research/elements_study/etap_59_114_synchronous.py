"""Этап 59: 1.1.4 SYNCHRONOUS — FVG-15m внутри времени OB-1h/2h.

ПОПРАВКА: Раньше (etap_50-58) я искал FVG-15m ПОСЛЕ закрытия OB-1h
(retest-логика как в 1.1.1). Это неправильно.

Правильная логика по user-у:
  Если OB-1h состоит из c1 (6:00-7:00) и c2 (7:00-8:00),
  то FVG-15m c2_close должен быть <= 8:00 (т.е. полностью внутри OB-pair времени).

Пробую 2 варианта:
  V_PARTIAL: только L4 (FVG-15m) синхронно с L3 (OB-1h). L1-L3 как раньше.
  V_FULL: вся цепочка nested-by-time. Каждый уровень внутри времени предыдущего.
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
                     "time": f.c2_time, "idx": idx,
                     "c0_time": f.c0_time})
    return out


def zones_overlap(b1, t1, b2, t2):
    return not (t1 < b2 or t2 < b1)


def detect_114_partial_sync(fvgs_top, obs_macro, obs_mid, fvgs_entry,
                              top_tf, macro_tf, mid_tf, entry_tf):
    """V_PARTIAL: L1-L3 retest как раньше, но L4 синхронно с L3.

    L4 FVG-15m: c0_time >= L3.prev_time AND c2_close <= L3.cur_close
    """
    setups = []
    top_td = pd.Timedelta(hours=TF_HOURS[top_tf])
    macro_td = pd.Timedelta(hours=TF_HOURS[macro_tf])
    mid_td = pd.Timedelta(hours=TF_HOURS[mid_tf])
    entry_td = pd.Timedelta(hours=TF_HOURS[entry_tf])
    top_life = pd.Timedelta(days=LIFE_DAYS[top_tf])
    macro_life = pd.Timedelta(days=LIFE_DAYS[macro_tf])

    obs_macro_sorted = sorted(obs_macro, key=lambda x: x["time"])
    obs_mid_sorted = sorted(obs_mid, key=lambda x: x["time"])
    fvgs_entry_sorted = sorted(fvgs_entry, key=lambda x: x["time"])
    obs_macro_times = np.array([np.datetime64(z["time"].tz_localize(None) if z["time"].tz else z["time"])
                                  for z in obs_macro_sorted])
    obs_mid_times = np.array([np.datetime64(z["time"].tz_localize(None) if z["time"].tz else z["time"])
                                for z in obs_mid_sorted])

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

            # SYNCHRONOUS L4 search:
            #   FVG-15m c0_time должен быть >= ob_mid.prev_time (внутри OB-pair start)
            #   FVG-15m c2_close (= c2_time + 15m) должен быть <= ob_mid.cur_close
            l3_start = ob_mid_found["prev_time"]   # = c1 OB open
            l3_close = ob_mid_found["time"] + mid_td  # = c2 OB close
            fvg_max_c2_open = l3_close - entry_td   # последний возможный c2 open

            fvg_entry_found = None
            for f_entry in fvgs_entry_sorted:
                if f_entry["c0_time"] < l3_start: continue
                if f_entry["time"] > fvg_max_c2_open: continue  # c2_open + 15m > l3_close
                if f_entry["direction"] != fvg_top["direction"]: continue
                if not zones_overlap(f_entry["bottom"], f_entry["top"],
                                      ob_mid_found["bottom"], ob_mid_found["top"]): continue
                if not zones_overlap(f_entry["bottom"], f_entry["top"],
                                      fvg_top["bottom"], fvg_top["top"]): continue
                fvg_entry_found = f_entry; break
            if fvg_entry_found is None: continue

            x1_bottom = max(fvg_top["bottom"], ob_macro["bottom"])
            x1_top = min(fvg_top["top"], ob_macro["top"])

            setups.append({
                "anchor_tf": top_tf, "macro_tf": macro_tf, "mid_tf": mid_tf,
                "anchor_time": fvg_top["time"],
                "trigger_time": fvg_entry_found["time"],
                "fvg_b": fvg_entry_found["bottom"],
                "fvg_t": fvg_entry_found["top"],
                "x1_bottom": x1_bottom, "x1_top": x1_top,
                "obh_b": ob_mid_found["bottom"],
                "obh_t": ob_mid_found["top"],
                "ob_mid_close": l3_close,  # = detection time
                "tf_minutes": 15,
                "year": fvg_entry_found["time"].year,
                "direction": fvg_entry_found["direction"],
                "signal_time": l3_close,  # detection at OB-mid close (synchronous)
            })
            break
    return setups


def detect_114_full_sync(fvgs_top, obs_macro, obs_mid, fvgs_entry,
                          top_tf, macro_tf, mid_tf, entry_tf):
    """V_FULL: полностью nested-by-time. Каждый уровень внутри времени предыдущего."""
    setups = []
    top_td = pd.Timedelta(hours=TF_HOURS[top_tf])
    macro_td = pd.Timedelta(hours=TF_HOURS[macro_tf])
    mid_td = pd.Timedelta(hours=TF_HOURS[mid_tf])
    entry_td = pd.Timedelta(hours=TF_HOURS[entry_tf])

    obs_macro_sorted = sorted(obs_macro, key=lambda x: x["time"])
    obs_mid_sorted = sorted(obs_mid, key=lambda x: x["time"])
    fvgs_entry_sorted = sorted(fvgs_entry, key=lambda x: x["time"])

    for fvg_top in fvgs_top:
        # L1 FVG-top span: c0_time -> c2_time + tf
        L1_start = fvg_top["c0_time"]
        L1_end = fvg_top["time"] + top_td

        for ob_macro in obs_macro_sorted:
            # L2 OB-macro inside L1 by time
            L2_start = ob_macro["prev_time"]
            L2_end = ob_macro["time"] + macro_td
            if L2_start < L1_start: continue
            if L2_end > L1_end: continue
            if ob_macro["direction"] != fvg_top["direction"]: continue
            if not zones_overlap(ob_macro["bottom"], ob_macro["top"],
                                  fvg_top["bottom"], fvg_top["top"]): continue

            for ob_mid in obs_mid_sorted:
                # L3 OB-mid inside L2 by time
                L3_start = ob_mid["prev_time"]
                L3_end = ob_mid["time"] + mid_td
                if L3_start < L2_start: continue
                if L3_end > L2_end: continue
                if ob_mid["direction"] != ob_macro["direction"]: continue
                if not zones_overlap(ob_mid["bottom"], ob_mid["top"],
                                      ob_macro["bottom"], ob_macro["top"]): continue
                if not zones_overlap(ob_mid["bottom"], ob_mid["top"],
                                      fvg_top["bottom"], fvg_top["top"]): continue

                for f_entry in fvgs_entry_sorted:
                    # L4 FVG-15m inside L3 by time
                    L4_start = f_entry["c0_time"]
                    L4_end = f_entry["time"] + entry_td
                    if L4_start < L3_start: continue
                    if L4_end > L3_end: continue
                    if f_entry["direction"] != ob_mid["direction"]: continue
                    if not zones_overlap(f_entry["bottom"], f_entry["top"],
                                          ob_mid["bottom"], ob_mid["top"]): continue
                    if not zones_overlap(f_entry["bottom"], f_entry["top"],
                                          fvg_top["bottom"], fvg_top["top"]): continue

                    x1_bottom = max(fvg_top["bottom"], ob_macro["bottom"])
                    x1_top = min(fvg_top["top"], ob_macro["top"])

                    setups.append({
                        "anchor_tf": top_tf, "macro_tf": macro_tf, "mid_tf": mid_tf,
                        "anchor_time": fvg_top["time"],
                        "trigger_time": f_entry["time"],
                        "fvg_b": f_entry["bottom"], "fvg_t": f_entry["top"],
                        "x1_bottom": x1_bottom, "x1_top": x1_top,
                        "obh_b": ob_mid["bottom"], "obh_t": ob_mid["top"],
                        "tf_minutes": 15,
                        "year": f_entry["time"].year,
                        "direction": f_entry["direction"],
                        # Detection at L1 (макро) c2_close = когда всё известно
                        "signal_time": L1_end,
                    })
                    break  # first L4 per L3
                else:
                    continue
                break  # first L3 per L2
            else:
                continue
            break  # first L2 per L1
    return setups


def build_orders(s):
    """SL от макро-кластера x1."""
    direction = s["direction"]
    fb, ft = s["fvg_b"], s["fvg_t"]
    x1b, x1t = s["x1_bottom"], s["x1_top"]
    if direction == "LONG":
        entry = fb + ENTRY_PCT * (ft - fb)
        if x1b >= fb:
            obb = s["obh_b"]
            sl = obb + USER_SL_LONG * (fb - obb)
        else:
            sl = x1b + USER_SL_LONG * (fb - x1b)
        if MIN_SL_PCT > 0:
            sl = min(sl, entry - entry * MIN_SL_PCT / 100)
        if sl >= entry: return None
    else:
        entry = ft - ENTRY_PCT * (ft - fb)
        if x1t <= ft:
            obt = s["obh_t"]
            sl = obt - USER_SL_SHORT * (obt - ft)
        else:
            sl = x1t - USER_SL_SHORT * (x1t - ft)
        if MIN_SL_PCT > 0:
            sl = max(sl, entry + entry * MIN_SL_PCT / 100)
        if sl <= entry: return None
    return entry, sl


def simulate_safe(s, entry, sl, tp, df_1m, max_hold_days=7):
    direction = s["direction"]
    risk = abs(entry - sl)
    if risk <= 0: return ("invalid", 0.0)
    # signal_time это detection time (L3.cur_close для partial, L1.c2_close для full)
    # Entry window starts at signal_time (когда сигнал доступен)
    entry_window_start = s["signal_time"]
    end_time = entry_window_start + pd.Timedelta(days=max_hold_days)
    et64 = np.datetime64(entry_window_start.tz_localize(None) if entry_window_start.tz else entry_window_start)
    ee64 = np.datetime64(end_time.tz_localize(None) if end_time.tz else end_time)
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
    if tp_first < sl_first: return ("win", abs(tp - entry) / risk)
    return ("loss", -1.0)


def do_match_aligned(s, entry, df_1d):
    ts = s["signal_time"]
    idx_d = df_1d.index.searchsorted(ts, side="right") - 1
    if idx_d < 0: return False
    do = df_1d["open"].iloc[idx_d]
    if pd.isna(do): return False
    if s["direction"] == "LONG": return entry < do
    return entry > do


def evaluate(setups, rr, df_1m, df_1d, only_dom=True):
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
        rows.append({**s, "entry": entry, "sl": sl, "tp": tp,
                      "outcome": outcome, "R": R})
    return pd.DataFrame(rows)


def report(label, df):
    cl = df[df["outcome"].isin(["win", "loss"])]
    n_total = len(df)
    if cl.empty:
        print(f"  {label}: n={n_total}, no closed"); return None
    nc = len(cl); wins = (cl["R"] > 0).sum()
    wr = wins/nc*100; tot = cl["R"].sum(); rt = cl["R"].mean()
    yr = cl.groupby("year")["R"].sum()
    bad = (yr < 0).sum()
    n_no_entry = (df["outcome"] == "no_entry").sum()
    n_not_filled = (df["outcome"] == "not_filled").sum()
    print(f"  {label}: n={n_total} closed={nc} no_entry={n_no_entry} not_filled={n_not_filled}")
    print(f"    WR={wr:.1f}%  total={tot:+.1f}R  R/tr={rt:+.3f}  bad={bad}/{len(yr)}")
    return tot


def main():
    t0 = time.time()
    print("[INFO] load")
    df_1d = load_df(SYMBOL, "1d")
    df_4h = load_df(SYMBOL, "4h")
    df_1h = load_df(SYMBOL, "1h")
    df_12h = compose_from_base(df_1h, "12h")
    df_6h = compose_from_base(df_1h, "6h")
    df_2h = compose_from_base(df_1h, "2h")
    df_1m = load_df(SYMBOL, "1m")
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

    fvgs_1d = collect_fvgs(df_1d, df_1d["atr14"], "1d")
    fvgs_12h = collect_fvgs(df_12h, df_12h["atr14"], "12h")
    obs_4h = collect_obs(df_4h, df_4h["atr14"], "4h")
    obs_6h = collect_obs(df_6h, df_6h["atr14"], "6h")
    obs_1h = collect_obs(df_1h, df_1h["atr14"], "1h")
    obs_2h = collect_obs(df_2h, df_2h["atr14"], "2h")
    fvgs_15m = collect_fvgs(df_15m, df_15m["atr14"], "15m")

    print(f"\n{'='*70}\nV_PARTIAL: L4 синхронно с L3 (FVG-15m внутри времени OB-1h/2h)")
    print(f"{'='*70}")
    all_setups = []
    for top_tf, top_zones in [("1d", fvgs_1d), ("12h", fvgs_12h)]:
        for macro_tf, macro_zones in [("4h", obs_4h), ("6h", obs_6h)]:
            for mid_tf, mid_zones in [("1h", obs_1h), ("2h", obs_2h)]:
                chains = detect_114_partial_sync(top_zones, macro_zones, mid_zones,
                                                   fvgs_15m, top_tf, macro_tf, mid_tf, "15m")
                all_setups.extend(chains)
    seen = set(); unique = []
    for s in all_setups:
        key = (s["signal_time"], s["direction"], round(s["fvg_b"], 2), round(s["fvg_t"], 2))
        if key in seen: continue
        seen.add(key); unique.append(s)
    print(f"  setups: {len(unique)}")

    print("\n  Без do_match:")
    for rr in [1.0, 1.5, 1.8, 2.0, 2.5]:
        df = evaluate(unique, rr, df_1m, df_1d, only_dom=False)
        report(f"    RR={rr}", df)

    print("\n  С do_match aligned:")
    for rr in [1.0, 1.5, 1.8, 2.0, 2.5]:
        df = evaluate(unique, rr, df_1m, df_1d, only_dom=True)
        report(f"    RR={rr}", df)

    print(f"\n{'='*70}\nV_FULL: все 4 уровня nested-by-time (полная синхронность)")
    print(f"{'='*70}")
    all_setups2 = []
    for top_tf, top_zones in [("1d", fvgs_1d), ("12h", fvgs_12h)]:
        for macro_tf, macro_zones in [("4h", obs_4h), ("6h", obs_6h)]:
            for mid_tf, mid_zones in [("1h", obs_1h), ("2h", obs_2h)]:
                chains = detect_114_full_sync(top_zones, macro_zones, mid_zones,
                                                fvgs_15m, top_tf, macro_tf, mid_tf, "15m")
                all_setups2.extend(chains)
    seen2 = set(); unique2 = []
    for s in all_setups2:
        key = (s["signal_time"], s["direction"], round(s["fvg_b"], 2), round(s["fvg_t"], 2))
        if key in seen2: continue
        seen2.add(key); unique2.append(s)
    print(f"  setups: {len(unique2)}")

    print("\n  Без do_match:")
    for rr in [1.0, 1.5, 1.8, 2.0, 2.5]:
        df = evaluate(unique2, rr, df_1m, df_1d, only_dom=False)
        report(f"    RR={rr}", df)

    print("\n  С do_match aligned:")
    for rr in [1.0, 1.5, 1.8, 2.0, 2.5]:
        df = evaluate(unique2, rr, df_1m, df_1d, only_dom=True)
        report(f"    RR={rr}", df)

    print(f"\n[TIME] {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
