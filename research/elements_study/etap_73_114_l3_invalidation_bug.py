"""Этап 73: проверка бага — L3 OB не фильтруется против L1 invalidation.

В etap_69 detect_with_funnel:
  - L2 check: `if l2_close > L1_active_end: continue` ✓
  - L3 search window: [l2_close, l2_close + l3_life]
  - L4 search: внутри L3 window
  - НИГДЕ нет проверки `l3_close < L1_active_end` или `f_entry_time < L1_active_end`

Если L1 инвалидируется ПОСЛЕ L2 close но ДО L3/L4 — текущий код всё равно генерит сетап.
Проверяем, сколько сетапов имеют L3.close > L1 invalidation time.
"""
from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df
import importlib.util
_spec = importlib.util.spec_from_file_location(
    "etap66_core", str(_Path(__file__).parent / "etap_66_114_chains_survey.py")
)
_e66 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_e66)

_e66.TF_HOURS["20m"] = 20/60
_e66.LIFE_DAYS["20m"] = 0.5

SYMBOL = "BTCUSDT"
START_DATE = "2020-01-01"


def detect_check_l1_inval(fvgs_top, l2_zones, l3_zones, fvgs_entry,
                            top_tf, l2_tf, l3_tf, entry_tf, df_top,
                            allow_multi=5):
    top_td = pd.Timedelta(hours=_e66.TF_HOURS[top_tf])
    l2_td = pd.Timedelta(hours=_e66.TF_HOURS[l2_tf])
    l3_td = pd.Timedelta(hours=_e66.TF_HOURS[l3_tf])
    entry_td = pd.Timedelta(hours=_e66.TF_HOURS[entry_tf])
    top_life = pd.Timedelta(days=_e66.LIFE_DAYS[top_tf])
    l3_life = pd.Timedelta(days=_e66.LIFE_DAYS[l3_tf])

    l3_sorted = sorted(l3_zones, key=lambda x: x.get("prev_time", x.get("c0_time", x["time"])))
    fvgs_entry_sorted = sorted(fvgs_entry, key=lambda x: x["c0_time"])
    l3_start_times = np.array([np.datetime64(
        (z.get("prev_time", z.get("c0_time", z["time"]))).tz_localize(None)
        if (z.get("prev_time", z.get("c0_time", z["time"]))).tz else
        z.get("prev_time", z.get("c0_time", z["time"])))
        for z in l3_sorted])
    fvgs_entry_c0_times = np.array([np.datetime64(z["c0_time"].tz_localize(None) if z["c0_time"].tz else z["c0_time"])
                                      for z in fvgs_entry_sorted])

    setups = []
    setups_after_l1_dead = []  # ones that L3_close > L1_active_end

    for fvg_top in fvgs_top:
        L1_close = fvg_top["time"] + top_td
        L1_max_end = L1_close + top_life
        inval = _e66.find_invalidation(df_top, fvg_top, top_td, L1_max_end)
        L1_active_end = inval if inval is not None else L1_max_end

        n_setups_for_this_l1 = 0
        for l2 in l2_zones:
            if l2["direction"] != fvg_top["direction"]: continue
            if not _e66.any_edge_inside(l2["bottom"], l2["top"], fvg_top["bottom"], fvg_top["top"]):
                continue
            l2_start = l2["prev_time"]
            l2_close = l2["time"] + l2_td
            if l2_start < fvg_top["c0_time"]: continue
            if l2_close > L1_active_end: continue

            l3_search_start = l2_close
            l3_search_end = l3_search_start + l3_life
            j0 = np.searchsorted(l3_start_times, np.datetime64(
                l3_search_start.tz_localize(None) if l3_search_start.tz else l3_search_start), side="left")
            j1 = np.searchsorted(l3_start_times, np.datetime64(
                l3_search_end.tz_localize(None) if l3_search_end.tz else l3_search_end), side="right")

            for oj in range(j0, j1):
                l3 = l3_sorted[oj]
                if l3["direction"] != fvg_top["direction"]: continue
                if not _e66.any_edge_inside(l3["bottom"], l3["top"], fvg_top["bottom"], fvg_top["top"]): continue
                if not _e66.any_edge_inside(l3["bottom"], l3["top"], l2["bottom"], l2["top"]): continue

                L3_start = l3["prev_time"]
                L3_close = l3["time"] + l3_td
                l4_max_c2_open = L3_close - entry_td

                # FLAG: L3 closed after L1 invalidation?
                l3_after_l1_dead = (L3_close > L1_active_end)

                k0 = np.searchsorted(fvgs_entry_c0_times, np.datetime64(
                    L3_start.tz_localize(None) if L3_start.tz else L3_start), side="left")
                f_e = None
                for ek in range(k0, len(fvgs_entry_sorted)):
                    f_entry = fvgs_entry_sorted[ek]
                    if f_entry["c0_time"] < L3_start: continue
                    if f_entry["time"] > l4_max_c2_open: continue
                    if f_entry["c0_time"] > L3_close: break
                    if f_entry["direction"] != fvg_top["direction"]: continue
                    if not _e66.zones_overlap(f_entry["bottom"], f_entry["top"],
                                                fvg_top["bottom"], fvg_top["top"]): continue
                    if not _e66.zones_overlap(f_entry["bottom"], f_entry["top"],
                                                l2["bottom"], l2["top"]): continue
                    f_e = f_entry; break
                if f_e is None: continue

                x1_b = max(fvg_top["bottom"], l2["bottom"])
                x1_t = min(fvg_top["top"], l2["top"])

                setup = {
                    "fvg_b": f_e["bottom"], "fvg_t": f_e["top"],
                    "x1_bottom": x1_b, "x1_top": x1_t,
                    "obh_b": l3["bottom"], "obh_t": l3["top"],
                    "tf_minutes": 15, "year": L3_close.year,
                    "direction": f_e["direction"], "signal_time": L3_close,
                    "_L1_active_end": L1_active_end,
                    "_l3_after_l1_dead": l3_after_l1_dead,
                    "_L1_close": L1_close,
                }
                setups.append(setup)
                if l3_after_l1_dead:
                    setups_after_l1_dead.append(setup)
                n_setups_for_this_l1 += 1
                if n_setups_for_this_l1 >= allow_multi:
                    break
            if n_setups_for_this_l1 >= allow_multi:
                break

    return setups, setups_after_l1_dead


