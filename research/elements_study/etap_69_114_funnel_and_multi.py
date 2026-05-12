"""Этап 69: воронка отсева + многократные сетапы на одну макро-FVG.

Вопрос: почему всего 30-40 сетапов на 6 лет? Реальные пропорции:
  463 FVG-d / 916 FVG-12h макрозон → ~30 сетапов после каскада
  Причина: break после первого валидного каскада + жёсткие фильтры

Воронка для chain B (FVG-12h -> OB-4h -> OB-1h -> FVG-15m):
  Stage 1: FVG-12h всего
  Stage 2: с хотя бы одним OB-4h в зоне (any_edge)
  Stage 3: с OB-4h до инвалидации
  Stage 4: с OB-1h в обоих зонах после OB-4h close
  Stage 5: с FVG-15m в синхрон с OB-1h, overlap L1+L2
  Stage 6: дедуп
  Stage 7: closed после simulator (no_entry, etc.)

Также: версия с allow_multi=N (несколько каскадов на одну L1).
"""
from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

import time
import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df

import importlib.util
_spec = importlib.util.spec_from_file_location(
    "etap66_core", str(_Path(__file__).parent / "etap_66_114_chains_survey.py")
)
_e66 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_e66)

SYMBOL = "BTCUSDT"
START_DATE = "2020-01-01"


# ===== Funnel-tracking detect =====

def detect_with_funnel(fvgs_top, l2_zones, l3_zones, fvgs_entry,
                        top_tf, l2_tf, l3_tf, entry_tf, df_top,
                        allow_multi=1):
    """Same as detect_4stage but tracks per-stage counts + allows N setups per L1.
    allow_multi=1 reproduces etap_66 behavior."""
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

    # Funnel counters
    funnel = {
        "S1_total_FVG_top": len(fvgs_top),
        "S2_has_OB_l2_in_zone": 0,
        "S3_l2_before_invalidation": 0,
        "S4_has_OB_l3_in_both_zones": 0,
        "S5_has_FVG_entry_synced": 0,
        "S6_at_least_one_setup": 0,
    }

    setups = []

    for fvg_top in fvgs_top:
        L1_close = fvg_top["time"] + top_td
        L1_max_end = L1_close + top_life
        inval = _e66.find_invalidation(df_top, fvg_top, top_td, L1_max_end)
        L1_active_end = inval if inval is not None else L1_max_end

        had_l2_overlap = False
        had_l2_before_inval = False
        had_l3_in_zone = False
        had_entry = False
        n_setups_for_this_l1 = 0

        for l2 in l2_zones:
            if l2["direction"] != fvg_top["direction"]: continue
            if not _e66.any_edge_inside(l2["bottom"], l2["top"], fvg_top["bottom"], fvg_top["top"]):
                continue
            had_l2_overlap = True

            l2_start = l2["prev_time"]
            l2_close = l2["time"] + l2_td
            if l2_start < fvg_top["c0_time"]: continue
            if l2_close > L1_active_end: continue
            had_l2_before_inval = True

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
                had_l3_in_zone = True

                L3_start = l3["prev_time"]
                L3_close = l3["time"] + l3_td
                l4_max_c2_open = L3_close - entry_td

                k0 = np.searchsorted(fvgs_entry_c0_times, np.datetime64(
                    L3_start.tz_localize(None) if L3_start.tz else L3_start), side="left")
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
                    had_entry = True

                    x1_b = max(fvg_top["bottom"], l2["bottom"])
                    x1_t = min(fvg_top["top"], l2["top"])

                    setups.append({
                        "fvg_b": f_entry["bottom"], "fvg_t": f_entry["top"],
                        "x1_bottom": x1_b, "x1_top": x1_t,
                        "obh_b": l3["bottom"], "obh_t": l3["top"],
                        "tf_minutes": 15,
                        "year": L3_close.year,
                        "direction": f_entry["direction"],
                        "signal_time": L3_close,
                    })
                    n_setups_for_this_l1 += 1
                    if n_setups_for_this_l1 >= allow_multi:
                        break
                if n_setups_for_this_l1 >= allow_multi:
                    break
            if n_setups_for_this_l1 >= allow_multi:
                break

        if had_l2_overlap: funnel["S2_has_OB_l2_in_zone"] += 1
        if had_l2_before_inval: funnel["S3_l2_before_invalidation"] += 1
        if had_l3_in_zone: funnel["S4_has_OB_l3_in_both_zones"] += 1
        if had_entry: funnel["S5_has_FVG_entry_synced"] += 1
        if n_setups_for_this_l1 > 0: funnel["S6_at_least_one_setup"] += 1

    return setups, funnel


