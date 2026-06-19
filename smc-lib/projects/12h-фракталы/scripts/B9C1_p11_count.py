"""B9C1 — P11_count 4-window OR-basket (15m direction-matched).

Others sub-condition.
P11_count = доля 15m-свечей внутри окна N×15m перед close(i), направленных ПРОТИВ pivot:
    FH: count(close < open)
    FL: count(close > open)
    P11_N = count / N

OR-union из 4 порогов:
    P11_8x15m  ≥ 0.65   (2h окно)
    P11_12x15m ≥ 0.75   (3h окно)
    P11_16x15m ≥ 0.65   (4h окно)
    P11_24x15m ≥ 0.65   (6h окно)

Causal: ✅ (окно полностью внутри 12h бара i).
"""
from __future__ import annotations
import numpy as np
from _lib import load_1m, load_12h, TF12, MS_M, load_baseline, match_pivots, report, save_fires


THRESHOLDS = [(8, 0.65), (12, 0.75), (16, 0.65), (24, 0.65)]


def aggregate_15m(rows_slice: list[tuple]) -> list[tuple]:
    """Aggregate 1m subset to 15m: (ts, o, h, l, c, v)."""
    out = []; cb = None; o = h = l = c = v = 0.0
    TF15 = 15 * MS_M
    for ts, oo, hh, ll, cc, vv in rows_slice:
        b = ts - (ts % TF15)
        if b != cb:
            if cb is not None: out.append((cb, o, h, l, c, v))
            cb = b; o, h, l, c, v = oo, hh, ll, cc, vv
        else:
            h = max(h, hh); l = min(l, ll); c = cc; v += vv
    if cb is not None: out.append((cb, o, h, l, c, v))
    return out


def main():
    bars = load_12h()
    rows = load_1m()
    ts1m = np.array([r[0] for r in rows], dtype=np.int64)
    t12 = bars["t"]; n12 = bars["n"]

    fires = set()
    for i in range(n12):
        pt_end = int(t12[i] + TF12)  # close (= open i+1)
        i_hi = int(np.searchsorted(ts1m, pt_end, side="left"))

        for N, threshold in THRESHOLDS:
            cut_ms = pt_end - N * 15 * MS_M
            i_lo = int(np.searchsorted(ts1m, cut_ms, side="left"))
            if i_lo >= i_hi: continue
            sub_15m = aggregate_15m(rows[i_lo:i_hi])
            if not sub_15m: continue
            # Bearish for FH (short zone): close < open
            cnt_short = sum(1 for b in sub_15m if b[4] < b[1])
            p_short = cnt_short / len(sub_15m)
            if p_short >= threshold:
                fires.add((i, "short"))
            # Bullish for FL (long zone)
            cnt_long = sum(1 for b in sub_15m if b[4] > b[1])
            p_long = cnt_long / len(sub_15m)
            if p_long >= threshold:
                fires.add((i, "long"))

    pmap = match_pivots(bars, load_baseline())
    report("B9C1", "P11_count 4-window OR", fires, pmap)
    save_fires("B9C1", fires, bars)


if __name__ == "__main__":
    main()
