"""B3C1 — maxV sweep (i-1).

Fractal Liquidity sub-condition #1. На 12h-баре i снят maxV-уровень бара i-1.
maxV = close 1m-свечи с максимальным dirVolume (bull/bear winner) внутри родительского 12h.
Causal: ✅ (maxV считается на i-1 — past).

Per memory [[maxv-force-model-5-conditions]] и [[feedback-vic-maxv-absolute-not-sided]].
"""
from __future__ import annotations
import numpy as np
from _lib import load_1m, load_12h, TF12, load_baseline, match_pivots, report, save_fires


def compute_maxv(rows: list[tuple], bars12: dict) -> np.ndarray:
    """maxV[i] = close 1m-свечи с max(bullVol, bearVol) внутри 12h(i). NaN если нет."""
    t12 = bars12["t"]; n12 = bars12["n"]
    maxv = np.full(n12, np.nan)
    # 1m bars индексированы по time; bucket по 12h:
    ts1m = np.array([r[0] for r in rows], dtype=np.int64)
    o1m = np.array([r[1] for r in rows])
    c1m = np.array([r[4] for r in rows])
    v1m = np.array([r[5] for r in rows])

    for i in range(n12):
        t_start = t12[i]
        t_end = t_start + TF12
        lo = int(np.searchsorted(ts1m, t_start, side="left"))
        hi = int(np.searchsorted(ts1m, t_end, side="left"))
        if hi <= lo: continue
        # dirVolume: bull = vol if close > open else 0; bear = vol if close < open else 0
        bull_v = np.where(c1m[lo:hi] > o1m[lo:hi], v1m[lo:hi], 0)
        bear_v = np.where(c1m[lo:hi] < o1m[lo:hi], v1m[lo:hi], 0)
        winner = np.maximum(bull_v, bear_v)
        if winner.max() <= 0: continue
        argmax = int(np.argmax(winner))
        maxv[i] = c1m[lo + argmax]
    return maxv


def main():
    bars = load_12h()
    rows = load_1m()
    maxv = compute_maxv(rows, bars)
    n12 = bars["n"]
    h12, l12, c12 = bars["h"], bars["l"], bars["c"]

    fires = set()
    for i in range(1, n12):
        mv = maxv[i-1]
        if np.isnan(mv): continue
        # FH sweep (short zone fires): high[i] > maxV AND close[i] < maxV
        if h12[i] > mv and c12[i] < mv:
            fires.add((i, "short"))
        # FL sweep (long zone fires): low[i] < maxV AND close[i] > maxV
        if l12[i] < mv and c12[i] > mv:
            fires.add((i, "long"))

    pmap = match_pivots(bars, load_baseline())
    report("B3C1", "maxV sweep (i-1)", fires, pmap)
    save_fires("B3C1", fires, bars)


if __name__ == "__main__":
    main()
