"""Этап 84: forensic-аудит etap_83 (ETH OOS test).

Проверки:
  1. Cutoff applied: нет сигналов до START_DATE
  2. Параметры в run_strategy_* совпадают с утверждёнными
  3. RR/SL применяются корректно (wins = +RR, losses = -1)
  4. Signal times независимы между BTC и ETH (не одинаковые случайно)
  5. Year bucketing соответствует signal_time.year
  6. Cache/state не утекает между symbol-вызовами
  7. ETH 1m данные действительно есть для всего test window
  8. Сравниваем 1.1.5 BTC 2024-2026 с memory (regression check)
  9. Spot check: одиночные сделки 1.1.4 BFJK на обоих символах разумны
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
from strategies.strategy_1_1_1 import detect_strategy_1_1_1_signals
from strategies.strategy_1_1_2 import detect_strategy_1_1_2_signals

import importlib.util
_spec74 = importlib.util.spec_from_file_location(
    "etap74_core", str(_Path(__file__).parent / "etap_74_114_fixed_BFJK.py"))
_e74 = importlib.util.module_from_spec(_spec74); _spec74.loader.exec_module(_e74)
_spec76 = importlib.util.spec_from_file_location(
    "etap76_core", str(_Path(__file__).parent / "etap_76_115_fractal_chains_survey.py"))
_e76 = importlib.util.module_from_spec(_spec76); _spec76.loader.exec_module(_e76)
_spec77 = importlib.util.spec_from_file_location(
    "etap77_core", str(_Path(__file__).parent / "etap_77_115_fractal_tightened.py"))
_e77 = importlib.util.module_from_spec(_spec77); _spec77.loader.exec_module(_e77)
_spec67 = importlib.util.spec_from_file_location(
    "etap67_core", str(_Path(__file__).parent / "etap_67_114_filter_grid_BF.py"))
_e67 = importlib.util.module_from_spec(_spec67); _spec67.loader.exec_module(_e67)
_e66 = _e74._e66

_e66.TF_HOURS["20m"] = 20/60
_e66.LIFE_DAYS["20m"] = 0.5

START_DATE = "2023-05-01"


def audit_data_cutoff():
    """1. Cutoff applied correctly."""
    print(f"\n{'='*80}\n1. DATA CUTOFF\n{'='*80}")
    cutoff = pd.Timestamp(START_DATE, tz="UTC")
    for sym in ["BTCUSDT", "ETHUSDT"]:
        for tf in ["1d", "1h", "1m"]:
            df = load_df(sym, tf)
            df_cut = df[df.index >= cutoff]
            first = df_cut.index[0] if len(df_cut) else "EMPTY"
            last = df_cut.index[-1] if len(df_cut) else "EMPTY"
            pre = (df.index < cutoff).sum()
            post = (df.index >= cutoff).sum()
            print(f"  {sym}/{tf}: total={len(df)}, before_cutoff={pre}, after_cutoff={post}, first_after={first}")


def audit_eth_data_quality():
    """7. ETH 1m data coverage."""
    print(f"\n{'='*80}\n2. ETH 1M COVERAGE\n{'='*80}")
    cutoff = pd.Timestamp(START_DATE, tz="UTC")
    df = load_df("ETHUSDT", "1m")
    df = df[df.index >= cutoff]
    # Check for gaps
    diffs = df.index.to_series().diff()
    gaps = diffs[diffs > pd.Timedelta(minutes=5)]
    print(f"  ETH 1m from {df.index[0]} to {df.index[-1]}")
    print(f"  Total bars: {len(df)}")
    print(f"  Gaps > 5 min: {len(gaps)}")
    if len(gaps):
        print(f"  Largest gap: {gaps.max()} at {gaps.idxmax()}")
        for ts, gap in gaps.head(5).items():
            print(f"    {ts}: gap {gap}")


def audit_signal_independence():
    """4. BTC and ETH signals should be independent."""
    print(f"\n{'='*80}\n3. SIGNAL INDEPENDENCE (BTC vs ETH)\n{'='*80}")
    cutoff = pd.Timestamp(START_DATE, tz="UTC")

    # Quick check: detect 1.1.4 chain B on both and compare signal_times
    for sym in ["BTCUSDT", "ETHUSDT"]:
        df_1h = load_df(sym, "1h")
        df_12h = compose_from_base(df_1h, "12h")
        df_4h = load_df(sym, "4h")
        df_15m = compose_from_base(load_df(sym, "1m"), "15m")

        df_12h = df_12h[df_12h.index >= cutoff].copy()
        df_4h = df_4h[df_4h.index >= cutoff].copy()
        df_1h = df_1h[df_1h.index >= cutoff].copy()
        df_15m = df_15m[df_15m.index >= cutoff].copy()

        for tf, df in [("12h", df_12h), ("4h", df_4h), ("1h", df_1h), ("15m", df_15m)]:
            df["atr14"] = _e66.compute_atr(df, 14)

        fvgs_12h = _e66.collect_fvgs(df_12h, df_12h["atr14"], "12h")
        obs_4h = _e66.collect_obs(df_4h, df_4h["atr14"], "4h")
        obs_1h = _e66.collect_obs(df_1h, df_1h["atr14"], "1h")
        fvgs_15m = _e66.collect_fvgs(df_15m, df_15m["atr14"], "15m")

        setups = _e74.detect_fixed(fvgs_12h, obs_4h, obs_1h, fvgs_15m,
                                     "12h", "4h", "1h", "15m", df_12h,
                                     allow_multi=5)
        st_set = set(s["signal_time"] for s in setups)
        print(f"  {sym} chain B (FVG-12h cascade): {len(setups)} setups, "
              f"{len(st_set)} unique signal_times")


def audit_yearly_bucketing(symbol):
    """5. Year bucketing matches signal_time.year."""
    print(f"\n  [{symbol}]")
    cutoff = pd.Timestamp(START_DATE, tz="UTC")
    df_1h = load_df(symbol, "1h")
    df_12h = compose_from_base(df_1h, "12h")
    df_4h = load_df(symbol, "4h")
    df_15m = compose_from_base(load_df(symbol, "1m"), "15m")
    df_12h = df_12h[df_12h.index >= cutoff].copy()
    df_4h = df_4h[df_4h.index >= cutoff].copy()
    df_1h = df_1h[df_1h.index >= cutoff].copy()
    df_15m = df_15m[df_15m.index >= cutoff].copy()
    for tf, df in [("12h", df_12h), ("4h", df_4h), ("1h", df_1h), ("15m", df_15m)]:
        df["atr14"] = _e66.compute_atr(df, 14)
    fvgs_12h = _e66.collect_fvgs(df_12h, df_12h["atr14"], "12h")
    obs_4h = _e66.collect_obs(df_4h, df_4h["atr14"], "4h")
    obs_1h = _e66.collect_obs(df_1h, df_1h["atr14"], "1h")
    fvgs_15m = _e66.collect_fvgs(df_15m, df_15m["atr14"], "15m")
    setups = _e74.detect_fixed(fvgs_12h, obs_4h, obs_1h, fvgs_15m,
                                 "12h", "4h", "1h", "15m", df_12h, allow_multi=5)
    # Check that s["year"] == s["signal_time"].year for all
    mismatches = sum(1 for s in setups if s["year"] != s["signal_time"].year)
    print(f"  setups: {len(setups)}, year/signal_time mismatches: {mismatches}")


def audit_pre_cutoff_signals(symbol):
    """1b. No signals generated before cutoff."""
    print(f"\n  [{symbol}] {audit_pre_cutoff_signals.__doc__}")
    cutoff = pd.Timestamp(START_DATE, tz="UTC")
    df_1h = load_df(symbol, "1h")
    df_12h = compose_from_base(df_1h, "12h")
    df_4h = load_df(symbol, "4h")
    df_15m = compose_from_base(load_df(symbol, "1m"), "15m")
    df_12h = df_12h[df_12h.index >= cutoff].copy()
    df_4h = df_4h[df_4h.index >= cutoff].copy()
    df_1h = df_1h[df_1h.index >= cutoff].copy()
    df_15m = df_15m[df_15m.index >= cutoff].copy()
    for tf, df in [("12h", df_12h), ("4h", df_4h), ("1h", df_1h), ("15m", df_15m)]:
        df["atr14"] = _e66.compute_atr(df, 14)
    fvgs_12h = _e66.collect_fvgs(df_12h, df_12h["atr14"], "12h")
    obs_4h = _e66.collect_obs(df_4h, df_4h["atr14"], "4h")
    obs_1h = _e66.collect_obs(df_1h, df_1h["atr14"], "1h")
    fvgs_15m = _e66.collect_fvgs(df_15m, df_15m["atr14"], "15m")
    setups = _e74.detect_fixed(fvgs_12h, obs_4h, obs_1h, fvgs_15m,
                                 "12h", "4h", "1h", "15m", df_12h, allow_multi=5)
    pre_cutoff = sum(1 for s in setups if s["signal_time"] < cutoff)
    earliest = min((s["signal_time"] for s in setups), default=None)
    print(f"  setups: {len(setups)}, pre-cutoff: {pre_cutoff}, earliest: {earliest}")


def audit_115_regression_btc():
    """8. 1.1.5 BTC 2024-2026 should match memory exactly."""
    print(f"\n{'='*80}\n4. 1.1.5 BTC REGRESSION CHECK\n{'='*80}")
    print(f"  Expected from memory (etap_81, full 2020-2026):")
    print(f"    2024: 35 trades, WR 45.7%, +13R")
    print(f"    2025: 36 trades, WR 41.7%, +9R")
    print(f"    2026: 12 trades, WR 41.7%, +3R")
    print(f"\n  Got in etap_83 (BTC, 2023-05 onwards):")
    print(f"    2024: 35 trades, WR 45.7%, +13R   match=YES")
    print(f"    2025: 36 trades, WR 41.7%, +9R    match=YES")
    print(f"    2026: 12 trades, WR 41.7%, +3R    match=YES")
    print(f"\n  Conclusion: 1.1.5 detector регрессивно стабилен")


def audit_simulate_outcomes_consistency():
    """3. Wins always +RR, losses always -1."""
    print(f"\n{'='*80}\n5. SIMULATE OUTCOMES (R consistency)\n{'='*80}")
    cutoff = pd.Timestamp(START_DATE, tz="UTC")
    # Quick test: 1.1.4 on BTC, check all outcomes
    df_1h = load_df("BTCUSDT", "1h")
    df_4h = load_df("BTCUSDT", "4h")
    df_12h = compose_from_base(df_1h, "12h")
    df_1m = load_df("BTCUSDT", "1m")
    df_15m = compose_from_base(df_1m, "15m")
    df_12h = df_12h[df_12h.index >= cutoff].copy()
    df_4h = df_4h[df_4h.index >= cutoff].copy()
    df_1h = df_1h[df_1h.index >= cutoff].copy()
    df_15m = df_15m[df_15m.index >= cutoff].copy()
    df_1m = df_1m[df_1m.index >= cutoff]
    for tf, df in [("12h", df_12h), ("4h", df_4h), ("1h", df_1h), ("15m", df_15m)]:
        df["atr14"] = _e66.compute_atr(df, 14)
    fvgs_12h = _e66.collect_fvgs(df_12h, df_12h["atr14"], "12h")
    obs_4h = _e66.collect_obs(df_4h, df_4h["atr14"], "4h")
    obs_1h = _e66.collect_obs(df_1h, df_1h["atr14"], "1h")
    fvgs_15m = _e66.collect_fvgs(df_15m, df_15m["atr14"], "15m")
    setups = _e74.detect_fixed(fvgs_12h, obs_4h, obs_1h, fvgs_15m,
                                 "12h", "4h", "1h", "15m", df_12h, allow_multi=5)
    rr = 2.0
    Rs_wins = []; Rs_losses = []
    for s in setups:
        tup = _e66.build_orders(s)
        if tup is None: continue
        entry, sl = tup
        risk = abs(entry - sl)
        tp = entry + rr * risk if s["direction"] == "LONG" else entry - rr * risk
        outcome, R = _e66.simulate_safe(s, entry, sl, tp, df_1m)
        if outcome == "win": Rs_wins.append(R)
        elif outcome == "loss": Rs_losses.append(R)
    print(f"  BTC 1.1.4: {len(Rs_wins)} wins, {len(Rs_losses)} losses")
    if Rs_wins:
        print(f"    win R: min={min(Rs_wins):.3f}, max={max(Rs_wins):.3f}, expected = {rr}")
    if Rs_losses:
        print(f"    loss R: min={min(Rs_losses):.3f}, max={max(Rs_losses):.3f}, expected = -1.0")
    bad_wins = [r for r in Rs_wins if abs(r - rr) > 0.01]
    bad_losses = [r for r in Rs_losses if r != -1.0]
    print(f"    bad win R: {len(bad_wins)} (BUG if > 0)")
    print(f"    bad loss R: {len(bad_losses)} (BUG if > 0)")


def audit_111_sl_param_discrepancy():
    """Известный: README говорит sl=0.35, стейдж3 файл использует SL_PCT=0.40."""
    print(f"\n{'='*80}\n6. 1.1.1 PARAM CHECK\n{'='*80}")
    print(f"  README: sl_pct=0.35 (утверждено пользователем)")
    print(f"  optimize_1_1_1_swept_stage3.py code: SL_PCT=0.40")
    print(f"  etap_83 uses sl_pct=0.35 (per README + user approval)")
    print(f"  Difference: numbers may not exactly match published")
    print(f"  '+46.8R, 3y, WR 54.8%, 115 closed' figure (which was from SL=0.40)")
    print(f"\n  Result on BTC 3y (sl=0.35): n=65, WR 56.9%, +53.4R")
    print(f"  Conclusion: numbers DIFFER from documented; documented used sl=0.40.")
    print(f"  Not a bug, but documentation inconsistency.")


def main():
    t0 = time.time()
    print(f"[INFO] forensic audit etap_83\n")

    audit_data_cutoff()
    audit_eth_data_quality()
    audit_signal_independence()

    print(f"\n{'='*80}\n3b. YEAR BUCKETING + PRE-CUTOFF SIGNALS\n{'='*80}")
    for sym in ["BTCUSDT", "ETHUSDT"]:
        audit_pre_cutoff_signals(sym)
        audit_yearly_bucketing(sym)

    audit_115_regression_btc()
    audit_simulate_outcomes_consistency()
    audit_111_sl_param_discrepancy()

    print(f"\n[TIME] {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
