"""Phase 0 — Regenerate D-only touches without lookahead.

Канон:
- Источник events: maxV_master_6m.parquet → filter TF=D (182 events)
- Touch anchor: ТОЛЬКО после parent_D_close (= formed_ts + 24h)
- Force: Gaussian σ = R/2, где R = max(L−zone_lo, zone_hi−L)
- TBM (Lopez de Prado Ch 3.4): PT=1.5×ATR(20), SL=1.0×ATR(20), t1=12 D-bars
- Sample weights: 1/n_concurrent_labels (Ch 4)
- Output: maxv_touches_D_clean.parquet
"""
from __future__ import annotations
import math, csv
from pathlib import Path
from datetime import datetime, timezone, timedelta
import numpy as np
import pandas as pd

MS_M = 60_000
TF_D_MS = 1440 * MS_M
ATR_N = 20
PT_ATR = 1.5
SL_ATR = 1.0
T1_BARS = 12
CSV_PATH = Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"

# === Load existing events, filter D ===
print("[1/5] Loading existing master events (D only)...")
df_events = pd.read_parquet(Path.home() / "Desktop/maxv_master_6m.parquet")
df_d = df_events[df_events["tf"] == "D"].copy().reset_index(drop=True)
print(f"  D events: {len(df_d)}")
print(f"  date range: {datetime.fromtimestamp(df_d['formed_ts'].min()/1000)} .. "
      f"{datetime.fromtimestamp(df_d['formed_ts'].max()/1000)}")

# === Load 1m bars covering events + t1 window ===
print("\n[2/5] Loading 1m bars...")
min_ts = int(df_d["formed_ts"].min()) - TF_D_MS  # for ATR lookback
max_ts = int(df_d["formed_ts"].max()) + TF_D_MS * (T1_BARS + 5)

