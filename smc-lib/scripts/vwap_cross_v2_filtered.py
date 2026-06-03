"""VWAP-cross v2 — with noise filters.

Filters:
  MIN_SPREAD_BPS — VWAP-spread at cross >= X bps от mid (избегать шумных пересечений)
  CONFIRM_BARS   — N подряд 4h-close в новом состоянии до entry
  MAX_ANCHOR_AGE_BARS — anchor 4h-fractal не старше N баров на момент entry

Grid over: MIN_SPREAD_BPS ∈ {10, 30, 50, 100}, CONFIRM_BARS ∈ {1, 2, 3},
           MAX_ANCHOR_AGE_BARS ∈ {30, 60, 120, ∞}, RR ∈ {1.0, 1.5, 2.0}.
"""
from __future__ import annotations

import csv
import pathlib
import sys
import time
from datetime import datetime, timezone
import numpy as np
from itertools import product

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from candle import Candle
from elements.fractal.code import detect_fractal

CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MS_HOUR = 3600_000
TF_4H_MS = 4 * MS_HOUR
MAX_HOLD_MIN = 30 * 24 * 60

t0 = time.time()


def load_1m():
    rows = []
    with CSV_PATH.open() as f:
        rd = csv.reader(f); next(rd)
        for r in rd:
            t = datetime.fromisoformat(r[0])
            rows.append((int(t.timestamp() * 1000),
                         float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
    return rows


def aggregate_4h(d):
    out = []; cb = None; o = h = l = c = v = 0.0
    for ts, oo, hh, ll, cc, vv in d:
        b = ts - (ts % TF_4H_MS)
        if b != cb:
            if cb is not None: out.append((cb, o, h, l, c, v))
            cb = b; o, h, l, c, v = oo, hh, ll, cc, vv
        else:
            h = max(h, hh); l = min(l, ll); c = cc; v += vv
    if cb is not None: out.append((cb, o, h, l, c, v))
    return out


print("Loading 1m...")
data = load_1m()
print(f"  {len(data):,} 1m rows ({time.time()-t0:.1f}s)")

ts_arr = np.array([r[0] for r in data], dtype=np.int64)
hi_arr = np.array([r[2] for r in data], dtype=np.float64)
lo_arr = np.array([r[3] for r in data], dtype=np.float64)
cl_arr = np.array([r[4] for r in data], dtype=np.float64)
vol_arr = np.array([r[5] for r in data], dtype=np.float64)
tp_arr = (hi_arr + lo_arr + cl_arr) / 3.0
pv_arr = tp_arr * vol_arr
cum_pv = np.cumsum(pv_arr)
cum_v = np.cumsum(vol_arr)


def vwap_at(anchor_ts, query_ts):
    if query_ts < anchor_ts: return None
    i0 = int(np.searchsorted(ts_arr, anchor_ts, side='left'))
    i1 = int(np.searchsorted(ts_arr, query_ts, side='right')) - 1
    if i1 < i0 or i0 >= len(ts_arr): return None
    pv = cum_pv[i1] - (cum_pv[i0-1] if i0 > 0 else 0)
    vv = cum_v[i1] - (cum_v[i0-1] if i0 > 0 else 0)
    return pv / vv if vv > 0 else None


def idx_at(ms):
    return int(np.searchsorted(ts_arr, ms, side='left'))


bars_4h = aggregate_4h(data)
last_ts = data[-1][0]
window_start_ms = last_ts - 6 * 365 * 24 * 3600 * 1000
bars_4h_idx_start = next(i for i, b in enumerate(bars_4h) if b[0] >= window_start_ms)
print(f"  {len(bars_4h):,} 4h bars; window start idx {bars_4h_idx_start}")

candles_4h = [Candle(open=b[1], high=b[2], low=b[3], close=b[4], open_time=b[0]) for b in bars_4h]

fractals = []
for i in range(2, len(candles_4h) - 2):
    f = detect_fractal(candles_4h[i-2:i+3], n=2)
    if f is None: continue
    fractals.append({
        "dir": f.direction,
        "level": f.level,
        "center_idx": i,
        "anchor_ts": candles_4h[i].open_time,
        "confirm_ts": candles_4h[i].open_time + 3 * TF_4H_MS,
    })
fh_sorted = sorted([f for f in fractals if f["dir"] == "high"], key=lambda x: x["confirm_ts"])
fl_sorted = sorted([f for f in fractals if f["dir"] == "low"], key=lambda x: x["confirm_ts"])
fh_confirm_ts = np.array([f["confirm_ts"] for f in fh_sorted])
fl_confirm_ts = np.array([f["confirm_ts"] for f in fl_sorted])


def active_fractal(sorted_list, sorted_ts, query_ts):
    if len(sorted_ts) == 0: return None
    idx = int(np.searchsorted(sorted_ts, query_ts, side='right')) - 1
    return sorted_list[idx] if idx >= 0 else None


def simulate(trade, rr, max_close_ts=None):
    sk = idx_at(trade["entry_ts"])
    ek = min(sk + MAX_HOLD_MIN, len(data))
    if max_close_ts is not None:
        ek = min(ek, idx_at(max_close_ts))
    side = trade["side"]; entry = trade["entry"]; sl = trade["sl"]
    tp = entry + rr * trade["r_unit"] if side == "long" else entry - rr * trade["r_unit"]
    for k in range(sk, ek):
        h_ = hi_arr[k]; l_ = lo_arr[k]
        if side == "long":
            if l_ <= sl: return {"outcome": "loss", "pnl_R": -1.0,
                                 "hold_min": (int(ts_arr[k]) - trade["entry_ts"]) // 60_000}
            if h_ >= tp: return {"outcome": "win", "pnl_R": rr,
                                 "hold_min": (int(ts_arr[k]) - trade["entry_ts"]) // 60_000}
        else:
            if h_ >= sl: return {"outcome": "loss", "pnl_R": -1.0,
                                 "hold_min": (int(ts_arr[k]) - trade["entry_ts"]) // 60_000}
            if l_ <= tp: return {"outcome": "win", "pnl_R": rr,
                                 "hold_min": (int(ts_arr[k]) - trade["entry_ts"]) // 60_000}
    return None


# === Pre-compute VWAP_FH and VWAP_FL at each 4h close ===
print("Pre-computing VWAP state per 4h bar...")
states = []  # list of (bar_idx, close_ts, close_price, v_fh, v_fl, fh, fl, state)
for bi in range(bars_4h_idx_start, len(bars_4h)):
    b_open, _, _, _, b_close_price, _ = bars_4h[bi]
    bar_close_ts = b_open + TF_4H_MS
    fh = active_fractal(fh_sorted, fh_confirm_ts, bar_close_ts)
    fl = active_fractal(fl_sorted, fl_confirm_ts, bar_close_ts)
    if fh is None or fl is None:
        states.append((bi, bar_close_ts, b_close_price, None, None, fh, fl, None))
        continue
    v_fh = vwap_at(fh["anchor_ts"], bar_close_ts - 60_000)
    v_fl = vwap_at(fl["anchor_ts"], bar_close_ts - 60_000)
    if v_fh is None or v_fl is None:
        states.append((bi, bar_close_ts, b_close_price, None, None, fh, fl, None))
        continue
    state = "BULL" if v_fl > v_fh else "BEAR"
    states.append((bi, bar_close_ts, b_close_price, v_fh, v_fl, fh, fl, state))
print(f"  Done ({time.time()-t0:.1f}s)")


def run_strategy(min_spread_bps, confirm_bars, max_anchor_age_bars, rr, regime_exit=True):
    """Returns list of trades with stats."""
    trades = []
    open_trade = None
    prev_state = None
    confirm_count = 0
    pending_dir = None

    for idx in range(len(states)):
        bi, close_ts, close_price, v_fh, v_fl, fh, fl, state = states[idx]
        if state is None:
            prev_state = None; confirm_count = 0; pending_dir = None
            continue

        # spread в bps от mid
        mid = (v_fh + v_fl) / 2
        spread_bps = abs(v_fl - v_fh) / mid * 10_000 if mid > 0 else 0

        # Manage open trade — regime flip exit
        if open_trade is not None and regime_exit:
            if prev_state is not None and state != open_trade["state_at_entry"]:
                # close at this bar close
                outcome = simulate(open_trade, rr, max_close_ts=close_ts)
                if outcome is None:
                    pnl = ((close_price - open_trade["entry"]) / open_trade["r_unit"]
                           if open_trade["side"] == "long"
                           else (open_trade["entry"] - close_price) / open_trade["r_unit"])
                    trades.append({**open_trade, "outcome": "regime_exit", "pnl_R": pnl})
                else:
                    trades.append({**open_trade, **outcome})
                open_trade = None

        # Detect cross
        if prev_state is not None and state != prev_state:
            confirm_count = 1; pending_dir = state
        elif pending_dir is not None and state == pending_dir:
            confirm_count += 1

        # Trigger entry?
        if (open_trade is None and pending_dir is not None
                and confirm_count >= confirm_bars
                and spread_bps >= min_spread_bps):
            # Check anchor age
            target_fractal = fl if pending_dir == "BULL" else fh  # leading анcor
            opposite_fractal = fh if pending_dir == "BULL" else fl
            anchor_age_bars = bi - target_fractal["center_idx"]
            opp_age_bars = bi - opposite_fractal["center_idx"]
            if max_anchor_age_bars is None or (anchor_age_bars <= max_anchor_age_bars
                                                and opp_age_bars <= max_anchor_age_bars):
                side = "long" if pending_dir == "BULL" else "short"
                entry = close_price
                sl = v_fh if side == "long" else v_fl
                if side == "long":
                    if entry > sl:
                        r_unit = entry - sl
                        open_trade = {"entry_ts": close_ts, "side": side, "entry": entry,
                                      "sl": sl, "r_unit": r_unit, "state_at_entry": state,
                                      "spread_bps": spread_bps, "anchor_age": anchor_age_bars}
                else:
                    if entry < sl:
                        r_unit = sl - entry
                        open_trade = {"entry_ts": close_ts, "side": side, "entry": entry,
                                      "sl": sl, "r_unit": r_unit, "state_at_entry": state,
                                      "spread_bps": spread_bps, "anchor_age": anchor_age_bars}
            pending_dir = None; confirm_count = 0

        prev_state = state

    # Force-close open trade
    if open_trade is not None:
        outcome = simulate(open_trade, rr)
        if outcome is not None:
            trades.append({**open_trade, **outcome})
    return trades


def stats(trades):
    w = sum(1 for t in trades if t["outcome"] == "win")
    l = sum(1 for t in trades if t["outcome"] == "loss")
    re = sum(1 for t in trades if t["outcome"] == "regime_exit")
    sr = sum(t["pnl_R"] for t in trades)
    n = w + l + re
    wr = w / (w + l) * 100 if (w + l) > 0 else 0
    rtr = sr / n if n else 0
    return n, w, l, re, wr, sr, rtr


# === Grid search ===
print("\n" + "=" * 100)
print(" Grid search")
print("=" * 100)

grid_results = []
for min_spread_bps, confirm_bars, max_age, rr in product(
    [0, 10, 30, 50, 100],
    [1, 2, 3],
    [30, 60, 120, 9999],
    [1.0, 1.5, 2.0],
):
    trades = run_strategy(min_spread_bps, confirm_bars, max_age, rr)
    n, w, l, re, wr, sr, rtr = stats(trades)
    if n < 30: continue
    grid_results.append({
        "spread": min_spread_bps, "confirm": confirm_bars, "age": max_age, "rr": rr,
        "n": n, "wr": wr, "sr": sr, "rtr": rtr
    })

# top by ΣR
print("\n--- TOP by ΣR (n>=30) ---")
grid_results.sort(key=lambda x: -x["sr"])
print(f"  {'spread':>7} {'conf':>5} {'age':>5} {'RR':>4}   {'n':>4}  {'WR':>6}  {'ΣR':>7}  {'R/tr':>7}")
for g in grid_results[:20]:
    print(f"  {g['spread']:>7} {g['confirm']:>5} {g['age']:>5} {g['rr']:>4.1f}   "
          f"{g['n']:>4}  {g['wr']:>5.2f}%  {g['sr']:>+6.1f}R  {g['rtr']:>+6.3f}R")

print("\n--- TOP by WR (n>=50) ---")
grid_filt = [g for g in grid_results if g["n"] >= 50]
grid_filt.sort(key=lambda x: -x["wr"])
for g in grid_filt[:15]:
    print(f"  {g['spread']:>7} {g['confirm']:>5} {g['age']:>5} {g['rr']:>4.1f}   "
          f"{g['n']:>4}  {g['wr']:>5.2f}%  {g['sr']:>+6.1f}R  {g['rtr']:>+6.3f}R")

print("\n--- TOP by R/tr (n>=80) ---")
grid_filt2 = [g for g in grid_results if g["n"] >= 80]
grid_filt2.sort(key=lambda x: -x["rtr"])
for g in grid_filt2[:15]:
    print(f"  {g['spread']:>7} {g['confirm']:>5} {g['age']:>5} {g['rr']:>4.1f}   "
          f"{g['n']:>4}  {g['wr']:>5.2f}%  {g['sr']:>+6.1f}R  {g['rtr']:>+6.3f}R")

print(f"\nTotal: {time.time()-t0:.1f}s")
