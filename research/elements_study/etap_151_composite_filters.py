"""etap_151: Composite filters на Variant C portfolio.

Tests:
  1. Variant G = Asia (Variant F) + score>=0.5 -- два validated filter stacked
  2. Variant C - hour 13 UTC -- excludes worst hour (R/tr -0.58 etap_149)
  3. Variant C - bottom 3 hours (13, 11, 17) -- exclude anti-edge cluster
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


def collect_variant_c_setups_and_scored(symbol, start_date):
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

    for s in combined:
        s["hour"] = s["signal_time"].hour
        sl_arr = score_long.index.searchsorted(s["signal_time"], side="right") - 1
        if sl_arr < 0:
            s["score"] = float("nan")
        else:
            ss = score_long.iloc[sl_arr] if s["direction"] == "LONG" else score_short.iloc[sl_arr]
            s["score"] = float(ss) if not pd.isna(ss) else float("nan")
    return combined, df_1m, df_1h, score_long, score_short


def eval_filter(setups, df_1m, df_1h, sl, ss, cap, th, cf, filter_fn):
    filtered = [s for s in setups if filter_fn(s)]
    trades = []
    for s in filtered:
        outc, R = simulate_floating(s, s["entry"], s["sl"], df_1m, df_1h,
                                     sl, ss, R_cap=cap, threshold=th, confirm=cf)
        if outc in ("win", "loss"):
            trades.append({"R": R, "year": s["signal_time"].year, "time": s["signal_time"]})
    n = len(trades)
    if n == 0: return None
    W = sum(1 for t in trades if t["R"] > 0); pnl = sum(t["R"] for t in trades)
    yr_map = defaultdict(float)
    for t in trades: yr_map[t["year"]] += t["R"]
    bad = sum(1 for v in yr_map.values() if v < 0)
    trades_sorted = sorted(trades, key=lambda t: t["time"])
    cum = 0.0; peak = 0.0; dd = 0.0
    for t in trades_sorted:
        cum += t["R"]; peak = max(peak, cum); dd = max(dd, peak - cum)
    return {"n": n, "wr": W/n*100, "pnl": pnl, "rpt": pnl/n,
            "bad": bad, "ytot": len(yr_map), "dd": dd, "setups": len(filtered)}


def main():
    print("etap_151: Composite filters tests")
    print()
    per_sym = {}
    for sym, start, cap, th, cf in SYMBOLS:
        print(f"  Computing {sym}...")
        setups, df_1m, df_1h, sl, ss = collect_variant_c_setups_and_scored(sym, start)
        per_sym[sym] = (setups, df_1m, df_1h, sl, ss, cap, th, cf)
        print(f"    {sym}: {len(setups)} setups")
    print()

    # Anti-edge hours (etap_149): hour 13 R/tr -0.58, hour 11 R/tr -0.28, hour 17 R/tr -0.33
    ANTI_HOURS = {11, 13, 17}
    DEAD_HOUR = {13}

    filters = [
        ("Variant C (baseline)",      lambda s: True),
        ("Variant F (Asia 00-07)",    lambda s: 0 <= s["hour"] < 7),
        ("Variant G (Asia + score>=0.5)", lambda s: 0 <= s["hour"] < 7 and (not pd.isna(s["score"])) and s["score"] >= 0.5),
        ("Variant C - hour 13",       lambda s: s["hour"] != 13),
        ("Variant C - anti-cluster (11,13,17)", lambda s: s["hour"] not in ANTI_HOURS),
        ("Variant C + score>=0 - anti-cluster", lambda s: s["hour"] not in ANTI_HOURS and (not pd.isna(s["score"])) and s["score"] >= 0.0),
    ]

    for sym in per_sym:
        setups, df_1m, df_1h, sl, ss, cap, th, cf = per_sym[sym]
        print(f"\n  {sym}:")
        print(f"    {'Filter':<42}  {'setups':>6}  {'n':>3}  {'WR':>5}  {'PnL':>8}  {'R/tr':>6}  {'bad':>5}  {'DD':>7}")
        for label, fn in filters:
            m = eval_filter(setups, df_1m, df_1h, sl, ss, cap, th, cf, fn)
            if m is None:
                print(f"    {label:<42}  no data"); continue
            print(f"    {label:<42}  {m['setups']:>6d}  {m['n']:>3d}  {m['wr']:>4.1f}%  "
                  f"{m['pnl']:>+6.1f}R  {m['rpt']:>+5.2f}  {m['bad']}/{m['ytot']}  -{m['dd']:>4.1f}R")

    print()
    print("  Portfolio BTC+ETH:")
    print("  " + "="*110)
    print(f"    {'Filter':<42}  {'n':>3}  {'WR':>5}  {'PnL':>8}  {'R/tr':>6}  {'bad_total':>9}  {'DD':>7}")
    for label, fn in filters:
        all_trades = []
        for sym in per_sym:
            setups, df_1m, df_1h, sl, ss, cap, th, cf = per_sym[sym]
            filtered = [s for s in setups if fn(s)]
            for s in filtered:
                outc, R = simulate_floating(s, s["entry"], s["sl"], df_1m, df_1h,
                                             sl, ss, R_cap=cap, threshold=th, confirm=cf)
                if outc in ("win", "loss"):
                    all_trades.append({"R": R, "year": s["signal_time"].year, "time": s["signal_time"]})
        n = len(all_trades)
        if n == 0:
            print(f"    {label:<42}  no data"); continue
        W = sum(1 for t in all_trades if t["R"] > 0); pnl = sum(t["R"] for t in all_trades)
        yr_map = defaultdict(float)
        for t in all_trades: yr_map[t["year"]] += t["R"]
        bad = sum(1 for v in yr_map.values() if v < 0)
        all_trades.sort(key=lambda t: t["time"])
        cum = 0.0; peak = 0.0; dd = 0.0
        for t in all_trades:
            cum += t["R"]; peak = max(peak, cum); dd = max(dd, peak - cum)
        print(f"    {label:<42}  {n:>3d}  {W/n*100:>4.1f}%  {pnl:>+6.1f}R  {pnl/n:>+5.2f}  "
              f"{bad:>3d}/{len(yr_map)}  -{dd:>5.1f}R")


if __name__ == "__main__":
    main()