rows = []
with CSV_PATH.open() as f:
    rd = csv.reader(f); next(rd)
    for r in rd:
        t = datetime.fromisoformat(r[0])
        ts = int(t.timestamp() * 1000)
        if ts < min_ts: continue
        if ts >= max_ts: break
        rows.append((ts, float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
print(f"  {len(rows):,} 1m bars")

# === Aggregate D ===
def agg_d(rs):
    out = []; cb = None; o=h=l=c=0.0; v=0.0
    for ts, oo, hh, ll, cc, vv in rs:
        b = ts - (ts % TF_D_MS)  # epoch anchor — for D = UTC midnight
        if b != cb:
            if cb is not None: out.append((cb,o,h,l,c,v))
            cb=b; o,h,l,c,v=oo,hh,ll,cc,vv
        else:
            h=max(h,hh); l=min(l,ll); c=cc; v+=vv
    if cb is not None: out.append((cb,o,h,l,c,v))
    return out

bars_d = agg_d(rows)
print(f"  D bars: {len(bars_d)}")

# ATR(20) rolling
def compute_atr(bars_d, n=ATR_N):
    atrs = []
    trs = []
    for i, b in enumerate(bars_d):
        if i == 0:
            trs.append(b[2] - b[3])
        else:
            pc = bars_d[i-1][4]
            trs.append(max(b[2]-b[3], abs(b[2]-pc), abs(b[3]-pc)))
        lo = max(0, i - n + 1)
        atrs.append(sum(trs[lo:i+1]) / (i - lo + 1) if i > 0 else trs[0])
    return atrs

atrs = compute_atr(bars_d)
d_idx_by_start = {b[0]: i for i, b in enumerate(bars_d)}

# === For each D event: find first touch + TBM exit ===
print(f"\n[3/5] Compute touches with parent_close anchor + TBM (PT={PT_ATR}×ATR, SL={SL_ATR}×ATR, t1={T1_BARS}D)...")

ts_arr = np.array([r[0] for r in rows], dtype=np.int64)
hi_arr = np.array([r[2] for r in rows], dtype=np.float64)
lo_arr = np.array([r[3] for r in rows], dtype=np.float64)
cl_arr = np.array([r[4] for r in rows], dtype=np.float64)

def find_first_touch(level, start_ts):
    """First 1m bar with low <= level <= high after start_ts."""
    i = int(np.searchsorted(ts_arr, start_ts, side='left'))
    while i < len(ts_arr):
        if lo_arr[i] <= level <= hi_arr[i]:
            return i
        i += 1
    return None

def apply_tbm(touch_idx, level, side, atr_val, t1_ts):
    """side: 'long' = expect bounce up (lower_wick/body_bottom anchor);
            'short' = expect rejection down (upper_wick/body_top)."""
    pt_dist = PT_ATR * atr_val
    sl_dist = SL_ATR * atr_val
    if side == "long":
        pt = level + pt_dist
        sl = level - sl_dist
    else:
        pt = level - pt_dist
        sl = level + sl_dist
    i = touch_idx
    while i < len(ts_arr) and ts_arr[i] < t1_ts:
        h, l = hi_arr[i], lo_arr[i]
        if side == "long":
            if h >= pt: return (+1, ts_arr[i], pt)
            if l <= sl: return (-1, ts_arr[i], sl)
        else:
            if l <= pt: return (+1, ts_arr[i], pt)
            if h >= sl: return (-1, ts_arr[i], sl)
        i += 1
    # t1 vertical: 0 timeout
    if i < len(ts_arr):
        return (0, ts_arr[i], cl_arr[i])
    return (0, t1_ts, cl_arr[-1])

touches = []
for _, e in df_d.iterrows():
    formed_ts = int(e["formed_ts"])
    L = float(e["level"])
    zlo, zhi = float(e["zone_lo"]), float(e["zone_hi"])
    pos = e["position"]
    parent_close = formed_ts + TF_D_MS

    # Touch search starts ONLY after parent close
    touch_idx = find_first_touch(L, parent_close)
    if touch_idx is None: continue
    touch_ts = int(ts_arr[touch_idx])
    touch_price = float(cl_arr[touch_idx])

    # TBM
    d_idx = d_idx_by_start.get(formed_ts)
    if d_idx is None: continue
    atr_val = atrs[d_idx]
    if atr_val <= 0: continue
    side = "long" if pos in ("lower_wick", "body_bottom") else "short"
    t1_ts = touch_ts + T1_BARS * TF_D_MS
    label, exit_ts, exit_price = apply_tbm(touch_idx, L, side, atr_val, t1_ts)

    # Gaussian force at touch_price
    R = max(L - zlo, zhi - L)
    sigma = R / 2 if R > 0 else 1.0
    delta = abs(touch_price - L)
    force_g = math.exp(-((delta / sigma) ** 2))

    # Age at touch (bars)
    n_bars_since_formed = (touch_ts - parent_close) // TF_D_MS

    touches.append({
        "tf": "D",
        "formed_ts": formed_ts,
        "parent_close_ts": parent_close,
        "level": L,
        "zone_lo": zlo, "zone_hi": zhi,
        "R": R,
        "touch_ts": touch_ts,
        "touch_price": touch_price,
        "force_gauss": force_g,
        "side": side,
        "label": label,
        "exit_ts": exit_ts,
        "exit_price": exit_price,
        "holding_min": (exit_ts - touch_ts) / 60_000,
        "atr_at_formed": atr_val,
        "pt_dist": PT_ATR * atr_val,
        "sl_dist": SL_ATR * atr_val,
        "n_bars_age_at_touch": n_bars_since_formed,
        "position": pos,
        "parent_color": e["parent_color"],
        "session": e.get("session", None),
    })

df_touches = pd.DataFrame(touches)
print(f"  Touches generated: {len(df_touches)}")

# === Concurrent labels for sample weights (Lopez de Prado Ch 4) ===
print(f"\n[4/5] Compute concurrent labels + uniqueness sample weights...")
# For each touch i, count how many other touches overlap [touch_ts_i, exit_ts_i]
intervals = df_touches[["touch_ts", "exit_ts"]].values
n = len(intervals)
n_conc = np.ones(n, dtype=np.float64)
# Naive O(n²) — fine for n~150
for i in range(n):
    ti_start, ti_end = intervals[i]
    cnt = 0
    for j in range(n):
        if j == i: continue
        tj_start, tj_end = intervals[j]
        if not (tj_end < ti_start or tj_start > ti_end):
            cnt += 1
    n_conc[i] = cnt + 1
df_touches["n_concurrent"] = n_conc
df_touches["sample_weight"] = 1.0 / df_touches["n_concurrent"]

# === Label distribution ===
print(f"\n[5/5] Summary:")
print(f"  Label distribution:")
print(df_touches["label"].value_counts(dropna=False).sort_index())
p1 = (df_touches["label"] == 1).mean()
pm = (df_touches["label"] == -1).mean()
p0 = (df_touches["label"] == 0).mean()
print(f"  P(+1) = {p1*100:.1f}%   P(-1) = {pm*100:.1f}%   P( 0) = {p0*100:.1f}%")

print(f"\n  Holding time stats:")
print(f"    median: {df_touches['holding_min'].median():.0f} min "
      f"({df_touches['holding_min'].median()/60:.1f} h)")
print(f"    p90:    {df_touches['holding_min'].quantile(0.9):.0f} min")

print(f"\n  Concurrent labels:")
print(f"    median: {df_touches['n_concurrent'].median():.0f}")
print(f"    max:    {df_touches['n_concurrent'].max():.0f}")
print(f"    weight median: {df_touches['sample_weight'].median():.3f}")

print(f"\n  Force_gauss stats:")
print(f"    min: {df_touches['force_gauss'].min():.3f}")
print(f"    median: {df_touches['force_gauss'].median():.3f}")
print(f"    max: {df_touches['force_gauss'].max():.3f}")

# Save
out = Path.home() / "Desktop" / "maxv_touches_D_clean.parquet"
df_touches.to_parquet(out, index=False)
print(f"\n→ Saved: {out}")
print(f"\n  Columns: {list(df_touches.columns)}")