def main():
    print("[INFO] load")
    df_1d = load_df(SYMBOL, "1d")
    df_4h = load_df(SYMBOL, "4h")
    df_1h = load_df(SYMBOL, "1h")
    df_12h = compose_from_base(df_1h, "12h")
    df_6h = compose_from_base(df_1h, "6h")
    df_2h = compose_from_base(df_1h, "2h")
    df_1m = load_df(SYMBOL, "1m")
    df_15m = compose_from_base(df_1m, "15m")
    df_20m = compose_from_base(df_1m, "20m")

    cutoff = pd.Timestamp(START_DATE, tz="UTC")
    df_1d = df_1d[df_1d.index >= cutoff].copy()
    df_4h = df_4h[df_4h.index >= cutoff].copy()
    df_1h = df_1h[df_1h.index >= cutoff].copy()
    df_12h = df_12h[df_12h.index >= cutoff].copy()
    df_6h = df_6h[df_6h.index >= cutoff].copy()
    df_2h = df_2h[df_2h.index >= cutoff].copy()
    df_15m = df_15m[df_15m.index >= cutoff].copy()
    df_20m = df_20m[df_20m.index >= cutoff].copy()
    df_1m = df_1m[df_1m.index >= cutoff]

    for tf, df in [("1d", df_1d), ("12h", df_12h), ("6h", df_6h),
                    ("4h", df_4h), ("2h", df_2h), ("1h", df_1h),
                    ("15m", df_15m), ("20m", df_20m)]:
        df["atr14"] = _e66.compute_atr(df, 14)

    fvgs_1d = _e66.collect_fvgs(df_1d, df_1d["atr14"], "1d")
    fvgs_12h = _e66.collect_fvgs(df_12h, df_12h["atr14"], "12h")
    obs_4h = _e66.collect_obs(df_4h, df_4h["atr14"], "4h")
    obs_6h = _e66.collect_obs(df_6h, df_6h["atr14"], "6h")
    obs_2h = _e66.collect_obs(df_2h, df_2h["atr14"], "2h")
    obs_1h = _e66.collect_obs(df_1h, df_1h["atr14"], "1h")
    fvgs_15m = _e66.collect_fvgs(df_15m, df_15m["atr14"], "15m")
    fvgs_20m = _e66.collect_fvgs(df_20m, df_20m["atr14"], "20m")

    chains = {
        "B": (fvgs_12h, obs_4h, obs_1h, fvgs_15m, "12h", "4h", "1h", "15m", df_12h),
        "F": (fvgs_1d, obs_6h, obs_2h, fvgs_15m, "1d", "6h", "2h", "15m", df_1d),
        "J": (fvgs_1d, obs_4h, obs_1h, fvgs_20m, "1d", "4h", "1h", "20m", df_1d),
        "K": (fvgs_12h, obs_4h, obs_1h, fvgs_20m, "12h", "4h", "1h", "20m", df_12h),
    }

    print(f"\n{'='*78}\nL3 vs L1 INVALIDATION CHECK\n{'='*78}")
    total_setups = 0; total_after_dead = 0
    all_dead_setups = []
    for name, args in chains.items():
        setups, dead = detect_check_l1_inval(*args, allow_multi=5)
        print(f"\n{name}: {len(setups)} setups, {len(dead)} with L3_close > L1_active_end")
        total_setups += len(setups)
        total_after_dead += len(dead)
        for s in dead:
            s["chain"] = name
            all_dead_setups.append(s)
        if dead:
            for d in dead[:3]:
                gap = (d["signal_time"] - d["_L1_active_end"]).total_seconds() / 3600
                print(f"   {d['signal_time']} {d['direction']}  L1_dead={d['_L1_active_end']}  L3>dead by {gap:.1f}h")

    print(f"\n{'='*78}\nTOTAL: {total_setups} setups, {total_after_dead} ({total_after_dead/total_setups*100:.1f}%) AFTER L1 dead")

    # Performance comparison: trades with L3 after L1 dead vs proper
    if all_dead_setups:
        print(f"\nNeed to evaluate the dead setups separately. Build orders + simulate.")
        # Build orders and simulate for dead setups
        results = []
        for s in all_dead_setups:
            tup = _e66.build_orders(s)
            if tup is None: continue
            entry, sl = tup
            risk = abs(entry - sl)
            tp = entry + 2.0 * risk if s["direction"] == "LONG" else entry - 2.0 * risk
            outcome, R = _e66.simulate_safe(s, entry, sl, tp, df_1m)
            results.append({"outcome": outcome, "R": R, "year": s["year"]})
        if results:
            df_r = pd.DataFrame(results)
            cl = df_r[df_r["outcome"].isin(["win", "loss"])]
            if not cl.empty:
                wr = (cl["outcome"] == "win").mean() * 100
                tot = cl["R"].sum()
                print(f"\n  Setups AFTER L1 dead: n_closed={len(cl)} WR={wr:.1f}% total={tot:+.1f}R avg={cl['R'].mean():+.2f}R")


if __name__ == "__main__":
    main()
