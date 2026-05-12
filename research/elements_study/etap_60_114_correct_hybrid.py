"""Этап 60: 1.1.4 hybrid (точная копия логики 1.1.1, адаптированная под FVG-d макро).

Правильная логика по образу production strategy_1_1_1.py:

  L1: FVG-1d/12h (макро-якорь)
     detect: c2_close
     time span: c0_time -> c2_close

  L2: OB-4h/6h ВНУТРИ времени L1 (synchronous — как macro-FVG в 1.1.1)
     search window: [L1.c0_time, L1.c2_close - macro_tf]
     overlap zone: with L1

  L3: OB-1h/2h ПОСЛЕ L1.c2_close (retest)
     search start: L1.c2_close
     overlap zone: with L1 AND L2

  L4: FVG-15m/20m ВНУТРИ времени L3 (synchronous — как entry-FVG в 1.1.1)
     search window: [L3.prev_time, L3.cur_time + (mid_tf - entry_tf)]
     (FVG c2_close <= L3.cur_close)
     overlap zone: with L3 AND L1

Detection time = L3.cur_close (когда всё известно).
Entry = limit на FVG-15m mid point после L3.cur_close.

Дополнительно тестируем:
  - SWEPT filter (на L3 OB-1h/2h как в 1.1.1)
  - do_match aligned filter
  - SL от макро-кластера x1 = пересечение FVG-1d ∩ OB-4h
  - RR sweep 1.0-2.5
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

OUT_DIR = Path("research/elements_study/output")


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


def detect_114_hybrid(fvgs_top, obs_macro, obs_mid, fvgs_entry,
                       top_tf, macro_tf, mid_tf, entry_tf,
                       df_15m):
    """Hybrid 1.1.4 как точная копия 1.1.1 logic."""
    setups = []
    top_td = pd.Timedelta(hours=TF_HOURS[top_tf])
    macro_td = pd.Timedelta(hours=TF_HOURS[macro_tf])
    mid_td = pd.Timedelta(hours=TF_HOURS[mid_tf])
    entry_td = pd.Timedelta(hours=TF_HOURS[entry_tf])
    mid_life = pd.Timedelta(days=LIFE_DAYS[mid_tf])

    obs_macro_sorted = sorted(obs_macro, key=lambda x: x["time"])
    obs_mid_sorted = sorted(obs_mid, key=lambda x: x["time"])
    fvgs_entry_sorted = sorted(fvgs_entry, key=lambda x: x["c0_time"])
    obs_macro_times = np.array([np.datetime64(z["time"].tz_localize(None) if z["time"].tz else z["time"])
                                  for z in obs_macro_sorted])
    obs_mid_prev_times = np.array([np.datetime64(z["prev_time"].tz_localize(None) if z["prev_time"].tz else z["prev_time"])
                                     for z in obs_mid_sorted])
    fvgs_entry_c0_times = np.array([np.datetime64(z["c0_time"].tz_localize(None) if z["c0_time"].tz else z["c0_time"])
                                      for z in fvgs_entry_sorted])

    for fvg_top in fvgs_top:
        # L1 span: c0_time -> c2_close
        L1_start = fvg_top["c0_time"]
        L1_close = fvg_top["time"] + top_td

        # L2 OB-macro: search inside L1 span (synchronous)
        # OB-pair полностью inside L1: prev_time >= L1_start, cur_close <= L1_close
        # cur_close = cur_time + macro_tf
        # → cur_time <= L1_close - macro_tf
        l2_search_start = L1_start
        l2_search_end_cur = L1_close - macro_td
        i0 = np.searchsorted(obs_macro_times, np.datetime64(
            l2_search_start.tz_localize(None) if l2_search_start.tz else l2_search_start), side="left")
        i1 = np.searchsorted(obs_macro_times, np.datetime64(
            l2_search_end_cur.tz_localize(None) if l2_search_end_cur.tz else l2_search_end_cur), side="right")

        for mi in range(i0, i1):
            ob_macro = obs_macro_sorted[mi]
            # Также prev_time >= L1_start
            if ob_macro["prev_time"] < L1_start: continue
            if ob_macro["direction"] != fvg_top["direction"]: continue
            if not zones_overlap(ob_macro["bottom"], ob_macro["top"],
                                  fvg_top["bottom"], fvg_top["top"]): continue

            # L3 OB-mid: ПОСЛЕ L1.c2_close (retest)
            # search start = L1_close
            # life = mid_life
            l3_search_start = L1_close
            l3_search_end_cur = L1_close + mid_life
            j0 = np.searchsorted(obs_mid_prev_times, np.datetime64(
                l3_search_start.tz_localize(None) if l3_search_start.tz else l3_search_start), side="left")
            j1 = np.searchsorted(obs_mid_prev_times, np.datetime64(
                l3_search_end_cur.tz_localize(None) if l3_search_end_cur.tz else l3_search_end_cur), side="right")

            ob_mid_found = None
            for oj in range(j0, j1):
                ob_mid = obs_mid_sorted[oj]
                if ob_mid["direction"] != ob_macro["direction"]: continue
                if not zones_overlap(ob_mid["bottom"], ob_mid["top"],
                                      fvg_top["bottom"], fvg_top["top"]): continue
                if not zones_overlap(ob_mid["bottom"], ob_mid["top"],
                                      ob_macro["bottom"], ob_macro["top"]): continue
                ob_mid_found = ob_mid; break
            if ob_mid_found is None: continue

            # L4 FVG-15m: ВНУТРИ времени L3 (synchronous)
            # FVG c2_close = c2_time + entry_td <= L3.cur_close = ob_mid.cur_time + mid_td
            # → c2_time <= ob_mid.cur_time + mid_td - entry_td
            # И c0_time >= ob_mid.prev_time
            L3_start = ob_mid_found["prev_time"]
            L3_close = ob_mid_found["time"] + mid_td
            l4_max_c2_open = L3_close - entry_td  # FVG c2_open <= this

            # Поиск FVG-15m с c0_time >= L3_start AND c2_time <= l4_max_c2_open
            k0 = np.searchsorted(fvgs_entry_c0_times, np.datetime64(
                L3_start.tz_localize(None) if L3_start.tz else L3_start), side="left")
            fvg_entry_found = None
            for ek in range(k0, len(fvgs_entry_sorted)):
                f_entry = fvgs_entry_sorted[ek]
                if f_entry["c0_time"] < L3_start: continue
                if f_entry["time"] > l4_max_c2_open: continue
                if f_entry["c0_time"] > L3_close: break  # выходим за окно
                if f_entry["direction"] != ob_mid_found["direction"]: continue
                if not zones_overlap(f_entry["bottom"], f_entry["top"],
                                      ob_mid_found["bottom"], ob_mid_found["top"]): continue
                if not zones_overlap(f_entry["bottom"], f_entry["top"],
                                      fvg_top["bottom"], fvg_top["top"]): continue
                fvg_entry_found = f_entry; break
            if fvg_entry_found is None: continue

            # макро-кластер x1 = пересечение FVG-top ∩ OB-macro
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
                "tf_minutes": 15,
                "year": L3_close.year,
                "direction": fvg_entry_found["direction"],
                # Detection time = L3.cur_close (когда всё известно)
                "signal_time": L3_close,
                # для SWEPT
                "ob_htf_tf": mid_tf,
                "ob_htf_cur_time": ob_mid_found["time"],
                "ob_htf_prev_time": ob_mid_found["prev_time"],
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
    entry_window_start = s["signal_time"]   # = L3.cur_close
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

    print("[INFO] detect HYBRID 1.1.4")
    all_setups = []
    for top_tf, top_zones in [("1d", fvgs_1d), ("12h", fvgs_12h)]:
        for macro_tf, macro_zones in [("4h", obs_4h), ("6h", obs_6h)]:
            for mid_tf, mid_zones in [("1h", obs_1h), ("2h", obs_2h)]:
                chains = detect_114_hybrid(top_zones, macro_zones, mid_zones,
                                             fvgs_15m, top_tf, macro_tf, mid_tf, "15m",
                                             df_15m)
                all_setups.extend(chains)
    seen = set(); unique = []
    for s in all_setups:
        key = (s["signal_time"], s["direction"], round(s["fvg_b"], 2), round(s["fvg_t"], 2))
        if key in seen: continue
        seen.add(key); unique.append(s)
    print(f"  setups: {len(unique)}")

    # SWEPT filter
    swept_setups = []
    for s in unique:
        sw = check_swept(s, df_1h, df_2h)
        if sw is None: continue
        if sw: swept_setups.append(s)
    print(f"  SWEPT-filtered: {len(swept_setups)} ({len(swept_setups)/max(len(unique),1)*100:.0f}%)")

    print(f"\n{'='*70}\nBASELINE (без фильтров)")
    print(f"{'='*70}\n")
    print("  ALL setups:")
    for rr in [1.0, 1.5, 1.8, 2.0, 2.5]:
        df = evaluate(unique, rr, df_1m, df_1d, only_dom=False)
        report(f"    RR={rr}", df)

    print("\n  SWEPT only:")
    for rr in [1.0, 1.5, 1.8, 2.0, 2.5]:
        df = evaluate(swept_setups, rr, df_1m, df_1d, only_dom=False)
        report(f"    RR={rr}", df)

    print(f"\n{'='*70}\n+ do_match aligned filter")
    print(f"{'='*70}\n")
    print("  ALL + do_match:")
    for rr in [1.0, 1.5, 1.8, 2.0, 2.5, 3.0]:
        df = evaluate(unique, rr, df_1m, df_1d, only_dom=True)
        report(f"    RR={rr}", df)

    print("\n  SWEPT + do_match:")
    for rr in [1.0, 1.5, 1.8, 2.0, 2.5, 3.0]:
        df = evaluate(swept_setups, rr, df_1m, df_1d, only_dom=True)
        report(f"    RR={rr}", df)

    # Year-by-year for best variant
    print(f"\n{'='*70}\nYEAR-BY-YEAR for best variants")
    print(f"{'='*70}")

    # Find best variant
    best_results = []
    for variant_label, cache, rr in [
        ("ALL RR=1.8 + do_match", unique, 1.8),
        ("ALL RR=2.0 + do_match", unique, 2.0),
        ("ALL RR=2.5 + do_match", unique, 2.5),
        ("SWEPT RR=1.8 + do_match", swept_setups, 1.8),
        ("SWEPT RR=2.5 + do_match", swept_setups, 2.5),
    ]:
        df = evaluate(cache, rr, df_1m, df_1d, only_dom=True)
        cl = df[df["outcome"].isin(["win", "loss"])]
        if cl.empty: continue
        tot = cl["R"].sum()
        best_results.append((variant_label, tot, df, cl))

    best_results.sort(key=lambda x: x[1], reverse=True)
    print(f"\n  Top variants:")
    for label, tot, df, cl in best_results[:3]:
        wr = (cl["R"] > 0).mean() * 100
        yr = cl.groupby("year")["R"].sum()
        bad = (yr < 0).sum()
        print(f"    {label}: total={tot:+.1f}R  WR={wr:.1f}%  n={len(cl)}  bad={bad}/{len(yr)}")

    if best_results:
        label, tot, df, cl = best_results[0]
        print(f"\n  YEAR-BY-YEAR for {label}:")
        yr_df = cl.groupby("year").agg(
            n=("R", "size"),
            wins=("outcome", lambda x: (x == "win").sum()),
            total_R=("R", "sum"))
        yr_df["WR"] = yr_df["wins"] / yr_df["n"] * 100
        for y, r in yr_df.iterrows():
            flag = " !" if r["total_R"] < 0 else ""
            print(f"    {int(y)}: n={int(r['n']):>3} WR={r['WR']:5.1f}% "
                  f"total={r['total_R']:+5.1f}R{flag}")

    print(f"\n[TIME] {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
