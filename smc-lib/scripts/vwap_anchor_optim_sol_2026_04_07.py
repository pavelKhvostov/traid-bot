"""Оптимизация anchor VWAP скользящей для SOL.
Search range: 2026-04-07 UTC day (96 × 15m candidates).
Control points: 6 closes (5 valid, 6th за пределами data).
Метрика: mean absolute % error к close 6h-баров в control точках.
"""
from __future__ import annotations
import csv, pathlib, sys
from datetime import datetime, timezone, timedelta
import numpy as np

sys.path.insert(0, str(pathlib.Path.home() / "smc-lib"))
from indicators.vwap_anchored import anchored_vwap

CSV = pathlib.Path.home() / "traid-bot/data/SOLUSDT_1m_vic_vadim.csv"
MSK = timezone(timedelta(hours=3))
UTC = timezone.utc
MS_M = 60_000
MS_H = 60*MS_M

ANCHOR_START = datetime(2026, 2, 2, 0, 0, tzinfo=UTC)
ANCHOR_END   = datetime(2026, 2, 15, 0, 0, tzinfo=UTC)   # exclusive (13 дней)
N_CANDIDATES = int((ANCHOR_END - ANCHOR_START).total_seconds() / 60 / 15)

CONTROL_MSK = [
    "2026-04-07 21:00",
    "2026-04-14 03:00",
    "2026-04-21 15:00",
    "2026-05-16 09:00",
    "2026-05-20 21:00",
    "2026-05-25 15:00",
]

