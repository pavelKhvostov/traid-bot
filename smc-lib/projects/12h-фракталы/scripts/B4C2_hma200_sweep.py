"""B4C2 — HMA-200 sweep D LIVE.

HMA-семейство, sub-условие #2.
Только Daily HMA-200, LIVE value.
Causal: ✅
"""
from __future__ import annotations
import numpy as np
import sys, pathlib
sys.path.insert(0, str(pathlib.Path.home() / "smc-lib"))
from indicators.trend_line_asvk import hma
from _lib import load_12h, load_htf_bars, load_baseline, match_pivots, report, save_fires
from B4C1_hma78_sweep import sweep_hma


def main():
    bars = load_12h()
    bars_d = load_htf_bars("D")
    t_d = np.array([b[0] for b in bars_d], dtype=np.int64)
    c_d = np.array([b[4] for b in bars_d])
    hma_d = np.array([x if x is not None else np.nan for x in hma(c_d.tolist(), 200)])
    fires = sweep_hma(bars, hma_d, t_d, bars)

    pmap = match_pivots(bars, load_baseline())
    report("B4C2", "HMA-200 sweep D LIVE", fires, pmap)
    save_fires("B4C2", fires, bars)


if __name__ == "__main__":
    main()
