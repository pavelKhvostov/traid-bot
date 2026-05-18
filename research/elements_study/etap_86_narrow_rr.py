"""Этап 86: тот же param tune что etap_85, но узкая сетка RR ∈ [1.8, 2.0, 2.2].

Цель: пользователь спросил какие лучшие в этом коридоре RR.
"""
from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

import time
import importlib.util
_spec85 = importlib.util.spec_from_file_location(
    "etap85_core", str(_Path(__file__).parent / "etap_85_eth_param_tune.py"))
_e85 = importlib.util.module_from_spec(_spec85); _spec85.loader.exec_module(_e85)

# Override grids
_e85.ENTRY_GRID = [0.50, 0.60, 0.70, 0.80, 0.90]
_e85.SL_GRID = [0.25, 0.35, 0.45, 0.55]
_e85.RR_GRID = [1.8, 2.0, 2.2]


def main():
    t0 = time.time()
    print(f"[INFO] Narrow RR tune: RR in [1.8, 2.0, 2.2]")
    print(f"[INFO] grid: 5 entry x 4 sl x 3 RR = 60 combos symmetric, 240 asymmetric per strategy")

    btc = _e85.load_all("BTCUSDT", _e85.START_DATE)
    eth = _e85.load_all("ETHUSDT", _e85.START_DATE)

    print(f"\n[INFO] caching detected setups...")
    s114_btc = _e85.cache_114_setups(btc)
    s114_eth = _e85.cache_114_setups(eth)
    print(f"  1.1.4 BFJK: BTC={len(s114_btc)}, ETH={len(s114_eth)}")
    s115_btc = _e85.cache_115_setups(btc)
    s115_eth = _e85.cache_115_setups(eth)
    print(f"  1.1.5: BTC={len(s115_btc)}, ETH={len(s115_eth)}")
    s111_btc = _e85.cache_111_signals(btc)
    s111_eth = _e85.cache_111_signals(eth)
    print(f"  1.1.1 SWEPT: BTC={len(s111_btc)}, ETH={len(s111_eth)}")

    def grid_asym(setups, df_1m, eval_fn):
        rows = []
        for e in _e85.ENTRY_GRID:
            for sL in _e85.SL_GRID:
                for sS in _e85.SL_GRID:
                    for rr in _e85.RR_GRID:
                        m = eval_fn(setups, e, sL, sS, rr, df_1m)
                        if m["n"] < 20: continue
                        rows.append({"entry": e, "sl_L": sL, "sl_S": sS, "rr": rr, **m})
        return rows

    def grid_sym(setups, df_1m, eval_fn):
        rows = []
        for e in _e85.ENTRY_GRID:
            for s in _e85.SL_GRID:
                for rr in _e85.RR_GRID:
                    m = eval_fn(setups, e, s, rr, df_1m)
                    if m["n"] < 20: continue
                    rows.append({"entry": e, "sl": s, "rr": rr, **m})
        return rows

    def show_top_dual_asym(name, btc_rows, eth_rows, top=15):
        print(f"\n--- {name} ---")
        dual = []
        for r in eth_rows:
            b = next((x for x in btc_rows if x["entry"]==r["entry"]
                       and x["sl_L"]==r["sl_L"] and x["sl_S"]==r["sl_S"]
                       and x["rr"]==r["rr"]), None)
            if b is None: continue
            if r["total"] > 0 and b["total"] > 0:
                dual.append({"e": r, "b": b, "sum": r["total"] + b["total"]})
        dual = sorted(dual, key=lambda x: x["sum"], reverse=True)[:top]
        print(f"  TOP {top} dual-asset (sorted by combined R):")
        print(f"  {'entry':<6} {'slL':<5} {'slS':<5} {'RR':<5} "
              f"{'BTC n':>6} {'BTC WR':>7} {'BTC R':>7} {'BTC av':>7} "
              f"{'ETH n':>6} {'ETH WR':>7} {'ETH R':>7} {'ETH av':>7} {'sum':>7}")
        for d in dual:
            r, b = d["e"], d["b"]
            print(f"  {r['entry']:<6} {r['sl_L']:<5} {r['sl_S']:<5} {r['rr']:<5} "
                  f"{b['n']:>6} {b['wr']:>6.1f}% {b['total']:>+6.1f} {b['avg']:>+6.2f} "
                  f"{r['n']:>6} {r['wr']:>6.1f}% {r['total']:>+6.1f} {r['avg']:>+6.2f} "
                  f"{d['sum']:>+6.1f}")

    def show_top_dual_sym(name, btc_rows, eth_rows, top=15):
        print(f"\n--- {name} ---")
        dual = []
        for r in eth_rows:
            b = next((x for x in btc_rows if x["entry"]==r["entry"]
                       and x["sl"]==r["sl"] and x["rr"]==r["rr"]), None)
            if b is None: continue
            if r["total"] > 0 and b["total"] > 0:
                dual.append({"e": r, "b": b, "sum": r["total"] + b["total"]})
        dual = sorted(dual, key=lambda x: x["sum"], reverse=True)[:top]
        print(f"  TOP {top} dual-asset (sorted by combined R):")
        print(f"  {'entry':<6} {'sl':<5} {'RR':<5} "
              f"{'BTC n':>6} {'BTC WR':>7} {'BTC R':>7} {'BTC av':>7} "
              f"{'ETH n':>6} {'ETH WR':>7} {'ETH R':>7} {'ETH av':>7} {'sum':>7}")
        for d in dual:
            r, b = d["e"], d["b"]
            print(f"  {r['entry']:<6} {r['sl']:<5} {r['rr']:<5} "
                  f"{b['n']:>6} {b['wr']:>6.1f}% {b['total']:>+6.1f} {b['avg']:>+6.2f} "
                  f"{r['n']:>6} {r['wr']:>6.1f}% {r['total']:>+6.1f} {r['avg']:>+6.2f} "
                  f"{d['sum']:>+6.1f}")

    def show_top_eth_only_asym(name, btc_rows, eth_rows, top=10):
        print(f"\n  TOP {top} by ETH alone (asym):")
        eth_sorted = sorted(eth_rows, key=lambda x: x["total"], reverse=True)[:top]
        for r in eth_sorted:
            b = next((x for x in btc_rows if x["entry"]==r["entry"]
                       and x["sl_L"]==r["sl_L"] and x["sl_S"]==r["sl_S"]
                       and x["rr"]==r["rr"]), None)
            bt = "—" if not b else f"BTC: n={b['n']:>3} WR={b['wr']:5.1f}% R={b['total']:+6.1f}R avg={b['avg']:+5.2f}"
            print(f"    e={r['entry']:.2f} slL={r['sl_L']:.2f} slS={r['sl_S']:.2f} RR={r['rr']:.1f}: "
                  f"ETH n={r['n']:>3} WR={r['wr']:5.1f}% R={r['total']:+6.1f}R avg={r['avg']:+5.2f} | {bt}")

    def show_top_eth_only_sym(name, btc_rows, eth_rows, top=10):
        print(f"\n  TOP {top} by ETH alone (sym):")
        eth_sorted = sorted(eth_rows, key=lambda x: x["total"], reverse=True)[:top]
        for r in eth_sorted:
            b = next((x for x in btc_rows if x["entry"]==r["entry"]
                       and x["sl"]==r["sl"] and x["rr"]==r["rr"]), None)
            bt = "—" if not b else f"BTC: n={b['n']:>3} WR={b['wr']:5.1f}% R={b['total']:+6.1f}R avg={b['avg']:+5.2f}"
            print(f"    e={r['entry']:.2f} sl={r['sl']:.2f} RR={r['rr']:.1f}: "
                  f"ETH n={r['n']:>3} WR={r['wr']:5.1f}% R={r['total']:+6.1f}R avg={r['avg']:+5.2f} | {bt}")

    # ==================== 1.1.4 ====================
    print(f"\n{'='*100}\n1.1.4 BFJK (RR in [1.8, 2.0, 2.2])\n{'='*100}")
    b114 = grid_asym(s114_btc, btc["1m"], _e85.eval_114)
    e114 = grid_asym(s114_eth, eth["1m"], _e85.eval_114)
    show_top_eth_only_asym("1.1.4 BFJK", b114, e114)
    show_top_dual_asym("1.1.4 BFJK", b114, e114)

    # ==================== 1.1.5 ====================
    print(f"\n{'='*100}\n1.1.5 hi-freq (RR in [1.8, 2.0, 2.2])\n{'='*100}")
    b115 = grid_asym(s115_btc, btc["1m"], _e85.eval_115)
    e115 = grid_asym(s115_eth, eth["1m"], _e85.eval_115)
    show_top_eth_only_asym("1.1.5", b115, e115)
    show_top_dual_asym("1.1.5", b115, e115)

    # ==================== 1.1.1 ====================
    print(f"\n{'='*100}\n1.1.1 SWEPT (RR in [1.8, 2.0, 2.2])\n{'='*100}")
    b111 = grid_sym(s111_btc, btc["1m"], _e85.eval_111)
    e111 = grid_sym(s111_eth, eth["1m"], _e85.eval_111)
    show_top_eth_only_sym("1.1.1 SWEPT", b111, e111)
    show_top_dual_sym("1.1.1 SWEPT", b111, e111)

    print(f"\n[TIME] {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
