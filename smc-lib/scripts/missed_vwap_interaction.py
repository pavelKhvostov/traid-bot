"""Check which D-fractal anchored VWAPs interact with the 3 missed pivots.

Missed:
  #14: 2026-03-04 12:00 UTC (FH/short)
  #15: 2026-03-08 12:00 UTC (FL/long)
  #48: 2026-05-06 00:00 UTC (FH/short)

For each missed, compute:
  - VWAP values at pivot bar close, for all D-fractals that are confirmed before
  - Distance from price (high for FH side, low for FL side, close)
  - Sweep check: bar.high > VWAP AND close < VWAP (FH); bar.low < VWAP AND close > VWAP (FL)
  - Confluence: list VWAPs within 0.5%, 1%, 2% from key price levels
"""
from __future__ import annotations
import csv
from pathlib import Path
from datetime import datetime, timezone, timedelta
import numpy as np
import pandas as pd

CSV_PATH = Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
TF_D_MS = 1440 * 60_000
TF_12H_MS = 720 * 60_000
START_MS = int(datetime(2020,1,1,tzinfo=timezone.utc).timestamp() * 1000)
MSK = timezone(timedelta(hours=3))

MISSED = [
    ("#14", datetime(2026, 3, 4, 12, 0, tzinfo=timezone.utc), "FH/short"),
    ("#15", datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc), "FL/long"),
    ("#48", datetime(2026, 5, 6, 0, 0, tzinfo=timezone.utc), "FH/short"),
]

print("[1/4] Loading 1m...")
rows = []
with CSV_PATH.open() as f:
    rd = csv.reader(f); next(rd)
    for r in rd:
        ts = int(datetime.fromisoformat(r[0]).timestamp() * 1000)
        if ts < START_MS - 5*TF_D_MS: continue
        rows.append((ts, float(r[2]), float(r[3]), float(r[4]), float(r[5])))  # ts, h, l, c, v
print(f"  {len(rows):,} 1m bars")
ts_arr = np.array([r[0] for r in rows], dtype=np.int64)
hi_arr = np.array([r[1] for r in rows])
lo_arr = np.array([r[2] for r in rows])
cl_arr = np.array([r[3] for r in rows])
vo_arr = np.array([r[4] for r in rows])

# Aggregate D
print("[2/4] Aggregating D + detecting Williams N=2 fractals...")
def agg(rs, tf_ms):
    out = []; cb = None; o=h=l=c=v=0.0
    for ts, hh, ll, cc, vv in rs:
        b = ts - (ts % tf_ms)
        if b != cb:
            if cb is not None: out.append((cb, h, l, c, v))
            cb = b; h, l, c, v = hh, ll, cc, vv
        else:
            h = max(h, hh); l = min(l, ll); c = cc; v += vv
    if cb is not None: out.append((cb, h, l, c, v))
    return out
barsD = [b for b in agg([(t, h, l, c, v) for t,h,l,c,v in zip(ts_arr, hi_arr, lo_arr, cl_arr, vo_arr)], TF_D_MS) if b[0] >= START_MS]

# Williams N=2 detect fractals
N = 2
fractals = []  # (ts_D_open, ready_ms, side, level)
for i in range(N, len(barsD) - N):
    h_i = barsD[i][1]; l_i = barsD[i][2]
    if all(h_i > barsD[i+j][1] for j in [-2,-1,1,2]):
        ready_ms = barsD[i+N][0] + TF_D_MS  # confirmed after 2 bars right
        fractals.append({"ts": barsD[i][0], "ready": ready_ms, "side": "FH", "level": h_i})
    if all(l_i < barsD[i+j][2] for j in [-2,-1,1,2]):
        ready_ms = barsD[i+N][0] + TF_D_MS
        fractals.append({"ts": barsD[i][0], "ready": ready_ms, "side": "FL", "level": l_i})
print(f"  Fractals: {len(fractals)} ({sum(1 for f in fractals if f['side']=='FH')} FH / {sum(1 for f in fractals if f['side']=='FL')} FL)")

# Build cumulative pv, vol for fast VWAP computation
print("[3/4] Computing cumulative pv/vol for VWAP...")
pv_cum = np.cumsum(cl_arr * vo_arr)
vol_cum = np.cumsum(vo_arr)

def vwap_at(anchor_ts: int, query_ts: int) -> float:
    """VWAP from anchor_ts to query_ts."""
    i_a = int(np.searchsorted(ts_arr, anchor_ts, side='left'))
    i_q = int(np.searchsorted(ts_arr, query_ts, side='right')) - 1
    if i_a > i_q: return None
    pv = pv_cum[i_q] - (pv_cum[i_a-1] if i_a > 0 else 0)
    v  = vol_cum[i_q] - (vol_cum[i_a-1] if i_a > 0 else 0)
    return pv / v if v > 0 else None

