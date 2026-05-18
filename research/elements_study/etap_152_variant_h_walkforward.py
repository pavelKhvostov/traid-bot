"""etap_152: Walk-forward Variant H (Variant C minus hours 11/13/17 UTC).

Variant H in-sample (etap_151): 461 trades / WR 54.7% / +149.9R / R/tr +0.33 / 1 bad / DD -8R.
Hours 11/13/17 chosen from etap_149 (negative R/tr in full-sample analysis).
Walk-forward: do these hours stay bad in OOS test years?
"""
from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
import importlib.util as _ilu
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists(): _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path: _sys.path.insert(0, str(_ROOT))

from collections import defaultdict
import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df

_E121 = _Path(__file__).parent / "etap_121_wicked_fractal_ob.py"
_E131 = _Path(__file__).parent / "etap_131_wicked_4stage_strict_dedup.py"
_E128 = _Path(__file__).parent / "etap_128_115_improve.py"
_E103 = _Path(__file__).parent / "etap_103_floating_tp.py"
_E143 = _Path(__file__).parent / "etap_143_v2_vs_a2_overlap.py"
for nm, p in [("etap121_core", _E121), ("etap131_core", _E131),
               ("etap128_core", _E128), ("etap103_core", _E103),
               ("etap143_core", _E143)]:
    _spec = _ilu.spec_from_file_location(nm, p)
    _m = _ilu.module_from_spec(_spec); _sys.modules[nm] = _m
    _spec.loader.exec_module(_m)

_e121 = _sys.modules["etap121_core"]
_e131 = _sys.modules["etap131_core"]
_e128 = _sys.modules["etap128_core"]
_e103 = _sys.modules["etap103_core"]
_e143 = _sys.modules["etap143_core"]

collect_wicked_fractal_obs = _e121.collect_wicked_fractal_obs
first_setup_per_ob = _e131.first_setup_per_ob
first_v2_setup_per_ob = _e143.first_v2_setup_per_ob
simulate_floating = _e128.simulate_floating
build_score_series = _e103.build_score_series

SYMBOLS = [
    ("BTCUSDT", "2020-01-01", 5.0, 0.0, 1),
    ("ETHUSDT", "2020-05-15", 5.0, -0.5, 3),
]
ANTI_HOURS = {11, 13, 17}


def collect_variant_c_trades_with_hour(symbol, start_date, cap, th, cf):
    df_1d = load_df(symbol, "1d"); df_1h = load_df(symbol, "1h"); df_1m = load_df(symbol, "1m")
    df_12h = compose_from_base(df_1h, "12h")
    df_4h = compose_from_base(df_1h, "4h"); df_6h = compose_from_base(df_1h, "6h")
    df_2h = compose_from_base(df_1h, "2h")
    df_15m = compose_from_base(df_1m, "15m"); df_20m = compose_from_base(df_1m, "20m")
    cutoff = pd.Timestamp(start_date, tz="UTC")
    df_1d = df_1d[df_1d.index >= cutoff].copy()
    df_1h = df_1h[df_1h.index >= cutoff].copy()
    df_12h = df_12h[df_12h.index >= cutoff].copy()
    df_4h = df_4h[df_4h.index >= cutoff].copy()
    df_6h = df_6h[df_6h.index >= cutoff].copy()
    df_2h = df_2h[df_2h.index >= cutoff].copy()
    df_15m = df_15m[df_15m.index >= cutoff].copy()
    df_20m = df_20m[df_20m.index >= cutoff].copy()
    df_1m = df_1m[df_1m.index >= cutoff]
    wf_1d = collect_wicked_fractal_obs(df_1d, 24)
    wf_12h = collect_wicked_fractal_obs(df_12h, 12)
    all_ob_d = [(ob, df_1d) for ob in wf_1d] + [(ob, df_12h) for ob in wf_12h]
    score_long, score_short = build_score_series(df_1h)

    a2_setups, v2_setups = [], []
    for ob, df_l1 in all_ob_d:
        s_a = first_setup_per_ob(ob, df_l1, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m,
                                 macro_kind="FVG", swept_required=False,
                                 entry_pct=0.80, sl_pct=0.35)
        if s_a is not None: a2_setups.append(s_a)
        s_v = first_v2_setup_per_ob(ob, df_l1, df_1h, df_2h, df_15m, df_20m)
        if s_v is not None: v2_setups.append(s_v)
    a2_keys = set((s["signal_time"].floor("h"), s["direction"]) for s in a2_setups)
    v2_unique = [s for s in v2_setups if (s["signal_time"].floor("h"), s["direction"]) not in a2_keys]
    combined = a2_setups + v2_unique

    trades = []
    for s in combined:
        outc, R = simulate_floating(s, s["entry"], s["sl"], df_1m, df_1h,
                                     score_long, score_short, R_cap=cap,
                                     threshold=th, confirm=cf)
        if outc in ("win", "loss"):
            trades.append({"R": R, "year": s["signal_time"].year,
                            "hour": s["signal_time"].hour, "time": s["signal_time"]})
    return trades


