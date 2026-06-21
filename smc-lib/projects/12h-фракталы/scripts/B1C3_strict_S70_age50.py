"""B1C3 — strict sweep FVG, S70 / AGE50.

Условие: pen ≥ 70% + close OUTSIDE + age ≥ 50 12h-bars.
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
    fires = fires_strict_sweep(fvgs, bars, atr12, pen_min=70, filt_type="AGE50")
    pmap = match_pivots(bars, load_baseline())
    report("B1C3", "S70 / AGE50", fires, pmap)
    save_fires("B1C3", fires, bars)


if __name__ == "__main__":
    main()
