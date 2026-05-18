"""etap_105: tune the D variant (R-cap + score-exit) — winner from etap_104.

Grid: R_cap × threshold × confirm. Looking for max PnL × (1 - top5_pct/100)
subject to median_R > 0 AND top5_pct < 20%.

Also test on ETH/SOL with the winner.
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

from pathlib import Path
import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df

_E104 = Path(__file__).parent / "etap_104_floating_variants.py"
_spec = _ilu.spec_from_file_location("etap104_core", _E104)
_e104 = _ilu.module_from_spec(_spec); _sys.modules["etap104_core"] = _e104
_spec.loader.exec_module(_e104)
variant_rcap_score = _e104.variant_rcap_score
variant_baseline_rr = _e104.variant_baseline_rr
collect_signals = _e104.collect_signals
evaluate_variant = _e104.evaluate_variant
distribution_stats = _e104.distribution_stats

_E103 = Path(__file__).parent / "etap_103_floating_tp.py"
_spec3 = _ilu.spec_from_file_location("etap103_core", _E103)
_e103 = _ilu.module_from_spec(_spec3); _sys.modules["etap103_core"] = _e103
_spec3.loader.exec_module(_e103)
build_score_series = _e103.build_score_series


def balance_score(st):
    if st is None or st["median_R"] <= 0 or st["top5_pct"] >= 20:
        return -999
    return st["pnl"] * (1 - st["top5_pct"]/100)


def tune_symbol(symbol):
    print(f"\n{'#'*72}\n#  TUNING D on {symbol}\n{'#'*72}")
    sigs, df_1m, df_1h, df_2h, years = collect_signals(symbol)
    print(f"  signals (swept): {len(sigs)}, years={years:.2f}")
    score_long, score_short = build_score_series(df_1h)

    # baseline reference
    trs_b = evaluate_variant("baseline", lambda s: variant_baseline_rr(s, df_1m), sigs)
    st_b = distribution_stats(trs_b)
    print(f"  BASELINE RR=2.2: PnL={st_b['pnl']:+.1f}R  WR={st_b['wr']:.1f}%  medR={st_b['median_R']:+.2f}")

    # grid D
    R_caps = [2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 6.0]
    thresholds = [-0.25, 0.0, +0.25]
    confirms = [1, 2, 3]

    print()
    print(f"  Grid: R_cap x threshold x confirm = {len(R_caps)}x{len(thresholds)}x{len(confirms)}")
    print()
    print(f"  {'R_cap':>5} {'th':>5} {'conf':>4} | {'n':>4} {'WR':>5} {'PnL':>8} {'medR':>6} "
          f"{'maxR':>5} {'top5%':>6} {'top10%':>7} | {'balance':>8}")
    print("  " + "-"*100)
    results = []
    for R_cap in R_caps:
        for th in thresholds:
            for cf in confirms:
                trs = evaluate_variant(f"D_cap{R_cap}_th{th}_cf{cf}",
                                         lambda s, _Rc=R_cap, _th=th, _cf=cf:
                                         variant_rcap_score(s, df_1m, df_1h,
                                                             score_long, score_short,
                                                             R_cap=_Rc, threshold=_th, confirm=_cf),
                                         sigs)
                st = distribution_stats(trs)
                if st is None: continue
                bs = balance_score(st)
                marker = "*" if bs > 100 else " "
                print(f"  {R_cap:>5.1f} {th:>+5.2f} {cf:>4d} | {st['n']:>4d} {st['wr']:>4.1f}% "
                      f"{st['pnl']:>+7.1f}R {st['median_R']:>+5.2f} "
                      f"{st['max_R']:>+4.1f} {st['top5_pct']:>5.1f}% {st['top10pct_pct']:>6.1f}% | "
                      f"{bs:>+7.1f}{marker}")
                results.append({"R_cap": R_cap, "th": th, "cf": cf, "st": st, "bs": bs})

    print()
    results.sort(key=lambda x: x["bs"], reverse=True)
    print(f"  TOP-5 by balance score:")
    for r in results[:5]:
        st = r["st"]
        print(f"    D R_cap={r['R_cap']} th={r['th']:+.2f} cf={r['cf']}: "
              f"PnL={st['pnl']:+.1f}R WR={st['wr']:.1f}% medR={st['median_R']:+.2f} "
              f"top5%={st['top5_pct']:.1f}% balance={r['bs']:+.1f}")

    return results, st_b


def main():
    print("etap_105: tune D variant (R-cap + score) на BTC + verify ETH/SOL")
    btc_results, btc_baseline = tune_symbol("BTCUSDT")

    if not btc_results: return
    # winner = top by balance
    winner = btc_results[0]
    print()
    print("="*88)
    print(f"WINNER on BTC: D R_cap={winner['R_cap']} th={winner['th']:+.2f} cf={winner['cf']}")
    print("="*88)
    print(f"  BTC PnL={winner['st']['pnl']:+.1f}R (baseline {btc_baseline['pnl']:+.1f}R)")
    print(f"  BTC WR={winner['st']['wr']:.1f}% (baseline {btc_baseline['wr']:.1f}%)")
    print(f"  BTC medR={winner['st']['median_R']:+.2f} (baseline {btc_baseline['median_R']:+.2f})")
    print(f"  top5%={winner['st']['top5_pct']:.1f}%  top10%={winner['st']['top10pct_pct']:.1f}%")

    # verify on ETH/SOL with winner params
    for symbol in ["ETHUSDT", "SOLUSDT"]:
        print()
        print(f"--- verify on {symbol} ---")
        sigs, df_1m, df_1h, df_2h, years = collect_signals(symbol)
        score_long, score_short = build_score_series(df_1h)
        trs_b = evaluate_variant("baseline", lambda s: variant_baseline_rr(s, df_1m), sigs)
        st_b = distribution_stats(trs_b)
        trs = evaluate_variant("D_winner",
                                 lambda s: variant_rcap_score(s, df_1m, df_1h,
                                                              score_long, score_short,
                                                              R_cap=winner["R_cap"],
                                                              threshold=winner["th"],
                                                              confirm=winner["cf"]),
                                 sigs)
        st = distribution_stats(trs)
        print(f"  {symbol} baseline: PnL={st_b['pnl']:+.1f}R WR={st_b['wr']:.1f}% medR={st_b['median_R']:+.2f}")
        print(f"  {symbol} D_winner: PnL={st['pnl']:+.1f}R WR={st['wr']:.1f}% medR={st['median_R']:+.2f} "
              f"top5%={st['top5_pct']:.1f}%")
        print(f"  delta: {st['pnl']-st_b['pnl']:+.1f}R  (+{(st['pnl']-st_b['pnl'])/abs(st_b['pnl'])*100 if st_b['pnl'] else 0:+.1f}%)")


if __name__ == "__main__":
    main()
