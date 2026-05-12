"""Этап 34: ЧЕСТНЫЙ re-test Strategy 1.1.1 с нашими стандартами.

4-уровневый каскад как в оригинале:
  L1: OB-{1d, 12h}  ← anchor
  L2: FVG-{4h, 6h}  ← macro confirmation (в зоне L1, same direction)
  L3: OB-{1h, 2h}   ← intermediate (в зоне L2 AND L1, same direction)
  L4: FVG-{15m}     ← entry trigger (в зоне L3, same direction)

Стандартизация (отличия от оригинала):
  ✓ Anchor confirmation timing: cur_close = cur_open + tf (для каждого уровня)
  ✓ min_sl_pct = 1.0% (вместо 0.15 x OB_depth = ~0.1%)
  ✓ entry_pct = 0.5 (mid FVG, вместо 0.80 hardcoded)
  ✓ 6 years (2020-2026) вместо 3y
  ✓ Round RR: 1.0, 1.5, 2.0, 2.5
  ✓ Year-by-year breakdown
  ✓ Dedup: 1 setup на цепочку (первая qualifying)

Comparison:
  - Strategy 1.1.1 honest (4-stage)
  - 2-stage baseline: OB-1d x FVG-15m (no middle layers)
  - C2 baseline: OB-6h x FVG-2h pro RR=1.0 (наш простой winner)
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
RRS = [1.0, 1.5, 2.0, 2.5]

# Lifetime для anchor зон (max_dist между уровнями)
LIFE_DAYS = {"1d": 14, "12h": 7, "4h": 3, "6h": 4,
              "1h": 1, "2h": 1.5, "15m": 0.5, "20m": 0.5}

# TF в часах для confirmation timing
TF_HOURS = {"1d": 24, "12h": 12, "6h": 6, "4h": 4,
             "2h": 2, "1h": 1, "20m": 1/3, "15m": 0.25}

OUT_DIR = Path("research/elements_study/output")


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


def zones_overlap(b1, t1, b2, t2):
    return not (t1 < b2 or t2 < b1)


def build_setup(trig, entry_pct, sl_buf, min_sl_pct, rr):
    zb = trig["bottom"]; zt = trig["top"]; atr = trig["atr"]
    direction = trig["direction"]
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
    if risk <= 0: return None
    if direction == "LONG":
        tp = entry + rr * risk
    else:
        tp = entry - rr * risk
    return entry, sl, tp


def detect_111_chain_setups(obs_top, fvgs_macro, obs_mid, fvgs_entry,
                             top_tf, macro_tf, mid_tf, entry_tf):
    """Возвращает list of (anchor=ob_top, ..., entry_fvg) с anchor-confirm fix.

    Каждый уровень confirmed на cur_close (cur_time + tf для OB) или
    c2_close (c2_time + tf для FVG).
    """
    setups = []
    top_tf_td = pd.Timedelta(hours=TF_HOURS[top_tf])
    macro_tf_td = pd.Timedelta(hours=TF_HOURS[macro_tf])
    mid_tf_td = pd.Timedelta(hours=TF_HOURS[mid_tf])
    entry_tf_td = pd.Timedelta(hours=TF_HOURS[entry_tf])

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
        l1_confirm = ob_top["time"] + top_tf_td  # FIX: cur_close
        l1_end = ob_top["time"] + top_life
        if l1_end <= l1_confirm: continue

        # Find first FVG-macro в (l1_confirm, l1_end) same direction in zone
        i0 = np.searchsorted(fvgs_macro_times, np.datetime64(
            l1_confirm.tz_localize(None) if l1_confirm.tz else l1_confirm),
            side="right")
        i1 = np.searchsorted(fvgs_macro_times, np.datetime64(
            l1_end.tz_localize(None) if l1_end.tz else l1_end), side="right")

        for mi in range(i0, i1):
            f_macro = fvgs_macro_sorted[mi]
            if f_macro["direction"] != ob_top["direction"]: continue
            if not zones_overlap(f_macro["bottom"], f_macro["top"],
                                  ob_top["bottom"], ob_top["top"]):
                continue
            l2_confirm = f_macro["time"] + macro_tf_td  # c2_close
            l2_end = f_macro["time"] + macro_life
            if l2_end <= l2_confirm: continue

            # Find first OB-mid в (l2_confirm, l2_end) inside L1 ∩ L2 zones
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
                                      ob_top["bottom"], ob_top["top"]):
                    continue
                if not zones_overlap(ob_mid["bottom"], ob_mid["top"],
                                      f_macro["bottom"], f_macro["top"]):
                    continue
                ob_mid_found = ob_mid
                break
            if ob_mid_found is None: continue

            l3_confirm = ob_mid_found["time"] + mid_tf_td
            l3_end = ob_mid_found["time"] + mid_life
            if l3_end <= l3_confirm: continue

            # Find first FVG-entry в (l3_confirm, l3_end) inside ob_mid_found zone
            k0 = np.searchsorted(fvgs_entry_times, np.datetime64(
                l3_confirm.tz_localize(None) if l3_confirm.tz else l3_confirm),
                side="right")
            k1 = np.searchsorted(fvgs_entry_times, np.datetime64(
                l3_end.tz_localize(None) if l3_end.tz else l3_end),
                side="right")

            fvg_entry_found = None
            for ek in range(k0, k1):
                f_entry = fvgs_entry_sorted[ek]
                if f_entry["direction"] != ob_top["direction"]: continue
                if not zones_overlap(f_entry["bottom"], f_entry["top"],
                                      ob_mid_found["bottom"],
                                      ob_mid_found["top"]):
                    continue
                fvg_entry_found = f_entry
                break
            if fvg_entry_found is None: continue

            setups.append({
                "anchor_time": ob_top["time"],
                "trigger_time": fvg_entry_found["time"],
                "trigger": fvg_entry_found,
                "year": fvg_entry_found["time"].year,
            })
            break  # dedup: 1 chain per anchor
    return setups


def evaluate(setups, sim, entry_tf, rr):
    rows = []
    for s in setups:
        t = s["trigger"]
        tup = build_setup(t, ENTRY_PCT, SL_BUF_ATR, MIN_SL_PCT, rr)
        if tup is None: continue
        entry, sl, tp = tup
        start = t["time"] + pd.Timedelta(hours=TF_HOURS[entry_tf])
        outcome, R = sim.simulate(t["direction"], entry, sl, tp, start,
                                    timeout_days=LIFE_DAYS[entry_tf])
        rows.append({"trigger_time": t["time"], "direction": t["direction"],
                      "outcome": outcome, "R": R, "year": s["year"]})
    return pd.DataFrame(rows)


def report(label, df, years):
    closed = df[df["outcome"].isin(["win", "loss"])].copy()
    if closed.empty:
        print(f"  {label}: no closed"); return
    n = len(df); nc = len(closed)
    w = (closed["outcome"] == "win").sum()
    print(f"\n  {label}: n_total={n}, closed={nc}, "
            f"WR={w/nc*100:.1f}%, total_R={closed['R'].sum():.1f}, "
            f"R/tr={closed['R'].mean():.3f}, freq={n/years/52:.2f}/wk")
    # year-by-year
    yr = closed.groupby("year").agg(
        n=("R", "size"),
        wins=("outcome", lambda x: (x == "win").sum()),
        total_R=("R", "sum"))
    yr["WR"] = yr["wins"]/yr["n"]*100
    yr["R_tr"] = yr["total_R"]/yr["n"]
    print(f"    year-by-year:")
    for y, r in yr.iterrows():
        print(f"      {int(y)}: n={r['n']}, WR={r['WR']:.0f}%, "
                f"total={r['total_R']:+.1f}R, R/tr={r['R_tr']:+.2f}")


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
        print(f"  {tf}: {len(df)} bars")
    df_1m = load_df(SYMBOL, "1m")
    df_1m = df_1m[df_1m.index >= pd.Timestamp(START_DATE, tz="UTC")]
    sim = FastSim(df_1m)
    years = (dfs["1d"].index[-1] - dfs["1d"].index[0]).days / 365
    print(f"  years: {years:.2f}")

    print("\n[INFO] collecting zones")
    obs = {}; fvgs = {}
    for tf in ["1d", "12h", "2h", "1h"]:
        obs[tf] = collect_obs(dfs[tf], dfs[tf]["atr14"], tf)
        print(f"  OB-{tf}: {len(obs[tf])}")
    for tf in ["6h", "4h", "15m"]:
        fvgs[tf] = collect_fvgs(dfs[tf], dfs[tf]["atr14"], tf)
        print(f"  FVG-{tf}: {len(fvgs[tf])}")

    # ----- 1. Strategy 1.1.1 HONEST 4-stage (all 8 chain combinations) -----
    print(f"\n[1] Strategy 1.1.1 HONEST 4-stage chains:")
    print(f"   (anchor-confirm fix, min_sl=1%, mid entry, 6y data)")
    all_111_setups = []
    chain_count = {}
    for top_tf in ["1d", "12h"]:
        for macro_tf in ["4h", "6h"]:
            for mid_tf in ["1h", "2h"]:
                # entry only 15m (20m data not collected here)
                entry_tf = "15m"
                setups = detect_111_chain_setups(
                    obs[top_tf], fvgs[macro_tf], obs[mid_tf], fvgs[entry_tf],
                    top_tf, macro_tf, mid_tf, entry_tf)
                key = f"{top_tf}-{macro_tf}-{mid_tf}-{entry_tf}"
                chain_count[key] = len(setups)
                all_111_setups.extend(setups)
    print(f"   chains:")
    for k, v in chain_count.items():
        print(f"     {k}: {v}")
    # dedup setups by (anchor_time, trigger_time, direction)
    seen = set()
    unique = []
    for s in all_111_setups:
        key = (s["anchor_time"], s["trigger_time"], s["trigger"]["direction"])
        if key in seen: continue
        seen.add(key)
        unique.append(s)
    print(f"   total chain setups: {len(all_111_setups)}, dedupedunique: {len(unique)}")

    print(f"\n  Backtest at multiple RR:")
    for rr in RRS:
        df_e = evaluate(unique, sim, "15m", rr)
        report(f"1.1.1 HONEST RR={rr}", df_e, years)

    # ----- 2. 2-stage baseline: OB-1d x FVG-15m -----
    print(f"\n[2] 2-stage baseline: OB-1d x FVG-15m (anchor-confirm fix)")
    setups_2stage = []
    obs_1d_sorted = obs["1d"]
    for ob in obs_1d_sorted:
        l1_confirm = ob["time"] + pd.Timedelta(hours=24)
        l1_end = ob["time"] + pd.Timedelta(days=14)
        if l1_end <= l1_confirm: continue
        for f in fvgs["15m"]:
            if f["time"] <= l1_confirm: continue
            if f["time"] > l1_end: continue
            if f["direction"] != ob["direction"]: continue
            if not zones_overlap(f["bottom"], f["top"],
                                  ob["bottom"], ob["top"]):
                continue
            setups_2stage.append({
                "anchor_time": ob["time"], "trigger_time": f["time"],
                "trigger": f, "year": f["time"].year})
            break  # first FVG only
    print(f"   2-stage setups: {len(setups_2stage)}")
    for rr in [1.0, 1.5]:
        df_e = evaluate(setups_2stage, sim, "15m", rr)
        report(f"2-stage OB-1dxFVG-15m RR={rr}", df_e, years)

    print(f"\n[TIME] {time.time()-t0:.1f}s")
    print(f"\n=== HEAD-TO-HEAD ===")
    print(f"  C2 baseline (etap_15 v7): WR 55.3%, +70R, R/tr 0.105, 2.33/нед, 0 минусовых лет")
    print(f"  Compare to 1.1.1 HONEST results above.")


if __name__ == "__main__":
    main()
