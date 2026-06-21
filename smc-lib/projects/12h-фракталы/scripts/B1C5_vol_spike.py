"""B1C5 — sweep FVG + volume spike.

Условие: pen ≥ 50% + close OUTSIDE + vol_z(50) ≥ +2σ на sweep bar.
vol_z — rolling z-score объёма 12h-бара, past-only окно 50.
Causal: ✅
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from _lib import load_12h, load_baseline, match_pivots, report, save_fires
from _fvg import scan_fvgs, build_events


def main():
    bars = load_12h()
    v_ser = pd.Series(bars["v"])
    v_mean = v_ser.rolling(50, min_periods=20).mean().bfill().values
    v_std = v_ser.rolling(50, min_periods=20).std().bfill().values
    v_z = (bars["v"] - v_mean) / np.where(v_std > 0, v_std, 1.0)

    fvgs = scan_fvgs()
    build_events(fvgs, bars)

    fires = set()
    for z in fvgs:
        for k, pen, ci, co_far in z["events"]:
            if pen >= 50 and co_far and v_z[k] >= 2.0:
                fires.add((k, z["direction"]))
                break

    pmap = match_pivots(bars, load_baseline())
    report("B1C5", "S50 + vol_z ≥ +2σ", fires, pmap)
    save_fires("B1C5", fires, bars)


if __name__ == "__main__":
    main()
