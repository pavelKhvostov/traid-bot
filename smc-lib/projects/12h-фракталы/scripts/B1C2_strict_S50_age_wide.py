"""B1C2 — strict sweep FVG, S50 / AGE50 ∧ WIDE.

Условие: pen ≥ 50% + close OUTSIDE + age ≥ 50 12h-bars + width ≥ 0.7 ATR.
Causal: ✅
"""
from __future__ import annotations
from _lib import load_12h, atr, load_baseline, match_pivots, report, save_fires
from _fvg import scan_fvgs, build_events, fires_strict_sweep


def main():
    bars = load_12h()
    atr12 = atr(bars["h"], bars["l"], bars["c"], 14)
    fvgs = scan_fvgs()
    build_events(fvgs, bars)
    fires = fires_strict_sweep(fvgs, bars, atr12, pen_min=50, filt_type="AGE50_WIDE")
    pmap = match_pivots(bars, load_baseline())
    report("B1C2", "S50 / AGE-WIDE", fires, pmap)
    save_fires("B1C2", fires, bars)


if __name__ == "__main__":
    main()
