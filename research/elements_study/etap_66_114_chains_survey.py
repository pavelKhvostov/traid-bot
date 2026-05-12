"""Этап 66: Quick survey 6 цепочек начинающихся с FVG-d/12h.

Цель: за один прогон сравнить альтернативы и выбрать топ-2-3 для глубокого
forensic.

Цепочки:
  A. FVG-d   → OB-4h → OB-1h → FVG-15m  (baseline 1.1.4 any_edge)
  B. FVG-12h → OB-4h → OB-1h → FVG-15m  (12h макро)
  C. FVG-d   → OB-4h → FVG-1h pro       (без mid OB, entry на FVG-1h)
  D. FVG-d   → OB-4h → FVG-2h pro       (как С2-style entry)
  E. FVG-d   → OB-4h → OB-2h → FVG-15m  (mid 2h вместо 1h)
  F. FVG-d   → OB-6h → OB-2h → FVG-15m  (mid 6h+2h)

Для каждой: RR sweep + do_match filter.
Все используют any_edge для OB-в-FVG, overlap для FVG-в-FVG.
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


def any_edge_inside(ob_b, ob_t, big_b, big_t):
    return (big_b <= ob_b <= big_t) or (big_b <= ob_t <= big_t)


def find_invalidation(df_top, fvg_top, top_td, life_end):
    L1_close = fvg_top["time"] + top_td
    df_window = df_top[(df_top.index > L1_close) & (df_top.index <= life_end)]
    if df_window.empty: return None
    if fvg_top["direction"] == "LONG":
        mask = df_window["low"] < fvg_top["bottom"]
    else:
        mask = df_window["high"] > fvg_top["top"]
    if not mask.any(): return None
    return df_window.index[mask][0]


def detect_4stage(fvgs_top, l2_zones, l2_kind, l3_zones, l3_kind, fvgs_entry,
                   top_tf, l2_tf, l3_tf, entry_tf, df_top):
    """4-stage cascade: FVG-top → L2 (OB or FVG) → L3 (OB or FVG) → FVG-15m.

    L2/L3 могут быть OB или FVG (любой комбо).
    any_edge для OB-в-зону, overlap для FVG-в-зону.
    """
    setups = []
    top_td = pd.Timedelta(hours=TF_HOURS[top_tf])
    l2_td = pd.Timedelta(hours=TF_HOURS[l2_tf])
    l3_td = pd.Timedelta(hours=TF_HOURS[l3_tf])
    entry_td = pd.Timedelta(hours=TF_HOURS[entry_tf])
    top_life = pd.Timedelta(days=LIFE_DAYS[top_tf])
    l3_life = pd.Timedelta(days=LIFE_DAYS[l3_tf])

    l3_sorted = sorted(l3_zones, key=lambda x: x.get("prev_time", x.get("c0_time", x["time"])))
    fvgs_entry_sorted = sorted(fvgs_entry, key=lambda x: x["c0_time"])
    l3_start_times = np.array([np.datetime64(
        (z.get("prev_time", z.get("c0_time", z["time"]))).tz_localize(None)
        if (z.get("prev_time", z.get("c0_time", z["time"]))).tz else
        z.get("prev_time", z.get("c0_time", z["time"])))
        for z in l3_sorted])
    fvgs_entry_c0_times = np.array([np.datetime64(z["c0_time"].tz_localize(None) if z["c0_time"].tz else z["c0_time"])
                                      for z in fvgs_entry_sorted])

    def zone_in_fvg(z, fvg, z_is_ob):
        if z_is_ob:
            return any_edge_inside(z["bottom"], z["top"], fvg["bottom"], fvg["top"])
        return zones_overlap(z["bottom"], z["top"], fvg["bottom"], fvg["top"])

    def zone_in_zone(z, big, z_is_ob, big_is_ob):
        if z_is_ob and big_is_ob:
            return any_edge_inside(z["bottom"], z["top"], big["bottom"], big["top"])
        return zones_overlap(z["bottom"], z["top"], big["bottom"], big["top"])

    def z_start(z, is_ob):
        return z["prev_time"] if is_ob else z["c0_time"]
    def z_close(z, td, is_ob):
        return z["time"] + td

    for fvg_top in fvgs_top:
        L1_close = fvg_top["time"] + top_td
        L1_max_end = L1_close + top_life
        inval = find_invalidation(df_top, fvg_top, top_td, L1_max_end)
        L1_active_end = inval if inval is not None else L1_max_end

        for l2 in l2_zones:
            l2_start = z_start(l2, l2_kind == "OB")
            l2_close = z_close(l2, l2_td, l2_kind == "OB")
            if l2_start < fvg_top["c0_time"]: continue
            if l2_close > L1_active_end: continue
            if l2["direction"] != fvg_top["direction"]: continue
            if not zone_in_fvg(l2, fvg_top, l2_kind == "OB"): continue

            l3_search_start = l2_close
            l3_search_end = l3_search_start + l3_life

            j0 = np.searchsorted(l3_start_times, np.datetime64(
                l3_search_start.tz_localize(None) if l3_search_start.tz else l3_search_start), side="left")
            j1 = np.searchsorted(l3_start_times, np.datetime64(
                l3_search_end.tz_localize(None) if l3_search_end.tz else l3_search_end), side="right")

            l3_found = None
            fvg_entry_found = None
            for oj in range(j0, j1):
                l3 = l3_sorted[oj]
                if l3["direction"] != fvg_top["direction"]: continue
                if not zone_in_fvg(l3, fvg_top, l3_kind == "OB"): continue
                if not zone_in_zone(l3, l2, l3_kind == "OB", l2_kind == "OB"): continue

                L3_start = z_start(l3, l3_kind == "OB")
                L3_close = z_close(l3, l3_td, l3_kind == "OB")
                l4_max_c2_open = L3_close - entry_td

                k0 = np.searchsorted(fvgs_entry_c0_times, np.datetime64(
                    L3_start.tz_localize(None) if L3_start.tz else L3_start), side="left")
                f_e = None
                for ek in range(k0, len(fvgs_entry_sorted)):
                    f_entry = fvgs_entry_sorted[ek]
                    if f_entry["c0_time"] < L3_start: continue
                    if f_entry["time"] > l4_max_c2_open: continue
                    if f_entry["c0_time"] > L3_close: break
                    if f_entry["direction"] != fvg_top["direction"]: continue
                    if not zones_overlap(f_entry["bottom"], f_entry["top"],
                                          fvg_top["bottom"], fvg_top["top"]): continue
                    if not zones_overlap(f_entry["bottom"], f_entry["top"],
                                          l2["bottom"], l2["top"]): continue
                    f_e = f_entry; break
                if f_e is None: continue
                l3_found = l3; fvg_entry_found = f_e; break

            if l3_found is None: continue

            x1_b = max(fvg_top["bottom"], l2["bottom"])
            x1_t = min(fvg_top["top"], l2["top"])
            L3_close = z_close(l3_found, l3_td, l3_kind == "OB")

            setups.append({
                "fvg_b": fvg_entry_found["bottom"], "fvg_t": fvg_entry_found["top"],
                "x1_bottom": x1_b, "x1_top": x1_t,
                "obh_b": l3_found["bottom"], "obh_t": l3_found["top"],
                "tf_minutes": 15,
                "year": L3_close.year,
                "direction": fvg_entry_found["direction"],
                "signal_time": L3_close,
            })
            break
    return setups


def detect_3stage(fvgs_top, l2_zones, l2_kind, fvgs_entry_pro,
                    top_tf, l2_tf, entry_tf, df_top, ema_arr, ema_index):
    """3-stage cascade: FVG-top → L2 → FVG-entry pro-trend (без mid OB).

    L2 = OB-4h/6h.
    Entry = FVG-1h/2h pro-trend (EMA200 на entry_tf).
    """
    setups = []
    top_td = pd.Timedelta(hours=TF_HOURS[top_tf])
    l2_td = pd.Timedelta(hours=TF_HOURS[l2_tf])
    entry_td = pd.Timedelta(hours=TF_HOURS[entry_tf])
    top_life = pd.Timedelta(days=LIFE_DAYS[top_tf])
    l2_life = pd.Timedelta(days=LIFE_DAYS[l2_tf])

    fvgs_entry_sorted = sorted(fvgs_entry_pro, key=lambda x: x["c0_time"])
    fvgs_entry_c0_times = np.array([np.datetime64(z["c0_time"].tz_localize(None) if z["c0_time"].tz else z["c0_time"])
                                      for z in fvgs_entry_sorted])

    for fvg_top in fvgs_top:
        L1_close = fvg_top["time"] + top_td
        L1_max_end = L1_close + top_life
        inval = find_invalidation(df_top, fvg_top, top_td, L1_max_end)
        L1_active_end = inval if inval is not None else L1_max_end

        for ob_l2 in l2_zones:
            ob_l2_close = ob_l2["time"] + l2_td
            if ob_l2["prev_time"] < fvg_top["c0_time"]: continue
            if ob_l2_close > L1_active_end: continue
            if ob_l2["direction"] != fvg_top["direction"]: continue
            if not any_edge_inside(ob_l2["bottom"], ob_l2["top"],
                                    fvg_top["bottom"], fvg_top["top"]): continue

            search_start = ob_l2_close
            search_end = ob_l2_close + l2_life

            k0 = np.searchsorted(fvgs_entry_c0_times, np.datetime64(
                search_start.tz_localize(None) if search_start.tz else search_start), side="left")
            k1 = np.searchsorted(fvgs_entry_c0_times, np.datetime64(
                search_end.tz_localize(None) if search_end.tz else search_end), side="right")

            fvg_entry_found = None
            for ek in range(k0, k1):
                f_entry = fvgs_entry_sorted[ek]
                if f_entry["direction"] != fvg_top["direction"]: continue
                # Pro-trend check (close vs EMA200 на entry tf at c2_time)
                pro_ok = f_entry.get("pro_trend") == True
                if not pro_ok: continue
                # Overlap с L1 И L2
                if not zones_overlap(f_entry["bottom"], f_entry["top"],
                                      fvg_top["bottom"], fvg_top["top"]): continue
                if not zones_overlap(f_entry["bottom"], f_entry["top"],
                                      ob_l2["bottom"], ob_l2["top"]): continue
                fvg_entry_found = f_entry; break
            if fvg_entry_found is None: continue

            x1_b = max(fvg_top["bottom"], ob_l2["bottom"])
            x1_t = min(fvg_top["top"], ob_l2["top"])
            entry_close = fvg_entry_found["time"] + entry_td

            setups.append({
                "fvg_b": fvg_entry_found["bottom"], "fvg_t": fvg_entry_found["top"],
                "x1_bottom": x1_b, "x1_top": x1_t,
                "obh_b": ob_l2["bottom"], "obh_t": ob_l2["top"],
                "tf_minutes": int(TF_HOURS[entry_tf] * 60),
                "year": entry_close.year,
                "direction": fvg_entry_found["direction"],
                "signal_time": entry_close,
            })
            break
    return setups


def build_orders(s):
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


def evaluate(setups, rr, df_1m, df_1d, only_dom=False):
    rows = []
    for s in setups:
        tup = build_orders(s)
        if tup is None: continue
        entry, sl = tup
        if only_dom and not do_match_aligned(s, entry, df_1d): continue
        risk = abs(entry - sl)
        tp = entry + rr * risk if s["direction"] == "LONG" else entry - rr * risk
        outcome, R = simulate_safe(s, entry, sl, tp, df_1m)
        rows.append({"outcome": outcome, "R": R, "year": s["year"]})
    return pd.DataFrame(rows)


def report_metrics(df):
    cl = df[df["outcome"].isin(["win", "loss"])]
    if cl.empty: return None
    nc = len(cl); wins = (cl["R"] > 0).sum()
    wr = wins/nc*100; tot = cl["R"].sum()
    yr = cl.groupby("year")["R"].sum()
    bad = (yr < 0).sum()
    return {"n": nc, "wr": wr, "total": tot, "bad": bad, "n_yrs": len(yr)}


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

    # Pre-compute EMA200 for pro-trend entry on 1h, 2h
    df_1h["ema200"] = df_1h["close"].ewm(span=200, adjust=False).mean()
    df_2h["ema200"] = df_2h["close"].ewm(span=200, adjust=False).mean()

    fvgs_1d = collect_fvgs(df_1d, df_1d["atr14"], "1d")
    fvgs_12h = collect_fvgs(df_12h, df_12h["atr14"], "12h")
    obs_4h = collect_obs(df_4h, df_4h["atr14"], "4h")
    obs_6h = collect_obs(df_6h, df_6h["atr14"], "6h")
    obs_1h = collect_obs(df_1h, df_1h["atr14"], "1h")
    obs_2h = collect_obs(df_2h, df_2h["atr14"], "2h")
    fvgs_15m = collect_fvgs(df_15m, df_15m["atr14"], "15m")

    # FVG-1h/2h with pro-trend flag (close[c2_idx] vs EMA200 at c2_idx)
    def fvgs_with_pro_trend(df_e):
        out = []
        ema = df_e["ema200"].to_numpy()
        close_arr = df_e["close"].to_numpy()
        for idx in range(2, len(df_e) - 1):
            f = detect_fvg(df_e, idx)
            if f is None: continue
            a = float(df_e["atr14"].iloc[idx])
            if pd.isna(a) or a <= 0: continue
            em = float(ema[idx]); cl = float(close_arr[idx])
            pro = ((f.direction == "LONG" and cl > em) or
                   (f.direction == "SHORT" and cl < em))
            out.append({"tf": df_e.columns.tolist(), "direction": f.direction,
                         "bottom": f.bottom, "top": f.top, "atr": a,
                         "time": f.c2_time, "idx": idx,
                         "c0_time": f.c0_time, "pro_trend": pro})
        return out

    fvgs_1h_pro = fvgs_with_pro_trend(df_1h)
    fvgs_2h_pro = fvgs_with_pro_trend(df_2h)

    print(f"[INFO] zones collected: FVG-1d={len(fvgs_1d)}, FVG-12h={len(fvgs_12h)}, "
          f"OB-4h={len(obs_4h)}, OB-6h={len(obs_6h)}, OB-2h={len(obs_2h)}, "
          f"OB-1h={len(obs_1h)}, FVG-15m={len(fvgs_15m)}, "
          f"FVG-1h pro={len(fvgs_1h_pro)}, FVG-2h pro={len(fvgs_2h_pro)}")

    # ==========================================================
    # Chain definitions
    # ==========================================================
    chains = [
        ("A: FVG-d -> OB-4h -> OB-1h -> FVG-15m (baseline)",
            lambda: detect_4stage(fvgs_1d, obs_4h, "OB", obs_1h, "OB",
                                    fvgs_15m, "1d", "4h", "1h", "15m", df_1d)),
        ("B: FVG-12h -> OB-4h -> OB-1h -> FVG-15m",
            lambda: detect_4stage(fvgs_12h, obs_4h, "OB", obs_1h, "OB",
                                    fvgs_15m, "12h", "4h", "1h", "15m", df_12h)),
        ("C: FVG-d -> OB-4h -> FVG-1h pro (3-stage)",
            lambda: detect_3stage(fvgs_1d, obs_4h, "OB", fvgs_1h_pro,
                                    "1d", "4h", "1h", df_1d, None, None)),
        ("D: FVG-d -> OB-4h -> FVG-2h pro (3-stage)",
            lambda: detect_3stage(fvgs_1d, obs_4h, "OB", fvgs_2h_pro,
                                    "1d", "4h", "2h", df_1d, None, None)),
        ("E: FVG-d -> OB-4h -> OB-2h -> FVG-15m",
            lambda: detect_4stage(fvgs_1d, obs_4h, "OB", obs_2h, "OB",
                                    fvgs_15m, "1d", "4h", "2h", "15m", df_1d)),
        ("F: FVG-d -> OB-6h -> OB-2h -> FVG-15m",
            lambda: detect_4stage(fvgs_1d, obs_6h, "OB", obs_2h, "OB",
                                    fvgs_15m, "1d", "6h", "2h", "15m", df_1d)),
    ]

    # ==========================================================
    # Run survey
    # ==========================================================
    all_results = []
    RR_LIST = [1.5, 1.8, 2.0, 2.5]

    for label, build_fn in chains:
        print(f"\n{'='*70}\n{label}")
        print(f"{'='*70}")
        chain_setups = build_fn()
        # Dedup
        seen = set(); unique = []
        for s in chain_setups:
            key = (s["signal_time"], s["direction"], round(s["fvg_b"], 2), round(s["fvg_t"], 2))
            if key in seen: continue
            seen.add(key); unique.append(s)
        print(f"  setups: {len(unique)}")

        # Test без do_match
        print(f"\n  Без do_match:")
        for rr in RR_LIST:
            df = evaluate(unique, rr, df_1m, df_1d, only_dom=False)
            m = report_metrics(df)
            if m:
                print(f"    RR={rr}: n={m['n']:>3} WR={m['wr']:5.1f}% "
                      f"total={m['total']:+6.1f}R bad={m['bad']}/{m['n_yrs']}")
                all_results.append({"label": label, "rr": rr, "dom": False,
                                     "setups": len(unique), **m})

        # Test с do_match
        print(f"  С do_match:")
        for rr in RR_LIST:
            df = evaluate(unique, rr, df_1m, df_1d, only_dom=True)
            m = report_metrics(df)
            if m:
                print(f"    RR={rr}: n={m['n']:>3} WR={m['wr']:5.1f}% "
                      f"total={m['total']:+6.1f}R bad={m['bad']}/{m['n_yrs']}")
                all_results.append({"label": label, "rr": rr, "dom": True,
                                     "setups": len(unique), **m})

    # ==========================================================
    # FINAL RANKINGS
    # ==========================================================
    print(f"\n\n{'='*80}\nFINAL RANKINGS")
    print(f"{'='*80}")

    print(f"\n--- TOP 10 by total R (без bad-year filter) ---")
    by_total = sorted(all_results, key=lambda x: x["total"], reverse=True)
    for r in by_total[:10]:
        dom_str = "+do_match" if r["dom"] else "no_dom"
        print(f"  {r['label'][:40]:<40} RR={r['rr']} {dom_str:<10} "
              f"n={r['n']:>3} WR={r['wr']:5.1f}% total={r['total']:+6.1f}R "
              f"bad={r['bad']}/{r['n_yrs']}")

    print(f"\n--- TOP 10 by total R (с bad_yrs <= 1) ---")
    clean = [r for r in all_results if r["bad"] <= 1]
    clean = sorted(clean, key=lambda x: x["total"], reverse=True)
    for r in clean[:10]:
        dom_str = "+do_match" if r["dom"] else "no_dom"
        print(f"  {r['label'][:40]:<40} RR={r['rr']} {dom_str:<10} "
              f"n={r['n']:>3} WR={r['wr']:5.1f}% total={r['total']:+6.1f}R "
              f"bad={r['bad']}/{r['n_yrs']}")

    print(f"\n--- BEST PER CHAIN (by total R) ---")
    by_chain = defaultdict(list)
    for r in all_results:
        by_chain[r["label"]].append(r)
    for label, rs in by_chain.items():
        best = max(rs, key=lambda x: x["total"])
        dom_str = "+do_match" if best["dom"] else "no_dom"
        print(f"  {label[:42]:<42}: RR={best['rr']} {dom_str:<10} "
              f"total={best['total']:+6.1f}R WR={best['wr']:.1f}% "
              f"bad={best['bad']}/{best['n_yrs']}")

    print(f"\n[TIME] {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
