"""Этап 70: цепочки/портфели под условие 1 сделка раз в 1-2 недели + WR>45% + RR>1.5.

6 лет × 26 (1/2 нед) = 156 closed min, 6 × 52 = 312 max.

План:
1. allow_multi=5 на всех цепочках из etap_66/68 (FVG-d/12h семья)
2. для каждой посчитать trades/year, WR, total R при RR=[1.8, 2.0, 2.5]
3. отобрать кандидатов под критерий
4. построить портфели (union dedup) из топовых цепочек
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
_spec = importlib.util.spec_from_file_location(
    "etap66_core", str(_Path(__file__).parent / "etap_66_114_chains_survey.py")
)
_e66 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_e66)

_spec69 = importlib.util.spec_from_file_location(
    "etap69_core", str(_Path(__file__).parent / "etap_69_114_funnel_and_multi.py")
)
_e69 = importlib.util.module_from_spec(_spec69)
_spec69.loader.exec_module(_e69)

# Patch TF_HOURS in BOTH module copies (etap_69 has its own _e66 instance)
for mod in [_e66, _e69._e66]:
    mod.TF_HOURS["20m"] = 20/60
    mod.TF_HOURS["30m"] = 0.5
    mod.LIFE_DAYS["20m"] = 0.5
    mod.LIFE_DAYS["30m"] = 0.75

SYMBOL = "BTCUSDT"
START_DATE = "2020-01-01"
N_YEARS = 6  # 2020-2025 (2026 partial)

# Targets
MIN_TRADES_PER_YEAR = 26   # 1 every 2 weeks
TARGET_TRADES_PER_YEAR = 40
MIN_WR = 45
MIN_RR = 1.5  # use RR > 1.5


def detect_multi(fvgs_top, l2_z, l3_z, fvg_e, t_tf, l2_tf, l3_tf, e_tf, df_t, AM):
    setups, _ = _e69.detect_with_funnel(fvgs_top, l2_z, l3_z, fvg_e,
                                         t_tf, l2_tf, l3_tf, e_tf, df_t, allow_multi=AM)
    return _e69.dedup(setups)


def detect_3stage_multi(fvgs_top, l2_z, l2_kind, fvgs_entry,
                          top_tf, l2_tf, entry_tf, df_top, allow_multi):
    """3-stage with allow_multi cascades per L1."""
    top_td = pd.Timedelta(hours=_e66.TF_HOURS[top_tf])
    l2_td = pd.Timedelta(hours=_e66.TF_HOURS[l2_tf])
    entry_td = pd.Timedelta(hours=_e66.TF_HOURS[entry_tf])
    top_life = pd.Timedelta(days=_e66.LIFE_DAYS[top_tf])
    l2_life = pd.Timedelta(days=_e66.LIFE_DAYS[l2_tf])

    fvgs_entry_sorted = sorted(fvgs_entry, key=lambda x: x["c0_time"])
    fvgs_entry_c0_times = np.array([np.datetime64(z["c0_time"].tz_localize(None) if z["c0_time"].tz else z["c0_time"])
                                      for z in fvgs_entry_sorted])
    setups = []

    for fvg_top in fvgs_top:
        L1_close = fvg_top["time"] + top_td
        L1_max_end = L1_close + top_life
        inval = _e66.find_invalidation(df_top, fvg_top, top_td, L1_max_end)
        L1_active_end = inval if inval is not None else L1_max_end

        n_setups_for_this_l1 = 0
        for ob_l2 in l2_z:
            ob_l2_close = ob_l2["time"] + l2_td
            if ob_l2["prev_time"] < fvg_top["c0_time"]: continue
            if ob_l2_close > L1_active_end: continue
            if ob_l2["direction"] != fvg_top["direction"]: continue
            if not _e66.any_edge_inside(ob_l2["bottom"], ob_l2["top"],
                                          fvg_top["bottom"], fvg_top["top"]): continue

            search_start = ob_l2_close
            search_end = ob_l2_close + l2_life
            k0 = np.searchsorted(fvgs_entry_c0_times, np.datetime64(
                search_start.tz_localize(None) if search_start.tz else search_start), side="left")
            k1 = np.searchsorted(fvgs_entry_c0_times, np.datetime64(
                search_end.tz_localize(None) if search_end.tz else search_end), side="right")

            for ek in range(k0, k1):
                f_entry = fvgs_entry_sorted[ek]
                if f_entry["direction"] != fvg_top["direction"]: continue
                if not _e66.zones_overlap(f_entry["bottom"], f_entry["top"],
                                            fvg_top["bottom"], fvg_top["top"]): continue
                if not _e66.zones_overlap(f_entry["bottom"], f_entry["top"],
                                            ob_l2["bottom"], ob_l2["top"]): continue

                x1_b = max(fvg_top["bottom"], ob_l2["bottom"])
                x1_t = min(fvg_top["top"], ob_l2["top"])
                entry_close = f_entry["time"] + entry_td

                setups.append({
                    "fvg_b": f_entry["bottom"], "fvg_t": f_entry["top"],
                    "x1_bottom": x1_b, "x1_top": x1_t,
                    "obh_b": ob_l2["bottom"], "obh_t": ob_l2["top"],
                    "tf_minutes": int(_e66.TF_HOURS[entry_tf] * 60),
                    "year": entry_close.year,
                    "direction": f_entry["direction"],
                    "signal_time": entry_close,
                })
                n_setups_for_this_l1 += 1
                if n_setups_for_this_l1 >= allow_multi:
                    break
            if n_setups_for_this_l1 >= allow_multi:
                break

    return _e69.dedup(setups)


def metrics_full(df, n_years):
    if df.empty or "outcome" not in df.columns: return None
    cl = df[df["outcome"].isin(["win", "loss"])]
    if cl.empty: return None
    nc = len(cl); wins = (cl["R"] > 0).sum()
    wr = wins/nc*100; tot = cl["R"].sum()
    yr = cl.groupby("year")["R"].sum()
    bad = (yr < 0).sum()
    tpy = nc / n_years
    return {"n": nc, "wr": wr, "total": tot, "bad": bad,
             "n_yrs": len(yr), "tpy": tpy, "avg_R": tot/nc}


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
    df_30m = compose_from_base(df_1m, "30m")

    cutoff = pd.Timestamp(START_DATE, tz="UTC")
    df_1d = df_1d[df_1d.index >= cutoff].copy()
    df_4h = df_4h[df_4h.index >= cutoff].copy()
    df_1h = df_1h[df_1h.index >= cutoff].copy()
    df_12h = df_12h[df_12h.index >= cutoff].copy()
    df_6h = df_6h[df_6h.index >= cutoff].copy()
    df_2h = df_2h[df_2h.index >= cutoff].copy()
    df_15m = df_15m[df_15m.index >= cutoff].copy()
    df_20m = df_20m[df_20m.index >= cutoff].copy()
    df_30m = df_30m[df_30m.index >= cutoff].copy()
    df_1m = df_1m[df_1m.index >= cutoff]

    for tf, df in [("1d", df_1d), ("12h", df_12h), ("6h", df_6h),
                    ("4h", df_4h), ("2h", df_2h), ("1h", df_1h),
                    ("15m", df_15m), ("20m", df_20m), ("30m", df_30m)]:
        df["atr14"] = _e66.compute_atr(df, 14)
    df_1h["ema200"] = df_1h["close"].ewm(span=200, adjust=False).mean()
    df_2h["ema200"] = df_2h["close"].ewm(span=200, adjust=False).mean()

    print("[INFO] collect zones")
    fvgs_1d = _e66.collect_fvgs(df_1d, df_1d["atr14"], "1d")
    fvgs_12h = _e66.collect_fvgs(df_12h, df_12h["atr14"], "12h")
    obs_4h = _e66.collect_obs(df_4h, df_4h["atr14"], "4h")
    obs_6h = _e66.collect_obs(df_6h, df_6h["atr14"], "6h")
    obs_2h = _e66.collect_obs(df_2h, df_2h["atr14"], "2h")
    obs_1h = _e66.collect_obs(df_1h, df_1h["atr14"], "1h")
    fvgs_15m = _e66.collect_fvgs(df_15m, df_15m["atr14"], "15m")
    fvgs_20m = _e66.collect_fvgs(df_20m, df_20m["atr14"], "20m")
    fvgs_30m = _e66.collect_fvgs(df_30m, df_30m["atr14"], "30m")

    # Chain definitions
    chains4 = {
        "A": (fvgs_1d, obs_4h, obs_1h, fvgs_15m, "1d", "4h", "1h", "15m", df_1d),
        "B": (fvgs_12h, obs_4h, obs_1h, fvgs_15m, "12h", "4h", "1h", "15m", df_12h),
        "F": (fvgs_1d, obs_6h, obs_2h, fvgs_15m, "1d", "6h", "2h", "15m", df_1d),
        "J": (fvgs_1d, obs_4h, obs_1h, fvgs_20m, "1d", "4h", "1h", "20m", df_1d),
        "K": (fvgs_12h, obs_4h, obs_1h, fvgs_20m, "12h", "4h", "1h", "20m", df_12h),
        "L": (fvgs_1d, obs_6h, obs_2h, fvgs_20m, "1d", "6h", "2h", "20m", df_1d),
        "M": (fvgs_12h, obs_4h, obs_1h, fvgs_30m, "12h", "4h", "1h", "30m", df_12h),
        "I": (fvgs_12h, obs_4h, obs_2h, fvgs_15m, "12h", "4h", "2h", "15m", df_12h),
        "E": (fvgs_1d, obs_4h, obs_2h, fvgs_15m, "1d", "4h", "2h", "15m", df_1d),
    }
    # 3-stage chains
    chains3 = {
        "N": (fvgs_12h, obs_4h, fvgs_30m, "12h", "4h", "30m", df_12h),
        "O": (fvgs_12h, obs_6h, fvgs_30m, "12h", "6h", "30m", df_12h),
    }

    AM = 5  # primary multi
    print(f"\n[INFO] detect all chains with allow_multi={AM}")
    setups_by_chain = {}
    for name, args in chains4.items():
        s = detect_multi(*args, AM)
        setups_by_chain[name] = s
        print(f"  {name}: {len(s)} setups")
    for name, args in chains3.items():
        s = detect_3stage_multi(args[0], args[1], "OB", args[2],
                                 args[3], args[4], args[5], args[6], AM)
        setups_by_chain[name] = s
        print(f"  {name}: {len(s)} setups (3-stage)")

    # Also test allow_multi=999 for top chains
    print(f"\n[INFO] also allow_multi=inf for top chains")
    for name in ["A", "B", "F", "K", "M", "N"]:
        if name in chains4:
            s = detect_multi(*chains4[name], 999)
        else:
            args = chains3[name]
            s = detect_3stage_multi(args[0], args[1], "OB", args[2],
                                     args[3], args[4], args[5], args[6], 999)
        setups_by_chain[f"{name}_inf"] = s
        print(f"  {name}_inf: {len(s)} setups")

    # ===== Single-chain evaluation =====
    print(f"\n{'='*100}")
    print(f"SINGLE-CHAIN EVALUATION (RR={MIN_RR}+, WR>={MIN_WR}%, >={MIN_TRADES_PER_YEAR}/year)")
    print(f"{'='*100}")
    print(f"  {'chain':<10} {'AM':<5} {'RR':<5} {'dom':<6} {'n':>4} {'tpy':>5} {'WR':>6} {'total':>8} {'avg_R':>7} {'bad':>5} {'pass':>5}")

    rows = []
    for name, setups in setups_by_chain.items():
        for rr in [1.8, 2.0, 2.5]:
            for dom in [False, True]:
                df = _e66.evaluate(setups, rr, df_1m, df_1d, only_dom=dom)
                m = metrics_full(df, N_YEARS)
                if not m: continue
                passes = (m["tpy"] >= MIN_TRADES_PER_YEAR
                          and m["wr"] > MIN_WR
                          and rr > MIN_RR)
                rows.append({"chain": name, "rr": rr, "dom": dom, **m, "pass": passes})

    # Show only passing rows
    passing = [r for r in rows if r["pass"]]
    print(f"\n--- CHAINS PASSING ALL CRITERIA ---")
    if not passing:
        print("  (none)")
    else:
        for r in sorted(passing, key=lambda x: x["total"], reverse=True):
            dom_lbl = "+dom" if r["dom"] else "no_dom"
            print(f"  {r['chain']:<10} AM=5  RR={r['rr']}  {dom_lbl:<6} "
                  f"n={r['n']:>3} tpy={r['tpy']:5.1f} "
                  f"WR={r['wr']:5.1f}% total={r['total']:+6.1f}R "
                  f"avg={r['avg_R']:+5.2f}R bad={r['bad']}/{r['n_yrs']}")

    # Show top by tpy regardless of pass
    print(f"\n--- TOP 15 by trades/year (RR>1.5, WR>45%) ---")
    qualifying = [r for r in rows if r["rr"] > 1.5 and r["wr"] > 45]
    qualifying = sorted(qualifying, key=lambda x: x["tpy"], reverse=True)
    for r in qualifying[:15]:
        dom_lbl = "+dom" if r["dom"] else "no_dom"
        mark = "PASS" if r["pass"] else " - "
        print(f"  {mark} {r['chain']:<10} RR={r['rr']}  {dom_lbl:<6} "
              f"n={r['n']:>3} tpy={r['tpy']:5.1f} "
              f"WR={r['wr']:5.1f}% total={r['total']:+6.1f}R "
              f"avg={r['avg_R']:+5.2f}R bad={r['bad']}/{r['n_yrs']}")

    # ===== Portfolio combinations =====
    print(f"\n\n{'='*100}")
    print(f"PORTFOLIO COMBINATIONS (union dedup, allow_multi=5)")
    print(f"{'='*100}")

    def merge_setups(*setups_lists):
        all_s = []
        for lst in setups_lists: all_s.extend(lst)
        return _e69.dedup(all_s)

    portfolios = {
        "B+F (top2)": merge_setups(setups_by_chain["B"], setups_by_chain["F"]),
        "B+K (12h family)": merge_setups(setups_by_chain["B"], setups_by_chain["K"]),
        "B+F+K": merge_setups(setups_by_chain["B"], setups_by_chain["F"], setups_by_chain["K"]),
        "B+F+K+M": merge_setups(setups_by_chain["B"], setups_by_chain["F"],
                                  setups_by_chain["K"], setups_by_chain["M"]),
        "B+F+J+K (incl 1d+12h x 15m+20m)": merge_setups(
            setups_by_chain["B"], setups_by_chain["F"],
            setups_by_chain["J"], setups_by_chain["K"]),
        "A+B+F (3 anchors)": merge_setups(setups_by_chain["A"], setups_by_chain["B"], setups_by_chain["F"]),
        "All 4-stage (A B F I J K L M E)": merge_setups(
            setups_by_chain["A"], setups_by_chain["B"], setups_by_chain["F"],
            setups_by_chain["I"], setups_by_chain["J"], setups_by_chain["K"],
            setups_by_chain["L"], setups_by_chain["M"], setups_by_chain["E"]),
        "B+F+N (incl 3-stage)": merge_setups(
            setups_by_chain["B"], setups_by_chain["F"], setups_by_chain["N"]),
        "Top4 multi=inf (B+F+K+M)": merge_setups(
            setups_by_chain["B_inf"], setups_by_chain["F_inf"],
            setups_by_chain["K_inf"], setups_by_chain["M_inf"]),
        "All multi=inf": merge_setups(
            setups_by_chain["A_inf"], setups_by_chain["B_inf"],
            setups_by_chain["F_inf"], setups_by_chain["K_inf"],
            setups_by_chain["M_inf"], setups_by_chain["N_inf"]),
    }

    print(f"\n  {'portfolio':<48} {'raw':>5} {'RR':<5} {'dom':<6} {'n':>4} {'tpy':>5} {'WR':>6} {'total':>8} {'avg_R':>7} {'bad':>5} {'pass':>5}")
    portfolio_rows = []
    for pname, setups in portfolios.items():
        for rr in [1.8, 2.0, 2.5]:
            for dom in [False, True]:
                df = _e66.evaluate(setups, rr, df_1m, df_1d, only_dom=dom)
                m = metrics_full(df, N_YEARS)
                if not m: continue
                passes = (m["tpy"] >= MIN_TRADES_PER_YEAR
                          and m["wr"] > MIN_WR
                          and rr > MIN_RR)
                portfolio_rows.append({"portfolio": pname, "raw": len(setups),
                                        "rr": rr, "dom": dom, "pass": passes, **m})
                if passes or m["tpy"] >= 20:
                    dom_lbl = "+dom" if dom else "no_dom"
                    mark = "PASS" if passes else " - "
                    print(f"  {pname[:46]:<48} {len(setups):>5} RR={rr:<3} {dom_lbl:<6} "
                          f"n={m['n']:>3} tpy={m['tpy']:5.1f} "
                          f"WR={m['wr']:5.1f}% total={m['total']:+6.1f}R "
                          f"avg={m['avg_R']:+5.2f}R bad={m['bad']}/{m['n_yrs']} {mark}")

    # PASSING PORTFOLIOS
    print(f"\n\n{'='*100}")
    print(f"PORTFOLIOS PASSING ALL CRITERIA (RR>1.5, WR>45%, tpy>={MIN_TRADES_PER_YEAR})")
    print(f"{'='*100}")
    pp = sorted([r for r in portfolio_rows if r["pass"]],
                key=lambda x: x["total"], reverse=True)
    if not pp:
        print("  (none)")
    else:
        for r in pp:
            dom_lbl = "+dom" if r["dom"] else "no_dom"
            print(f"  {r['portfolio'][:48]:<48} RR={r['rr']}  {dom_lbl:<6} "
                  f"n={r['n']:>3} tpy={r['tpy']:5.1f} "
                  f"WR={r['wr']:5.1f}% total={r['total']:+6.1f}R "
                  f"avg={r['avg_R']:+5.2f}R bad={r['bad']}/{r['n_yrs']}")

    print(f"\n[TIME] {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
