"""Stratify C4 (FVG 50% sweep multi-TF) — найти которые подусловия дают P(W) > 70%.

Current C4: ANY FVG on {12h, D, 2D, 3D, W} has FIRST 50%-sweep at pivot → c4=True
Precision: 59.4% / 180 fires / 73 fails (worst condition)

Strategies tested:
1. Stratify by FVG TF — какая TF самая reliable?
2. FVG age (bars between FVG c3 and pivot) — свежие vs старые?
3. FVG width (relative to ATR) — узкие vs широкие?
4. FVG direction-match with HMA-78 — sweep против тренда vs по тренду?

Output: precision table per stratum.
"""
from __future__ import annotations
import csv, math, pathlib, sys
from datetime import datetime, timezone, timedelta
import numpy as np

sys.path.insert(0, str(pathlib.Path.home() / "smc-lib"))
from candle import Candle
from elements.fvg.code import detect_fvg
from elements.fractal.code import detect_fractal

CSV = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MSK = timezone(timedelta(hours=3))
MS_M = 60_000
TF12 = 12 * 60 * MS_M
TFD = 24 * 60 * MS_M
TF2D = 2 * TFD
TF3D = 3 * TFD
TFW = 7 * TFD
MON_ANCHOR = int(datetime(2017, 1, 2, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
START = int(datetime(2020, 5, 27, 0, 0, tzinfo=MSK).timestamp() * 1000)

print("Loading 1m...")
rows = []
with CSV.open() as f:
    rd = csv.reader(f); next(rd)
    for r in rd:
        t = datetime.fromisoformat(r[0])
        rows.append((int(t.timestamp() * 1000), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
print(f"  {len(rows):,} 1m bars")


def agg(d, tfms, anchor=0):
    out = []; cb = None; o = h = l = c = 0.0; v = 0.0
    for ts, oo, hh, ll, cc, vv in d:
        b = ts - ((ts - anchor) % tfms)
        if b != cb:
            if cb is not None: out.append((cb, o, h, l, c, v))
            cb = b; o, h, l, c, v = oo, hh, ll, cc, vv
        else:
            h = max(h, hh); l = min(l, ll); c = cc; v += vv
    if cb is not None: out.append((cb, o, h, l, c, v))
    return out


bars12 = agg(rows, TF12)
n12 = len(bars12)
t12 = np.array([b[0] for b in bars12], dtype=np.int64)
o12 = np.array([b[1] for b in bars12]); h12 = np.array([b[2] for b in bars12])
l12 = np.array([b[3] for b in bars12]); c12 = np.array([b[4] for b in bars12])

bars_by_tf = {"12h": bars12, "D": agg(rows, TFD), "2D": agg(rows, TF2D),
              "3D": agg(rows, TF3D), "W": agg(rows, TFW, MON_ANCHOR)}
cans_by_tf = {tf: [Candle(open=b[1], high=b[2], low=b[3], close=b[4], open_time=b[0]) for b in bb]
              for tf, bb in bars_by_tf.items()}
tfms_map = {"12h": TF12, "D": TFD, "2D": TF2D, "3D": TF3D, "W": TFW}


# === FVG enumeration with tracking ===
print("Scanning FVGs...")
all_fvg = []
for tf, cans in cans_by_tf.items():
    tfms = tfms_map[tf]
    for i in range(len(cans) - 2):
        fv = detect_fvg(cans[i], cans[i + 1], cans[i + 2])
        if fv is None: continue
        ready = cans[i + 2].open_time + tfms
        all_fvg.append({
            "tf": tf, "direction": fv.direction,
            "zone_lo": fv.zone[0], "zone_hi": fv.zone[1],
            "c3_ms": cans[i + 2].open_time,
            "ready_ms": ready,
            "width": fv.zone[1] - fv.zone[0],
        })
print(f"  Total FVGs: {len(all_fvg)}")


# First-50% sweep on 12h
def fvg_first_50sweep_idx(z):
    sp = int(np.searchsorted(t12, z["ready_ms"], side='left'))
    if sp >= n12: return None
    zlo, zhi = z["zone_lo"], z["zone_hi"]
    mid = (zlo + zhi) / 2
    for k in range(sp, n12):
        if z["direction"] == "short":
            if h12[k] >= mid and c12[k] < zlo: return k
        else:
            if l12[k] <= mid and c12[k] > zhi: return k
    return None


print("Computing first-50%-sweep for each FVG...")
for z in all_fvg:
    z["fs50_idx"] = fvg_first_50sweep_idx(z)
print(f"  Swept FVGs: {sum(1 for z in all_fvg if z['fs50_idx'] is not None)}")


# === Williams fractals on 12h ===
candles_12 = [Candle(open=b[1], high=b[2], low=b[3], close=b[4], open_time=b[0]) for b in bars12]
pivots = {}
for i in range(2, n12 - 2):
    fr = detect_fractal(candles_12[i - 2:i + 3], n=2)
    if fr is not None and bars12[i][0] >= START:
        pivots[i] = {"direction": fr.direction, "open_ms": bars12[i][0]}
print(f"Williams 12h pivots (post-2020-05-27): {len(pivots)}")


# === ATR(14) on 12h ===
def atr(highs, lows, closes, n=14):
    tr = np.zeros(len(highs))
    for i in range(1, len(highs)):
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
    out = np.zeros(len(highs))
    for i in range(n, len(highs)):
        out[i] = tr[i - n + 1:i + 1].mean()
    return out


atr12 = atr(h12, l12, c12, 14)


# === HMA-78 on 12h for direction filter ===
def wma(values, n):
    out = [None] * len(values)
    if n > len(values): return out
    w = np.arange(1, n + 1, dtype=float); s = w.sum()
    arr = np.array(values, dtype=float)
    for i in range(n - 1, len(values)):
        out[i] = float((arr[i - n + 1:i + 1] * w).sum() / s)
    return out


def hma(values, n):
    half = wma(values, n // 2); full = wma(values, n)
    diff = [(2 * half[i] - full[i]) if (half[i] is not None and full[i] is not None) else 0.0 for i in range(len(values))]
    sqrt_n = int(round(math.sqrt(n)))
    return wma(diff, sqrt_n)


hma78_12 = hma(c12.tolist(), 78)


# === C4 stratification ===
# For each pivot, find which FVGs swept at this pivot's index, with their stratum tags
print("\nBuilding stratification matrix...")
fvg_by_sweep_idx = {}
for z in all_fvg:
    if z["fs50_idx"] is not None:
        fvg_by_sweep_idx.setdefault(z["fs50_idx"], []).append(z)


stratum_rows = []
for pi, p in pivots.items():
    pdir = p["direction"]
    # Match: pivot direction "high" pairs with FVG "short" (FH = sweep upper)
    expected_fvg_dir = "short" if pdir == "high" else "long"

    # Which FVGs swept at this pivot?
    swept_here = fvg_by_sweep_idx.get(pi, [])
    swept_matched = [z for z in swept_here if z["direction"] == expected_fvg_dir]

    if not swept_matched:
        continue  # C4 fires только если есть direction-matched

    # Williams confirmed?
    # Check: high[pi] > h[pi±1,±2] for FH, or low[pi] < l[pi±1,±2] for FL
    confirmed = True
    for off in [-2, -1, 1, 2]:
        k = pi + off
        if k < 0 or k >= n12: confirmed = False; break
        if pdir == "high":
            if h12[k] >= h12[pi]: confirmed = False; break
        else:
            if l12[k] <= l12[pi]: confirmed = False; break

    # For each swept FVG — log stratum row
    for z in swept_matched:
        bars_age = (t12[pi] - z["c3_ms"]) // (TF12)  # in 12h bars
        z_tf = z["tf"]
        atr_val = atr12[pi] if atr12[pi] > 0 else 1.0
        width_atr = z["width"] / atr_val
        # HMA slope
        hma_now = hma78_12[pi - 1] if pi - 1 < len(hma78_12) and hma78_12[pi - 1] is not None else None
        hma_prev = hma78_12[pi - 6] if pi - 6 < len(hma78_12) and pi - 6 >= 0 and hma78_12[pi - 6] is not None else None
        hma_slope = "up" if hma_now and hma_prev and hma_now > hma_prev else ("down" if hma_now and hma_prev and hma_now < hma_prev else "flat")
        # Direction-match: pivot direction vs HMA slope
        # FH (sweep up) против up-slope = pivot — counter-trend = stronger?
        if pdir == "high":
            slope_match = "counter" if hma_slope == "up" else ("with" if hma_slope == "down" else "flat")
        else:
            slope_match = "counter" if hma_slope == "down" else ("with" if hma_slope == "up" else "flat")

        stratum_rows.append({
            "pi": pi, "pivot_dir": pdir, "confirmed": confirmed,
            "fvg_tf": z_tf, "age_bars12": int(bars_age),
            "width_atr": float(width_atr),
            "slope_match": slope_match,
        })

import pandas as pd
df = pd.DataFrame(stratum_rows)
print(f"\nC4 firing rows (after direction-match): {len(df)}")
print(f"Unique pivots fired by C4: {df['pi'].nunique()}")

# We want per pivot at LEAST ONE matching FVG fires — but for stratification
# we look at FVG-level, not pivot-level.
# Per pivot: confirmed if ANY of its FVG-matches has confirmed=True (same for all since same pi)
# So per stratum we count UNIQUE PIVOTS that fired for that stratum AND were confirmed.

def stat(df_sub, label):
    if df_sub.empty: return f"  {label:<35} 0 fires"
    n_piv = df_sub["pi"].nunique()
    pivs = df_sub.drop_duplicates("pi")[["pi","confirmed"]]
    conf = int(pivs["confirmed"].sum())
    p = conf / n_piv if n_piv else 0
    lift_from_base = p - 0.489
    return f"  {label:<35} pivs={n_piv:<4} conf={conf:<4} P={p*100:5.1f}%  Δ={lift_from_base*100:+5.1f}pp"

print("\n=== Stratification by FVG TF ===")
for tf in ["12h", "D", "2D", "3D", "W"]:
    print(stat(df[df["fvg_tf"] == tf], f"FVG-{tf}"))

print("\n=== Stratification by FVG age (12h bars between c3 and pivot) ===")
for lo, hi, lbl in [(0,5,"≤5 bars"), (5,20,"5-20"), (20,60,"20-60"), (60,200,"60-200"), (200,9999,">200")]:
    print(stat(df[(df["age_bars12"] >= lo) & (df["age_bars12"] < hi)], lbl))

print("\n=== Stratification by FVG width / ATR ===")
for lo, hi, lbl in [(0,0.3,"≤0.3 ATR"), (0.3,0.7,"0.3-0.7"), (0.7,1.5,"0.7-1.5"), (1.5,3.0,"1.5-3.0"), (3.0,99,">3.0")]:
    print(stat(df[(df["width_atr"] >= lo) & (df["width_atr"] < hi)], lbl))

print("\n=== Stratification by HMA-78 slope match ===")
for slope in ["counter", "with", "flat"]:
    print(stat(df[df["slope_match"] == slope], slope))

print("\n=== Cross: FVG TF × age ===")
for tf in ["12h", "D", "2D", "3D", "W"]:
    print(f"\n  {tf}:")
    for lo, hi, lbl in [(0,10,"young<10"), (10,50,"mid"), (50,9999,"old≥50")]:
        sub = df[(df["fvg_tf"] == tf) & (df["age_bars12"] >= lo) & (df["age_bars12"] < hi)]
        print(stat(sub, f"  {lbl}"))

# Best subset = combination giving >70% precision with reasonable volume
print("\n=== Top combinations ===")
# By TF + slope
for tf in ["12h", "D", "2D", "3D", "W"]:
    for slope in ["counter", "with"]:
        sub = df[(df["fvg_tf"] == tf) & (df["slope_match"] == slope)]
        if sub["pi"].nunique() >= 10:
            print(stat(sub, f"{tf} × {slope}-slope"))

out = pathlib.Path.home() / "Desktop" / "c4_stratify.csv"
df.to_csv(out, index=False)
print(f"\nFull → {out}")
