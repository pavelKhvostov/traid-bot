"""Этап 77: ужесточение fractal-cascade для повышения WR до >45%.

Из etap_76: best WR 40.8% на B5+K5 — мало. Гипотеза:
- allow_multi=5 = слишком много коррелированных каскадов
- proximity=3×ATR = OB-4h попадает слишком далеко от sweep
- sweep depth не проверяется — слабые sweep'ы не отсеиваются

Эксперимент: сетка по параметрам
  allow_multi: [1, 2, 3]
  proximity_atr: [1.0, 1.5, 2.0]
  min_sweep_depth_atr: [0.0, 0.3, 0.5]  # sweep должен пробить fractal не менее чем на X*ATR

Также: LONG-only vs SHORT-only vs both — есть ли direction asymmetry?
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
import time
import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df
import importlib.util
_spec76 = importlib.util.spec_from_file_location(
    "etap76_core", str(_Path(__file__).parent / "etap_76_115_fractal_chains_survey.py")
)
_e76 = importlib.util.module_from_spec(_spec76)
_spec76.loader.exec_module(_e76)
_e66 = _e76._e66

SYMBOL = "BTCUSDT"
START_DATE = "2020-01-01"
N_YEARS = 6.3


def detect_strict(fractals, l2_zones, l3_zones, fvgs_entry,
                    top_tf, l2_tf, l3_tf, entry_tf,
                    allow_multi, proximity_atr, min_sweep_depth_atr):
    """Same as detect_4stage_fractal but parametrized."""
    l2_td = pd.Timedelta(hours=_e66.TF_HOURS[l2_tf])
    l3_td = pd.Timedelta(hours=_e66.TF_HOURS[l3_tf])
    entry_td = pd.Timedelta(hours=_e66.TF_HOURS[entry_tf])
    cascade_window = pd.Timedelta(days=_e76.CASCADE_DAYS[top_tf])
    l3_life = pd.Timedelta(days=_e66.LIFE_DAYS[l3_tf])

    l3_sorted = sorted(l3_zones, key=lambda x: x["prev_time"])
    fvgs_entry_sorted = sorted(fvgs_entry, key=lambda x: x["c0_time"])
    l3_start_times = np.array([np.datetime64(
        z["prev_time"].tz_localize(None) if z["prev_time"].tz else z["prev_time"])
        for z in l3_sorted])
    fvgs_entry_c0_times = np.array([np.datetime64(
        z["c0_time"].tz_localize(None) if z["c0_time"].tz else z["c0_time"])
        for z in fvgs_entry_sorted])

    setups = []

    for fr in fractals:
        sweep_close = fr["sweep_close_time"]
        cascade_end = sweep_close + cascade_window
        sweep_ext = fr["sweep_extreme"]
        # Sweep depth check: how deep was the sweep beyond fractal level?
        if fr["direction"] == "SHORT":
            sweep_depth = fr["sweep_high"] - fr["level"]
        else:
            sweep_depth = fr["level"] - fr["sweep_low"]
        if sweep_depth < min_sweep_depth_atr * fr["atr"]: continue

        n_setups = 0
        for l2 in l2_zones:
            if l2["direction"] != fr["direction"]: continue
            l2_start = l2["prev_time"]
            l2_close = l2["time"] + l2_td
            if l2_start < sweep_close: continue
            if l2_close > cascade_end: continue
            l2_mid = (l2["bottom"] + l2["top"]) / 2
            if abs(l2_mid - sweep_ext) > proximity_atr * fr["atr"]: continue

            l3_search_start = l2_close
            l3_search_end = min(l3_search_start + l3_life, cascade_end)

            j0 = np.searchsorted(l3_start_times, np.datetime64(
                l3_search_start.tz_localize(None) if l3_search_start.tz else l3_search_start), side="left")
            j1 = np.searchsorted(l3_start_times, np.datetime64(
                l3_search_end.tz_localize(None) if l3_search_end.tz else l3_search_end), side="right")

            for oj in range(j0, j1):
                l3 = l3_sorted[oj]
                if l3["direction"] != fr["direction"]: continue
                L3_start = l3["prev_time"]
                L3_close = l3["time"] + l3_td
                if L3_close > cascade_end: continue
                l3_mid = (l3["bottom"] + l3["top"]) / 2
                if abs(l3_mid - sweep_ext) > proximity_atr * fr["atr"]: continue

                l4_max_c2_open = L3_close - entry_td
                k0 = np.searchsorted(fvgs_entry_c0_times, np.datetime64(
                    L3_start.tz_localize(None) if L3_start.tz else L3_start), side="left")
                f_e = None
                for ek in range(k0, len(fvgs_entry_sorted)):
                    f_entry = fvgs_entry_sorted[ek]
                    if f_entry["c0_time"] < L3_start: continue
                    if f_entry["time"] > l4_max_c2_open: continue
                    if f_entry["c0_time"] > L3_close: break
                    if f_entry["direction"] != fr["direction"]: continue
                    if (f_entry["time"] + entry_td) > cascade_end: continue
                    f_e = f_entry; break

                if f_e is None: continue

                setups.append({
                    "fvg_b": f_e["bottom"], "fvg_t": f_e["top"],
                    "obh_b": l3["bottom"], "obh_t": l3["top"],
                    "x1_bottom": sweep_ext, "x1_top": sweep_ext,
                    "sweep_extreme": sweep_ext,
                    "tf_minutes": int(_e66.TF_HOURS[entry_tf] * 60),
                    "year": L3_close.year,
                    "direction": fr["direction"],
                    "signal_time": L3_close,
                    "fractal_kind": fr["kind"],
                    "atr": fr["atr"],
                })
                n_setups += 1
                if n_setups >= allow_multi: break
            if n_setups >= allow_multi: break

    return _e76.dedup(setups)


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

    fractals_1d = _e76.collect_fractals_with_sweep(df_1d, df_1d["atr14"], "1d")
    fractals_12h = _e76.collect_fractals_with_sweep(df_12h, df_12h["atr14"], "12h")
    obs_4h = _e66.collect_obs(df_4h, df_4h["atr14"], "4h")
    obs_1h = _e66.collect_obs(df_1h, df_1h["atr14"], "1h")
    fvgs_15m = _e66.collect_fvgs(df_15m, df_15m["atr14"], "15m")
    fvgs_20m = _e66.collect_fvgs(df_20m, df_20m["atr14"], "20m")

    print(f"\n[INFO] strict grid: chain=B5 (FH/FL-12h -> OB-4h -> OB-1h -> FVG-15m)")
    print(f"  allow_multi x proximity x sweep_depth -> metrics\n")

    chain_args = (fractals_12h, obs_4h, obs_1h, fvgs_15m, "12h", "4h", "1h", "15m")

    print(f"  {'AM':>3} {'prox':>5} {'depth':>6} {'dir':<5} {'RR':>4} "
          f"{'n':>4} {'tpy':>5} {'WR':>6} {'total':>8} {'avg':>7} {'bad':>5} {'pass':>5}")

    rows = []
    AM_LIST = [1, 2, 3]
    PROX_LIST = [1.0, 1.5, 2.0]
    DEPTH_LIST = [0.0, 0.3, 0.5]
    RR_LIST = [1.8, 2.0, 2.5]

    for AM in AM_LIST:
        for PROX in PROX_LIST:
            for DEPTH in DEPTH_LIST:
                setups = detect_strict(*chain_args,
                                         allow_multi=AM, proximity_atr=PROX,
                                         min_sweep_depth_atr=DEPTH)
                if len(setups) < 30: continue  # too few

                for direction_filter in ["both", "LONG", "SHORT"]:
                    for rr in RR_LIST:
                        if direction_filter == "both":
                            s_filt = setups
                        else:
                            s_filt = [s for s in setups if s["direction"] == direction_filter]
                        if len(s_filt) < 30: continue
                        df = _e76.evaluate(s_filt, rr, df_1m, df_1d, only_dom=False)
                        m = _e76.metrics(df)
                        if not m: continue
                        passes = (m["tpy"] >= 26 and m["wr"] > 45 and rr > 1.5
                                   and m["bad"] <= 2)
                        if passes:
                            print(f"  {AM:>3} {PROX:>5.1f} {DEPTH:>6.1f} {direction_filter:<5} RR={rr} "
                                  f"n={m['n']:>3} tpy={m['tpy']:5.1f} "
                                  f"WR={m['wr']:5.1f}% total={m['total']:+6.1f}R "
                                  f"avg={m['avg_R']:+5.2f}R bad={m['bad']}/{m['n_yrs']} PASS")
                        rows.append({"AM": AM, "PROX": PROX, "DEPTH": DEPTH,
                                      "dir": direction_filter, "rr": rr,
                                      "pass": passes, **m})

    # Top results
    print(f"\n\n{'='*88}\nTOP 20 by total R (n>=30, bad<=2):\n{'='*88}")
    clean = [r for r in rows if r["n"] >= 30 and r["bad"] <= 2]
    by_total = sorted(clean, key=lambda x: x["total"], reverse=True)[:20]
    for r in by_total:
        mark = "PASS" if r["pass"] else " - "
        print(f"  {mark} AM={r['AM']} prox={r['PROX']:.1f} depth={r['DEPTH']:.1f} "
              f"dir={r['dir']:<5} RR={r['rr']} n={r['n']:>3} tpy={r['tpy']:5.1f} "
              f"WR={r['wr']:5.1f}% total={r['total']:+6.1f}R avg={r['avg_R']:+5.2f}R "
              f"bad={r['bad']}/{r['n_yrs']}")

    print(f"\n--- TOP 20 by WR (n>=30) ---")
    by_wr = sorted([r for r in rows if r["n"] >= 30], key=lambda x: x["wr"], reverse=True)[:20]
    for r in by_wr:
        mark = "PASS" if r["pass"] else " - "
        print(f"  {mark} AM={r['AM']} prox={r['PROX']:.1f} depth={r['DEPTH']:.1f} "
              f"dir={r['dir']:<5} RR={r['rr']} n={r['n']:>3} tpy={r['tpy']:5.1f} "
              f"WR={r['wr']:5.1f}% total={r['total']:+6.1f}R avg={r['avg_R']:+5.2f}R "
              f"bad={r['bad']}/{r['n_yrs']}")

    print(f"\n--- PASSING ALL CRITERIA ({len([r for r in rows if r['pass']])} configurations) ---")
    pass_rows = sorted([r for r in rows if r["pass"]], key=lambda x: x["total"], reverse=True)[:15]
    for r in pass_rows:
        print(f"  AM={r['AM']} prox={r['PROX']:.1f} depth={r['DEPTH']:.1f} "
              f"dir={r['dir']:<5} RR={r['rr']} n={r['n']:>3} tpy={r['tpy']:5.1f} "
              f"WR={r['wr']:5.1f}% total={r['total']:+6.1f}R avg={r['avg_R']:+5.2f}R "
              f"bad={r['bad']}/{r['n_yrs']}")

    print(f"\n[TIME] {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
