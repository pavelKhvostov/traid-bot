"""C4 sweep-depth grid — тест разных глубин penetration в FVG.

Текущий C4 = "FIRST 50%-sweep FVG". Тестируем:
- d=30%: shallow sweep (price wick ≥ zone_lo + 0.30 × width) + close back outside
- d=50%: текущий канон (mid-zone)
- d=70%: deeper sweep
- d=85%: deep
- d=100%: full fill (wick covers entire FVG)

Гипотеза: глубокий sweep = stronger commitment к ликвидной зоне → higher P(W).
"""
from __future__ import annotations
import csv, math, pathlib, sys
from datetime import datetime, timezone, timedelta
import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path.home() / "smc-lib"))
from candle import Candle
from elements.fvg.code import detect_fvg

CSV = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MS_M = 60_000
TF12 = 12 * 60 * MS_M
TFD = 24 * 60 * MS_M
TF2D = 2 * TFD
TF3D = 3 * TFD
TFW = 7 * TFD
MON_ANCHOR = int(datetime(2017, 1, 2, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)

DEPTHS = [0.30, 0.50, 0.70, 0.85, 1.00]

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
h12 = np.array([b[2] for b in bars12]); l12 = np.array([b[3] for b in bars12]); c12 = np.array([b[4] for b in bars12])

bars_by_tf = {"12h": bars12, "D": agg(rows, TFD), "2D": agg(rows, TF2D),
              "3D": agg(rows, TF3D), "W": agg(rows, TFW, MON_ANCHOR)}
cans_by_tf = {tf: [Candle(open=b[1], high=b[2], low=b[3], close=b[4], open_time=b[0]) for b in bb]
              for tf, bb in bars_by_tf.items()}
tfms_map = {"12h": TF12, "D": TFD, "2D": TF2D, "3D": TF3D, "W": TFW}

# Scan all FVGs
print("Scanning FVGs across TFs...")
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
        })
print(f"  Total FVGs: {len(all_fvg)}")


# First-sweep at depth d (0..1) on 12h grid
# SHORT zone [zlo,zhi]: penetration = (high - zlo) / (zhi - zlo)
#   wick ≥ zlo + d × width AND close < zlo
# LONG zone [zlo,zhi]: penetration = (zhi - low) / (zhi - zlo)
#   wick ≤ zhi - d × width AND close > zhi
def first_sweep_idx(z, d):
    sp = int(np.searchsorted(t12, z["ready_ms"], side='left'))
    if sp >= n12: return None
    zlo, zhi = z["zone_lo"], z["zone_hi"]
    w = zhi - zlo
    thresh_short = zlo + d * w  # high must reach this
    thresh_long = zhi - d * w   # low must reach this
    for k in range(sp, n12):
        if z["direction"] == "short":
            if h12[k] >= thresh_short and c12[k] < zlo: return k
        else:
            if l12[k] <= thresh_long and c12[k] > zhi: return k
    return None


# Load baseline parquet
print("Loading baseline parquet...")
df_base = pd.read_parquet(pathlib.Path.home() / "Desktop/pred12h_baseline_c1c7.parquet")
df_base["pivot_open_ts_ms"] = df_base["pivot_open_ts_ms"].astype("int64")
print(f"  Baseline pivots: {len(df_base)}, confirmed: {df_base['confirmed'].sum()}, imp: {df_base['is_imp'].sum()}")

ts_to_idx = {int(t): k for k, t in enumerate(t12)}


print("\n" + "="*80)
print("C4 SWEEP DEPTH GRID")
print("="*80)

depth_results = []

for d in DEPTHS:
    # Build fvg_at_bar for this depth
    fvg_at_bar = {}
    for z in all_fvg:
        k = first_sweep_idx(z, d)
        if k is None: continue
        fvg_at_bar.setdefault(k, []).append(z)

    # Iterate baseline pivots, find C4 fires
    fires = []
    for _, p in df_base.iterrows():
        ts_ms = int(p["pivot_open_ts_ms"])
        if ts_ms not in ts_to_idx: continue
        bar_idx = ts_to_idx[ts_ms]
        pdir = p["direction"]
        expected_dir = "short" if pdir == "high" else "long"
        swept_at = fvg_at_bar.get(bar_idx, [])
        matched = [z for z in swept_at if z["direction"] == expected_dir]
        if matched:
            fires.append((ts_ms, bool(p["confirmed"]), bool(p["is_imp"])))

    n = len(fires)
    conf = sum(1 for _, c, _ in fires if c)
    imp = sum(1 for _, _, i in fires if i)
    wr = 100 * conf / n if n else 0
    depth_results.append((d, n, conf, wr, imp))
    print(f"  depth={int(d*100):>3}%  n={n:>4}  conf={conf:>4}  WR={wr:5.1f}%  imp={imp}")

print("\n=== Best depth standalone ===")
sorted_by_wr = sorted(depth_results, key=lambda x: x[3], reverse=True)
for d, n, conf, wr, imp in sorted_by_wr:
    print(f"  depth={int(d*100):>3}%  n={n:>4}  WR={wr:5.1f}%  imp={imp}")

# Cross with age ≥ 50
print("\n=== Depth × (age ≥ 50) ===")
print("Loading 1m...")
# Recompute FVG ages (need TF12-based age)
for d in DEPTHS:
    n=0; conf=0; imp=0
    for z in all_fvg:
        k = first_sweep_idx(z, d)
        if k is None: continue
        age_bars = (t12[k] - z["c3_ms"]) // TF12
        if age_bars < 50: continue
        # Check if k corresponds to a baseline pivot
        ts_ms = int(t12[k])
        row = df_base[df_base["pivot_open_ts_ms"] == ts_ms]
        if row.empty: continue
        p = row.iloc[0]
        pdir = p["direction"]
        if (pdir == "high" and z["direction"] != "short") or (pdir == "low" and z["direction"] != "long"):
            continue
        # Avoid double counting per pivot
    # simpler: rebuild fires set
    fires = set()
    confs = set()
    imps = set()
    for z in all_fvg:
        k = first_sweep_idx(z, d)
        if k is None: continue
        age_bars = (t12[k] - z["c3_ms"]) // TF12
        if age_bars < 50: continue
        ts_ms = int(t12[k])
        row = df_base[df_base["pivot_open_ts_ms"] == ts_ms]
        if row.empty: continue
        p = row.iloc[0]
        pdir = p["direction"]
        expected = "short" if pdir == "high" else "long"
        if z["direction"] != expected: continue
        fires.add(ts_ms)
        if bool(p["confirmed"]): confs.add(ts_ms)
        if bool(p["is_imp"]): imps.add(ts_ms)
    n = len(fires); conf = len(confs); imp = len(imps)
    wr = 100 * conf / n if n else 0
    print(f"  depth={int(d*100):>3}% ∩ age≥50:  n={n:>4}  conf={conf:>4}  WR={wr:5.1f}%  imp={imp}")
