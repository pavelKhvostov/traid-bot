"""C4 stratification v2 — корректный baseline (parquet с 1272 кандидатами F1∩F2∩F3).

Для каждого pivot из baseline (confirmed + not-confirmed):
1. Найти ALL FVGs со swept_50%_idx == pivot.i_g (на 12h grid)
2. Отметить TF / age / width
3. Aggregate per stratum

Цель: найти sub-conditions C4 которые дают P(W) > 70% (vs текущие 59.4%).
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

print("Loading 1m...")
rows = []
with CSV.open() as f:
    rd = csv.reader(f); next(rd)
    for r in rd:
        t = datetime.fromisoformat(r[0])
        rows.append((int(t.timestamp() * 1000), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))


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
o12 = np.array([b[1] for b in bars12])
h12 = np.array([b[2] for b in bars12]); l12 = np.array([b[3] for b in bars12]); c12 = np.array([b[4] for b in bars12])

bars_by_tf = {"12h": bars12, "D": agg(rows, TFD), "2D": agg(rows, TF2D),
              "3D": agg(rows, TF3D), "W": agg(rows, TFW, MON_ANCHOR)}
cans_by_tf = {tf: [Candle(open=b[1], high=b[2], low=b[3], close=b[4], open_time=b[0]) for b in bb]
              for tf, bb in bars_by_tf.items()}
tfms_map = {"12h": TF12, "D": TFD, "2D": TF2D, "3D": TF3D, "W": TFW}

# ATR(14)
def atr_calc(highs, lows, closes, n=14):
    tr = np.zeros(len(highs))
    for i in range(1, len(highs)):
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
    out = np.zeros(len(highs))
    for i in range(n, len(highs)):
        out[i] = tr[i - n + 1:i + 1].mean()
    return out


atr12 = atr_calc(h12, l12, c12, 14)


# HMA-78 on 12h
def wma(vals, n):
    out = [None] * len(vals)
    if n > len(vals): return out
    w = np.arange(1, n + 1, dtype=float); s = w.sum(); arr = np.array(vals, dtype=float)
    for i in range(n - 1, len(vals)):
        out[i] = float((arr[i - n + 1:i + 1] * w).sum() / s)
    return out


def hma(vals, n):
    half = wma(vals, n // 2); full = wma(vals, n)
    diff = [(2 * half[i] - full[i]) if (half[i] is not None and full[i] is not None) else 0.0 for i in range(len(vals))]
    return wma(diff, int(round(math.sqrt(n))))


hma78_12 = hma(c12.tolist(), 78)

# Scan all FVGs with metadata
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
            "width": fv.zone[1] - fv.zone[0],
        })
print(f"  Total FVGs: {len(all_fvg)}")


# First-50% sweep on 12h grid
def fvg_sweep_idx(z):
    sp = int(np.searchsorted(t12, z["ready_ms"], side='left'))
    if sp >= n12: return None
    zlo, zhi = z["zone_lo"], z["zone_hi"]; mid = (zlo + zhi) / 2
    for k in range(sp, n12):
        if z["direction"] == "short":
            if h12[k] >= mid and c12[k] < zlo: return k
        else:
            if l12[k] <= mid and c12[k] > zhi: return k
    return None


print("Computing fs50_idx for each FVG...")
for z in all_fvg:
    z["fs50_idx"] = fvg_sweep_idx(z)
swept = sum(1 for z in all_fvg if z["fs50_idx"] is not None)
print(f"  FVGs with fs50 sweep: {swept}")

# Map: 12h bar index → list of FVGs sweeping at this bar
fvg_at_bar = {}
for z in all_fvg:
    k = z["fs50_idx"]
    if k is None: continue
    fvg_at_bar.setdefault(k, []).append(z)


# Load baseline parquet
print("Loading baseline parquet...")
df_base = pd.read_parquet(pathlib.Path.home() / "Desktop/pred12h_baseline_c1c7.parquet")
df_base["pivot_open_ts_ms"] = df_base["pivot_open_ts_ms"].astype("int64")
print(f"  Baseline pivots: {len(df_base)}, confirmed: {df_base['confirmed'].sum()}, c4 fires: {df_base['c4'].sum()}")

# Build pivot lookup: ts → (confirmed, direction, is_imp)
ts_to_idx = {int(t): k for k, t in enumerate(t12)}

# For each baseline pivot, find FVGs that fired (direction-matched)
print("\nStratifying C4...")
stratum = []
for _, p in df_base.iterrows():
    ts_ms = int(p["pivot_open_ts_ms"])
    if ts_ms not in ts_to_idx: continue
    bar_idx = ts_to_idx[ts_ms]
    pdir = p["direction"]
    expected_fvg_dir = "short" if pdir == "high" else "long"
    swept_at = fvg_at_bar.get(bar_idx, [])
    matched = [z for z in swept_at if z["direction"] == expected_fvg_dir]
    if not matched: continue  # C4 не должна была fire
    atr_val = atr12[bar_idx] if atr12[bar_idx] > 0 else 1.0

    for z in matched:
        age_bars = (t12[bar_idx] - z["c3_ms"]) // TF12
        width_atr = z["width"] / atr_val
        # HMA slope
        hma_now = hma78_12[bar_idx - 1] if bar_idx >= 1 else None
        hma_prev = hma78_12[bar_idx - 6] if bar_idx >= 6 else None
        if hma_now is not None and hma_prev is not None:
            hma_slope = "up" if hma_now > hma_prev else "down"
        else:
            hma_slope = "flat"
        slope_match = ("counter" if (pdir == "high" and hma_slope == "up") or (pdir == "low" and hma_slope == "down")
                       else ("with" if hma_slope != "flat" else "flat"))
        stratum.append({
            "ts_ms": ts_ms, "pivot_dir": pdir,
            "confirmed": bool(p["confirmed"]), "is_imp": bool(p["is_imp"]),
            "fvg_tf": z["tf"], "age_bars12": int(age_bars),
            "width_atr": float(width_atr), "slope_match": slope_match,
        })

# Add 22-target labels
sys.path.insert(0, str(pathlib.Path.home() / "smc-lib" / "prediction-algo"))
from force_model_v3.targets_22 import SHORT_TARGETS, LONG_TARGETS  # noqa: E402
targets_22_ms = {int(ts.timestamp() * 1000) for ts in (SHORT_TARGETS | LONG_TARGETS)}

df = pd.DataFrame(stratum)
df["is_target22"] = df["ts_ms"].isin(targets_22_ms)
print(f"\nC4 FVG-firing rows: {len(df)} from {df['ts_ms'].nunique()} unique pivots")
piv_unique = df.drop_duplicates("ts_ms")
print(f"  Of which confirmed: {piv_unique['confirmed'].sum()} / {len(piv_unique)} = {piv_unique['confirmed'].mean()*100:.1f}%")
print(f"  imp (old-18 list) caught: {piv_unique['is_imp'].sum()}")
print(f"  22-targets caught: {piv_unique['is_target22'].sum()}")


def stat(sub, label):
    if sub.empty: return f"  {label:<35} 0 fires"
    # Unique pivots
    pivs = sub.drop_duplicates("ts_ms")
    n = len(pivs); conf = int(pivs["confirmed"].sum())
    p = conf / n if n else 0
    return f"  {label:<35} pivs={n:<4} conf={conf:<4} P={p*100:5.1f}%  imp={int(pivs['is_imp'].sum())}  tg22={int(pivs['is_target22'].sum())}"


print("\n=== By FVG TF ===")
for tf in ["12h", "D", "2D", "3D", "W"]:
    print(stat(df[df["fvg_tf"] == tf], f"FVG-{tf}"))

print("\n=== By FVG age (12h bars between c3 and pivot) ===")
for lo, hi, lbl in [(0,5,"≤5 bars"), (5,20,"5-20"), (20,60,"20-60"), (60,200,"60-200"), (200,9999,">200")]:
    print(stat(df[(df["age_bars12"] >= lo) & (df["age_bars12"] < hi)], lbl))

print("\n=== By FVG width / ATR(14) ===")
for lo, hi, lbl in [(0,0.3,"≤0.3"), (0.3,0.7,"0.3-0.7"), (0.7,1.5,"0.7-1.5"), (1.5,3.0,"1.5-3.0"), (3.0,99,">3.0")]:
    print(stat(df[(df["width_atr"] >= lo) & (df["width_atr"] < hi)], f"w {lbl}"))

print("\n=== By HMA-78 slope match ===")
for slope in ["counter", "with", "flat"]:
    print(stat(df[df["slope_match"] == slope], slope))

print("\n=== Cross: TF × slope ===")
for tf in ["12h", "D", "2D", "3D", "W"]:
    for slope in ["counter", "with"]:
        sub = df[(df["fvg_tf"] == tf) & (df["slope_match"] == slope)]
        if sub.drop_duplicates("ts_ms").shape[0] >= 5:
            print(stat(sub, f"{tf} × {slope}"))

print("\n=== Cross: TF × width ===")
for tf in ["12h", "D", "2D", "3D", "W"]:
    for lo, hi, lbl in [(0,0.5,"narrow"), (0.5,1.5,"medium"), (1.5,9999,"wide")]:
        sub = df[(df["fvg_tf"] == tf) & (df["width_atr"] >= lo) & (df["width_atr"] < hi)]
        if sub.drop_duplicates("ts_ms").shape[0] >= 5:
            print(stat(sub, f"{tf} × {lbl}"))

# Show list of CAUGHT imp and 22-targets per TF
print("\n=== Caught imp (old 18-list) per FVG TF ===")
for tf in ["12h", "D", "2D", "3D", "W"]:
    sub = df[(df["fvg_tf"] == tf) & (df["is_imp"])]
    if sub.empty: continue
    pivs = sub.drop_duplicates("ts_ms")
    print(f"  FVG-{tf} imp caught:")
    for _, p in pivs.iterrows():
        ts = pd.to_datetime(p["ts_ms"], unit='ms', utc=True)
        msk = ts.tz_convert("Europe/Moscow").strftime("%Y-%m-%d %H:%M MSK")
        cf = "✓" if p["confirmed"] else "✗"
        print(f"    {cf} {msk} {p['pivot_dir']:<4} confirmed={p['confirmed']}")

print("\n=== Caught 22-targets per FVG TF ===")
for tf in ["12h", "D", "2D", "3D", "W"]:
    sub = df[(df["fvg_tf"] == tf) & (df["is_target22"])]
    if sub.empty: continue
    pivs = sub.drop_duplicates("ts_ms")
    print(f"  FVG-{tf} 22-targets caught:")
    for _, p in pivs.iterrows():
        ts = pd.to_datetime(p["ts_ms"], unit='ms', utc=True)
        msk = ts.tz_convert("Europe/Moscow").strftime("%Y-%m-%d %H:%M MSK")
        cf = "✓" if p["confirmed"] else "✗"
        print(f"    {cf} {msk} {p['pivot_dir']:<4}")

# Per-stratum imp/target catches
print("\n=== Caught imp + 22-targets per top combination ===")
top_combos = [
    ("3D × counter", df[(df["fvg_tf"]=="3D") & (df["slope_match"]=="counter")]),
    ("D × wide", df[(df["fvg_tf"]=="D") & (df["width_atr"] >= 1.5)]),
    ("W × medium", df[(df["fvg_tf"]=="W") & (df["width_atr"] >= 0.5) & (df["width_atr"] < 1.5)]),
    ("Age ≥ 60 bars", df[df["age_bars12"] >= 60]),
    ("Width ≥ 0.7 ATR", df[df["width_atr"] >= 0.7]),
    ("HTF 3D+W", df[df["fvg_tf"].isin(["3D","W"])]),
]
for name, sub in top_combos:
    if sub.empty: continue
    pivs = sub.drop_duplicates("ts_ms")
    imp_pivs = pivs[pivs["is_imp"]]
    tg_pivs = pivs[pivs["is_target22"]]
    print(f"\n  '{name}': n={len(pivs)}, conf={pivs['confirmed'].sum()}, imp={len(imp_pivs)}, tg22={len(tg_pivs)}")
    if len(imp_pivs) or len(tg_pivs):
        for _, p in pivs[pivs["is_imp"] | pivs["is_target22"]].iterrows():
            ts = pd.to_datetime(p["ts_ms"], unit='ms', utc=True)
            msk = ts.tz_convert("Europe/Moscow").strftime("%Y-%m-%d %H:%M MSK")
            tags = []
            if p["is_imp"]: tags.append("imp")
            if p["is_target22"]: tags.append("tg22")
            cf = "✓" if p["confirmed"] else "✗"
            print(f"    {cf} {msk} {p['pivot_dir']:<4} [{', '.join(tags)}]")

out = pathlib.Path.home() / "Desktop/c4_stratify_v2.csv"
df.to_csv(out, index=False)
print(f"\nFull → {out}")