# === [4/4] For each missed, analyze VWAP interactions ===
print(f"\n[4/4] Per-missed VWAP analysis:")
print(f"{'='*80}")

for tag, dt_close, label in MISSED:
    bar_close_ms = int(dt_close.timestamp() * 1000)
    bar_open_ms = bar_close_ms - TF_12H_MS  # 12h bar opens 12h before close

    # Get 12h bar OHLC
    i_start = int(np.searchsorted(ts_arr, bar_open_ms))
    i_end = int(np.searchsorted(ts_arr, bar_close_ms))
    if i_end > i_start:
        bar_high = hi_arr[i_start:i_end].max()
        bar_low = lo_arr[i_start:i_end].min()
        bar_close = cl_arr[i_end-1]
    else:
        bar_high = bar_low = bar_close = 0

    dt_msk = dt_close.astimezone(MSK)
    print(f"\n{tag}: {dt_msk.strftime('%Y-%m-%d %H:%M MSK')} ({label})")
    print(f"  12h bar: H={bar_high:.0f} L={bar_low:.0f} C={bar_close:.0f}")

    # Filter fractals: only those confirmed BEFORE this bar
    side_match = "FH" if "FH" in label else "FL"
    # Direction-matched: FH pivot → SHORT zone test → VWAP from FH (descending magnet from prior top)
    # FL pivot → LONG zone test → VWAP from FL
    relevant = [f for f in fractals if f["side"] == side_match and f["ready"] <= bar_open_ms]
    print(f"  Relevant {side_match} fractals (ready before bar): {len(relevant)}")

    # Compute VWAP for each
    results = []
    for f in relevant:
        v = vwap_at(f["ts"], bar_close_ms)
        if v is None: continue
        # Sweep check
        if side_match == "FH":
            # short-side sweep: high > VWAP AND close < VWAP
            swept = bar_high > v and bar_close < v
            wick_dist_pct = (bar_high - v) / v * 100  # positive if wick above VWAP
        else:
            # long-side sweep: low < VWAP AND close > VWAP
            swept = bar_low < v and bar_close > v
            wick_dist_pct = (v - bar_low) / v * 100  # positive if wick below VWAP
        dist_close_pct = abs(bar_close - v) / v * 100
        results.append({
            "anchor": datetime.fromtimestamp(f["ts"]/1000, tz=timezone.utc).strftime("%Y-%m-%d"),
            "side": f["side"],
            "vwap": v,
            "level": f["level"],
            "dist_close_pct": dist_close_pct,
            "wick_dist_pct": wick_dist_pct,
            "swept": swept,
        })

    df = pd.DataFrame(results).sort_values("dist_close_pct")

    # Swept VWAPs (these are the C8 candidates)
    swept = df[df["swept"] == True]
    print(f"\n  ★ Swept VWAPs (high>VWAP AND close<VWAP for FH; mirror for FL): {len(swept)}")
    if len(swept):
        for _, r in swept.head(10).iterrows():
            print(f"    {r['side']} anchor {r['anchor']}  VWAP={r['vwap']:.0f}  dist_close={r['dist_close_pct']:.2f}%  wick_above={r['wick_dist_pct']:.2f}%")
    else:
        print(f"    ✗ NONE")

    # Near VWAPs (within 1% of close, regardless of sweep)
    near = df[df["dist_close_pct"] <= 1.0]
    print(f"\n  Within 1% of close: {len(near)}")
    for _, r in near.head(8).iterrows():
        flag = "★" if r["swept"] else " "
        side_pos = "above" if r["vwap"] > bar_close else "below"
        print(f"    {flag} VWAP={r['vwap']:.0f}  {side_pos}  dist={r['dist_close_pct']:.2f}%  anchor {r['anchor']}")

    # Wider 2%
    in2 = df[df["dist_close_pct"] <= 2.0]
    print(f"\n  Within 2% of close: {len(in2)}")

    # Within wick range
    in_wick_h = df[df["vwap"].between(bar_low, bar_high)]
    print(f"  Inside 12h bar wick range [{bar_low:.0f}, {bar_high:.0f}]: {len(in_wick_h)}")
    for _, r in in_wick_h.head(5).iterrows():
        flag = "★" if r["swept"] else " "
        print(f"    {flag} VWAP={r['vwap']:.0f}  anchor {r['anchor']}")
