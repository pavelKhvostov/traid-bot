"""etap_136: A2 floating TP per-symbol tuning grid на BTC и ETH.

etap_135 portfolio = +77.9R с одним global конфигом (cap=5.0 th=-0.5 cf=3).
Тестируем per-symbol optimization (как для 1.1.1: BTC/ETH 4.5/-0.25/2 vs SOL 3.5/0/1).

Grid:
  R_cap     ∈ {3.0, 3.5, 4.0, 4.5, 5.0}
  threshold ∈ {-0.5, -0.25, 0.0, +0.25}
  confirm   ∈ {1, 2, 3}

Total: 60 configs / symbol. Best by PnL и by R/tr.
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
for nm, p in [("etap121_core", _E121), ("etap131_core", _E131),
               ("etap128_core", _E128), ("etap103_core", _E103)]:
    _spec = _ilu.spec_from_file_location(nm, p)
    _m = _ilu.module_from_spec(_spec); _sys.modules[nm] = _m
    _spec.loader.exec_module(_m)

_e121 = _sys.modules["etap121_core"]
_e131 = _sys.modules["etap131_core"]
_e128 = _sys.modules["etap128_core"]
_e103 = _sys.modules["etap103_core"]

collect_wicked_fractal_obs = _e121.collect_wicked_fractal_obs
first_setup_per_ob = _e131.first_setup_per_ob
simulate_floating = _e128.simulate_floating
build_score_series = _e103.build_score_series

SYMBOLS = [("BTCUSDT", "2020-01-01"), ("ETHUSDT", "2020-05-15")]
RR = 2.0
CAPS = [3.0, 3.5, 4.0, 4.5, 5.0]
THS = [-0.5, -0.25, 0.0, 0.25]
CFS = [1, 2, 3]


def collect_setups_and_simulate(symbol, start_date):
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

    setups = []
    for ob, df_l1 in all_ob_d:
        s = first_setup_per_ob(ob, df_l1, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m,
                               macro_kind="FVG", swept_required=False,
                               entry_pct=0.80, sl_pct=0.35)
        if s is not None: setups.append(s)
    score_long, score_short = build_score_series(df_1h)

    results = {}
    for cap in CAPS:
        for th in THS:
            for cf in CFS:
                trades = []
                for s in setups:
                    outc, R = simulate_floating(s, s["entry"], s["sl"], df_1m, df_1h,
                                                 score_long, score_short, R_cap=cap,
                                                 threshold=th, confirm=cf)
                    if outc in ("win", "loss"):
                        trades.append({"R": R, "year": s["signal_time"].year})
                n = len(trades)
                if n == 0: continue
                W = sum(1 for t in trades if t["R"] > 0)
                pnl = sum(t["R"] for t in trades)
                yr_map = defaultdict(float)
                for t in trades: yr_map[t["year"]] += t["R"]
                bad = sum(1 for v in yr_map.values() if v < 0)
                results[(cap, th, cf)] = {
                    "n": n, "wr": W/n*100, "pnl": pnl,
                    "rpt": pnl/n, "bad": bad, "ytot": len(yr_map),
                }
    return setups, results


def main():
    print("etap_136: A2 floating TP per-symbol tuning grid (BTC + ETH)")
    print(f"Grid: cap×th×cf = {len(CAPS)}×{len(THS)}×{len(CFS)} = {len(CAPS)*len(THS)*len(CFS)} configs/symbol")
    print()
    per_sym = {}
    for sym, start in SYMBOLS:
        print(f"  Computing {sym}...")
        setups, results = collect_setups_and_simulate(sym, start)
        per_sym[sym] = (setups, results)
        print(f"    {sym}: {len(setups)} setups, {len(results)} configs")
    print()

    # Top-5 configs per symbol by PnL
    print("  TOP-5 by PnL per symbol:")
    print("  " + "="*85)
    for sym, (setups, results) in per_sym.items():
        ranked = sorted(results.items(), key=lambda kv: -kv[1]["pnl"])
        print(f"\n  {sym} (n_setups={len(setups)}):")
        print(f"    {'cap':>4} {'th':>6} {'cf':>2}  {'n':>3} {'WR':>6} {'PnL':>8} {'R/tr':>6} {'bad':>5}")
        for (cap, th, cf), d in ranked[:5]:
            print(f"    {cap:>4.1f} {th:>+5.2f} {cf:>2}  {d['n']:>3d} {d['wr']:>5.1f}% {d['pnl']:>+6.1f}R {d['rpt']:>+5.2f} {d['bad']}/{d['ytot']}")

    # Top-5 by R/tr (per-trade)
    print()
    print("  TOP-5 by R/tr per symbol (only configs n>=30):")
    print("  " + "="*85)
    for sym, (setups, results) in per_sym.items():
        eligible = [(k, v) for k, v in results.items() if v["n"] >= 30]
        ranked = sorted(eligible, key=lambda kv: -kv[1]["rpt"])
        print(f"\n  {sym}:")
        print(f"    {'cap':>4} {'th':>6} {'cf':>2}  {'n':>3} {'WR':>6} {'PnL':>8} {'R/tr':>6} {'bad':>5}")
        for (cap, th, cf), d in ranked[:5]:
            print(f"    {cap:>4.1f} {th:>+5.2f} {cf:>2}  {d['n']:>3d} {d['wr']:>5.1f}% {d['pnl']:>+6.1f}R {d['rpt']:>+5.2f} {d['bad']}/{d['ytot']}")

    # Per-symbol best PnL → portfolio sum
    print()
    print("  Portfolio sum with PER-SYMBOL optimal:")
    print("  " + "="*85)
    total_pnl = 0.0; total_n = 0; total_bad = 0
    for sym, (setups, results) in per_sym.items():
        best_key = max(results, key=lambda k: results[k]["pnl"])
        d = results[best_key]
        cap, th, cf = best_key
        total_pnl += d["pnl"]; total_n += d["n"]; total_bad += d["bad"]
        print(f"  {sym}: cap={cap} th={th:+.2f} cf={cf} -> PnL {d['pnl']:+.1f}R / n={d['n']} / WR={d['wr']:.1f}% / bad={d['bad']}/{d['ytot']}")
    print(f"  TOTAL: PnL={total_pnl:+.1f}R  n={total_n}  bad_total={total_bad}")
    print()
    print(f"  ref global (cap=5.0 th=-0.5 cf=3): +77.9R / 146 / 4 bad sum")


if __name__ == "__main__":
    main()
