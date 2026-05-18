"""etap_142: Walk-forward валидация Tier-1 premium signal.

Tier-1 (etap_141): BTC + Variant B + score>=+0.50 -> 22 trades / 86% WR / 0 DD / 0 bad / +32.8R.
22 trades over 6.3y -- thin sample, риск overfit. Walk-forward test.

Окна: 2023, 2024, 2025, 2026 (test) на train [2020..test-1].
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

SYMBOL = "BTCUSDT"
START_DATE = "2020-01-01"


def main():
    print("etap_142: Walk-forward Tier-1 premium (BTC + Variant B + score>=0.50)")
    print()
    df_1d = load_df(SYMBOL, "1d"); df_1h = load_df(SYMBOL, "1h"); df_1m = load_df(SYMBOL, "1m")
    df_12h = compose_from_base(df_1h, "12h")
    df_4h = compose_from_base(df_1h, "4h"); df_6h = compose_from_base(df_1h, "6h")
    df_2h = compose_from_base(df_1h, "2h")
    df_15m = compose_from_base(df_1m, "15m"); df_20m = compose_from_base(df_1m, "20m")
    cutoff = pd.Timestamp(START_DATE, tz="UTC")
    df_1d = df_1d[df_1d.index >= cutoff].copy()
    df_1h = df_1h[df_1h.index >= cutoff].copy()
    df_12h = df_12h[df_12h.index >= cutoff].copy()
    df_4h = df_4h[df_4h.index >= cutoff].copy()
    df_6h = df_6h[df_6h.index >= cutoff].copy()
    df_2h = df_2h[df_2h.index >= cutoff].copy()
    df_15m = df_15m[df_15m.index >= cutoff].copy()
    df_20m = df_20m[df_20m.index >= cutoff].copy()
    df_1m = df_1m[df_1m.index >= cutoff]
    score_long, score_short = build_score_series(df_1h)
    wf_1d = collect_wicked_fractal_obs(df_1d, 24)
    wf_12h = collect_wicked_fractal_obs(df_12h, 12)
    all_ob_d = [(ob, df_1d) for ob in wf_1d] + [(ob, df_12h) for ob in wf_12h]
    setups = []
    for ob, df_l1 in all_ob_d:
        s = first_setup_per_ob(ob, df_l1, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m,
                               macro_kind="FVG", swept_required=False,
                               entry_pct=0.80, sl_pct=0.35)
        if s is not None: setups.append(s)
    # attach score
    for s in setups:
        sl_arr = score_long.index.searchsorted(s["signal_time"], side="right") - 1
        if sl_arr < 0:
            s["score"] = float("nan")
        else:
            ss = score_long.iloc[sl_arr] if s["direction"] == "LONG" else score_short.iloc[sl_arr]
            s["score"] = float(ss) if not pd.isna(ss) else float("nan")
    # simulate all setups with Variant B's BTC config (cap=5.0 th=0.0 cf=1)
    trades = []
    for s in setups:
        outc, R = simulate_floating(s, s["entry"], s["sl"], df_1m, df_1h,
                                     score_long, score_short, R_cap=5.0,
                                     threshold=0.0, confirm=1)
        if outc in ("win", "loss"):
            trades.append({"R": R, "year": s["signal_time"].year,
                            "time": s["signal_time"], "score": s["score"]})
    print(f"  Total BTC closed trades: {len(trades)}")

    # Year-by-year, with vs without score>=0.50 filter
    print()
    print("  Year-by-year breakdown:")
    print("  " + "="*100)
    print(f"  {'Year':>4}  {'All n':>5} {'All WR':>7} {'All PnL':>8}  |  "
          f"{'Tier-1 n':>8} {'Tier-1 WR':>9} {'Tier-1 PnL':>11}  {'Tier-1 trades':>16}")
    print("  " + "-"*100)
    by_year_all = defaultdict(list); by_year_t1 = defaultdict(list)
    for t in trades:
        by_year_all[t["year"]].append(t["R"])
        if not pd.isna(t["score"]) and t["score"] >= 0.50:
            by_year_t1[t["year"]].append(t["R"])
    for yr in sorted(by_year_all.keys()):
        ar = by_year_all[yr]; tr = by_year_t1[yr]
        a_n = len(ar); a_w = sum(1 for r in ar if r > 0); a_pnl = sum(ar)
        t_n = len(tr); t_w = sum(1 for r in tr if r > 0); t_pnl = sum(tr)
        a_wr = a_w/a_n*100 if a_n else 0
        t_wr = t_w/t_n*100 if t_n else 0
        trades_str = ", ".join(f"{r:+.1f}" for r in tr) if tr else "-"
        print(f"  {yr:>4}  {a_n:>5d} {a_wr:>6.1f}% {a_pnl:>+7.1f}R  |  "
              f"{t_n:>8d} {t_wr:>8.1f}% {t_pnl:>+10.1f}R  {trades_str}")

    # Walk-forward: tier-1 trades grouped by year
    print()
    print("  Tier-1 OOS check (each year acts as 'test', prior years as 'train'):")
    print("  " + "="*100)
    print(f"  Train period: 2020..N-1 (count Tier-1 trades + PnL)")
    print(f"  Test year N: count Tier-1 trades + PnL")
    print()
    train_pnl_cum = 0.0; train_n_cum = 0; train_w_cum = 0
    test_pnl_cum = 0.0; test_n_cum = 0; test_w_cum = 0
    print(f"  {'Test year':>9} {'Train trades':>13} {'Train PnL':>10} {'Train WR':>9}  "
          f"{'Test trades':>12} {'Test PnL':>9} {'Test WR':>8}")
    test_years = sorted(by_year_all.keys())[1:]  # skip first year (no train)
    for test_yr in test_years:
        train = [r for yr in by_year_t1 for r in by_year_t1[yr] if yr < test_yr]
        test = by_year_t1.get(test_yr, [])
        tr_n = len(train); tr_w = sum(1 for r in train if r > 0); tr_pnl = sum(train)
        ts_n = len(test); ts_w = sum(1 for r in test if r > 0); ts_pnl = sum(test)
        tr_wr = tr_w/tr_n*100 if tr_n else 0
        ts_wr = ts_w/ts_n*100 if ts_n else 0
        print(f"  {test_yr:>9d} {tr_n:>13d} {tr_pnl:>+8.1f}R {tr_wr:>7.1f}%  "
              f"{ts_n:>12d} {ts_pnl:>+7.1f}R {ts_wr:>6.1f}%")
        test_pnl_cum += ts_pnl; test_n_cum += ts_n; test_w_cum += ts_w

    print()
    if test_n_cum > 0:
        print(f"  Combined OOS (Tier-1 trades in years 2021-2026): "
              f"n={test_n_cum}  WR={test_w_cum/test_n_cum*100:.1f}%  PnL={test_pnl_cum:+.1f}R")
    print(f"  Compare in-sample full-period Tier-1 (etap_141): 22 / 86.4% / +32.8R / 0 DD")


if __name__ == "__main__":
    main()
