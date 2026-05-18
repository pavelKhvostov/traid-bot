"""etap_147: Walk-forward Variant D (Variant C + score>=0.50).

Variant D (etap_146): 68 trades / WR 55.9% / +48.8R / 0 bad / DD -3.7R / R/tr +0.72.
Best DD/PnL ratio во всей серии. Проверяем OOS robustness.

Окна: 2021..2026 test, train [2020..test-1].
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
SCORE_THRESHOLD = 0.50


def collect_variant_d_trades(symbol, start_date, cap, th, cf):
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

    # score filter
    filtered = []
    for s in combined:
        sl_arr = score_long.index.searchsorted(s["signal_time"], side="right") - 1
        if sl_arr < 0: continue
        ss = score_long.iloc[sl_arr] if s["direction"] == "LONG" else score_short.iloc[sl_arr]
        if pd.isna(ss): continue
        if float(ss) >= SCORE_THRESHOLD: filtered.append(s)

    trades = []
    for s in filtered:
        outc, R = simulate_floating(s, s["entry"], s["sl"], df_1m, df_1h,
                                     score_long, score_short, R_cap=cap,
                                     threshold=th, confirm=cf)
        if outc in ("win", "loss"):
            trades.append({"R": R, "year": s["signal_time"].year, "time": s["signal_time"]})
    return trades


def main():
    print("etap_147: Walk-forward Variant D (Variant C + score>=0.50)")
    print()
    all_trades = []
    for sym, start, cap, th, cf in SYMBOLS:
        print(f"  Computing {sym}...")
        ts = collect_variant_d_trades(sym, start, cap, th, cf)
        for t in ts: t["symbol"] = sym
        all_trades.extend(ts)
        print(f"    {sym}: {len(ts)} Variant D trades")
    all_trades.sort(key=lambda t: t["time"])
    print(f"  Total Variant D portfolio trades: {len(all_trades)}")
    print()

    print("  Year-by-year:")
    print("  " + "="*80)
    by_year = defaultdict(lambda: {"n":0, "W":0, "R":0.0})
    for t in all_trades:
        by_year[t["year"]]["n"] += 1
        if t["R"] > 0: by_year[t["year"]]["W"] += 1
        by_year[t["year"]]["R"] += t["R"]
    for yr in sorted(by_year):
        d = by_year[yr]
        wr = d["W"]/d["n"]*100 if d["n"] else 0
        marker = " <- BAD" if d["R"] < 0 else ""
        print(f"    {yr}: n={d['n']:>3d} WR={wr:>4.1f}% PnL={d['R']:>+6.1f}R{marker}")
    total_pnl = sum(by_year[yr]["R"] for yr in by_year)
    total_n = sum(by_year[yr]["n"] for yr in by_year)
    bad = sum(1 for yr in by_year if by_year[yr]["R"] < 0)
    print(f"  TOTAL: n={total_n} PnL={total_pnl:+.1f}R bad={bad}/{len(by_year)}")
    print()

    print("  Walk-forward:")
    print("  " + "="*80)
    print(f"    {'Test year':>9} {'Train n':>8} {'Train PnL':>10} {'Train WR':>9} "
          f"{'Test n':>7} {'Test PnL':>9} {'Test WR':>8}")
    test_years_to_check = [2021, 2022, 2023, 2024, 2025, 2026]
    cum_test_pnl = 0.0; cum_test_n = 0; cum_test_W = 0
    for test_yr in test_years_to_check:
        train = [t for t in all_trades if t["year"] < test_yr]
        test = [t for t in all_trades if t["year"] == test_yr]
        tr_n = len(train); tr_pnl = sum(t["R"] for t in train); tr_W = sum(1 for t in train if t["R"] > 0)
        ts_n = len(test); ts_pnl = sum(t["R"] for t in test); ts_W = sum(1 for t in test if t["R"] > 0)
        tr_wr = tr_W/tr_n*100 if tr_n else 0
        ts_wr = ts_W/ts_n*100 if ts_n else 0
        cum_test_pnl += ts_pnl; cum_test_n += ts_n; cum_test_W += ts_W
        marker = " <- BAD" if ts_pnl < 0 else ""
        print(f"    {test_yr:>9d} {tr_n:>8d} {tr_pnl:>+8.1f}R {tr_wr:>7.1f}% "
              f"{ts_n:>7d} {ts_pnl:>+7.1f}R {ts_wr:>6.1f}%{marker}")
    print()
    if cum_test_n > 0:
        print(f"  Combined OOS 2021-2026: n={cum_test_n} WR={cum_test_W/cum_test_n*100:.1f}% PnL={cum_test_pnl:+.1f}R")
    print(f"  Compare in-sample: 68 trades / WR 55.9% / +48.8R / 0 bad / DD -3.7R / R/tr +0.72")


if __name__ == "__main__":
    main()
