"""Forensics: какие D-fractal VWAPs касались LONG ob_vc 2h cur 2026-06-05 23:00 МСК.

Show ALL active VWAPs at born_ms with:
  - Anchor date
  - VWAP value at born_ms
  - Distance to drop_lo (LONG) — % and abs
  - Position: above / inside-bar-range / below
  - Interaction during formation (prev+cur 4h window)

Goal: human inspection of which VWAPs actually mattered.
"""
import sys, pathlib, csv
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from _lib import aggregate_all_tfs, to_candles, detect_williams_n2

CSV_1M = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
START_MS = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
N_FRACTAL = 2

# Target: LONG ob_vc cur 2026-06-05 23:00 МСК = 2026-06-05 20:00 UTC
# cur 2h bar opens at 20:00 UTC = 23:00 МСК
TARGET_CUR_OPEN_UTC = datetime(2026, 6, 5, 20, 0, tzinfo=timezone.utc)
TARGET_CUR_OPEN_MS = int(TARGET_CUR_OPEN_UTC.timestamp() * 1000)
TF_2H = 2 * 3600 * 1000


def msk(dt_utc): return dt_utc + timedelta(hours=3)


def fmt(ts_ms):
    dt = datetime.fromtimestamp(ts_ms/1000, tz=timezone.utc)
    return f"{dt.date()} {dt.strftime('%H:%M')}UTC ({msk(dt).strftime('%H:%M')}MSK)"


