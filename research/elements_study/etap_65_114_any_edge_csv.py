"""Этап 65: CSV позиций для 1.1.4 any_edge + do_match (правильная семантика).

Параметры:
  - Каскад: L1 FVG-d/12h → L2 OB-4h/6h в зоне L1 (any_edge) →
            L3 OB-1h/2h в зоне L1 ∩ L2 (any_edge) →
            L4 FVG-15m в зоне L1 ∩ L2 (overlap)
  - Invalidation tracking для L1
  - SL anchor x1 = пересечение FVG-1d ∩ OB-4h
  - entry=0.7, sl=0.35L/0.65S, min_sl=1%, RR=1.8
  - + do_match aligned filter

Best variant: ALL + do_match RR=1.8 → +27.8R / WR 47.1% / 1 bad yr
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
OUT_FULL = OUT_DIR / "etap65_114_anyedge_positions_full.csv"
OUT_HUMAN = OUT_DIR / "etap65_114_anyedge_positions_human.csv"


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
        prev = df.iloc[idx - 1]
        out.append({"tf": tf, "direction": ob.direction,
                     "bottom": ob.bottom, "top": ob.top, "atr": a,
                     "time": ob.cur_time, "idx": idx,
                     "prev_time": ob.prev_time,
                     "origin": float(prev["open"])})
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
    """Хотя бы одна грань OB внутри big-зоны."""
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


def detect_114_anyedge(fvgs_top, obs_macro, obs_mid, fvgs_entry,
                        top_tf, macro_tf, mid_tf, entry_tf, df_top):
    setups = []
    top_td = pd.Timedelta(hours=TF_HOURS[top_tf])
    macro_td = pd.Timedelta(hours=TF_HOURS[macro_tf])
    mid_td = pd.Timedelta(hours=TF_HOURS[mid_tf])
    entry_td = pd.Timedelta(hours=TF_HOURS[entry_tf])
    top_life = pd.Timedelta(days=LIFE_DAYS[top_tf])
    mid_life = pd.Timedelta(days=LIFE_DAYS[mid_tf])

    obs_mid_sorted = sorted(obs_mid, key=lambda x: x["prev_time"])
    fvgs_entry_sorted = sorted(fvgs_entry, key=lambda x: x["c0_time"])
    obs_mid_prev_times = np.array([np.datetime64(z["prev_time"].tz_localize(None) if z["prev_time"].tz else z["prev_time"])
                                     for z in obs_mid_sorted])
    fvgs_entry_c0_times = np.array([np.datetime64(z["c0_time"].tz_localize(None) if z["c0_time"].tz else z["c0_time"])
                                      for z in fvgs_entry_sorted])

    for fvg_top in fvgs_top:
        L1_close = fvg_top["time"] + top_td
        L1_max_end = L1_close + top_life
        inval_time = find_invalidation(df_top, fvg_top, top_td, L1_max_end)
        L1_active_end = inval_time if inval_time is not None else L1_max_end

        for ob_macro in obs_macro:
            ob_macro_close = ob_macro["time"] + macro_td
            if ob_macro["prev_time"] < fvg_top["c0_time"]: continue
            if ob_macro_close > L1_active_end: continue
            if ob_macro["direction"] != fvg_top["direction"]: continue
            # any_edge: OB-4h в зоне FVG-1d
            if not any_edge_inside(ob_macro["bottom"], ob_macro["top"],
                                    fvg_top["bottom"], fvg_top["top"]): continue

            l3_search_start = ob_macro_close
            l3_search_end = l3_search_start + mid_life

            j0 = np.searchsorted(obs_mid_prev_times, np.datetime64(
                l3_search_start.tz_localize(None) if l3_search_start.tz else l3_search_start), side="left")
            j1 = np.searchsorted(obs_mid_prev_times, np.datetime64(
                l3_search_end.tz_localize(None) if l3_search_end.tz else l3_search_end), side="right")

            ob_mid_found = None
            fvg_entry_found = None
            for oj in range(j0, j1):
                ob_mid = obs_mid_sorted[oj]
                if ob_mid["direction"] != fvg_top["direction"]: continue
                # any_edge: OB-1h в зоне FVG-1d И OB-4h
                if not any_edge_inside(ob_mid["bottom"], ob_mid["top"],
                                        fvg_top["bottom"], fvg_top["top"]): continue
                if not any_edge_inside(ob_mid["bottom"], ob_mid["top"],
                                        ob_macro["bottom"], ob_macro["top"]): continue

                L3_start = ob_mid["prev_time"]
                L3_close = ob_mid["time"] + mid_td
                l4_max_c2_open = L3_close - entry_td

                k0 = np.searchsorted(fvgs_entry_c0_times, np.datetime64(
                    L3_start.tz_localize(None) if L3_start.tz else L3_start), side="left")
                f_e_found = None
                for ek in range(k0, len(fvgs_entry_sorted)):
                    f_entry = fvgs_entry_sorted[ek]
                    if f_entry["c0_time"] < L3_start: continue
                    if f_entry["time"] > l4_max_c2_open: continue
                    if f_entry["c0_time"] > L3_close: break
                    if f_entry["direction"] != fvg_top["direction"]: continue
                    # L4 — overlap (по user-spec "хотя бы одной частью")
                    if not zones_overlap(f_entry["bottom"], f_entry["top"],
                                          fvg_top["bottom"], fvg_top["top"]): continue
                    if not zones_overlap(f_entry["bottom"], f_entry["top"],
                                          ob_macro["bottom"], ob_macro["top"]): continue
                    f_e_found = f_entry; break
                if f_e_found is None: continue
                ob_mid_found = ob_mid
                fvg_entry_found = f_e_found
                break

            if ob_mid_found is None or fvg_entry_found is None: continue

            x1_bottom = max(fvg_top["bottom"], ob_macro["bottom"])
            x1_top = min(fvg_top["top"], ob_macro["top"])
            L3_close = ob_mid_found["time"] + mid_td

            setups.append({
                "anchor_kind": "FVG", "anchor_tf": top_tf,
                "macro_tf": macro_tf, "mid_tf": mid_tf,
                "anchor_c0_time": fvg_top["c0_time"],
                "anchor_c2_close": L1_close,
                "L1_active_end": L1_active_end,
                "L1_invalidated": inval_time is not None,
                "macro_prev_time": ob_macro["prev_time"],
                "macro_cur_close": ob_macro_close,
                "mid_prev_time": ob_mid_found["prev_time"],
                "mid_cur_close": L3_close,
                "trigger_c0_time": fvg_entry_found["c0_time"],
                "trigger_c2_time": fvg_entry_found["time"],
                "trigger_c2_close": fvg_entry_found["time"] + entry_td,
                # Zones
                "anchor_fvg_bot": fvg_top["bottom"],
                "anchor_fvg_top": fvg_top["top"],
                "macro_ob_bot": ob_macro["bottom"],
                "macro_ob_top": ob_macro["top"],
                "mid_ob_bot": ob_mid_found["bottom"],
                "mid_ob_top": ob_mid_found["top"],
                "fvg_b": fvg_entry_found["bottom"],
                "fvg_t": fvg_entry_found["top"],
                "x1_bottom": x1_bottom, "x1_top": x1_top,
                "obh_b": ob_mid_found["bottom"],
                "obh_t": ob_mid_found["top"],
                "tf_minutes": 15,
                "year": L3_close.year,
                "month": L3_close.month,
                "direction": fvg_entry_found["direction"],
                "signal_time": L3_close,
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
    if risk <= 0: return ("invalid", 0.0, None, None)
    entry_window_start = s["signal_time"]
    end_time = entry_window_start + pd.Timedelta(days=max_hold_days)
    et64 = np.datetime64(entry_window_start.tz_localize(None) if entry_window_start.tz else entry_window_start)
    ee64 = np.datetime64(end_time.tz_localize(None) if end_time.tz else end_time)
    i0 = np.searchsorted(df_1m.index.values, et64)
    i1 = np.searchsorted(df_1m.index.values, ee64)
    if i1 <= i0: return ("no_data", 0.0, None, None)
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
    if tp_pre < ent_idx: return ("no_entry", 0.0, None, None)
    if ent_idx >= len(h): return ("not_filled", 0.0, None, None)
    fill_ts = pd.Timestamp(df_1m.index.values[i0 + ent_idx]).tz_localize("UTC")
    post_h = h[ent_idx:]; post_l = l[ent_idx:]
    if direction == "LONG":
        sl_m = post_l <= sl; tp_m = post_h >= tp
    else:
        sl_m = post_h >= sl; tp_m = post_l <= tp
    sl_first = int(np.argmax(sl_m)) if sl_m.any() else -1
    tp_first = int(np.argmax(tp_m)) if tp_m.any() else -1
    if sl_first == -1 and tp_first == -1: return ("open", 0.0, fill_ts, None)
    if sl_first == -1:
        close_ts = pd.Timestamp(df_1m.index.values[i0 + ent_idx + tp_first]).tz_localize("UTC")
        return ("win", abs(tp - entry) / risk, fill_ts, close_ts)
    if tp_first == -1:
        close_ts = pd.Timestamp(df_1m.index.values[i0 + ent_idx + sl_first]).tz_localize("UTC")
        return ("loss", -1.0, fill_ts, close_ts)
    if tp_first < sl_first:
        close_ts = pd.Timestamp(df_1m.index.values[i0 + ent_idx + tp_first]).tz_localize("UTC")
        return ("win", abs(tp - entry) / risk, fill_ts, close_ts)
    close_ts = pd.Timestamp(df_1m.index.values[i0 + ent_idx + sl_first]).tz_localize("UTC")
    return ("loss", -1.0, fill_ts, close_ts)


OUTCOME_RU = {
    "win":        "ПРИБЫЛЬ (TP)",
    "loss":       "УБЫТОК (SL)",
    "open":       "осталась открытой",
    "not_filled": "лимит не заполнился",
    "no_entry":   "пропуск (TP до entry)",
    "no_data":    "нет данных",
    "invalid":    "невалидный сетап",
}


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

    print("[INFO] detect 1.1.4 any_edge")
    df_top_map = {"1d": df_1d, "12h": df_12h}
    all_setups = []
    for top_tf, top_zones in [("1d", fvgs_1d), ("12h", fvgs_12h)]:
        for macro_tf, macro_zones in [("4h", obs_4h), ("6h", obs_6h)]:
            for mid_tf, mid_zones in [("1h", obs_1h), ("2h", obs_2h)]:
                chains = detect_114_anyedge(top_zones, macro_zones, mid_zones,
                                              fvgs_15m, top_tf, macro_tf, mid_tf, "15m",
                                              df_top_map[top_tf])
                all_setups.extend(chains)
    seen = set(); unique = []
    for s in all_setups:
        key = (s["signal_time"], s["direction"], round(s["fvg_b"], 2), round(s["fvg_t"], 2))
        if key in seen: continue
        seen.add(key); unique.append(s)
    print(f"  setups: {len(unique)}")

    print("[INFO] simulate + filter by do_match aligned")
    rows = []
    skipped_dom = 0
    for s in unique:
        tup = build_orders(s)
        if tup is None: continue
        entry, sl = tup
        ts = s["signal_time"]
        idx_d = df_1d.index.searchsorted(ts, side="right") - 1
        do = float(df_1d["open"].iloc[idx_d]) if idx_d >= 0 else None
        if do is None or pd.isna(do):
            skipped_dom += 1; continue
        if s["direction"] == "LONG":
            do_aligned = entry < do
            do_pos = "discount" if do_aligned else ("premium" if entry > do else "mid")
        else:
            do_aligned = entry > do
            do_pos = "premium" if do_aligned else ("discount" if entry < do else "mid")
        if not do_aligned:
            skipped_dom += 1; continue

        sw = check_swept(s, df_1h, df_2h)
        risk = abs(entry - sl)
        tp = entry + RR * risk if s["direction"] == "LONG" else entry - RR * risk
        outcome, R, fill_ts, close_ts = simulate_safe(s, entry, sl, tp, df_1m)

        risk_pct = risk / entry * 100
        target_pct = RR * risk_pct
        if outcome == "win":
            actual_R = R; actual_pnl_pct = target_pct; exit_price = tp
        elif outcome == "loss":
            actual_R = -1.0; actual_pnl_pct = -risk_pct; exit_price = sl
        else:
            actual_R = 0.0; actual_pnl_pct = 0.0; exit_price = None

        hold_h = ((close_ts - s["signal_time"]).total_seconds() / 3600
                    if close_ts is not None else None)
        time_to_fill_h = ((fill_ts - s["signal_time"]).total_seconds() / 3600
                           if fill_ts is not None else None)

        rows.append({
            "trade_id": len(rows) + 1,
            "year": s["year"], "month": s["month"],
            "direction": s["direction"],
            "anchor_c0_time_utc": s["anchor_c0_time"].strftime("%Y-%m-%d %H:%M"),
            "anchor_c2_close_utc": s["anchor_c2_close"].strftime("%Y-%m-%d %H:%M"),
            "L1_invalidated": s["L1_invalidated"],
            "L1_active_end_utc": s["L1_active_end"].strftime("%Y-%m-%d %H:%M"),
            "macro_prev_utc": s["macro_prev_time"].strftime("%Y-%m-%d %H:%M"),
            "macro_close_utc": s["macro_cur_close"].strftime("%Y-%m-%d %H:%M"),
            "mid_prev_utc": s["mid_prev_time"].strftime("%Y-%m-%d %H:%M"),
            "mid_close_utc": s["mid_cur_close"].strftime("%Y-%m-%d %H:%M"),
            "trigger_c0_utc": s["trigger_c0_time"].strftime("%Y-%m-%d %H:%M"),
            "trigger_c2_close_utc": s["trigger_c2_close"].strftime("%Y-%m-%d %H:%M"),
            "signal_time_utc": s["signal_time"].strftime("%Y-%m-%d %H:%M"),
            "fill_time_utc": fill_ts.strftime("%Y-%m-%d %H:%M") if fill_ts is not None else "",
            "exit_time_utc": close_ts.strftime("%Y-%m-%d %H:%M") if close_ts is not None else "",
            "anchor_tf": s["anchor_tf"], "macro_tf": s["macro_tf"],
            "mid_tf": s["mid_tf"], "swept": sw,
            "L1_anchor_fvg_bot": round(s["anchor_fvg_bot"], 2),
            "L1_anchor_fvg_top": round(s["anchor_fvg_top"], 2),
            "L2_macro_ob_bot": round(s["macro_ob_bot"], 2),
            "L2_macro_ob_top": round(s["macro_ob_top"], 2),
            "L3_mid_ob_bot": round(s["mid_ob_bot"], 2),
            "L3_mid_ob_top": round(s["mid_ob_top"], 2),
            "L4_fvg_15m_bot": round(s["fvg_b"], 2),
            "L4_fvg_15m_top": round(s["fvg_t"], 2),
            "x1_intersect_bot": round(s["x1_bottom"], 2),
            "x1_intersect_top": round(s["x1_top"], 2),
            "daily_open": round(do, 2),
            "do_pos": do_pos,
            "entry_price": round(entry, 2),
            "sl_price": round(sl, 2),
            "tp_price": round(tp, 2),
            "risk_pct": round(risk_pct, 3),
            "target_pct": round(target_pct, 3),
            "rr_target": RR,
            "outcome_code": outcome,
            "outcome_ru": OUTCOME_RU.get(outcome, outcome),
            "result_R": round(actual_R, 3),
            "result_pnl_pct": round(actual_pnl_pct, 3),
            "exit_price": round(exit_price, 2) if exit_price is not None else "",
            "time_to_fill_hours": round(time_to_fill_h, 1) if time_to_fill_h is not None else "",
            "hold_hours": round(hold_h, 1) if hold_h is not None else "",
            "hold_days": round(hold_h / 24, 2) if hold_h is not None else "",
        })

    df_full = pd.DataFrame(rows)
    cum = 0.0; cum_p = 0.0
    cum_R_list = []; cum_p_list = []
    for _, row in df_full.iterrows():
        if row["outcome_code"] in ("win", "loss"):
            cum += row["result_R"]
            cum_p += row["result_pnl_pct"]
        cum_R_list.append(round(cum, 2))
        cum_p_list.append(round(cum_p, 2))
    df_full["cumulative_R"] = cum_R_list
    df_full["cumulative_pnl_pct"] = cum_p_list

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df_full.to_csv(OUT_FULL, index=False, encoding="utf-8-sig")
    print(f"\n[OK] full CSV: {OUT_FULL}")
    print(f"     {len(df_full)} positions, {len(df_full.columns)} columns")

    cols_human = [
        ("trade_id", "№"),
        ("anchor_c2_close_utc", "FVG-d/12h готов"),
        ("anchor_tf", "ТФ FVG"),
        ("L1_invalidated", "FVG invalidated?"),
        ("macro_close_utc", "OB-4h/6h close"),
        ("macro_tf", "ТФ макро OB"),
        ("mid_close_utc", "OB-1h/2h close (= signal)"),
        ("mid_tf", "ТФ mid OB"),
        ("trigger_c2_close_utc", "FVG-15m c2 close"),
        ("direction", "Направление"),
        ("entry_price", "Вход"),
        ("sl_price", "Стоп"),
        ("tp_price", "Цель"),
        ("daily_open", "Daily Open"),
        ("do_pos", "Где entry"),
        ("swept", "SWEPT?"),
        ("risk_pct", "Риск %"),
        ("outcome_code", "Результат"),
        ("result_R", "R"),
        ("result_pnl_pct", "Прибыль %"),
        ("hold_hours", "Удержание ч"),
        ("cumulative_R", "Накопит. R"),
    ]
    df_human = df_full[[c for c, _ in cols_human]].copy()
    df_human["outcome_code"] = df_full["outcome_code"].map(OUTCOME_RU).fillna(df_full["outcome_code"])
    df_human["direction"] = df_full["direction"].map({"LONG": "ЛОНГ", "SHORT": "ШОРТ"})
    df_human["do_pos"] = df_full["do_pos"].map({"discount": "ниже DO", "premium": "выше DO", "mid": "на DO"})
    df_human["L1_invalidated"] = df_full["L1_invalidated"].map({True: "да", False: "нет"})
    df_human["swept"] = df_full["swept"].map({True: "да", False: "нет"}).fillna("")
    df_human.columns = [name for _, name in cols_human]
    df_human.to_csv(OUT_HUMAN, index=False, encoding="utf-8-sig")
    print(f"\n[OK] human CSV: {OUT_HUMAN}")
    print(f"     {len(df_human)} positions, {len(df_human.columns)} columns")

    print("\n" + "=" * 70)
    print("СВОДКА")
    print("=" * 70)
    closed = df_full[df_full["outcome_code"].isin(["win", "loss"])]
    print(f"  Setups unique:                       {len(unique)}")
    print(f"  Отрезано do_match counter:           {skipped_dom}")
    print(f"  Прошло do_match aligned:             {len(df_full)}")
    print(f"  L1 invalidated:                      {df_full['L1_invalidated'].sum()}")
    print(f"  SWEPT setups:                        {(df_full['swept'] == True).sum()}")
    print(f"  Закрыто:                             {len(closed)}")
    print(f"     прибыль:                          {(closed['outcome_code'] == 'win').sum()}")
    print(f"     убыток:                           {(closed['outcome_code'] == 'loss').sum()}")
    n_no_entry = (df_full["outcome_code"] == "no_entry").sum()
    n_no_fill = (df_full["outcome_code"] == "not_filled").sum()
    n_open = (df_full["outcome_code"] == "open").sum()
    print(f"     no_entry:                         {n_no_entry}")
    print(f"     not_filled:                       {n_no_fill}")
    print(f"     open:                             {n_open}")
    if len(closed) > 0:
        wr = (closed["outcome_code"] == "win").mean() * 100
        total_R = closed["result_R"].sum()
        years = (df_1d.index[-1] - df_1d.index[0]).days / 365
        yr = closed.groupby("year")["result_R"].sum()
        bad = (yr < 0).sum()
        print(f"\n  WinRate:        {wr:.1f}%")
        print(f"  Total R:        {total_R:+.1f}")
        print(f"  Per year:       {total_R/years:+.1f}R")
        print(f"  Bad years:      {bad}/{len(yr)}")
        print(f"  Avg hold:       {closed['hold_hours'].astype(float).mean():.1f}h")

    print(f"\n[TIME] {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
