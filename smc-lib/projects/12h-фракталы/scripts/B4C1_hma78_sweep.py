"""B4C1 — HMA-78 sweep (12h ∪ D), LIVE value.

HMA-семейство, sub-условие #1.
LIVE = HMA-value на close предыдущего бара (как displayed на live-чарте).
Sweep на pivot bar i: wick проходит через HMA(i-1), close на противоположной стороне.
Union: 12h ИЛИ D.
Causal: ✅ (HMA past-only weighted MA).

Per memory [[feedback-trendline-hma-78-200-default]].
"""
from __future__ import annotations
import numpy as np
import sys, pathlib
sys.path.insert(0, str(pathlib.Path.home() / "smc-lib"))
from indicators.trend_line_asvk import hma
from _lib import load_12h, load_htf_bars, load_baseline, match_pivots, report, save_fires


def sweep_hma(bars: dict, hma_arr: np.ndarray, t_arr: np.ndarray, bars_self: dict) -> set:
    """Применить HMA-sweep к 12h pivot bar i. hma_arr — HMA values, t_arr — соответствующие timestamps.

    Для каждого 12h bar i находим LIVE HMA value (close предыдущего родительского бара ≤ i).
    Sweep:  FH (short): high[i] crosses HMA, close[i] на противоположной стороне
            FL (long):  low[i] crosses HMA mirror
    """
    t12 = bars["t"]; n12 = bars["n"]
    h12, l12, c12 = bars["h"], bars["l"], bars["c"]
    fires = set()
    for i in range(n12):
        # Live HMA = value at bar j where t_arr[j] <= open bar i (последний завершённый родительский)
        j = int(np.searchsorted(t_arr, t12[i], side="right")) - 2
        if j < 0 or j >= len(hma_arr): continue
        v = hma_arr[j]
        if np.isnan(v): continue
        # FH: high crosses HMA from below, close back below
        if l12[i] < v < h12[i]:
            if c12[i] < v:
                fires.add((i, "short"))
            elif c12[i] > v:
                fires.add((i, "long"))
    return fires


def main():
    bars = load_12h()
    # 12h HMA-78
    hma12 = np.array([x if x is not None else np.nan for x in hma(bars["c"].tolist(), 78)])
    fires = sweep_hma(bars, hma12, bars["t"], bars)
    # D HMA-78
    bars_d = load_htf_bars("D")
    t_d = np.array([b[0] for b in bars_d], dtype=np.int64)
    c_d = np.array([b[4] for b in bars_d])
    hma_d = np.array([x if x is not None else np.nan for x in hma(c_d.tolist(), 78)])
    fires |= sweep_hma(bars, hma_d, t_d, bars)

    pmap = match_pivots(bars, load_baseline())
    report("B4C1", "HMA-78 sweep (12h ∪ D) LIVE", fires, pmap)
    save_fires("B4C1", fires, bars)


if __name__ == "__main__":
    main()
