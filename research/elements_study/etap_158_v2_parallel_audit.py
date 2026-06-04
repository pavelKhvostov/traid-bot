"""etap_158: Параллельный V2 backtest + audit на 10 cores.

Стратегия параллелизации:
  - Главный процесс собирает кандидатов L1 OB-D
  - ProcessPoolExecutor распределяет их по workers (1 worker = N L1 OBs)
  - Каждый worker делает полный sub-cascade scan (L2 macro + ob_vc detection)
    с собственной копией dataframes (через pickle init)
  - Главный процесс собирает результаты, считает score, симулирует floating

  1m данные большие (3.3M строк) — копируются в каждый worker один раз через
  process initializer, не на каждый job.
"""
from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists(): _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path: _sys.path.insert(0, str(_ROOT))

import time
import os
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed

import pandas as pd

from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_1 import detect_ob_pair, collect_valid_macro_fvgs
from strategies.strategy_1_1_1_floating import (
    FLOATING_TP_CONFIG, build_score_series, simulate_floating,
)
from strategies.strategy_1_1_1_floating_v2 import detect_ob_vc

SYMBOL = "BTCUSDT"
START_DATE = "2020-01-01"
N_WORKERS = 10  # 12 cores - 2 для main + OS

# Global frames для workers (set by initializer)
_WORKER_DFS: dict = {}


def _init_worker(df_4h, df_6h, df_1h, df_2h, df_15m, df_20m, df_1m):
    """Process initializer: dataframes копируются один раз на worker."""
    _WORKER_DFS["df_4h"] = df_4h
    _WORKER_DFS["df_6h"] = df_6h
    _WORKER_DFS["df_1h"] = df_1h
    _WORKER_DFS["df_2h"] = df_2h
    _WORKER_DFS["df_15m"] = df_15m
    _WORKER_DFS["df_20m"] = df_20m
    _WORKER_DFS["df_1m"] = df_1m


def _scan_one_l1_ob(ob_d_data) -> list[dict]:
    """Worker job: scan один L1 OB-D, вернуть list of ob_vc signals."""
    ob_top, top_tf_hours, top_label = ob_d_data
    df_4h = _WORKER_DFS["df_4h"]; df_6h = _WORKER_DFS["df_6h"]
    df_1h = _WORKER_DFS["df_1h"]; df_2h = _WORKER_DFS["df_2h"]
    df_15m = _WORKER_DFS["df_15m"]; df_20m = _WORKER_DFS["df_20m"]
    df_1m = _WORKER_DFS["df_1m"]

    out: list[dict] = []
    valid_4h = collect_valid_macro_fvgs(df_4h, ob_top, htf_hours=4, top_tf_hours=top_tf_hours)
    valid_6h = collect_valid_macro_fvgs(df_6h, ob_top, htf_hours=6, top_tf_hours=top_tf_hours)
    for fvg_macro, macro_tf in [(f, "4h") for f in valid_4h] + [(f, "6h") for f in valid_6h]:
        search_start = ob_top.cur_time + pd.Timedelta(hours=top_tf_hours)
        for df_htf, htf_label, htf_hours in [(df_1h, "1h", 1), (df_2h, "2h", 2)]:
            dfw_htf = df_htf[df_htf.index >= search_start]
            if len(dfw_htf) < 3:
                continue
            for i in range(1, len(dfw_htf)):
                cand_ob = detect_ob_pair(dfw_htf, i)
                if cand_ob is None or cand_ob.direction != ob_top.direction:
                    continue
                if not (cand_ob.top >= fvg_macro.bottom and cand_ob.bottom <= fvg_macro.top):
                    continue
                if not (cand_ob.top >= ob_top.bottom and cand_ob.bottom <= ob_top.top):
                    continue
                for df_ltf, ltf_label, tf_min in [(df_15m, "15m", 15), (df_20m, "20m", 20)]:
                    ob_vc = detect_ob_vc(
                        ob=cand_ob, df_htf=dfw_htf, df_ltf=df_ltf,
                        htf_label=htf_label, ltf_label=ltf_label,
                        fvg_tf_minutes=tf_min, df_1m=df_1m, n_fractal=2,
                    )
                    if ob_vc is None:
                        continue
                    out.append({
                        "direction": ob_top.direction,
                        "signal_time": ob_vc.fvg.c2_time,
                        "top_tf": top_label,
                        "ob_d_cur_time": ob_top.cur_time,
                        "ob_d_zone": (ob_top.bottom, ob_top.top),
                        "fvg_macro_tf": macro_tf,
                        "fvg_macro_zone": (fvg_macro.bottom, fvg_macro.top),
                        "ob_htf_tf": ob_vc.htf_label,
                        "ob_htf_prev_time": ob_vc.ob.prev_time,
                        "ob_htf_cur_time": ob_vc.ob.cur_time,
                        "ob_htf_zone": (ob_vc.ob.bottom, ob_vc.ob.top),
                        "fvg_tf": ob_vc.ltf_label,
                        "fvg_c2_time": ob_vc.fvg.c2_time,
                        "fvg_zone": (ob_vc.fvg.bottom, ob_vc.fvg.top),
                        "ob_vc_fractal_confirmation": ob_vc.fractal_confirmation_time,
                        "version": "v2_ob_vc",
                    })
                    break
    return out