# Load 1m + cumulative for VWAP
rows = []
with CSV_1M.open() as f:
    rd = csv.reader(f); next(rd)
    for r in rd:
        t = int(datetime.fromisoformat(r[0]).timestamp() * 1000)
        if t < START_MS: continue
        rows.append((t, float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
ts_1m = np.array([r[0] for r in rows], dtype=np.int64)
c_1m = np.array([r[4] for r in rows], dtype=np.float64)
v_1m = np.array([r[5] for r in rows], dtype=np.float64)
cum_pv = np.concatenate(([0.0], np.cumsum(c_1m * v_1m)))
cum_v = np.concatenate(([0.0], np.cumsum(v_1m)))


def vwap_at(anchor_ts, target_ts):
    i_a = int(np.searchsorted(ts_1m, anchor_ts, side="left"))
    i_t = int(np.searchsorted(ts_1m, target_ts, side="right"))
    if i_t <= i_a: return None
    p = cum_pv[i_t] - cum_pv[i_a]; v = cum_v[i_t] - cum_v[i_a]
    return p / v if v > 0 else None


# Aggregate
rows_ohlc = [(r[0], r[1], r[2], r[3], r[4]) for r in rows]
cans_d = aggregate_all_tfs(rows_ohlc)
cans_2h = to_candles(cans_d["2h"])
cans_1d = to_candles(cans_d["1d"])

# Find the target 2h cur bar
bar2h_idx = {c.open_time: i for i, c in enumerate(cans_2h)}
idx = bar2h_idx.get(TARGET_CUR_OPEN_MS)
if idx is None:
    print(f"❌ Target cur bar not found at {fmt(TARGET_CUR_OPEN_MS)}")
    sys.exit(1)
prev = cans_2h[idx-1]; cur = cans_2h[idx]
born_ms = cur.open_time + TF_2H  # cur close
drop_lo = min(prev.low, cur.low)
drop_hi = max(prev.high, cur.high)
cur_close = cur.close

# Load Phase 1.5 to verify it IS an ob_vc and get its details
src = pd.read_parquet(pathlib.Path(__file__).parent.parent / "data/ob_vc_phase1_5.parquet")
g2h = src[(src.htf == "2h") & (src.direction == "long") & (src.ob_cur_open_ms == TARGET_CUR_OPEN_MS)]
if len(g2h) == 0:
    print(f"⚠ no ob_vc setup at {fmt(TARGET_CUR_OPEN_MS)} in Phase 1.5 data")
else:
    print(f"✓ Found {len(g2h)} FVG-component for this setup")
    born_ms_actual = int(g2h.iloc[0].born_ms)
    if born_ms_actual != born_ms:
        born_ms = born_ms_actual
        print(f"  born_ms updated to {fmt(born_ms)}")

print(f"\n{'='*80}")
print(f"OB_VC 2h LONG cur 2026-06-05 23:00 МСК — FORENSICS")
print(f"{'='*80}")
print(f"cur bar:   open={fmt(cur.open_time)}  O={cur.open:.2f} H={cur.high:.2f} L={cur.low:.2f} C={cur.close:.2f}")
print(f"prev bar:  open={fmt(prev.open_time)}  O={prev.open:.2f} H={prev.high:.2f} L={prev.low:.2f} C={prev.close:.2f}")
print(f"drop_lo:   {drop_lo:.2f}")
print(f"drop_hi:   {drop_hi:.2f}")
print(f"cur.close: {cur_close:.2f}")
print(f"born_ms:   {fmt(born_ms)}")

# All D fractals
fhs, fls = detect_williams_n2(cans_1d, n=N_FRACTAL)
ALL = []
for (i, lvl, _) in fls:
    if i + 1 < len(cans_1d):
        ALL.append({"type":"FL", "anchor_ts": int(cans_1d[i+1].open_time),
                    "fractal_ts": int(cans_1d[i].open_time), "level": float(lvl)})
for (i, lvl, _) in fhs:
    if i + 1 < len(cans_1d):
        ALL.append({"type":"FH", "anchor_ts": int(cans_1d[i+1].open_time),
                    "fractal_ts": int(cans_1d[i].open_time), "level": float(lvl)})

# Only those active (anchor < born_ms)
active = [a for a in ALL if a["anchor_ts"] < born_ms]
print(f"\nTotal D fractals: {len(ALL)}  active at born_ms: {len(active)}")

# Compute VWAP value at born_ms for each
rows_out = []
for a in active:
    v = vwap_at(a["anchor_ts"], born_ms)
    if v is None: continue
    age_d = (born_ms - a["anchor_ts"]) / (24*3600*1000)
    dist_pct = (drop_lo - v) / v * 100  # LONG: drop_lo vs vwap
    # Interaction during 4h formation (prev open → cur close)
    v_at_prev_open = vwap_at(a["anchor_ts"], prev.open_time)
    v_at_cur_open = vwap_at(a["anchor_ts"], cur.open_time)
    # Classification
    if drop_lo <= v <= cur_close:
        interaction = "WICKED-RECOVERED"  # wick punched below, close above
    elif prev.low <= v <= prev.high or cur.low <= v <= cur.high:
        interaction = "IN-BAR-RANGE"
    elif abs(dist_pct) <= 0.5:
        interaction = "NEAR (±0.5%)"
    elif v > drop_hi:
        interaction = "above bar"
    else:
        interaction = "below drop"
    rows_out.append({
        "type": a["type"], "fractal_date": datetime.fromtimestamp(a["fractal_ts"]/1000, tz=timezone.utc).date(),
        "anchor_date": datetime.fromtimestamp(a["anchor_ts"]/1000, tz=timezone.utc).date(),
        "age_d": int(age_d), "fractal_lvl": a["level"],
        "vwap_at_born": v, "dist_pct": dist_pct, "interaction": interaction,
    })

odf = pd.DataFrame(rows_out)
print(f"VWAPs with valid value at born_ms: {len(odf)}")
print(f"  FL: {(odf.type=='FL').sum()}  FH: {(odf.type=='FH').sum()}")

# Show ALL with |dist_pct| ≤ 1.0% sorted by dist
near = odf[odf.dist_pct.abs() <= 1.0].sort_values("dist_pct").copy()
print(f"\n{'='*100}")
print(f"VWAPs that INTERACTED (|dist| ≤ 1.0% from drop_lo {drop_lo:.0f})")
print(f"{'='*100}")
print(f"{'type':<5} {'fractal_d':<12} {'age_d':>6} {'frac_lvl':>9} {'VWAP@born':>10} {'dist_pct':>9} {'interaction':<22}")
for _, r in near.iterrows():
    print(f"{r['type']:<5} {str(r['fractal_date']):<12} {r['age_d']:>6} {r['fractal_lvl']:>9.0f} {r['vwap_at_born']:>10.0f} {r['dist_pct']:>+8.2f}% {r['interaction']:<22}")

# Show ALL within bar range
in_range = odf[(odf.vwap_at_born >= drop_lo) & (odf.vwap_at_born <= drop_hi)].sort_values("vwap_at_born")
print(f"\n{'='*100}")
print(f"VWAPs INSIDE bar range [{drop_lo:.0f}, {drop_hi:.0f}] — directly touched by 2h bars")
print(f"{'='*100}")
print(f"Count: {len(in_range)}")
for _, r in in_range.iterrows():
    print(f"  {r['type']:<3} {str(r['fractal_date'])} age={r['age_d']}d  fractal_lvl={r['fractal_lvl']:.0f}  VWAP@born={r['vwap_at_born']:.0f}  dist={r['dist_pct']:+.2f}%")

# Summary by age buckets
print(f"\n{'='*100}")
print(f"AGE BUCKETS — count of VWAPs near (±0.5%) drop_lo {drop_lo:.0f}")
print(f"{'='*100}")
for lo, hi in [(0,30),(30,90),(90,180),(180,365),(365,9999)]:
    sub = odf[(odf.age_d >= lo) & (odf.age_d < hi)]
    near_sub = sub[sub.dist_pct.abs() <= 0.5]
    total = sub
    print(f"  age [{lo:>3},{hi:>4}) days: total active={len(total):>3}  near±0.5%={len(near_sub):>2}  (FL={(near_sub.type=='FL').sum()}, FH={(near_sub.type=='FH').sum()})")

# Same-direction (FL) only
print(f"\n{'='*100}")
print(f"SAME-DIR (FL) VWAPs by distance — all 325 active scanned for LONG analysis")
print(f"{'='*100}")
fl = odf[odf.type == "FL"].copy()
for lab, mask in [
    ("within ±0.3% of drop_lo", fl.dist_pct.abs() <= 0.3),
    ("within ±0.5% of drop_lo", fl.dist_pct.abs() <= 0.5),
    ("within ±1.0%", fl.dist_pct.abs() <= 1.0),
    ("above drop_lo by ≥0.5%", fl.dist_pct < -0.5),  # vwap above drop_lo (LONG: drop_lo below vwap)
    ("below drop_lo by ≥0.5%", fl.dist_pct > 0.5),
]:
    n = mask.sum()
    if n > 0:
        sub = fl[mask]
        avg_age = sub.age_d.mean()
        print(f"  {lab:<32} N={n:>3}  avg_age={avg_age:.0f}d")

# Save full
out_path = pathlib.Path(__file__).parent.parent / "data/t1a_vwap_forensics.parquet"
odf.to_parquet(out_path)
print(f"\nSaved full table: {out_path}")
