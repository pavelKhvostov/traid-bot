"""Проверка дополнительных C3-фильтров на Core-сетапах:
Core = (sweep_FH ∪ OB_sweep) ∩ sweep_maxV[i] для HH
Core = (sweep_FL ∪ OB_sweep) ∩ sweep_maxV[i] для LL

C3 кандидаты:
  a) iFVG (any LTF 15m-4h) bull→bear / bear→bull в свече i
  b) iFVG (1h-2h only)
  c) OB(1h-2h) ∩ FVG(1h-2h) в свече i (тройной confluence из triple-скрипта)

Цель: посмотреть, добавляет ли C3 precision к Core (177 setups).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from research.vic_vadim.predict_fractal_maxv import (
    load_15m, compose_htf, compose_ltf,
    find_ob_zones, find_fractals,
    calculate_maxv_12h_bar,
    zone_sweep_flags, fractal_sweep_flags,
    find_fvgs_for_ltf, flags_in_12h,
    HTF_LIST,
)
from research.vic_vadim.predict_fractal_confluence import (
    find_fvgs_indexed, find_ifvg_events,
)


def main() -> None:
    df_15m = load_15m()
    df_12h = compose_htf(df_15m, "12h").sort_index()
    print(f"12h BTC: {len(df_12h)} баров")

    # === Core flags ===
    df_15m_naive = df_15m.copy(); df_15m_naive.index.name = None
    maxv = np.array([calculate_maxv_12h_bar(df_15m_naive, t) or np.nan for t in df_12h.index])
    h = df_12h["high"].to_numpy(); l = df_12h["low"].to_numpy(); c = df_12h["close"].to_numpy()
    sw_short = np.zeros(len(df_12h), dtype=bool)
    sw_long = np.zeros(len(df_12h), dtype=bool)
    for i in range(1, len(df_12h)):
        if np.isnan(maxv[i-1]): continue
        if h[i] > maxv[i-1] and c[i] < maxv[i-1]: sw_short[i] = True
        if l[i] < maxv[i-1] and c[i] > maxv[i-1]: sw_long[i] = True

    htf_dfs = {tf: compose_htf(df_15m, freq).sort_index() for tf, freq in HTF_LIST}
    all_ob, all_fract = [], []
    for tf, df_tf in htf_dfs.items():
        all_ob += find_ob_zones(df_tf, tf)
        all_fract += find_fractals(df_tf, tf)
    c1_fh = fractal_sweep_flags(df_12h, all_fract, "FH")
    c1_fl = fractal_sweep_flags(df_12h, all_fract, "FL")
    c1_obs = zone_sweep_flags(df_12h, all_ob, "SHORT")
    c1_obl = zone_sweep_flags(df_12h, all_ob, "LONG")

    hh_core = (c1_fh | c1_obs) & sw_short
    ll_core = (c1_fl | c1_obl) & sw_long
    print(f"HH Core: {hh_core.sum()}, LL Core: {ll_core.sum()}")

    # === C3 flags ===
    LTF_LIST = [("15m","15min"),("30m","30min"),("45m","45min"),
                ("1h","60min"),("2h","120min"),("3h","180min"),("4h","240min")]

    ifvg_b2s_any, ifvg_s2b_any = [], []
    ifvg_b2s_12, ifvg_s2b_12 = [], []
    ob_short_12, ob_long_12 = [], []
    fvg_short_12, fvg_long_12 = [], []

    for tf, freq in LTF_LIST:
        df_tf = compose_ltf(df_15m, freq).sort_index()
        fvgs_full = find_fvgs_indexed(df_tf)
        ifvgs = find_ifvg_events(df_tf, fvgs_full)
        for e in ifvgs:
            t = pd.Timestamp(e["event_time"])
            if t.tz is None: t = t.tz_localize("UTC")
            if e["dir_a"] == "LONG" and e["dir_b"] == "SHORT":
                ifvg_b2s_any.append(t)
                if tf in ("1h","2h"): ifvg_b2s_12.append(t)
            elif e["dir_a"] == "SHORT" and e["dir_b"] == "LONG":
                ifvg_s2b_any.append(t)
                if tf in ("1h","2h"): ifvg_s2b_12.append(t)
        if tf in ("1h","2h"):
            for ob in find_ob_zones(df_tf, tf):
                t = pd.Timestamp(ob["ready_time"])
                if t.tz is None: t = t.tz_localize("UTC")
                (ob_short_12 if ob["dir"] == "SHORT" else ob_long_12).append(t)
            for f in find_fvgs_for_ltf(df_tf):
                t = pd.Timestamp(f["c2_close_time"])
                if t.tz is None: t = t.tz_localize("UTC")
                (fvg_short_12 if f["dir"] == "SHORT" else fvg_long_12).append(t)

    f_ifvg_b2s_any = flags_in_12h(df_12h, ifvg_b2s_any)
    f_ifvg_s2b_any = flags_in_12h(df_12h, ifvg_s2b_any)
    f_ifvg_b2s_12 = flags_in_12h(df_12h, ifvg_b2s_12)
    f_ifvg_s2b_12 = flags_in_12h(df_12h, ifvg_s2b_12)
    f_ob_s_12 = flags_in_12h(df_12h, ob_short_12)
    f_ob_l_12 = flags_in_12h(df_12h, ob_long_12)
    f_fvg_s_12 = flags_in_12h(df_12h, fvg_short_12)
    f_fvg_l_12 = flags_in_12h(df_12h, fvg_long_12)
    f_obfvg_12_hh = f_ob_s_12 & f_fvg_s_12
    f_obfvg_12_ll = f_ob_l_12 & f_fvg_l_12

    # target
    n = len(df_12h); valid = np.arange(2, n - 2)
    hh = ((h[valid]>h[valid-2])&(h[valid]>h[valid-1])&(h[valid]>h[valid+1])&(h[valid]>h[valid+2]))
    ll = ((l[valid]<l[valid-2])&(l[valid]<l[valid-1])&(l[valid]<l[valid+1])&(l[valid]<l[valid+2]))
    n_total = len(valid); base_hh = hh.mean(); base_ll = ll.mean()

    def report(label, target, cond, base, parent_n):
        n_c = int(cond.sum()); n_tc = int((target & cond).sum())
        prec = n_tc / n_c if n_c else float("nan")
        lift = prec / base if base else float("nan")
        keep = n_c / parent_n if parent_n else float("nan")
        print(f"  {label:<48} n={n_c:3d}  hits={n_tc:3d}  prec={prec*100:6.2f}%  "
              f"lift=×{lift:.2f}  keep={keep*100:5.1f}% от Core")

    print(f"\nbaseline P(HH)={base_hh*100:.2f}%  P(LL)={base_ll*100:.2f}%")

    print(f"\n=== HH Core (n={hh_core[valid].sum()}, prec=81.93%) + C3 фильтры ===")
    core_hh = hh_core[valid]
    n_core_hh = int(core_hh.sum())
    print(f"  baseline:")
    report("HH Core (без C3)", hh, core_hh, base_hh, n_core_hh)
    report("HH Core ∩ iFVG b→s (any LTF)", hh, core_hh & f_ifvg_b2s_any[valid], base_hh, n_core_hh)
    report("HH Core ∩ iFVG b→s (1h-2h)",   hh, core_hh & f_ifvg_b2s_12[valid], base_hh, n_core_hh)
    report("HH Core ∩ OB+FVG (1h-2h)",     hh, core_hh & f_obfvg_12_hh[valid], base_hh, n_core_hh)
    report("HH Core ∩ (iFVG any | OB+FVG)", hh, core_hh & (f_ifvg_b2s_any[valid] | f_obfvg_12_hh[valid]), base_hh, n_core_hh)
    report("HH Core ∩ iFVG b→s ∩ OB+FVG",  hh, core_hh & f_ifvg_b2s_any[valid] & f_obfvg_12_hh[valid], base_hh, n_core_hh)

    print(f"\n=== LL Core (n={ll_core[valid].sum()}, prec=73.40%) + C3 фильтры ===")
    core_ll = ll_core[valid]
    n_core_ll = int(core_ll.sum())
    report("LL Core (без C3)", ll, core_ll, base_ll, n_core_ll)
    report("LL Core ∩ iFVG s→b (any LTF)", ll, core_ll & f_ifvg_s2b_any[valid], base_ll, n_core_ll)
    report("LL Core ∩ iFVG s→b (1h-2h)",   ll, core_ll & f_ifvg_s2b_12[valid], base_ll, n_core_ll)
    report("LL Core ∩ OB+FVG (1h-2h)",     ll, core_ll & f_obfvg_12_ll[valid], base_ll, n_core_ll)
    report("LL Core ∩ (iFVG any | OB+FVG)", ll, core_ll & (f_ifvg_s2b_any[valid] | f_obfvg_12_ll[valid]), base_ll, n_core_ll)
    report("LL Core ∩ iFVG s→b ∩ OB+FVG",  ll, core_ll & f_ifvg_s2b_any[valid] & f_obfvg_12_ll[valid], base_ll, n_core_ll)


if __name__ == "__main__":
    main()