def main():
    print(f"etap_158: V2 PARALLEL backtest + audit (workers={N_WORKERS})")
    print(f"PID main: {os.getpid()}")
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
    print(f"Data: {df_1d.index[0]} -> {df_1d.index[-1]}")
    print(f"  1d={len(df_1d)}  1h={len(df_1h)}  1m={len(df_1m)} rows")
    print()

    # Step 1: collect all L1 OB-Ds
    print("Step 1: collect L1 OB-Ds...")
    t0 = time.time()
    l1_obs: list = []
    for df_top, top_tf_hours, top_label in [(df_1d, 24, "1d"), (df_12h, 12, "12h")]:
        for idx in range(1, len(df_top)):
            ob = detect_ob_pair(df_top, idx)
            if ob is not None:
                l1_obs.append((ob, top_tf_hours, top_label))
    print(f"  {len(l1_obs)} L1 OB candidates  (t={time.time()-t0:.1f}s)")
    print()

    # Step 2: parallel scan
    print(f"Step 2: parallel scan через {N_WORKERS} workers...")
    t0 = time.time()
    all_signals: list[dict] = []
    completed = 0
    with ProcessPoolExecutor(
        max_workers=N_WORKERS,
        initializer=_init_worker,
        initargs=(df_4h, df_6h, df_1h, df_2h, df_15m, df_20m, df_1m),
    ) as pool:
        futures = {pool.submit(_scan_one_l1_ob, ob_data): ob_data for ob_data in l1_obs}
        for fut in as_completed(futures):
            try:
                signals = fut.result()
            except Exception as e:
                print(f"  worker error: {e}")
                continue
            all_signals.extend(signals)
            completed += 1
            if completed % 50 == 0:
                print(f"  [{completed}/{len(l1_obs)}] L1 OBs done, signals so far: {len(all_signals)}")
    print(f"  Total signals: {len(all_signals)}  (parallel scan t={time.time()-t0:.1f}s)")
    print()

    # Step 3: build score (1 раз для main process)
    print("Step 3: build score series...")
    t0 = time.time()
    score_long, score_short = build_score_series(df_1h)
    print(f"  done (t={time.time()-t0:.1f}s)")
    print()

    # Step 4: simulate floating per signal (multi-process)
    print("Step 4: simulate floating TP per signal...")
    cfg = FLOATING_TP_CONFIG[SYMBOL]
    t0 = time.time()
    trades = []
    for sig in all_signals:
        result = simulate_floating(
            sig, df_1m, df_1h, score_long, score_short,
            R_cap=cfg["R_cap"], threshold=cfg["threshold"], confirm=cfg["confirm"],
        )
        if result is None:
            continue
        trades.append({
            **sig,
            "outcome": result.outcome, "R": result.R,
            "exit_time": result.exit_time, "exit_reason": result.exit_reason,
            "hold_h": result.hold_h, "max_R": result.max_R,
        })
    print(f"  {len(trades)} trades simulated  (t={time.time()-t0:.1f}s)")
    print()

    # ===========================================
    # AUDIT
    # ===========================================
    closed = [t for t in trades if t["outcome"] in ("win", "loss", "flat")]
    print("=" * 70)
    print(f"V2 raw results: {len(closed)} closed trades")
    print("=" * 70)
    raw_pnl = sum(t["R"] for t in closed)
    raw_W = sum(1 for t in closed if t["R"] > 0)
    print(f"  PnL: {raw_pnl:+.1f}R  WR: {raw_W/len(closed)*100:.1f}%  R/tr: {raw_pnl/len(closed):+.3f}")
    print()

    # Audit A: Multi-shot dedup
    print("=" * 70)
    print("AUDIT A: Multi-shot dedup by (signal_time floor 1h, direction)")
    print("=" * 70)
    seen = {}
    for t in closed:
        key = (t["signal_time"].floor("h"), t["direction"])
        if key not in seen:
            seen[key] = t
    unique = list(seen.values())
    u_pnl = sum(t["R"] for t in unique)
    u_W = sum(1 for t in unique if t["R"] > 0)
    print(f"  Raw multi-shot:     n={len(closed):>4d}  PnL={raw_pnl:>+8.1f}R  WR={raw_W/len(closed)*100:5.1f}%  R/tr={raw_pnl/len(closed):+.3f}")
    print(f"  Unique:             n={len(unique):>4d}  PnL={u_pnl:>+8.1f}R  WR={u_W/len(unique)*100:5.1f}%  R/tr={u_pnl/len(unique):+.3f}")
    print(f"  Inflation:          {len(closed)/len(unique):.2f}× count, {raw_pnl/u_pnl:.2f}× PnL")
    print()

    # Audit B: Lookahead — fix signal_time = fractal_confirmation_time
    print("=" * 70)
    print("AUDIT B: Lookahead fix — signal_time → fractal_confirmation_time")
    print("=" * 70)
    fixed = []
    for t in unique:
        sig_t = pd.Timestamp(t["signal_time"])
        frac_t = pd.Timestamp(t["ob_vc_fractal_confirmation"])
        if frac_t > sig_t:
            # ИСТИННЫЙ signal_time = fractal_confirmation_time
            # Это значит что entry должен ставиться ПОЗЖЕ на (frac_t - sig_t)
            # И мы должны проверить что FVG entry всё ещё валидна на момент frac_t
            # (если она к этому моменту consumed на 1m — setup мёртв)
            # Сейчас просто фиксируем сколько таких trades
            fixed.append({**t, "fixed_signal_time": frac_t, "delay_h": (frac_t - sig_t).total_seconds()/3600})
        else:
            fixed.append({**t, "fixed_signal_time": sig_t, "delay_h": 0})
    delays = [t["delay_h"] for t in fixed]
    print(f"  Trades с lookahead (fractal > signal): {sum(1 for t in fixed if t['delay_h'] > 0)} / {len(fixed)}")
    if any(d > 0 for d in delays):
        nonzero = [d for d in delays if d > 0]
        print(f"  Среднее опережение: {sum(nonzero)/len(nonzero):.1f}h, max={max(nonzero):.1f}h")
    print(f"\n  ⚠ Каноны #5/#8 ob_vc используют fractal_confirmation_time для отсева FVG.")
    print(f"  В live: в момент FVG.c2_time мы НЕ знаем будет ли подтверждённый фрактал.")
    print(f"  Это lookahead — мы выбираем setup'ы которые задним числом получили confirmation.")
    print(f"  Honest fix: entry только ПОСЛЕ fractal_confirmation_time (отложить fill).")
    print()

    # Audit C: Exit reasons и cap_hit dominance
    print("=" * 70)
    print("AUDIT C: Exit reasons на UNIQUE")
    print("=" * 70)
    by_reason = defaultdict(lambda: {"n": 0, "R": 0.0})
    for t in unique:
        by_reason[t["exit_reason"]]["n"] += 1
        by_reason[t["exit_reason"]]["R"] += t["R"]
    for r, d in sorted(by_reason.items()):
        avg_R = d["R"]/d["n"] if d["n"] else 0
        share = d["R"]/u_pnl*100 if u_pnl else 0
        print(f"  {r:<15} n={d['n']:>3d} PnL={d['R']:>+7.1f}R avg={avg_R:>+.2f}R doля={share:>5.1f}%")
    print()

    # Audit D: Per-year на UNIQUE
    print("=" * 70)
    print("AUDIT D: Per-year на UNIQUE")
    print("=" * 70)
    by_year = defaultdict(lambda: {"n": 0, "W": 0, "R": 0.0})
    for t in unique:
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
    print(f"  Bad years (unique): {bad_yrs}/{len(by_year)}")
    print()

    # Final
    print("=" * 70)
    print("VERDICT")
    print("=" * 70)
    print(f"  Raw etap_156 claim:     +1451R / 1721 trades / R/tr +0.84 / 0 bad")
    print(f"  Honest unique:          {u_pnl:>+5.1f}R / {len(unique):>4d} trades / R/tr {u_pnl/len(unique):+.2f} / {bad_yrs} bad")
    print(f"  Multi-shot inflation:   {raw_pnl/u_pnl:.2f}×")
    print(f"  Lookahead trades:       {sum(1 for t in fixed if t['delay_h'] > 0)}/{len(fixed)} ({sum(1 for t in fixed if t['delay_h'] > 0)/len(fixed)*100:.0f}%)")


if __name__ == "__main__":
    main()
