"""B2C2 — FIRST 50%-sweep ob_liq (multi-TF).

OB-семейство, sub-условие #2. Использует detect_ob_liq (2-свечный, 2-условный маркер).
Без Williams-фрактальности — per memory [[feedback-ob-liq-no-fractality]].
Multi-TF: 12h ∪ D ∪ 2D ∪ 3D ∪ W.
50%-sweep = wick ≥ midpoint zone + close back OUTSIDE.
Causal: ✅
"""
from __future__ import annotations
import numpy as np
import sys, pathlib
sys.path.insert(0, str(pathlib.Path.home() / "smc-lib"))
from candle import Candle
from elements.ob_liq.code import detect_ob_liq
from _lib import load_12h, load_htf_bars, TF_HTF, load_baseline, match_pivots, report, save_fires


def scan_ob_liq(tfs=("12h", "D", "2D", "3D", "W")) -> list[dict]:
    zones = []
    for tf in tfs:
        bars = load_htf_bars(tf)
        cans = [Candle(open=b[1], high=b[2], low=b[3], close=b[4], open_time=b[0]) for b in bars]
        tfms = TF_HTF[tf]
        for i in range(len(cans) - 1):
            ob = detect_ob_liq(cans[i], cans[i+1])
            if ob is None: continue
            zones.append({
                "tf": tf,
                "direction": ob.direction,
                "zlo": ob.zone[0],
                "zhi": ob.zone[1],
                "ready_ms": cans[i+1].open_time + tfms,
            })
    return zones


def main():
    bars = load_12h()
    zones = scan_ob_liq()
    n12 = bars["n"]
    t12, h12, l12, c12 = bars["t"], bars["h"], bars["l"], bars["c"]
    fires = set()
    for z in zones:
        sp = int(np.searchsorted(t12, z["ready_ms"], side="left"))
        if sp >= n12: continue
        zlo, zhi = z["zlo"], z["zhi"]
        mid = (zlo + zhi) / 2
        for k in range(sp, n12):
            if z["direction"] == "short":
                if h12[k] >= mid and c12[k] < zlo:
                    fires.add((k, "short")); break
            else:
                if l12[k] <= mid and c12[k] > zhi:
                    fires.add((k, "long")); break

    pmap = match_pivots(bars, load_baseline())
    report("B2C2", "ob_liq FIRST 50%-sweep (multi-TF)", fires, pmap)
    save_fires("B2C2", fires, bars)


if __name__ == "__main__":
    main()
