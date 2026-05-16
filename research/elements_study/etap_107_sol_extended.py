"""etap_107: SOL extended grid — заполнить пропуски 3.0-4.5 + confirm 3,4.

Предыдущая остановка на cap=3.0 (+90.5R) была преждевременной. PnL рос
монотонно. Заполняю промежуток + добавляю медленные confirm.
"""
from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
import importlib.util as _ilu
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists(): _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path: _sys.path.insert(0, str(_ROOT))

from pathlib import Path
_E104 = Path(__file__).parent / "etap_104_floating_variants.py"
_spec = _ilu.spec_from_file_location("etap104_core", _E104)
_e104 = _ilu.module_from_spec(_spec); _sys.modules["etap104_core"] = _e104
_spec.loader.exec_module(_e104)
variant_rcap_score = _e104.variant_rcap_score
collect_signals = _e104.collect_signals
evaluate_variant = _e104.evaluate_variant
distribution_stats = _e104.distribution_stats

_E103 = Path(__file__).parent / "etap_103_floating_tp.py"
_spec3 = _ilu.spec_from_file_location("etap103_core", _E103)
_e103 = _ilu.module_from_spec(_spec3); _sys.modules["etap103_core"] = _e103
_spec3.loader.exec_module(_e103)
build_score_series = _e103.build_score_series


def main():
    print("etap_107: SOL extended D-grid (filling 3.0-4.5 gap + cf=3,4)")
    sigs, df_1m, df_1h, df_2h, years = collect_signals("SOLUSDT")
    print(f"  SOL signals (swept): {len(sigs)}, years={years:.2f}")
    score_long, score_short = build_score_series(df_1h)

    print()
    print(f"  {'cap':>4} {'th':>5} {'cf':>3} | {'n':>4} {'WR':>5} {'PnL':>9} {'medR':>6} "
          f"{'maxR':>5} {'top5%':>6} {'top10%':>7} {'pass':>6}")
    print("  " + "-"*86)

    # Filling gap 3.0-4.5 and add cf=3,4 across all relevant caps
    caps = [2.5, 3.0, 3.25, 3.5, 3.75, 4.0, 4.25, 4.5]
    thresholds = [-0.5, -0.25, 0.0, +0.25]
    confirms = [1, 2, 3, 4]

    results = []
    for cap in caps:
        for th in thresholds:
            for cf in confirms:
                trs = evaluate_variant("D",
                                         lambda s, _c=cap, _t=th, _cf=cf:
                                         variant_rcap_score(s, df_1m, df_1h,
                                                             score_long, score_short,
                                                             R_cap=_c, threshold=_t, confirm=_cf),
                                         sigs)
                st = distribution_stats(trs)
                if st is None: continue
                pass_strict = (st["median_R"] > 0 and st["top5_pct"] < 20)
                tag = "PASS" if pass_strict else "    "
                print(f"  {cap:>4.2f} {th:>+5.2f} {cf:>3d} | {st['n']:>4d} {st['wr']:>4.1f}% "
                      f"{st['pnl']:>+8.1f}R {st['median_R']:>+5.2f} {st['max_R']:>+4.1f} "
                      f"{st['top5_pct']:>5.1f}% {st['top10pct_pct']:>6.1f}% {tag}")
                results.append({"cap": cap, "th": th, "cf": cf, "st": st, "pass": pass_strict})

    print()
    print("TOP-10 ALL by PnL (passing smoothness):")
    passing = [r for r in results if r["pass"]]
    passing.sort(key=lambda x: x["st"]["pnl"], reverse=True)
    for r in passing[:10]:
        st = r["st"]
        print(f"  cap={r['cap']} th={r['th']:+.2f} cf={r['cf']}: PnL={st['pnl']:+.1f}R "
              f"WR={st['wr']:.1f}% medR={st['median_R']:+.2f} top5={st['top5_pct']:.1f}%")

    print()
    print("TOP-5 ALL (ignore smoothness) — for reference:")
    results.sort(key=lambda x: x["st"]["pnl"], reverse=True)
    for r in results[:5]:
        st = r["st"]
        tag = "PASS" if r["pass"] else "FAT-TAIL"
        print(f"  cap={r['cap']} th={r['th']:+.2f} cf={r['cf']}: PnL={st['pnl']:+.1f}R "
              f"medR={st['median_R']:+.2f} top5={st['top5_pct']:.1f}% [{tag}]")


if __name__ == "__main__":
    main()
