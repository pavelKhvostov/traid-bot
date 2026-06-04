"""etap_156: Backtest сравнение 1.1.1 floating v1 vs v2 (с ob_vc 9 канонов).

v1: strategies/strategy_1_1_1_floating.py — SWEPT filter
v2: strategies/strategy_1_1_1_floating_v2.py — ob_vc 9 канонов вместо SWEPT

Прогон на BTC 6.3y (2020-01 → 2026-05). Одни и те же per-symbol floating
configs (R_cap=4.5, th=-0.25, cf=2 для BTC).
"""
from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists(): _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path: _sys.path.insert(0, str(_ROOT))

import time
from collections import defaultdict

import pandas as pd

from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_1_floating import run_symbol_backtest, aggregate_stats
from strategies.strategy_1_1_1_floating_v2 import run_symbol_backtest_v2


SYMBOL = "BTCUSDT"
START_DATE = "2020-01-01"


def main():
    print(f"etap_156: V1 vs V2 backtest на {SYMBOL}")
    print()
    print("Loading data...")
    df_1d = load_df(SYMBOL, "1d")
    df_1h = load_df(SYMBOL, "1h")
    df_1m = load_df(SYMBOL, "1m")
    df_12h = compose_from_base(df_1h, "12h")
    df_4h = compose_from_base(df_1h, "4h")
    df_6h = compose_from_base(df_1h, "6h")
    df_2h = compose_from_base(df_1h, "2h")
    df_15m = compose_from_base(df_1m, "15m")
    df_20m = compose_from_base(df_1m, "20m")
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
    print(f"Data range: {df_1d.index[0]} -> {df_1d.index[-1]}")
    print(f"  1d bars: {len(df_1d)}, 1h bars: {len(df_1h)}, 1m bars: {len(df_1m)}")
    print()

    # ============================================================
    # V1 backtest
    # ============================================================
    print("=" * 70)
    print("V1: strategy_1_1_1_floating.py (SWEPT filter)")
    print("=" * 70)
    t0 = time.time()
    trades_v1 = run_symbol_backtest(SYMBOL, df_1d, df_12h, df_4h, df_6h,
                                      df_1h, df_2h, df_15m, df_20m, df_1m)
    t1 = time.time()
    stats_v1 = aggregate_stats(trades_v1)
    print(f"  Время: {t1 - t0:.1f}s")
    print(f"  Total trades collected: {len(trades_v1)}")
    if stats_v1.get("n", 0) > 0:
        print(f"  n closed: {stats_v1['n']}, W={stats_v1['W']}, L={stats_v1['L']}")
        print(f"  WR: {stats_v1['WR']}%")
        print(f"  Total R: {stats_v1['total_R']}")
        print(f"  R/trade: {stats_v1['R_per_trade']}")
        print(f"  Bad years: {stats_v1['bad_years']}/{stats_v1['total_years']}")
        print(f"  Exit reasons:")
        for r, d in sorted(stats_v1["by_exit_reason"].items()):
            print(f"    {r:<15} n={d['n']:>3d}, total R={d['R']:>+6.1f}")
    print()

    # ============================================================
    # V2 backtest
    # ============================================================
    print("=" * 70)
    print("V2: strategy_1_1_1_floating_v2.py (ob_vc 9 канонов)")
    print("=" * 70)
    t0 = time.time()
    trades_v2 = run_symbol_backtest_v2(SYMBOL, df_1d, df_12h, df_4h, df_6h,
                                         df_1h, df_2h, df_15m, df_20m, df_1m)
    t1 = time.time()
    stats_v2 = aggregate_stats(trades_v2)
    print(f"  Время: {t1 - t0:.1f}s")
    print(f"  Total trades collected: {len(trades_v2)}")
    if stats_v2.get("n", 0) > 0:
        print(f"  n closed: {stats_v2['n']}, W={stats_v2['W']}, L={stats_v2['L']}")
        print(f"  WR: {stats_v2['WR']}%")
        print(f"  Total R: {stats_v2['total_R']}")
        print(f"  R/trade: {stats_v2['R_per_trade']}")
        print(f"  Bad years: {stats_v2['bad_years']}/{stats_v2['total_years']}")
        print(f"  Exit reasons:")
        for r, d in sorted(stats_v2["by_exit_reason"].items()):
            print(f"    {r:<15} n={d['n']:>3d}, total R={d['R']:>+6.1f}")
    print()

    # ============================================================
    # Side-by-side comparison
    # ============================================================
    print("=" * 70)
    print("СРАВНЕНИЕ V1 vs V2")
    print("=" * 70)
    if stats_v1.get("n", 0) > 0 and stats_v2.get("n", 0) > 0:
        print(f"  {'Metric':<25}  {'V1 (SWEPT)':>14}  {'V2 (ob_vc)':>14}  {'Δ':>10}")
        print(f"  {'-' * 25}  {'-' * 14}  {'-' * 14}  {'-' * 10}")
        print(f"  {'n closed':<25}  {stats_v1['n']:>14d}  {stats_v2['n']:>14d}  {stats_v2['n'] - stats_v1['n']:>+10d}")
        print(f"  {'WR (%)':<25}  {stats_v1['WR']:>14.1f}  {stats_v2['WR']:>14.1f}  {stats_v2['WR'] - stats_v1['WR']:>+10.1f}")
        print(f"  {'Total R':<25}  {stats_v1['total_R']:>14.1f}  {stats_v2['total_R']:>14.1f}  {stats_v2['total_R'] - stats_v1['total_R']:>+10.1f}")
        print(f"  {'R/trade':<25}  {stats_v1['R_per_trade']:>14.3f}  {stats_v2['R_per_trade']:>14.3f}  {stats_v2['R_per_trade'] - stats_v1['R_per_trade']:>+10.3f}")
        print(f"  {'Bad years':<25}  {stats_v1['bad_years']:>12d}/{stats_v1['total_years']:<1d}  {stats_v2['bad_years']:>12d}/{stats_v2['total_years']:<1d}")
    print()

    # ============================================================
    # Per-year breakdown
    # ============================================================
    print("Per-year R breakdown:")
    print(f"  {'Year':<6}  {'V1 R':>10}  {'V2 R':>10}  {'V1 n':>6}  {'V2 n':>6}")
    print(f"  {'-' * 6}  {'-' * 10}  {'-' * 10}  {'-' * 6}  {'-' * 6}")
    years = sorted(set(list(stats_v1.get("by_year", {}).keys()) + list(stats_v2.get("by_year", {}).keys())))
    n_per_year_v1 = defaultdict(int); n_per_year_v2 = defaultdict(int)
    for t in trades_v1:
        if t["outcome"] in ("win", "loss", "flat"):
            n_per_year_v1[pd.Timestamp(t["signal_time"]).year] += 1
    for t in trades_v2:
        if t["outcome"] in ("win", "loss", "flat"):
            n_per_year_v2[pd.Timestamp(t["signal_time"]).year] += 1
    for y in years:
        r_v1 = stats_v1.get("by_year", {}).get(y, 0)
        r_v2 = stats_v2.get("by_year", {}).get(y, 0)
        print(f"  {y:<6d}  {r_v1:>+9.1f}R  {r_v2:>+9.1f}R  {n_per_year_v1[y]:>6d}  {n_per_year_v2[y]:>6d}")

    # Overlap analysis
    print()
    print("Overlap analysis:")
    keys_v1 = set((t["signal_time"].floor("h"), t["direction"])
                   for t in trades_v1 if t["outcome"] in ("win", "loss", "flat"))
    keys_v2 = set((t["signal_time"].floor("h"), t["direction"])
                   for t in trades_v2 if t["outcome"] in ("win", "loss", "flat"))
    overlap = keys_v1 & keys_v2
    only_v1 = keys_v1 - keys_v2
    only_v2 = keys_v2 - keys_v1
    print(f"  V1 ∩ V2 (overlap):   {len(overlap)} trades")
    print(f"  V1 only:             {len(only_v1)} trades")
    print(f"  V2 only:             {len(only_v2)} trades")


if __name__ == "__main__":
    main()
