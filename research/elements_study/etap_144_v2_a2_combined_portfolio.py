"""etap_144: V2 + A2 combined portfolio на BTC+ETH с Variant-B-style floating.

etap_143: V2 ∩ A2 = 5 setups (almost disjoint).
  A2: 85 setups, 69 closed, WR 75%, +43R, 0 bad
  V2: 258 setups, 198 closed, WR 64%, +38R, 2 bad
  Combined A2 + (V2\A2): 261 closed, +81R, 0 bad на BTC

Тестируем:
  1. V2 на ETH с Variant-B-style floating (etap_127 был с F12 baseline, тогда ETH +4R)
  2. Combined V2+A2 portfolio BTC+ETH
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
from strategies.strategy_1_1_1 import detect_ob_pair, detect_fvg

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


def collect_both(symbol, start_date, cap, th, cf):
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
    a2_setups, v2_setups = [], []
    for ob, df_l1 in all_ob_d:
        s_a = first_setup_per_ob(ob, df_l1, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m,
                                 macro_kind="FVG", swept_required=False,
                                 entry_pct=0.80, sl_pct=0.35)
        if s_a is not None:
            s_a["source"] = "A2"; a2_setups.append(s_a)
        s_v = first_v2_setup_per_ob(ob, df_l1, df_1h, df_2h, df_15m, df_20m)
        if s_v is not None:
            v2_setups.append(s_v)

    score_long, score_short = build_score_series(df_1h)

    a2_keys = set((s["signal_time"].floor("h"), s["direction"]) for s in a2_setups)
    v2_unique = [s for s in v2_setups if (s["signal_time"].floor("h"), s["direction"]) not in a2_keys]
    combined = a2_setups + v2_unique

    def sim_setups(setups):
        trades = []
        for s in setups:
            outc, R = simulate_floating(s, s["entry"], s["sl"], df_1m, df_1h,
                                         score_long, score_short, R_cap=cap,
                                         threshold=th, confirm=cf)
            if outc in ("win", "loss"):
                trades.append({"R": R, "year": s["signal_time"].year,
                                "time": s["signal_time"], "symbol": symbol})
        return trades

    return {
        "a2_trades": sim_setups(a2_setups),
        "v2_trades": sim_setups(v2_setups),
        "v2_unique_trades": sim_setups(v2_unique),
        "combined_trades": sim_setups(combined),
        "a2_n_setups": len(a2_setups),
        "v2_n_setups": len(v2_setups),
        "v2_unique_n_setups": len(v2_unique),
    }


def metrics(trades):
    n = len(trades)
    if n == 0: return None
    W = sum(1 for t in trades if t["R"] > 0); pnl = sum(t["R"] for t in trades)
    yr = defaultdict(float)
    for t in trades: yr[t["year"]] += t["R"]
    bad = sum(1 for v in yr.values() if v < 0)
    cum = 0.0; peak = 0.0; dd = 0.0
    trades_sorted = sorted(trades, key=lambda t: t["time"])
    for t in trades_sorted:
        cum += t["R"]; peak = max(peak, cum); dd = max(dd, peak - cum)
    return {"n": n, "wr": W/n*100, "pnl": pnl, "rpt": pnl/n, "bad": bad, "ytot": len(yr), "dd": dd}


def show(label, trades):
    m = metrics(trades)
    if m is None:
        print(f"  {label:<40} no data"); return
    print(f"  {label:<40} n={m['n']:>3d} WR={m['wr']:>4.1f}% PnL={m['pnl']:>+6.1f}R "
          f"R/tr={m['rpt']:+.2f} bad={m['bad']}/{m['ytot']} DD=-{m['dd']:>4.1f}R")


def main():
    print("etap_144: V2+A2 combined portfolio (BTC+ETH) with Variant-B-style floating")
    print()
    res = {}
    for sym, start, cap, th, cf in SYMBOLS:
        print(f"  Computing {sym} (cap={cap} th={th} cf={cf})...")
        res[sym] = collect_both(sym, start, cap, th, cf)
        print(f"    A2 setups={res[sym]['a2_n_setups']}  V2 setups={res[sym]['v2_n_setups']}  "
              f"V2\\A2={res[sym]['v2_unique_n_setups']}")

    print()
    print("  Per-symbol:")
    print("  " + "="*100)
    for sym in res:
        print(f"\n  {sym}:")
        show("A2 only",        res[sym]["a2_trades"])
        show("V2 only",        res[sym]["v2_trades"])
        show("V2 \\ A2 (V2 unique)", res[sym]["v2_unique_trades"])
        show("Combined A2 + (V2\\A2)", res[sym]["combined_trades"])

    print()
    print("  Portfolio merged BTC+ETH:")
    print("  " + "="*100)
    a2_port = res["BTCUSDT"]["a2_trades"] + res["ETHUSDT"]["a2_trades"]
    show("A2 portfolio (Variant B)", a2_port)
    v2_port = res["BTCUSDT"]["v2_trades"] + res["ETHUSDT"]["v2_trades"]
    show("V2 portfolio", v2_port)
    combined_port = res["BTCUSDT"]["combined_trades"] + res["ETHUSDT"]["combined_trades"]
    show("Combined A2 + (V2\\A2) portfolio", combined_port)

    # Year-by-year on combined portfolio
    print()
    print("  Combined A2+(V2\\A2) portfolio year-by-year:")
    print("  " + "-"*60)
    by_year = defaultdict(lambda: {"n": 0, "W": 0, "R": 0.0})
    for t in combined_port:
        by_year[t["year"]]["n"] += 1
        if t["R"] > 0: by_year[t["year"]]["W"] += 1
        by_year[t["year"]]["R"] += t["R"]
    for yr in sorted(by_year):
        d = by_year[yr]
        wr = d["W"]/d["n"]*100 if d["n"] else 0
        marker = " <- BAD" if d["R"] < 0 else ""
        print(f"    {yr}: n={d['n']:>3d} WR={wr:>4.1f}% PnL={d['R']:>+6.1f}R{marker}")


if __name__ == "__main__":
    main()