def dedup(setups):
    seen = set(); out = []
    for s in setups:
        k = (s["signal_time"], s["direction"], round(s["fvg_b"], 2), round(s["fvg_t"], 2))
        if k in seen: continue
        seen.add(k); out.append(s)
    return out


def main():
    t0 = time.time()
    print("[INFO] load")
    df_1d = load_df(SYMBOL, "1d")
    df_4h = load_df(SYMBOL, "4h")
    df_1h = load_df(SYMBOL, "1h")
    df_12h = compose_from_base(df_1h, "12h")
    df_2h = compose_from_base(df_1h, "2h")
    df_6h = compose_from_base(df_1h, "6h")
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
        df["atr14"] = _e66.compute_atr(df, 14)

    fvgs_1d = _e66.collect_fvgs(df_1d, df_1d["atr14"], "1d")
    fvgs_12h = _e66.collect_fvgs(df_12h, df_12h["atr14"], "12h")
    obs_4h = _e66.collect_obs(df_4h, df_4h["atr14"], "4h")
    obs_6h = _e66.collect_obs(df_6h, df_6h["atr14"], "6h")
    obs_2h = _e66.collect_obs(df_2h, df_2h["atr14"], "2h")
    obs_1h = _e66.collect_obs(df_1h, df_1h["atr14"], "1h")
    fvgs_15m = _e66.collect_fvgs(df_15m, df_15m["atr14"], "15m")

    chains = [
        ("A: FVG-d->OB-4h->OB-1h->FVG-15m",
            fvgs_1d, obs_4h, obs_1h, fvgs_15m, "1d", "4h", "1h", "15m", df_1d),
        ("B: FVG-12h->OB-4h->OB-1h->FVG-15m",
            fvgs_12h, obs_4h, obs_1h, fvgs_15m, "12h", "4h", "1h", "15m", df_12h),
        ("F: FVG-d->OB-6h->OB-2h->FVG-15m",
            fvgs_1d, obs_6h, obs_2h, fvgs_15m, "1d", "6h", "2h", "15m", df_1d),
    ]

    # ===== Funnel diagnostic =====
    print(f"\n{'='*78}\nFUNNEL DIAGNOSTIC (allow_multi=1, как в etap_66)\n{'='*78}")
    for label, fvgs_top, l2_z, l3_z, fvg_e, t_tf, l2_tf, l3_tf, e_tf, df_t in chains:
        _, funnel = detect_with_funnel(fvgs_top, l2_z, l3_z, fvg_e,
                                         t_tf, l2_tf, l3_tf, e_tf, df_t, allow_multi=1)
        print(f"\n{label}")
        prev = funnel["S1_total_FVG_top"]
        for k, v in funnel.items():
            pct_of_total = v / funnel["S1_total_FVG_top"] * 100 if funnel["S1_total_FVG_top"] else 0
            drop = (prev - v) if prev else 0
            print(f"  {k:<38} {v:>5}  ({pct_of_total:5.1f}% of L1)  -drop={drop}")
            prev = v

    # ===== Multi-setup comparison =====
    print(f"\n\n{'='*78}\nMULTI-SETUP COMPARISON (allow_multi=1,2,3,5,unlimited)\n{'='*78}")
    for label, fvgs_top, l2_z, l3_z, fvg_e, t_tf, l2_tf, l3_tf, e_tf, df_t in chains:
        print(f"\n{label}")
        for AM in [1, 2, 3, 5, 999]:
            setups, _ = detect_with_funnel(fvgs_top, l2_z, l3_z, fvg_e,
                                             t_tf, l2_tf, l3_tf, e_tf, df_t, allow_multi=AM)
            uniq = dedup(setups)
            # Trade evaluation
            best_total = None; best_meta = None
            for rr in [1.5, 1.8, 2.0, 2.5]:
                for dom in [False, True]:
                    df = _e66.evaluate(uniq, rr, df_1m, df_1d, only_dom=dom)
                    m = _e66.report_metrics(df)
                    if not m: continue
                    if best_total is None or m["total"] > best_total:
                        best_total = m["total"]
                        best_meta = (rr, dom, m)
            am_str = "inf" if AM == 999 else str(AM)
            n_setups = len(setups)
            n_uniq = len(uniq)
            if best_meta:
                rr, dom, m = best_meta
                dom_lbl = "+dom" if dom else "no_dom"
                print(f"  allow_multi={am_str:<3} raw={n_setups:>3} uniq={n_uniq:>3}  "
                      f"best: RR={rr} {dom_lbl:<7} n={m['n']:>3} WR={m['wr']:5.1f}% "
                      f"total={m['total']:+6.1f}R bad={m['bad']}/{m['n_yrs']}")

    print(f"\n[TIME] {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