def main():
    print("etap_152: Walk-forward Variant H = Variant C minus hours 11/13/17 UTC")
    print()
    all_trades = []
    for sym, start, cap, th, cf in SYMBOLS:
        ts = collect_variant_c_trades_with_hour(sym, start, cap, th, cf)
        for t in ts: t["symbol"] = sym
        all_trades.extend(ts)
    all_trades.sort(key=lambda t: t["time"])

    h_trades = [t for t in all_trades if t["hour"] not in ANTI_HOURS]
    excluded = [t for t in all_trades if t["hour"] in ANTI_HOURS]
    print(f"  Variant C total: {len(all_trades)} trades")
    print(f"  Excluded (anti-hours 11/13/17): {len(excluded)} trades, {sum(t['R'] for t in excluded):+.1f}R")
    print(f"  Variant H (kept): {len(h_trades)} trades")
    print()

    # Year-by-year for H
    print("  Variant H year-by-year:")
    print("  " + "="*80)
    by_year = defaultdict(lambda: {"n":0, "W":0, "R":0.0})
    for t in h_trades:
        by_year[t["year"]]["n"] += 1
        if t["R"] > 0: by_year[t["year"]]["W"] += 1
        by_year[t["year"]]["R"] += t["R"]
    for yr in sorted(by_year):
        d = by_year[yr]
        wr = d["W"]/d["n"]*100 if d["n"] else 0
        marker = " <- BAD" if d["R"] < 0 else ""
        print(f"    {yr}: n={d['n']:>3d} WR={wr:>4.1f}% PnL={d['R']:>+6.1f}R{marker}")
    print()

    # Walk-forward: для каждого test year, check if anti-hours staying bad on train (data-leak proof)
    print("  Walk-forward: are anti-hours 11/13/17 still net-negative on cumulative train?")
    print("  " + "="*100)
    print(f"    {'Test year':>9}  {'Train anti-hours':>17} {'Train other-hours':>17}  {'Test anti R':>11} {'Test other R':>13}")
    for test_yr in [2021, 2022, 2023, 2024, 2025, 2026]:
        tr_anti = [t for t in all_trades if t["year"] < test_yr and t["hour"] in ANTI_HOURS]
        tr_other = [t for t in all_trades if t["year"] < test_yr and t["hour"] not in ANTI_HOURS]
        ts_anti = [t for t in all_trades if t["year"] == test_yr and t["hour"] in ANTI_HOURS]
        ts_other = [t for t in all_trades if t["year"] == test_yr and t["hour"] not in ANTI_HOURS]
        tr_anti_pnl = sum(t["R"] for t in tr_anti)
        tr_other_pnl = sum(t["R"] for t in tr_other)
        ts_anti_pnl = sum(t["R"] for t in ts_anti)
        ts_other_pnl = sum(t["R"] for t in ts_other)
        print(f"    {test_yr:>9d}  {len(tr_anti):>5d}/{tr_anti_pnl:>+6.1f}R  "
              f"{len(tr_other):>5d}/{tr_other_pnl:>+6.1f}R  "
              f"{len(ts_anti):>3d}/{ts_anti_pnl:>+5.1f}R  {len(ts_other):>3d}/{ts_other_pnl:>+5.1f}R")

    # Combined OOS
    print()
    oos_h = [t for t in all_trades if t["year"] >= 2021 and t["hour"] not in ANTI_HOURS]
    oos_anti = [t for t in all_trades if t["year"] >= 2021 and t["hour"] in ANTI_HOURS]
    print(f"  OOS Variant H (2021-2026): n={len(oos_h)} PnL={sum(t['R'] for t in oos_h):+.1f}R "
          f"R/tr={sum(t['R'] for t in oos_h)/len(oos_h) if oos_h else 0:+.2f}")
    print(f"  OOS Anti-hours (2021-2026): n={len(oos_anti)} PnL={sum(t['R'] for t in oos_anti):+.1f}R "
          f"R/tr={sum(t['R'] for t in oos_anti)/len(oos_anti) if oos_anti else 0:+.2f}")
    print()
    print("  In-sample reference: Variant H 461 / +149.9R / R/tr +0.33")


if __name__ == "__main__":
    main()
