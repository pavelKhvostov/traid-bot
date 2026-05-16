"""etap_110: разбор откуда взялось 2157 trades на 1.1.2 BTC.

Layers:
  1. Сколько top-OB найдено на BTC 6.34y
  2. Сколько (top × macro OB) пар
  3. Сколько (top × macro × htf-OB × entry FVG) — multi-shot signals
  4. После build_setup валидации
  5. После no_entry / nf фильтрации = closed trades
  6. После дедупа (signal_time, direction, round(entry, 2))
  7. Уникальных по (signal_time, direction) только
"""
from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
import importlib.util as _ilu

_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists(): _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path: _sys.path.insert(0, str(_ROOT))

from collections import defaultdict
from pathlib import Path
import pandas as pd

from data_manager import compose_from_base, load_df

_E109 = Path(__file__).parent / "etap_109_floating_112.py"
_spec = _ilu.spec_from_file_location("etap109_core", _E109)
_e109 = _ilu.module_from_spec(_spec); _sys.modules["etap109_core"] = _e109
_spec.loader.exec_module(_e109)

detect_multi_signals_112 = _e109.detect_multi_signals_112
build_setup_112 = _e109.build_setup_112
variant_baseline_rr = _e109.variant_baseline_rr
collect_signals_112 = _e109.collect_signals_112
DAYS_BACK_TARGET = 2313


def main():
    print("etap_110: signal funnel audit for 1.1.2 BTC")
    sigs, df_1m, df_1h, df_2h, years = collect_signals_112("BTCUSDT")
    print(f"\nLayer 1 — Raw signals from multi-shot detector:")
    print(f"  Total signals: {len(sigs)}")

    # by top_tf
    by_top = defaultdict(int)
    for s in sigs:
        by_top[s["top_tf"]] += 1
    for k, v in sorted(by_top.items()):
        print(f"    top_tf={k}: {v}")

    # by macro_tf
    by_macro = defaultdict(int)
    for s in sigs:
        by_macro[s["ob_macro_tf"]] += 1
    for k, v in sorted(by_macro.items()):
        print(f"    macro_tf={k}: {v}")

    # by (signal_time, direction, entry) uniqueness
    by_sig_entry = defaultdict(int)
    for s in sigs:
        setup = build_setup_112(s)
        if setup is None: continue
        entry, sl = setup
        key = (s["signal_time"], s["direction"], round(entry, 2))
        by_sig_entry[key] += 1

    n_unique_entry = len(by_sig_entry)
    n_with_dup = sum(1 for c in by_sig_entry.values() if c > 1)
    max_dup = max(by_sig_entry.values()) if by_sig_entry else 0
    avg_dup = sum(by_sig_entry.values()) / len(by_sig_entry) if by_sig_entry else 0
    print(f"\nLayer 2 — Unique (signal_time, direction, entry):")
    print(f"  Unique entries: {n_unique_entry}")
    print(f"  Entries with >1 occurrence: {n_with_dup}")
    print(f"  Max duplicates for one entry: {max_dup}")
    print(f"  Avg duplicates per entry: {avg_dup:.1f}")

    # by (signal_time, direction) — most relaxed dedup
    by_st_dir = defaultdict(int)
    for s in sigs:
        by_st_dir[(s["signal_time"], s["direction"])] += 1
    print(f"\nLayer 3 — Unique (signal_time, direction):")
    print(f"  Unique: {len(by_st_dir)}")

    # Сколько закрытых трейдов в multi-shot baseline
    print(f"\nLayer 4 — Closed trades after simulator (baseline RR=2.2):")
    closed_count = 0
    no_entry_count = 0
    nf_count = 0
    for s in sigs:
        r = variant_baseline_rr(s, df_1m)
        if r is None: continue
        if r["outcome"] in ("win", "loss", "flat"):
            closed_count += 1
        elif r["exit_reason"] == "no_entry":
            no_entry_count += 1
        elif r["exit_reason"] == "nf":
            nf_count += 1
    print(f"  closed (win/loss/flat): {closed_count}")
    print(f"  no_entry (TP до entry): {no_entry_count}")
    print(f"  not_filled (entry не дотронулась): {nf_count}")

    # Dedup at closed level
    print(f"\nLayer 5 — После дедупа closed trades по (signal_time, direction, entry):")
    closed_by_key = {}
    for s in sigs:
        r = variant_baseline_rr(s, df_1m)
        if r is None: continue
        if r["outcome"] not in ("win", "loss", "flat"): continue
        setup = build_setup_112(s)
        if setup is None: continue
        entry, _ = setup
        key = (s["signal_time"], s["direction"], round(entry, 2))
        if key not in closed_by_key:
            closed_by_key[key] = r
    print(f"  Unique closed trades: {len(closed_by_key)}")
    print(f"  Inflation factor: {closed_count / len(closed_by_key) if closed_by_key else 1:.2f}x")

    # PnL with dedup
    pnl_dedup = sum(r["R"] for r in closed_by_key.values())
    W_d = sum(1 for r in closed_by_key.values() if r["R"] > 0)
    L_d = sum(1 for r in closed_by_key.values() if r["R"] < 0)
    print(f"  Dedupped baseline PnL: {pnl_dedup:+.1f}R  WR: {W_d/(W_d+L_d)*100:.1f}%")


if __name__ == "__main__":
    main()
