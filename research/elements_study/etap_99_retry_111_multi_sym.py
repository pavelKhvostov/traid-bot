"""etap_99: retry-after-SL для 1.1.1 на BTC/ETH/SOL.

Цель: ответ на вопрос пользователя "а за 6 лет? по BTC, ETH, SOL".
Замечание: 1m данные для ETH и SOL начинаются 2023-04-26, физически 6y
есть только для BTC. Для ETH/SOL прогоняем max доступный window.

Использует логику из etap_98 (detect_multi_signals, check_swept,
simulate_one, run_experiment).
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
import importlib.util as _ilu

_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    if _ROOT.parent == _ROOT:
        raise RuntimeError("repo root not found")
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df

# импорт логики etap_98
_E98_PATH = Path(__file__).parent / "etap_98_retry_after_sl_111.py"
_spec = _ilu.spec_from_file_location("etap98_core", _E98_PATH)
_e98 = _ilu.module_from_spec(_spec)
_sys.modules["etap98_core"] = _e98
_spec.loader.exec_module(_e98)

detect_multi_signals = _e98.detect_multi_signals
run_experiment = _e98.run_experiment
ENTRY_PCT = _e98.ENTRY_PCT
SL_PCT = _e98.SL_PCT
RR = _e98.RR

DAYS_BACK_TARGET = 2190  # 6 лет
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


def summarize_compact(trades, rr=RR):
    closed = [t for t in trades if t["outcome"] in ("win", "loss")]
    W = sum(1 for t in closed if t["outcome"] == "win")
    L = sum(1 for t in closed if t["outcome"] == "loss")
    n = W + L
    wr = (W / n * 100) if n else 0.0
    pnl = W * rr - L * 1.0
    r_per = pnl / n if n else 0.0
    yearly = defaultdict(lambda: [0, 0, 0.0])
    for t in closed:
        y = pd.Timestamp(t["signal_time"]).year
        if t["outcome"] == "win":
            yearly[y][0] += 1; yearly[y][2] += rr
        else:
            yearly[y][1] += 1; yearly[y][2] -= 1.0
    bad = sum(1 for y in yearly if yearly[y][2] < 0)
    return {
        "n": n, "W": W, "L": L, "wr": wr, "pnl": pnl, "r_per": r_per,
        "bad": bad, "yearly": dict(yearly),
    }


def run_symbol(symbol: str) -> dict:
    print(f"\n{'#'*72}\n#  {symbol}\n{'#'*72}")

    df_1d = load_df(symbol, "1d")
    df_4h = load_df(symbol, "4h")
    df_1h = load_df(symbol, "1h")
    df_15m = load_df(symbol, "15m")
    df_1m = load_df(symbol, "1m")
    if any(df.empty for df in (df_1d, df_4h, df_1h, df_15m, df_1m)):
        print(f"  [SKIP] {symbol}: пустые данные на одном из ТФ")
        return None
    df_12h = compose_from_base(df_1h, "12h")
    df_6h = compose_from_base(df_1h, "6h")
    df_2h = compose_from_base(df_1h, "2h")
    df_20m = compose_from_base(df_1m, "20m")

    # Cutoff: max(6y_ago, 1m_data_start), 1m данные нужны для simulate_one.
    today = pd.Timestamp.now(tz="UTC").normalize()
    six_y_ago = today - pd.Timedelta(days=DAYS_BACK_TARGET)
    data_start = df_1m.index[0]
    cutoff = max(six_y_ago, data_start)
    actual_days = (today - cutoff).days
    print(f"  data: 1d={len(df_1d)} 1h={len(df_1h)} 15m={len(df_15m)} 1m={len(df_1m)}")
    print(f"  6y target cutoff = {six_y_ago.date()},  1m starts = {data_start.date()}")
    print(f"  effective cutoff = {cutoff.date()}  ({actual_days} days = {actual_days/365:.1f} years)")

    df_1d_f = df_1d[df_1d.index >= cutoff]
    df_12h_f = df_12h[df_12h.index >= cutoff]

    print(f"  detect multi-shot...")
    groups = detect_multi_signals(df_1d_f, df_12h_f, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m)
    total_pairs = sum(len(g) for g in groups.values())
    multi_zones = sum(1 for g in groups.values() if len(g) > 1)
    print(f"  zones={len(groups)}  total pairs={total_pairs}  multi-shot zones={multi_zones}")

    print(f"  baseline...")
    baseline = run_experiment(groups, df_1m, df_1h, df_2h, mode="baseline")
    print(f"  retry...")
    retry = run_experiment(groups, df_1m, df_1h, df_2h, mode="retry")

    b = summarize_compact(baseline)
    r = summarize_compact(retry)

    # retry-only (idx > 0)
    retry_only_closed = [
        t for t in retry
        if t["trade_idx_in_zone"] > 0 and t["outcome"] in ("win", "loss")
    ]
    rW = sum(1 for t in retry_only_closed if t["outcome"] == "win")
    rL = sum(1 for t in retry_only_closed if t["outcome"] == "loss")
    rn = rW + rL
    rwr = (rW / rn * 100) if rn else 0.0
    rpnl = rW * RR - rL * 1.0

    bwl = f"{b['W']}/{b['L']}"
    rwl = f"{r['W']}/{r['L']}"
    dwl = f"+{r['W']-b['W']}/{r['L']-b['L']:+d}"
    print(f"\n  {'metric':<14} {'baseline':>14} {'retry':>14}  {'delta':>10}")
    print(f"  {'-'*14} {'-'*14} {'-'*14}  {'-'*10}")
    print(f"  {'closed':<14} {b['n']:>14d} {r['n']:>14d}  {r['n']-b['n']:>+10d}")
    print(f"  {'W/L':<14} {bwl:>14} {rwl:>14}  {dwl:>10}")
    print(f"  {'WR %':<14} {b['wr']:>14.1f} {r['wr']:>14.1f}  {r['wr']-b['wr']:>+10.1f}")
    print(f"  {'PnL R':<14} {b['pnl']:>+14.1f} {r['pnl']:>+14.1f}  {r['pnl']-b['pnl']:>+10.1f}")
    print(f"  {'R/trade':<14} {b['r_per']:>+14.3f} {r['r_per']:>+14.3f}  {r['r_per']-b['r_per']:>+10.3f}")
    print(f"  {'bad years':<14} {b['bad']:>14d} {r['bad']:>14d}  {r['bad']-b['bad']:>+10d}")

    print(f"\n  retry-only trades (idx > 0): n={rn}  W={rW} L={rL}  WR={rwr:.1f}%  PnL={rpnl:+.1f}R")

    print(f"\n  По годам (baseline -> retry):")
    all_years = sorted(set(list(b["yearly"].keys()) + list(r["yearly"].keys())))
    for y in all_years:
        bW, bL, bp = b["yearly"].get(y, [0, 0, 0.0])
        rW2, rL2, rp = r["yearly"].get(y, [0, 0, 0.0])
        bwr = bW / (bW + bL) * 100 if (bW + bL) else 0
        rwr2 = rW2 / (rW2 + rL2) * 100 if (rW2 + rL2) else 0
        print(f"    {y}: baseline n={bW+bL:3d} WR={bwr:5.1f}% PnL={bp:+6.1f}R  |  "
              f"retry n={rW2+rL2:3d} WR={rwr2:5.1f}% PnL={rp:+6.1f}R  |  "
              f"delta={rp-bp:+5.1f}R")

    return {
        "symbol": symbol,
        "days": actual_days,
        "years": actual_days / 365,
        "zones": len(groups),
        "pairs": total_pairs,
        "baseline": b,
        "retry": r,
        "retry_only": {"n": rn, "W": rW, "L": rL, "wr": rwr, "pnl": rpnl},
    }


def main():
    print(f"etap_99: 1.1.1 retry-after-SL multi-symbol test")
    print(f"params: entry={ENTRY_PCT} sl={SL_PCT} sym RR={RR}, SWEPT ON, target {DAYS_BACK_TARGET}d (~6y)")
    print(f"NOTE: ETH/SOL 1m data starts 2023-04-26 -> effective window ~3y")

    results = []
    for sym in SYMBOLS:
        r = run_symbol(sym)
        if r is not None:
            results.append(r)

    # Сводная таблица
    print(f"\n\n{'='*88}")
    print(f"СВОДКА  (entry={ENTRY_PCT} sl={SL_PCT} RR={RR}, SWEPT ON)")
    print(f"{'='*88}")
    print(f"{'sym':<8} {'years':>5} {'mode':<10} {'n':>4} {'WR':>6} {'PnL':>8} {'R/t':>7} {'bad':>4}")
    print("-" * 64)
    for r in results:
        b = r["baseline"]; rt = r["retry"]
        print(f"{r['symbol']:<8} {r['years']:>5.1f} {'baseline':<10} "
              f"{b['n']:>4d} {b['wr']:>5.1f}% {b['pnl']:>+7.1f}R {b['r_per']:>+6.3f} {b['bad']:>4d}")
        print(f"{'':<8} {'':>5} {'retry':<10} "
              f"{rt['n']:>4d} {rt['wr']:>5.1f}% {rt['pnl']:>+7.1f}R {rt['r_per']:>+6.3f} {rt['bad']:>4d}")
        delta_pnl = rt['pnl'] - b['pnl']
        delta_wr = rt['wr'] - b['wr']
        ro = r["retry_only"]
        print(f"{'':<8} {'':>5} {'  delta':<10} "
              f"{rt['n']-b['n']:>+4d} {delta_wr:>+5.1f}pp {delta_pnl:>+7.1f}R")
        print(f"{'':<8} {'':>5} {'  retry-only':<12} "
              f"n={ro['n']} W/L={ro['W']}/{ro['L']} WR={ro['wr']:.1f}% PnL={ro['pnl']:+.1f}R")
        print()

    # Sum across symbols
    total_b_n = sum(r["baseline"]["n"] for r in results)
    total_b_pnl = sum(r["baseline"]["pnl"] for r in results)
    total_r_n = sum(r["retry"]["n"] for r in results)
    total_r_pnl = sum(r["retry"]["pnl"] for r in results)
    total_ro = {
        "n": sum(r["retry_only"]["n"] for r in results),
        "W": sum(r["retry_only"]["W"] for r in results),
        "L": sum(r["retry_only"]["L"] for r in results),
        "pnl": sum(r["retry_only"]["pnl"] for r in results),
    }
    ro_wr = total_ro["W"] / total_ro["n"] * 100 if total_ro["n"] else 0
    print("-" * 64)
    print(f"SUMS across all symbols:")
    print(f"  baseline: n={total_b_n}  PnL={total_b_pnl:+.1f}R")
    print(f"  retry:    n={total_r_n}  PnL={total_r_pnl:+.1f}R")
    print(f"  delta:    {total_r_n - total_b_n:+d} trades  {total_r_pnl - total_b_pnl:+.1f}R")
    print(f"  retry-only trades: n={total_ro['n']}  W/L={total_ro['W']}/{total_ro['L']}  "
          f"WR={ro_wr:.1f}%  PnL={total_ro['pnl']:+.1f}R")


if __name__ == "__main__":
    main()
