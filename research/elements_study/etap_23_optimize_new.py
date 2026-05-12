"""Этап 23: 3-stage оптимизация двух best NEW кандидатов из etap_22.

Цель: проверить, могут ли новые комбинации превзойти текущий D2 (+89.5R / R/tr 0.297)
после оптимизации entry/SL/RR.

NEW бази:
  N1 = OB+FVG-12h confluence x FVG-2h pro  (WR 60.2%, +24R, 0.56/нед, R/tr 0.203)
       Сильнейший в семействе А по WR.
  N2 = OB-12h+OB-4h triple stack x FVG-1h pro  (WR 57.9%, +22R, 0.70/нед, R/tr 0.157)
       Сильнейший в семействе C.

Stages — same as etap_19:
  S1: entry_pct sweep
  S2: SL sweep (sl_buf x min_sl_pct)
  S3: RR sweep
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

from itertools import product
from pathlib import Path
import time
import numpy as np
import pandas as pd

from data_manager import load_df
from strategies.strategy_1_1_1 import detect_ob_pair, detect_fvg

SYMBOL = "BTCUSDT"
START_DATE = "2020-01-01"

TF_LIFE_DAYS = {"1d": 30, "12h": 14, "6h": 10, "4h": 5,
                "2h": 3, "1h": 2, "15m": 1}

OUT_DIR = Path("research/elements_study/output")

ENTRY_PCTS = [0.0, 0.25, 0.5, 0.75, 1.0]
SL_BUFS = [0.0, 0.15, 0.3, 0.5, 0.7]
MIN_SL_PCTS = [0.5, 1.0, 1.5]
RRS = [1.5, 1.75, 2.0, 2.25, 2.5, 3.0]


def compute_atr(df, period=14):
    high = df["high"]; low = df["low"]; pc = df["close"].shift(1)
    tr = pd.concat([(high-low),(high-pc).abs(),(low-pc).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


class FastSim:
    def __init__(self, df_1m):
        self.ts = df_1m.index.values
        self.high = df_1m["high"].to_numpy(dtype=float)
        self.low = df_1m["low"].to_numpy(dtype=float)

    def simulate(self, direction, entry, sl, tp, start_time, timeout_days):
        end_time = start_time + pd.Timedelta(days=timeout_days)
        i0 = np.searchsorted(self.ts, np.datetime64(start_time.tz_localize(None) if start_time.tz else start_time))
        i1 = np.searchsorted(self.ts, np.datetime64(end_time.tz_localize(None) if end_time.tz else end_time))
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
        out.append({"kind": "OB", "tf": tf_label, "direction": ob.direction,
                    "bottom": ob.bottom, "top": ob.top, "atr": atr,
                    "time": ob.cur_time, "idx": idx})
    return out


def collect_fvgs(df, atr_series, tf_label):
    out = []
    for idx in range(2, len(df) - 1):
        f = detect_fvg(df, idx)
        if f is None: continue
        atr = float(atr_series.iloc[idx])
        if pd.isna(atr) or atr <= 0: continue
        out.append({"kind": "FVG", "tf": tf_label, "direction": f.direction,
                    "bottom": f.bottom, "top": f.top, "atr": atr,
                    "time": f.c2_time, "idx": idx})
    return out


def collect_zone_confluence(zones1, zones2, max_offset_bars=10):
    out = []
    z2_sorted = sorted(zones2, key=lambda x: x["idx"])
    z2_idxs = np.array([z["idx"] for z in z2_sorted])
    for z1 in zones1:
        i_lo = np.searchsorted(z2_idxs, z1["idx"] - max_offset_bars, side="left")
        i_hi = np.searchsorted(z2_idxs, z1["idx"] + max_offset_bars, side="right")
        for ti in range(i_lo, i_hi):
            z2 = z2_sorted[ti]
            if z2["direction"] != z1["direction"]: continue
            zb = max(z1["bottom"], z2["bottom"])
            zt = min(z1["top"], z2["top"])
            if zt <= zb: continue
            out.append({"tf": z1["tf"], "direction": z1["direction"],
                        "bottom": zb, "top": zt, "atr": z1["atr"],
                        "time": max(z1["time"], z2["time"])})
    return out


def collect_triple_stack(htf_anchors, mid_zones, htf_tf, mid_tf):
    out = []
    htf_tf_td = pd.Timedelta(htf_tf)
    mid_sorted = sorted(mid_zones, key=lambda x: x["time"])
    mid_times = np.array([np.datetime64(z["time"].tz_localize(None) if z["time"].tz else z["time"])
                           for z in mid_sorted])
    for a in htf_anchors:
        a_start = a["time"] + htf_tf_td
        a_end = a["time"] + pd.Timedelta(days=TF_LIFE_DAYS.get(htf_tf, 5))
        if a_end <= a_start: continue
        i_start = np.searchsorted(mid_times,
                                    np.datetime64(a_start.tz_localize(None) if a_start.tz else a_start),
                                    side="right")
        i_end = np.searchsorted(mid_times,
                                  np.datetime64(a_end.tz_localize(None) if a_end.tz else a_end),
                                  side="right")
        for ti in range(i_start, i_end):
            m = mid_sorted[ti]
            if m["direction"] != a["direction"]: continue
            if not (m["top"] >= a["bottom"] and m["bottom"] <= a["top"]):
                continue
            zb = max(m["bottom"], a["bottom"])
            zt = min(m["top"], a["top"])
            if zt <= zb: continue
            mid_confirm = m["time"] + pd.Timedelta(mid_tf)
            out.append({"tf": mid_tf, "direction": m["direction"],
                        "bottom": zb, "top": zt, "atr": m["atr"],
                        "time": mid_confirm})
            break
    return out


def zones_overlap(b1, t1, b2, t2):
    return not (t1 < b2 or t2 < b1)


def build_base_setups(anchors, triggers, df_trig, t_tf, anchor_offset_td, life_days, filt):
    a_life = pd.Timedelta(days=life_days)
    ema_arr = df_trig["ema200"].to_numpy()
    close_arr = df_trig["close"].to_numpy()
    t_sorted = sorted(triggers, key=lambda x: x["time"])
    t_times = np.array([np.datetime64(t["time"].tz_localize(None) if t["time"].tz else t["time"])
                         for t in t_sorted])
    setups = []
    for a in anchors:
        a_start = a["time"] + anchor_offset_td
        a_end = a["time"] + a_life
        if a_end <= a_start: continue
        i_start = np.searchsorted(t_times,
                                   np.datetime64(a_start.tz_localize(None) if a_start.tz else a_start),
                                   side="right")
        i_end = np.searchsorted(t_times,
                                 np.datetime64(a_end.tz_localize(None) if a_end.tz else a_end),
                                 side="right")
        for ti in range(i_start, i_end):
            t = t_sorted[ti]
            if t["direction"] != a["direction"]: continue
            if not zones_overlap(t["bottom"], t["top"], a["bottom"], a["top"]):
                continue
            em = float(ema_arr[t["idx"]])
            cl = float(close_arr[t["idx"]])
            pro = ((t["direction"] == "LONG" and cl > em) or
                   (t["direction"] == "SHORT" and cl < em))
            if filt == "pro" and not pro: continue
            setups.append({"trigger_time": t["time"], "direction": t["direction"],
                            "fvg_bottom": t["bottom"], "fvg_top": t["top"],
                            "fvg_atr": t["atr"], "year": t["time"].year, "pro": pro})
            break
    return setups


def evaluate(setups, sim, t_tf, entry_pct, sl_buf, min_sl_pct, rr):
    rows = []
    for s in setups:
        direction = s["direction"]
        zb = s["fvg_bottom"]; zt = s["fvg_top"]; atr = s["fvg_atr"]
        size = zt - zb
        if direction == "LONG":
            entry = zb + entry_pct * size
            atr_sl = zb - sl_buf * atr
            sl = min(atr_sl, entry - entry * min_sl_pct / 100)
        else:
            entry = zt - entry_pct * size
            atr_sl = zt + sl_buf * atr
            sl = max(atr_sl, entry + entry * min_sl_pct / 100)
        risk = abs(entry - sl)
        if risk <= 0: continue
        if direction == "LONG":
            tp = entry + rr * risk
        else:
            tp = entry - rr * risk
        start = s["trigger_time"] + pd.Timedelta(t_tf)
        outcome, R = sim.simulate(direction, entry, sl, tp, start,
                                    TF_LIFE_DAYS.get(t_tf, 5))
        rows.append({"outcome": outcome, "R": R, "year": s["year"]})
    if not rows: return None
    df_e = pd.DataFrame(rows)
    closed = df_e[df_e["outcome"].isin(["win", "loss"])]
    if closed.empty: return None
    w = (closed["outcome"] == "win").sum()
    return {"n_total": len(df_e), "n_closed": len(closed),
            "WR": round(w/len(closed)*100, 1),
            "total_R": round(closed["R"].sum(), 1),
            "R_tr": round(closed["R"].mean(), 3),
            "df": closed}


def optimize(setups, sim, t_tf, label):
    print(f"\n{'='*70}\n{label}\n{'='*70}")
    print(f"  base setups: {len(setups)}")

    # S1
    print(f"\n  [S1] entry sweep")
    s1_rows = []
    for ep in ENTRY_PCTS:
        r = evaluate(setups, sim, t_tf, ep, 0.3, 1.0, 1.5)
        if r:
            row = {"stage": 1, "entry_pct": ep, "sl_buf": 0.3,
                    "min_sl": 1.0, "RR": 1.5, "n": r["n_total"],
                    "WR": r["WR"], "total_R": r["total_R"], "R_tr": r["R_tr"]}
            s1_rows.append(row)
    s1 = pd.DataFrame(s1_rows)
    print(s1[["entry_pct", "n", "WR", "total_R", "R_tr"]].to_string(index=False))
    s1_pass = s1[s1["WR"] >= 50]
    if s1_pass.empty: s1_pass = s1
    best_entry = s1_pass.sort_values("total_R", ascending=False).iloc[0]["entry_pct"]
    print(f"  -> best entry={best_entry}")

    # S2
    print(f"\n  [S2] SL sweep")
    s2_rows = []
    for sl_buf, msp in product(SL_BUFS, MIN_SL_PCTS):
        r = evaluate(setups, sim, t_tf, best_entry, sl_buf, msp, 1.5)
        if r:
            s2_rows.append({"sl_buf": sl_buf, "min_sl": msp, "n": r["n_total"],
                              "WR": r["WR"], "total_R": r["total_R"], "R_tr": r["R_tr"]})
    s2 = pd.DataFrame(s2_rows)
    s2_valid = s2[(s2["min_sl"] >= 1.0) & (s2["WR"] >= 50)]
    if s2_valid.empty:
        s2_valid = s2[s2["min_sl"] >= 1.0]
    if s2_valid.empty: s2_valid = s2
    print(s2.sort_values("total_R", ascending=False).head(8).to_string(index=False))
    best_sl = s2_valid.sort_values("total_R", ascending=False).iloc[0]
    print(f"  -> sl_buf={best_sl['sl_buf']}, min_sl={best_sl['min_sl']}")

    # S3
    print(f"\n  [S3] RR sweep")
    s3_rows = []
    for rr in RRS:
        r = evaluate(setups, sim, t_tf, best_entry, best_sl["sl_buf"],
                       best_sl["min_sl"], rr)
        if r:
            s3_rows.append({"RR": rr, "n": r["n_total"], "WR": r["WR"],
                              "total_R": r["total_R"], "R_tr": r["R_tr"]})
    s3 = pd.DataFrame(s3_rows)
    print(s3.to_string(index=False))
    s3_valid = s3[s3["WR"] >= 45]
    if s3_valid.empty: s3_valid = s3
    best_rr = s3_valid.sort_values("total_R", ascending=False).iloc[0]
    print(f"\n  *** FINAL: entry={best_entry}, sl_buf={best_sl['sl_buf']}, "
            f"min_sl={best_sl['min_sl']}, RR={best_rr['RR']}")
    print(f"     Result: WR={best_rr['WR']}%, total_R={best_rr['total_R']}, "
            f"R/tr={best_rr['R_tr']}")


def main():
    t0 = time.time()
    print("[INFO] loading")
    needed = ["1h", "2h", "4h", "12h"]
    dfs = {}
    for tf in needed:
        df = load_df(SYMBOL, tf)
        df = df[df.index >= pd.Timestamp(START_DATE, tz="UTC")].copy()
        df["atr14"] = compute_atr(df, 14)
        df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
        dfs[tf] = df
        print(f"  {tf}: {len(df)} bars")
    df_1m = load_df(SYMBOL, "1m")
    df_1m = df_1m[df_1m.index >= pd.Timestamp(START_DATE, tz="UTC")]
    sim = FastSim(df_1m)

    obs_4h = collect_obs(dfs["4h"], dfs["4h"]["atr14"], "4h")
    obs_12h = collect_obs(dfs["12h"], dfs["12h"]["atr14"], "12h")
    fvgs_12h = collect_fvgs(dfs["12h"], dfs["12h"]["atr14"], "12h")
    fvgs_2h = collect_fvgs(dfs["2h"], dfs["2h"]["atr14"], "2h")
    fvgs_1h = collect_fvgs(dfs["1h"], dfs["1h"]["atr14"], "1h")

    # ---- N1: OB+FVG-12h confluence x FVG-2h pro ----
    confl_12h = collect_zone_confluence(obs_12h, fvgs_12h, max_offset_bars=10)
    print(f"\n  OB+FVG-12h confluence anchors: {len(confl_12h)}")
    n1_setups = build_base_setups(confl_12h, fvgs_2h, dfs["2h"], "2h",
                                     pd.Timedelta("12h"),  # use 12h as confirm offset (approx)
                                     14, "pro")
    optimize(n1_setups, sim, "2h", "N1: OB+FVG-12h confluence x FVG-2h pro")

    # ---- N2: triple OB-12h+OB-4h x FVG-1h pro ----
    triple = collect_triple_stack(obs_12h, obs_4h, "12h", "4h")
    print(f"\n  OB-12h+OB-4h triple anchors: {len(triple)}")
    n2_setups = build_base_setups(triple, fvgs_1h, dfs["1h"], "1h",
                                     pd.Timedelta(0),  # already confirmed
                                     5, "pro")
    optimize(n2_setups, sim, "1h", "N2: OB-12h+OB-4h triple x FVG-1h pro")

    print(f"\n[TIME] total {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
