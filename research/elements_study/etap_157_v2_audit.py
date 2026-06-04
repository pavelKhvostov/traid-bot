"""etap_157: Аудит V2 backtest +1451R — проверка на 2 подозрения.

Подозрение #1 — LOOKAHEAD в signal_time:
  В V2 я использовал signal_time = ob_vc.fvg.c2_time.
  Но валидация ob_vc (каноны #5/#8) использует first_Williams_fractal.confirmation_time,
  который наступает ПОСЛЕ FVG.c2_time на 2+ HTF-бара.

  То есть в момент signal_time мы НЕ знаем будет ли фрактал → используем
  будущую инфу для отсева. КЛАССИЧЕСКИЙ LOOKAHEAD.

  Правильно: signal_time = max(fvg.c2_time, fractal_confirmation_time)
  → entry только ПОСЛЕ того как фрактал confirmed.

Подозрение #2 — MULTI-SHOT inflation:
  detect_signals_111_v2 итерирует HTF×{many OBs}×LTF — каждый L1 OB
  порождает 50+ ob_vc сигналов через много HTF-OB кандидатов.
  Это видно: 6013 raw signals → 1721 closed.
  Реальный edge per UNIQUE setup может быть в 2-5× меньше.

Проверки:
  A. Сколько unique (signal_time floor 1h, direction) среди 1721 closed?
  B. Если signal_time = fractal_confirmation_time, сколько trades выживет?
  C. Сравнить per-trade R на unique-only выборке.

Бэктест уже сохранён в /tmp/etap_156_out.txt — переиспользуем trades.
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
from strategies.strategy_1_1_1_floating_v2 import run_symbol_backtest_v2

SYMBOL = "BTCUSDT"
START_DATE = "2020-01-01"


def main():
    print("etap_157: V2 backtest audit — lookahead + multi-shot inflation")
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
    print(f"Data loaded: {df_1d.index[0]} -> {df_1d.index[-1]}")

    # Run v2 backtest
    t0 = time.time()
    trades = run_symbol_backtest_v2(SYMBOL, df_1d, df_12h, df_4h, df_6h,
                                      df_1h, df_2h, df_15m, df_20m, df_1m)
    print(f"V2 backtest: {len(trades)} raw trades, time {time.time()-t0:.1f}s")
    closed = [t for t in trades if t["outcome"] in ("win", "loss", "flat")]
    print(f"  closed: {len(closed)}")
    print()

    # ===========================================
    # CHECK A: Unique vs multi-shot
    # ===========================================
    print("=" * 70)
    print("CHECK A: Unique deduped vs multi-shot raw")
    print("=" * 70)

    keys_seen = {}
    unique_trades = []
    for t in closed:
        key = (t["signal_time"].floor("h"), t["direction"])
        if key in keys_seen:
            continue
        keys_seen[key] = t
        unique_trades.append(t)

    raw_pnl = sum(t["R"] for t in closed)
    unique_pnl = sum(t["R"] for t in unique_trades)
    raw_wr = sum(1 for t in closed if t["R"] > 0) / len(closed) * 100
    unique_wr = sum(1 for t in unique_trades if t["R"] > 0) / len(unique_trades) * 100

    print(f"  Raw multi-shot:     n={len(closed):>4d}  PnL={raw_pnl:>+8.1f}R  WR={raw_wr:.1f}%  R/tr={raw_pnl/len(closed):+.3f}")
    print(f"  Unique (1h, dir):   n={len(unique_trades):>4d}  PnL={unique_pnl:>+8.1f}R  WR={unique_wr:.1f}%  R/tr={unique_pnl/len(unique_trades):+.3f}")
    print(f"  Inflation factor:   {len(closed)/len(unique_trades):.2f}× by count, {raw_pnl/unique_pnl:.2f}× by PnL")
    print()

    # ===========================================
    # CHECK B: Lookahead — signal_time vs fractal_confirmation
    # ===========================================
    print("=" * 70)
    print("CHECK B: Lookahead — fractal confirmation time vs signal_time")
    print("=" * 70)
    lookahead_examples = []
    fixed_lookahead_trades = []
    for t in unique_trades:
        signal_t = pd.Timestamp(t["signal_time"])
        fractal_t = pd.Timestamp(t["ob_vc_fractal_confirmation"])
        gap = (fractal_t - signal_t).total_seconds() / 3600  # часы
        if fractal_t > signal_t:
            lookahead_examples.append((signal_t, fractal_t, gap))
            # Реальный signal_time должен быть после fractal_confirmation_time
            fixed_t = dict(t)
            fixed_t["original_signal_time"] = signal_t
            fixed_t["fixed_signal_time"] = fractal_t
            fixed_t["lookahead_hours"] = gap
            fixed_lookahead_trades.append(fixed_t)

    print(f"  Trades с lookahead (fractal_confirm > signal): {len(lookahead_examples)} / {len(unique_trades)}")
    if lookahead_examples:
        gaps = [g for _, _, g in lookahead_examples]
        print(f"  Среднее опережение fractal: {sum(gaps)/len(gaps):.1f}ч")
        print(f"  Max lookahead: {max(gaps):.1f}ч")
        print(f"  Примеры:")
        for sig_t, frac_t, gap in lookahead_examples[:5]:
            print(f"    signal={sig_t}  fractal_confirm={frac_t}  Δ={gap:.1f}ч")
    print()

    # ===========================================
    # CHECK C: SL/cap precedence (intra-bar)
    # ===========================================
    print("=" * 70)
    print("CHECK C: Exit reasons breakdown")
    print("=" * 70)
    by_reason = defaultdict(lambda: {"n": 0, "R": 0.0})
    for t in unique_trades:
        by_reason[t["exit_reason"]]["n"] += 1
        by_reason[t["exit_reason"]]["R"] += t["R"]
    for r, d in sorted(by_reason.items()):
        avg_R = d["R"] / d["n"] if d["n"] else 0
        print(f"  {r:<15} n={d['n']:>3d}  PnL={d['R']:>+8.1f}R  avg={avg_R:>+.2f}R")
    cap_share = by_reason.get("cap_hit", {"R": 0})["R"] / unique_pnl * 100 if unique_pnl else 0
    print(f"\n  cap_hit доля в total PnL: {cap_share:.1f}%")
    print()

    # ===========================================
    # CHECK D: Per-year analysis on UNIQUE
    # ===========================================
    print("=" * 70)
    print("CHECK D: Per-year на UNIQUE trades")
    print("=" * 70)
    by_year = defaultdict(lambda: {"n": 0, "W": 0, "R": 0.0})
    for t in unique_trades:
        y = pd.Timestamp(t["signal_time"]).year
        by_year[y]["n"] += 1
        if t["R"] > 0: by_year[y]["W"] += 1
        by_year[y]["R"] += t["R"]
    for y in sorted(by_year):
        d = by_year[y]
        wr = d["W"]/d["n"]*100 if d["n"] else 0
        mark = " ⚠ BAD" if d["R"] < 0 else ""
        print(f"  {y}: n={d['n']:>3d} WR={wr:>4.1f}% R={d['R']:>+7.1f}R{mark}")
    bad_yrs = sum(1 for y in by_year if by_year[y]["R"] < 0)
    print(f"  Bad years: {bad_yrs}/{len(by_year)}")
    print()

    # Final verdict
    print("=" * 70)
    print("VERDICT")
    print("=" * 70)
    print(f"  Raw V2 (заявлено в etap_156):    +1451R / 1721 trades / R/tr +0.84")
    print(f"  After dedup (unique):            {unique_pnl:>+5.1f}R / {len(unique_trades):>4d} trades / R/tr {unique_pnl/len(unique_trades):+.2f}")
    print(f"  Multi-shot inflation:            {raw_pnl/unique_pnl:.2f}×")
    print(f"  Lookahead trades:                {len(lookahead_examples)} ({len(lookahead_examples)/len(unique_trades)*100:.0f}% of unique)")


if __name__ == "__main__":
    main()
