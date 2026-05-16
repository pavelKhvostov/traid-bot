"""etap_106: SOL needs tighter R_cap. Test D variant с R_cap ∈ {2, 2.5, 3} на SOL."""
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
variant_baseline_rr = _e104.variant_baseline_rr
collect_signals = _e104.collect_signals
evaluate_variant = _e104.evaluate_variant
distribution_stats = _e104.distribution_stats

_E103 = Path(__file__).parent / "etap_103_floating_tp.py"
_spec3 = _ilu.spec_from_file_location("etap103_core", _E103)
_e103 = _ilu.module_from_spec(_spec3); _sys.modules["etap103_core"] = _e103
_spec3.loader.exec_module(_e103)
build_score_series = _e103.build_score_series


def main():
    print("etap_106: SOL-specific tight cap tuning")
    sigs, df_1m, df_1h, df_2h, years = collect_signals("SOLUSDT")
    print(f"  SOL signals (swept): {len(sigs)}, years={years:.2f}")
    score_long, score_short = build_score_series(df_1h)
    trs_b = evaluate_variant("baseline", lambda s: variant_baseline_rr(s, df_1m), sigs)
    st_b = distribution_stats(trs_b)
    print(f"  baseline: PnL={st_b['pnl']:+.1f}R WR={st_b['wr']:.1f}% medR={st_b['median_R']:+.2f}")
    print()
    print(f"  {'cap':>4} {'th':>5} {'cf':>3} | {'n':>4} {'WR':>5} {'PnL':>9} {'medR':>6} "
          f"{'maxR':>5} {'top5%':>6} {'top10%':>7}")
    print("  " + "-"*80)
    for cap in [1.5, 2.0, 2.5, 3.0]:
        for th in [-0.25, 0.0, +0.25]:
            for cf in [1, 2]:
                trs = evaluate_variant("D",
                                         lambda s, _c=cap, _t=th, _cf=cf:
                                         variant_rcap_score(s, df_1m, df_1h,
                                                             score_long, score_short,
                                                             R_cap=_c, threshold=_t, confirm=_cf),
                                         sigs)
                st = distribution_stats(trs)
                if st is None: continue
                pass_ = "PASS" if (st["median_R"] > 0 and st["top5_pct"] < 20) else "    "
                print(f"  {cap:>4.1f} {th:>+5.2f} {cf:>3d} | {st['n']:>4d} {st['wr']:>4.1f}% "
                      f"{st['pnl']:>+8.1f}R {st['median_R']:>+5.2f} {st['max_R']:>+4.1f} "
                      f"{st['top5_pct']:>5.1f}% {st['top10pct_pct']:>6.1f}% {pass_}")


if __name__ == "__main__":
    main()
