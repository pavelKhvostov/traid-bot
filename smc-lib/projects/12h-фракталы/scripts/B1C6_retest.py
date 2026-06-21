"""B1C6 — sweep FVG → retest (close inside ≤ 3 баров).

Условие: pen ≥ 50% + close OUTSIDE на sweep_k → close INSIDE в окне (sweep_k, sweep_k+3].
Fire bar = retest bar (не sweep bar).
Causal: ✅ (retest bar — текущий, sweep — в прошлом).
"""
from __future__ import annotations
from _lib import load_12h, load_baseline, match_pivots, report, save_fires
from _fvg import scan_fvgs, build_events


def main(N: int = 3):
    bars = load_12h()
    fvgs = scan_fvgs()
    build_events(fvgs, bars)

    fires = set()
    for z in fvgs:
        sweep_k = None
        for k, pen, ci, co_far in z["events"]:
            if sweep_k is None and pen >= 50 and co_far:
                sweep_k = k
                continue
            if sweep_k is not None and k <= sweep_k + N and ci:
                fires.add((k, z["direction"]))
                break

    pmap = match_pivots(bars, load_baseline())
    report("B1C6", f"S50 → close inside ≤{N}b", fires, pmap)
    save_fires("B1C6", fires, bars)


if __name__ == "__main__":
    main()