print("Loading SOL 1m...")
rows = []
with CSV.open() as f:
    rd = csv.reader(f); next(rd)
    for r in rd:
        t = datetime.fromisoformat(r[0])
        rows.append((int(t.timestamp()*1000), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
print(f"  {len(rows)} 1m bars (до {datetime.fromtimestamp(rows[-1][0]/1000, MSK).strftime('%Y-%m-%d %H:%M')} MSK)")

def aggregate(d, tfms):
    out=[]; cb=None; o=h=l=c=0.0; v=0.0
    for ts,oo,hh,ll,cc,vv in d:
        b = ts - (ts % tfms)
        if b!=cb:
            if cb is not None: out.append((cb,o,h,l,c,v))
            cb=b; o,h,l,c=oo,hh,ll,cc; v=vv
        else:
            h=max(h,hh); l=min(l,ll); c=cc; v+=vv
    if cb is not None: out.append((cb,o,h,l,c,v))
    return out

bars_15m = aggregate(rows, 15*MS_M)
bars_6h = aggregate(rows, 6*MS_H)
print(f"  15m bars: {len(bars_15m)}, 6h bars: {len(bars_6h)}\n")

last_ts = rows[-1][0]
controls = []
for label in CONTROL_MSK:
    dt_msk = datetime.strptime(label, "%Y-%m-%d %H:%M").replace(tzinfo=MSK)
    ts_utc = int(dt_msk.timestamp() * 1000)
    target_bar_open = ts_utc - 6*MS_H
    bar = next((b for b in bars_6h if b[0] == target_bar_open), None)
    if bar is None or ts_utc > last_ts:
        controls.append((ts_utc, label, None))
    else:
        controls.append((ts_utc, label, bar[4]))

print(f"Control points (close 6h-бара SOL):")
print(f"  {'#':<3} {'MSK time':<19} {'UTC time':<19} {'close':>9}")
valid_controls = []
for i, (ts, label, c) in enumerate(controls, 1):
    utc_dt = datetime.fromtimestamp(ts/1000, UTC).strftime('%Y-%m-%d %H:%M')
    c_str = f"{c:.2f}" if c is not None else "n/a (past data end)"
    print(f"  {i:<3} {label:<19} {utc_dt:<19} {c_str:>9}")
    if c is not None: valid_controls.append((ts, label, c))
print(f"\nИспользуем {len(valid_controls)} из {len(controls)}.\n")
print(f"Anchor candidates: {N_CANDIDATES} × 15m начиная с {ANCHOR_START.astimezone(MSK).strftime('%Y-%m-%d %H:%M')} MSK\n")

anchors = []
for k in range(N_CANDIDATES):
    a_ts = int(ANCHOR_START.timestamp()*1000) + k * 15 * MS_M
    anchors.append(a_ts)

ts_15m = np.array([b[0] for b in bars_15m], dtype=np.int64)
def find_15m_idx(ts):
    idx = int(np.searchsorted(ts_15m, ts, side='left'))
    return idx if idx < len(bars_15m) else None

ohlcv_15m = [(b[1], b[2], b[3], b[4], b[5]) for b in bars_15m]

def control_15m_idx(ts):
    target = ts - 15*MS_M
    idx_arr = np.where(ts_15m == target)[0]
    if len(idx_arr) > 0: return int(idx_arr[0])
    idx = int(np.searchsorted(ts_15m, ts, side='right')) - 1
    return idx if 0 <= idx < len(bars_15m) else None

print("Computing VWAP per anchor + evaluating at control points...")
results = []
for a_ts in anchors:
    a_idx = find_15m_idx(a_ts)
    if a_idx is None: continue
    vw_series = anchored_vwap(ohlcv_15m, a_idx)
    per_ctrl = []
    for c_ts, label, c_close in valid_controls:
        c_idx = control_15m_idx(c_ts)
        if c_idx is None or c_idx < a_idx or vw_series[c_idx] is None:
            per_ctrl.append(None)
        else:
            v = vw_series[c_idx]
            err_pct = (v - c_close) / c_close * 100
            per_ctrl.append((v, err_pct))
    valid_errs = [abs(p[1]) for p in per_ctrl if p is not None]
    if not valid_errs: continue
    mae = float(np.mean(valid_errs))
    max_err = float(np.max(valid_errs))
    results.append({"anchor_ts": a_ts, "per_ctrl": per_ctrl, "mae": mae, "max_err": max_err})

results.sort(key=lambda r: r["mae"])
print(f"Computed {len(results)} anchors.\n")

print(f"{'='*120}")
print(f"  TOP-10 anchors по MIN MAE на SOL (search 2026-04-07)")
print(f"{'='*120}")
print(f"  {'#':<3} {'Anchor MSK':<19} {'MAE%':>7} {'MaxErr%':>9} {'errors per control point (%)':<40}")
for i, r in enumerate(results[:10], 1):
    a_msk = datetime.fromtimestamp(r["anchor_ts"]/1000, MSK).strftime('%m-%d %H:%M')
    errs = "  ".join(f"{p[1]:+6.2f}" if p else "   n/a" for p in r["per_ctrl"])
    print(f"  {i:<3} {a_msk:<19} {r['mae']:>6.2f}  {r['max_err']:>8.2f}  [{errs}]")

print(f"\n  WORST-3 anchors:")
for i, r in enumerate(results[-3:], 1):
    a_msk = datetime.fromtimestamp(r["anchor_ts"]/1000, MSK).strftime('%m-%d %H:%M')
    errs = "  ".join(f"{p[1]:+6.2f}" if p else "   n/a" for p in r["per_ctrl"])
    print(f"  {i:<3} {a_msk:<19} {r['mae']:>6.2f}  {r['max_err']:>8.2f}  [{errs}]")

print(f"\n{'='*120}")
print(f"  ★ BEST ANCHOR (SOL)")
print(f"{'='*120}")
best = results[0]
print(f"  Anchor: {datetime.fromtimestamp(best['anchor_ts']/1000, MSK).strftime('%Y-%m-%d %H:%M')} MSK"
      f"  ({datetime.fromtimestamp(best['anchor_ts']/1000, UTC).strftime('%Y-%m-%d %H:%M')} UTC)")
print(f"  MAE: {best['mae']:.3f}%, MaxErr: {best['max_err']:.3f}%")
print(f"\n  Detail per control point:")
print(f"    {'#':<3} {'Control MSK':<19} {'Close':>9} {'VWAP_now':>9} {'Δ%':>7}")
for i, ((ts, label, c_close), pc) in enumerate(zip(valid_controls, best['per_ctrl']), 1):
    if pc is None:
        print(f"    {i:<3} {label:<19} {c_close:>9.2f} {'n/a':>9} {'n/a':>7}")
    else:
        v, err = pc
        print(f"    {i:<3} {label:<19} {c_close:>9.2f} {v:>9.2f} {err:>+6.2f}%")

# Landscape по дню (если search range > 1 дня)
print(f"\n{'='*120}")
print(f"  MAE landscape — best 15m в каждый день search range (MSK)")
print(f"{'='*120}")
date_best = {}
for r in results:
    msk = datetime.fromtimestamp(r["anchor_ts"]/1000, MSK)
    date_label = msk.strftime('%Y-%m-%d')
    if date_label not in date_best or r["mae"] < date_best[date_label]["mae"]:
        date_best[date_label] = {"mae": r["mae"], "anchor_msk": msk.strftime('%H:%M'), "max_err": r["max_err"]}
print(f"  {'Date':<13} {'best 15m':<10} {'MAE%':>7} {'MaxErr%':>9}")
for dl in sorted(date_best.keys()):
    d = date_best[dl]
    print(f"  {dl:<13} {d['anchor_msk']:<10} {d['mae']:>6.2f} {d['max_err']:>8.2f}")

# Mean MAE per day
print(f"\n  MAE по дню (среднее по всем 15m anchors):")
date_avg = {}
for r in results:
    msk = datetime.fromtimestamp(r["anchor_ts"]/1000, MSK)
    date_label = msk.strftime('%Y-%m-%d')
    date_avg.setdefault(date_label, []).append(r["mae"])
print(f"  {'Date':<13} {'mean MAE':>9} {'min MAE':>9} {'max MAE':>9} {'spread':>8}")
for dl in sorted(date_avg.keys()):
    arr = date_avg[dl]
    print(f"  {dl:<13} {np.mean(arr):>8.3f} {np.min(arr):>8.3f} {np.max(arr):>8.3f} {(np.max(arr)-np.min(arr)):>7.3f}")
