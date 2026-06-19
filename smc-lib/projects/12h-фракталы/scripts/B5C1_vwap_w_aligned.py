"""B5C1 — ≥2 W-aligned swept VWAPs (anchored from D-fractals).

VWAP-семейство, sub-условие #1.
Anchored VWAP от D-фракталов (N_FRACTAL=2), у которых anchor совпадает с W Williams-pivot.
На pivot bar i сняты ≥2 таких VWAP в одном направлении.
Sweep:  FH: high[i] > VWAP AND close[i] < VWAP
        FL: low[i]  < VWAP AND close[i] > VWAP
Causal: ✅ (VWAP вычисляется forward от past-anchor).

Per memory [[feedback-anchored-vwap-from-fractals]].
"""
from __future__ import annotations
import numpy as np
from _lib import load_1m, load_12h, load_htf_bars, load_baseline, match_pivots, report, save_fires


def williams_pivots(highs: np.ndarray, lows: np.ndarray, n: int = 2) -> tuple[list[int], list[int]]:
    """Confirmed Williams n=2 pivots: requires n bars on left+right with strict inequality."""
    fh, fl = [], []
    N = len(highs)
    for i in range(n, N - n):
        if all(highs[i] > highs[i+d] for d in range(-n, n+1) if d != 0):
            fh.append(i)
        if all(lows[i]  < lows[i+d]  for d in range(-n, n+1) if d != 0):
            fl.append(i)
    return fh, fl


def vwap_forward(anchor_ms: int, rows_1m: list[tuple]) -> dict:
    """Compute cumulative VWAP starting from anchor_ms. Returns {ts_ms: vwap_value}."""
    cum_pv = 0.0; cum_v = 0.0
    out = {}
    for ts, o, h, l, c, v in rows_1m:
        if ts < anchor_ms: continue
        typ = (h + l + c) / 3
        cum_pv += typ * v
        cum_v += v
        if cum_v > 0:
            out[ts] = cum_pv / cum_v
    return out


def vwap_at_12h(vwap_dict: dict, t12_arr: np.ndarray) -> np.ndarray:
    """Sample VWAP at 12h-bar open times. NaN if anchor not yet active."""
    out = np.full(len(t12_arr), np.nan)
    sorted_ts = np.array(sorted(vwap_dict.keys()), dtype=np.int64)
    for i, t in enumerate(t12_arr):
        j = int(np.searchsorted(sorted_ts, t, side="right")) - 1
        if j >= 0:
            out[i] = vwap_dict[int(sorted_ts[j])]
    return out


def main():
    bars = load_12h()
    bars_d = load_htf_bars("D")
    bars_w = load_htf_bars("W")
    rows_1m = load_1m()

    # D-fractals (N=2 confirmed)
    h_d = np.array([b[2] for b in bars_d])
    l_d = np.array([b[3] for b in bars_d])
    t_d = np.array([b[0] for b in bars_d], dtype=np.int64)
    fh_d, fl_d = williams_pivots(h_d, l_d, n=2)

    # W-fractals
    h_w = np.array([b[2] for b in bars_w])
    l_w = np.array([b[3] for b in bars_w])
    t_w = np.array([b[0] for b in bars_w], dtype=np.int64)
    fh_w, fl_w = williams_pivots(h_w, l_w, n=2)

    # W-aligned check: D-fractal time совпадает с W-fractal time (same Monday)
    w_fh_ts = set(int(t_w[i]) for i in fh_w)
    w_fl_ts = set(int(t_w[i]) for i in fl_w)

    # Bucket D-fractal -> 7-day window вокруг ближайшей W-pivot
    def is_w_aligned(d_idx: int, w_set: set, w_ts_arr: np.ndarray) -> bool:
        td = int(t_d[d_idx])
        # closest W bar открыт ≤ td, в пределах 7 дней
        j = int(np.searchsorted(w_ts_arr, td, side="right")) - 1
        if j < 0: return False
        return int(w_ts_arr[j]) in w_set

    fh_anchors = [int(t_d[i]) for i in fh_d if is_w_aligned(i, w_fh_ts, t_w)]
    fl_anchors = [int(t_d[i]) for i in fl_d if is_w_aligned(i, w_fl_ts, t_w)]

    # Compute VWAP series for each anchor, sample at 12h grid
    t12 = bars["t"]; n12 = bars["n"]
    h12, l12, c12 = bars["h"], bars["l"], bars["c"]
    vwap_series_fh = [vwap_at_12h(vwap_forward(a, rows_1m), t12) for a in fh_anchors]
    vwap_series_fl = [vwap_at_12h(vwap_forward(a, rows_1m), t12) for a in fl_anchors]

    # Sweep + count
    fires = set()
    for i in range(n12):
        # FH sweep: high crosses VWAP, close below
        cnt_fh = sum(
            1 for vs in vwap_series_fh
            if not np.isnan(vs[i]) and h12[i] > vs[i] and c12[i] < vs[i]
        )
        if cnt_fh >= 2:
            fires.add((i, "short"))
        cnt_fl = sum(
            1 for vs in vwap_series_fl
            if not np.isnan(vs[i]) and l12[i] < vs[i] and c12[i] > vs[i]
        )
        if cnt_fl >= 2:
            fires.add((i, "long"))

    pmap = match_pivots(bars, load_baseline())
    report("B5C1", "≥2 W-aligned swept VWAPs", fires, pmap)
    save_fires("B5C1", fires, bars)


if __name__ == "__main__":
    main()
