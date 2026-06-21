"""C4 sub-basket — параллельные FVG-conditions Dx.

Архитектура (как C1-C9 в основной корзине):
  C4 = D1 ∪ D2 ∪ ... ∪ Dk

Каждое Dx — независимая комбинация:
  - WHEN: lifecycle gate (когда FVG "active")
      L0 = never abandon (default)
      L1 = abandon after first wick ≥50%
      L2 = abandon after first wick ≥100% (full fill)
      L3 = abandon after first close inside zone
      L4 = abandon after N bars without action (timeout)

  - WHAT: sweep formula
      S50 = high≥mid + close<zlo (default canon)
      S70 = high≥70%-pt + close<zlo
      S100 = high≥zhi + close<zlo (full)
      W50 = high≥mid (wick-fill, no close req)
      W100 = high≥zhi (full wick-fill)
      CINS = high≥mid + close INSIDE zone (consumption rejection)

  - FILTER: дополнительные ограничения
      F_ANY, F_HTF (D+), F_AGE50, F_WIDE, etc.

Каждый Dx evaluates standalone на baseline 1267:
  → n, conf, WR, imp, target22

Output: ranked list, candidate OR-basket.
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
TIMEOUT_BARS = 120  # ~60 days on 12h grid

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


bars12 = agg(rows, TF12); n12 = len(bars12)
t12 = np.array([b[0] for b in bars12], dtype=np.int64)
h12 = np.array([b[2] for b in bars12]); l12 = np.array([b[3] for b in bars12]); c12 = np.array([b[4] for b in bars12])
v12 = np.array([b[5] for b in bars12])

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
            "zlo": fv.zone[0], "zhi": fv.zone[1],
            "c3_ms": cans[i + 2].open_time,
            "ready_ms": ready,
        })
print(f"  Total FVGs: {len(all_fvg)}")


# ─── Compute "events" per FVG: list of (bar_idx, penetration, close_inside, close_outside) ───
# Forward-scan from ready, log every touch
print("Computing per-FVG event timelines...")
for z in all_fvg:
    sp = int(np.searchsorted(t12, z["ready_ms"], side='left'))
    z["events"] = []  # list of (k, pen_pct, close_inside, close_outside, close_outside_far)
    if sp >= n12:
        continue
    zlo, zhi = z["zlo"], z["zhi"]
    w = zhi - zlo
    if w <= 0:
        continue
    for k in range(sp, n12):
        if z["direction"] == "short":
            h, c = h12[k], c12[k]
            if h < zlo: continue  # no touch
            pen = min((h - zlo) / w * 100, 999)
            close_inside = (c >= zlo and c <= zhi)
            close_outside_far = (c < zlo)   # rejection back below
            close_outside_thru = (c > zhi)  # closed THROUGH (breakout)
        else:  # long FVG
            l, c = l12[k], c12[k]
            if l > zhi: continue
            pen = min((zhi - l) / w * 100, 999)
            close_inside = (c >= zlo and c <= zhi)
            close_outside_far = (c > zhi)
            close_outside_thru = (c < zlo)
        z["events"].append((k, pen, close_inside, close_outside_far, close_outside_thru))


# ─── Lifecycle gates: compute "active_until" index per FVG, per lifecycle model ───
def active_until(z, lifecycle):
    """Return bar idx (exclusive) when FVG becomes inactive. None = never (active forever)."""
    if lifecycle == "L0":
        return None
    if lifecycle == "L1":  # first wick≥50%
        for k, pen, ci, co_far, co_thru in z["events"]:
            if pen >= 50:
                return k + 1  # k is mitigation bar; from k+1 onward = inactive
        return None
    if lifecycle == "L2":  # first full fill ≥100%
        for k, pen, ci, co_far, co_thru in z["events"]:
            if pen >= 100:
                return k + 1
        return None
    if lifecycle == "L3":  # first close inside
        for k, pen, ci, co_far, co_thru in z["events"]:
            if ci:
                return k + 1
        return None
    if lifecycle == "L4":  # timeout TIMEOUT_BARS bars
        sp = int(np.searchsorted(t12, z["ready_ms"], side='left'))
        return sp + TIMEOUT_BARS
    return None


# ─── Sweep formulas ───
def is_sweep(pen, close_inside, close_out_far, close_out_thru, mode):
    if mode == "S50":  return pen >= 50  and close_out_far
    if mode == "S70":  return pen >= 70  and close_out_far
    if mode == "S100": return pen >= 100 and close_out_far
    if mode == "W50":  return pen >= 50
    if mode == "W100": return pen >= 100
    if mode == "CINS": return pen >= 50  and close_inside
    return False


# ─── Filter on FVG metadata ───
def fvg_passes_filter(z, k, ftype):
    if ftype == "ANY":
        return True
    age = (t12[k] - z["c3_ms"]) // TF12
    width = z["zhi"] - z["zlo"]
    atr = atr12[k] if atr12[k] > 0 else 1.0
    if ftype == "HTF":     # D+
        return z["tf"] in ("D", "2D", "3D", "W")
    if ftype == "12h":
        return z["tf"] == "12h"
    if ftype == "AGE50":
        return age >= 50
    if ftype == "WIDE":
        return width / atr >= 0.7
    if ftype == "HTF_AGE50":
        return z["tf"] in ("D", "2D", "3D", "W") and age >= 50
    if ftype == "HTF_WIDE":
        return z["tf"] in ("D", "2D", "3D", "W") and width / atr >= 0.7
    if ftype == "AGE50_WIDE":
        return age >= 50 and width / atr >= 0.7
    return False


# ─── Compute C4 fires per Dx variant ───
def evaluate_dx(lifecycle, sweep_mode, filter_type, first_only=True):
    """Return set of bar_idx where Dx fires (a pivot would have C4=True)."""
    fires = set()
    for z in all_fvg:
        au = active_until(z, lifecycle)  # None = never
        triggered = False
        for k, pen, ci, co_far, co_thru in z["events"]:
            if au is not None and k >= au:
                break
            if not is_sweep(pen, ci, co_far, co_thru, sweep_mode):
                continue
            if not fvg_passes_filter(z, k, filter_type):
                continue
            fires.add((k, z["direction"]))
            triggered = True
            if first_only:
                break
    return fires


# ─── Load baseline ───
print("Loading baseline parquet...")
df_base = pd.read_parquet(pathlib.Path.home() / "Desktop/pred12h_baseline_c1c7.parquet")
df_base["pivot_open_ts_ms"] = df_base["pivot_open_ts_ms"].astype("int64")

ts_to_idx = {int(t): k for k, t in enumerate(t12)}

# Map pivots: bar_idx → (confirmed, is_imp, direction)
pivot_map = {}
for _, p in df_base.iterrows():
    ts_ms = int(p["pivot_open_ts_ms"])
    if ts_ms not in ts_to_idx: continue
    k = ts_to_idx[ts_ms]
    pdir = p["direction"]
    expected_fvg_dir = "short" if pdir == "high" else "long"
    pivot_map[(k, expected_fvg_dir)] = (bool(p["confirmed"]), bool(p["is_imp"]), pdir, ts_ms)

baseline_n = len(df_base)
baseline_conf = int(df_base["confirmed"].sum())
baseline_imp = int(df_base["is_imp"].sum())
print(f"  Baseline: n={baseline_n}, conf={baseline_conf}, imp={baseline_imp}")


def stats_for_variant(fires):
    matched = []
    for (k, fvg_dir), _ in [(f, None) for f in fires]:
        if (k, fvg_dir) in pivot_map:
            matched.append(pivot_map[(k, fvg_dir)])
    n = len(matched)
    conf = sum(1 for c, _, _, _ in matched if c)
    imp = sum(1 for _, i, _, _ in matched if i)
    wr = 100 * conf / n if n else 0.0
    imp_list = [ts for _, i, _, ts in matched if i]
    return n, conf, wr, imp, imp_list


# ─── Grid: lifecycle × sweep × filter ───
LIFECYCLES = ["L0", "L1", "L2", "L3", "L4"]
SWEEP_MODES = ["S50", "S70", "S100", "W50", "W100", "CINS"]
FILTERS = ["ANY", "HTF", "12h", "AGE50", "WIDE", "HTF_AGE50", "HTF_WIDE", "AGE50_WIDE"]

print("\n" + "="*100)
print("C4 sub-basket grid: lifecycle × sweep × filter")
print("="*100)

results = []
for lc in LIFECYCLES:
    for sm in SWEEP_MODES:
        for ft in FILTERS:
            fires = evaluate_dx(lc, sm, ft)
            n, conf, wr, imp, imp_list = stats_for_variant(fires)
            if n < 10: continue  # skip noise
            results.append({
                "lifecycle": lc, "sweep": sm, "filter": ft,
                "n": n, "conf": conf, "WR": wr, "imp": imp,
                "imp_list": imp_list,
            })

rdf = pd.DataFrame(results)
rdf["Δ_baseline"] = rdf["WR"] - 48.9

# Sort by WR desc
rdf_top_wr = rdf.sort_values("WR", ascending=False).head(20)
print("\n=== TOP-20 by WR (n ≥ 10) ===")
print(f"{'Lc':<3} {'Sw':<5} {'Filter':<13} {'n':>4} {'conf':>4} {'WR':>6} {'Δ':>6} {'imp':>4}")
for _, r in rdf_top_wr.iterrows():
    print(f"{r['lifecycle']:<3} {r['sweep']:<5} {r['filter']:<13} {r['n']:>4} {r['conf']:>4} {r['WR']:>5.1f}% {r['Δ_baseline']:+5.1f} {r['imp']:>4}")

# Sort by imp catches
rdf_top_imp = rdf.sort_values(["imp", "WR"], ascending=[False, False]).head(20)
print("\n=== TOP-20 by imp catches (then WR) ===")
print(f"{'Lc':<3} {'Sw':<5} {'Filter':<13} {'n':>4} {'conf':>4} {'WR':>6} {'Δ':>6} {'imp':>4}")
for _, r in rdf_top_imp.iterrows():
    print(f"{r['lifecycle']:<3} {r['sweep']:<5} {r['filter']:<13} {r['n']:>4} {r['conf']:>4} {r['WR']:>5.1f}% {r['Δ_baseline']:+5.1f} {r['imp']:>4}")

# Find variants that catch missed #48 (2026-05-06 03:00 MSK = 1746496800000 UTC)
imp48_ms = int(datetime(2026, 5, 6, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
print(f"\n=== Variants that catch missed imp #48 (2026-05-06 03:00 MSK = {imp48_ms} UTC) ===")
catches_48 = []
for _, r in rdf.iterrows():
    if imp48_ms in r["imp_list"]:
        catches_48.append(r)
if catches_48:
    print(f"{'Lc':<3} {'Sw':<5} {'Filter':<13} {'n':>4} {'WR':>6} {'imp':>4}")
    for r in sorted(catches_48, key=lambda x: -x["WR"])[:15]:
        print(f"{r['lifecycle']:<3} {r['sweep']:<5} {r['filter']:<13} {r['n']:>4} {r['WR']:>5.1f}% {r['imp']:>4}")
else:
    print("  No variant catches #48 (this is bad)")

# Save full results
out = pathlib.Path.home() / "Desktop/c4_subbasket_grid.csv"
rdf_save = rdf.drop("imp_list", axis=1)
rdf_save.to_csv(out, index=False)
print(f"\nFull grid → {out} ({len(rdf)} variants)")

# Default C4 reference
default_fires = evaluate_dx("L0", "S50", "ANY")
n0, c0, wr0, imp0, _ = stats_for_variant(default_fires)
print(f"\nDefault C4 (L0/S50/ANY): n={n0}, conf={c0}, WR={wr0:.1f}%, imp={imp0}")
