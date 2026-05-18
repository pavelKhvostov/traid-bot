"""etap_138: Walk-forward validation Variant B на BTC+ETH portfolio.

Variant B (etap_137): BTC cap=5.0 th=0.0 cf=1 + ETH cap=5.0 th=-0.5 cf=3 = +80.3R / 0 bad / 6.3y.
Опасность: per-symbol grid выбран на ВСЕЙ выборке (in-sample) -- может быть overfit.

Walk-forward подход:
  Окно 1: train 2020-2022 (3y) -> pick optimal config -> test 2023 (1y)
  Окно 2: train 2020-2023 (4y) -> pick optimal config -> test 2024 (1y)
  Окно 3: train 2020-2024 (5y) -> pick optimal config -> test 2025 (1y)
  Окно 4: train 2020-2025 (6y) -> pick optimal config -> test 2026 (partial)

Считаем кумулятивный test-PnL. Если walk-forward PnL положителен и
~совпадает с in-sample, значит strategy не overfit.

Grid pruned: cap ∈ {3.5, 4.5, 5.0}, th ∈ {-0.5, 0.0}, cf ∈ {1, 3} = 12 configs.
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
CAPS = [3.5, 4.5, 5.0]
THS = [-0.5, 0.0]
CFS = [1, 3]


def simulate_setups_all_configs(symbol, start_date):
    """Возвращает для каждого setup'а dict {config: (year, R)}."""
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
    # For each setup compute (year, R) for each config
    per_setup_results = []  # list of (year, time, {cfg: R})
    for s in setups:
        cfg_results = {}
        for cap in CAPS:
            for th in THS:
                for cf in CFS:
                    outc, R = simulate_floating(s, s["entry"], s["sl"], df_1m, df_1h,
                                                 score_long, score_short, R_cap=cap,
                                                 threshold=th, confirm=cf)
                    if outc in ("win", "loss"):
                        cfg_results[(cap, th, cf)] = R
        if cfg_results:
            per_setup_results.append((s["signal_time"].year, s["signal_time"], cfg_results))
    return per_setup_results


def pick_best_in_train(per_setup, train_end_year):
    """Выбрать лучший config по PnL на train выборке (year <= train_end_year)."""
    train = [(yr, t, r) for yr, t, r in per_setup if yr <= train_end_year]
    pnl_by_cfg = defaultdict(float)
    bad_by_cfg = defaultdict(lambda: defaultdict(float))
    n_by_cfg = defaultdict(int)
    for yr, t, r in train:
        for cfg, R in r.items():
            pnl_by_cfg[cfg] += R
            bad_by_cfg[cfg][yr] += R
            n_by_cfg[cfg] += 1
    if not pnl_by_cfg: return None, 0.0, 0
    best = max(pnl_by_cfg, key=lambda k: pnl_by_cfg[k])
    return best, pnl_by_cfg[best], n_by_cfg[best]


def test_with_config(per_setup, cfg, test_year):
    test = [(yr, t, r) for yr, t, r in per_setup if yr == test_year and cfg in r]
    pnl = sum(r[cfg] for yr, t, r in test)
    n = len(test)
    W = sum(1 for yr, t, r in test if r[cfg] > 0)
    return pnl, n, (W/n*100 if n else 0)


def main():
    print("etap_138: Walk-forward validation Variant B (BTC+ETH)")
    print(f"Grid pruned: cap×th×cf = {len(CAPS)}×{len(THS)}×{len(CFS)} = {len(CAPS)*len(THS)*len(CFS)} configs")
    print()
    print("Computing all setup results...")
    per_sym_results = {}
    for sym, start in SYMBOLS:
        per_sym_results[sym] = simulate_setups_all_configs(sym, start)
        print(f"  {sym}: {len(per_sym_results[sym])} closed setups")
    print()

    train_ends = [2022, 2023, 2024, 2025]
    test_years = [2023, 2024, 2025, 2026]
    print("Walk-forward windows:")
    print("  " + "="*100)
    print(f"  {'Train end':>10} {'Test year':>10}  {'Symbol':>8}  {'Best cfg':>20}  "
          f"{'Train PnL':>10}  {'Test PnL':>9}  {'Test WR':>8}  {'Test n':>7}")
    print("  " + "-"*100)
    sym_test_totals = defaultdict(float)
    sym_test_n = defaultdict(int)
    for train_end, test_yr in zip(train_ends, test_years):
        for sym in per_sym_results:
            per_setup = per_sym_results[sym]
            best, train_pnl, train_n = pick_best_in_train(per_setup, train_end)
            if best is None:
                print(f"  {train_end:>10d} {test_yr:>10d}  {sym:>8}  {'no data':>20}  -  -  -  -")
                continue
            test_pnl, test_n, test_wr = test_with_config(per_setup, best, test_yr)
            cap, th, cf = best
            cfg_str = f"cap={cap} th={th:+.2f} cf={cf}"
            print(f"  {train_end:>10d} {test_yr:>10d}  {sym:>8}  {cfg_str:>20}  "
                  f"{train_pnl:>+8.1f}R  {test_pnl:>+7.1f}R  {test_wr:>6.1f}%  {test_n:>5d}")
            sym_test_totals[sym] += test_pnl
            sym_test_n[sym] += test_n
    print("  " + "="*100)
    total_pnl = sum(sym_test_totals.values()); total_n = sum(sym_test_n.values())
    for sym in sym_test_totals:
        print(f"  {sym}: walk-forward total PnL={sym_test_totals[sym]:+.1f}R / n={sym_test_n[sym]}")
    print(f"  Combined walk-forward: PnL={total_pnl:+.1f}R / n={total_n} / R/tr={total_pnl/total_n:+.2f}")
    print()
    print(f"  Compare in-sample Variant B (etap_137): +80.3R / 146 closed (2020-2026)")
    print(f"  Walk-forward covers 2023-2026 only — partial period")


if __name__ == "__main__":
    main()
