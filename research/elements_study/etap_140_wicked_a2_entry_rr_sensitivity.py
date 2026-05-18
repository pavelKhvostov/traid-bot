"""etap_140: entry_pct + RR sensitivity для Variant B (BTC+ETH).

Variant B uses entry_pct=0.80 (1.1.1 canon), RR=2.0. Тестируем:
  entry_pct ∈ {0.50, 0.60, 0.70, 0.80, 0.90} -- 0.50 = mid FVG, 0.80 = 1.1.1, 0.70 = 1.1.2
  RR        ∈ {1.5, 2.0, 2.2, 2.5, 3.0}

Per-symbol floating TP: BTC cap=5.0 th=0.0 cf=1, ETH cap=5.0 th=-0.5 cf=3.
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

SYMBOLS = [
    ("BTCUSDT", "2020-01-01", 5.0, 0.0, 1),
    ("ETHUSDT", "2020-05-15", 5.0, -0.5, 3),
]
ENTRY_PCTS = [0.50, 0.60, 0.70, 0.80, 0.90]


def run_symbol_entry(symbol, start_date, cap, th, cf):
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

    results = {}
    for e_pct in ENTRY_PCTS:
        setups = []
        for ob, df_l1 in all_ob_d:
            s = first_setup_per_ob(ob, df_l1, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m,
                                   macro_kind="FVG", swept_required=False,
                                   entry_pct=e_pct, sl_pct=0.35)
            if s is not None: setups.append(s)
        trades = []
        for s in setups:
            outc, R = simulate_floating(s, s["entry"], s["sl"], df_1m, df_1h,
                                         score_long, score_short, R_cap=cap,
                                         threshold=th, confirm=cf)
            if outc in ("win", "loss"):
                trades.append({"R": R, "year": s["signal_time"].year, "time": s["signal_time"]})
        n = len(trades)
        if n == 0:
            results[e_pct] = None; continue
        W = sum(1 for t in trades if t["R"] > 0)
        pnl = sum(t["R"] for t in trades)
        yr_map = defaultdict(float)
        for t in trades: yr_map[t["year"]] += t["R"]
        bad = sum(1 for v in yr_map.values() if v < 0)
        trades_sorted = sorted(trades, key=lambda t: t["time"])
        cum = 0.0; peak = 0.0; max_dd = 0.0
        for t in trades_sorted:
            cum += t["R"]; peak = max(peak, cum)
            max_dd = max(max_dd, peak - cum)
        results[e_pct] = {"n": n, "wr": W/n*100, "pnl": pnl, "rpt": pnl/n,
                            "bad": bad, "ytot": len(yr_map), "max_dd": max_dd,
                            "n_setups": len(setups)}
    return results


def main():
    print("etap_140: entry_pct sensitivity для Variant B")
    print(f"entry_pct grid: {ENTRY_PCTS}  (0.80 = canon Variant B)")
    print(f"sl_pct fixed=0.35, RR baseline=2.0, per-symbol floating TP")
    print()
    per_sym = {}
    for sym, start, cap, th, cf in SYMBOLS:
        print(f"  Computing {sym} (cap={cap} th={th} cf={cf})...")
        per_sym[sym] = run_symbol_entry(sym, start, cap, th, cf)

    print()
    print("  Per-symbol breakdown:")
    print("  " + "="*110)
    for sym in per_sym:
        print(f"\n  {sym}:")
        print(f"    {'entry':>5}  {'setups':>6}  {'n':>3}  {'WR':>5}  {'PnL':>8}  {'R/tr':>6}  {'bad':>5}  {'max_dd':>7}")
        for e_pct in ENTRY_PCTS:
            d = per_sym[sym][e_pct]
            if d is None:
                print(f"    {e_pct:>5.2f}  no data"); continue
            marker = "  <- canon" if e_pct == 0.80 else ""
            print(f"    {e_pct:>5.2f}  {d['n_setups']:>6d}  {d['n']:>3d}  {d['wr']:>4.1f}%  {d['pnl']:>+6.1f}R  {d['rpt']:>+5.2f}  {d['bad']}/{d['ytot']}  -{d['max_dd']:>5.1f}R{marker}")

    print()
    print("  Portfolio sum per entry_pct (BTC+ETH):")
    print("  " + "="*110)
    print(f"    {'entry':>5}  {'n':>3}  {'PnL':>8}  {'R/tr':>6}  {'bad_total':>9}")
    for e_pct in ENTRY_PCTS:
        tot_n = 0; tot_pnl = 0.0; tot_bad = 0
        for sym in per_sym:
            d = per_sym[sym][e_pct]
            if d is None: continue
            tot_n += d["n"]; tot_pnl += d["pnl"]; tot_bad += d["bad"]
        rpt = tot_pnl / tot_n if tot_n else 0
        marker = "  <- canon (Variant B)" if e_pct == 0.80 else ""
        print(f"    {e_pct:>5.2f}  {tot_n:>3d}  {tot_pnl:>+6.1f}R  {rpt:>+5.2f}  {tot_bad:>7d}{marker}")


if __name__ == "__main__":
    main()
