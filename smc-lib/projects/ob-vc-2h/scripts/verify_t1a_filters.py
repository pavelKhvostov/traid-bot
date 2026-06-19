"""Verify all filter implementations on T1a example.
T1a LONG cur 2026-06-05 23:00 МСК = 20:00 UTC
"""
import sys, pathlib, csv
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from _lib import aggregate_all_tfs, to_candles, detect_williams_n2

CSV_1M = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
START_MS = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
TARGET_CUR_OPEN = int(datetime(2026, 6, 5, 20, 0, tzinfo=timezone.utc).timestamp() * 1000)
MSK = timezone(timedelta(hours=3))


def fmt(ms): return datetime.fromtimestamp(ms/1000, tz=timezone.utc).astimezone(MSK).strftime("%Y-%m-%d %H:%M")


rows = []
with CSV_1M.open() as f:
    rd = csv.reader(f); next(rd)
    for r in rd:
        t = int(datetime.fromisoformat(r[0]).timestamp() * 1000)
        if t < START_MS: continue
        rows.append((t, float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))

rows_ohlc = [(r[0], r[1], r[2], r[3], r[4]) for r in rows]
cans_d = aggregate_all_tfs(rows_ohlc)
cans_2h = to_candles(cans_d["2h"])
cans_4h = to_candles(cans_d["4h"])
cans_6h = to_candles(cans_d["6h"])
cans_15m = to_candles(cans_d["15m"])

bar2h = {c.open_time: i for i, c in enumerate(cans_2h)}
idx = bar2h[TARGET_CUR_OPEN]
prev = cans_2h[idx-1]; cur = cans_2h[idx]
born_ms = cur.open_time + 2*3600*1000
print(f"T1a: prev {fmt(prev.open_time)} O={prev.open:.0f} H={prev.high:.0f} L={prev.low:.0f} C={prev.close:.0f}")
print(f"     cur  {fmt(cur.open_time)} O={cur.open:.0f} H={cur.high:.0f} L={cur.low:.0f} C={cur.close:.0f}")
print(f"     born_ms: {fmt(born_ms)}  drop_lo={min(prev.low,cur.low):.0f}")

# ─── 1. Parent 4h ob_vc check ─────────────────────────
df = pd.read_parquet(pathlib.Path(__file__).parent.parent / "data/ob_vc_phase1_5.parquet")
print(f"\n{'='*80}")
print(f"1. PARENT 4h ob_vc check")
print(f"{'='*80}")
h4_long = df[(df.htf == "4h") & (df.direction == "long")].groupby("ob_cur_open_ms").agg(
    born_ms=("born_ms","first"),
    ob_zone_lo=("ob_zone_lo","first"),
    ob_zone_hi=("ob_zone_hi","first"),
    drop_lo=("drop_lo","first"),
    valid_until_ms=("valid_until_ms","first"),
).reset_index()
# Filter: born before our 2h, still valid, zone overlap with our 2h fvg
my_zone_lo = 0
my_fvg = df[(df.htf == "2h") & (df.direction == "long") & (df.ob_cur_open_ms == TARGET_CUR_OPEN)]
print(f"Our 2h FVGs ({len(my_fvg)} components):")
for _, r in my_fvg.iterrows():
    print(f"  ltf={r.ltf}  fvg_zone=[{r.fvg_zone_lo:.0f}, {r.fvg_zone_hi:.0f}]")
my_z_lo = my_fvg.fvg_zone_lo.min(); my_z_hi = my_fvg.fvg_zone_hi.max()
print(f"  combined fvg range: [{my_z_lo:.0f}, {my_z_hi:.0f}]")

h4_pre = h4_long[(h4_long.born_ms <= born_ms) & (h4_long.valid_until_ms > born_ms)]
print(f"\n4h LONG ob_vc with born_ms ≤ our born AND still valid: {len(h4_pre)}")
# Zone overlap with our 2h zone
overlap = h4_pre[(h4_pre.ob_zone_lo <= my_z_hi) & (h4_pre.ob_zone_hi >= my_z_lo)]
print(f"  WITH zone overlap with our 2h FVG: {len(overlap)}")
for _, r in overlap.head(5).iterrows():
    age_h = (born_ms - r.born_ms) / 3600000
    print(f"    4h ob_vc born {fmt(r.born_ms)} ({age_h:.1f}h ago)  zone=[{r.ob_zone_lo:.0f}, {r.ob_zone_hi:.0f}]  drop_lo={r.drop_lo:.0f}")

# Alternative: check 4h ob_vc whose zone CONTAINS our 2h drop_lo
drop_lo_2h = min(prev.low, cur.low)
contains_drop = h4_pre[(h4_pre.ob_zone_lo <= drop_lo_2h) & (h4_pre.ob_zone_hi >= drop_lo_2h)]
print(f"\n  4h ob_vc whose zone CONTAINS our drop_lo {drop_lo_2h:.0f}: {len(contains_drop)}")
for _, r in contains_drop.head(5).iterrows():
    age_h = (born_ms - r.born_ms) / 3600000
    print(f"    4h ob_vc born {fmt(r.born_ms)} ({age_h:.1f}h ago)  zone=[{r.ob_zone_lo:.0f}, {r.ob_zone_hi:.0f}]")

# Time-based: 2h cur falls within HTF cur+prev bar time window
# 4h cur containing our 2h cur
h4_long_full = df[(df.htf == "4h") & (df.direction == "long")].groupby("ob_cur_open_ms").agg(
    born_ms=("born_ms","first"),
    ob_cur_close_ms=("ob_cur_close_ms","first"),
    ob_zone_lo=("ob_zone_lo","first"),
    ob_zone_hi=("ob_zone_hi","first"),
).reset_index()
# 4h time range: [ob_cur_open - 4h, ob_cur_close] = full prev+cur 8h
time_contain = h4_long_full[(h4_long_full.ob_cur_open_ms - 4*3600*1000 <= prev.open_time) &
                            (h4_long_full.ob_cur_close_ms >= cur.open_time + 2*3600*1000)]
print(f"\n  4h ob_vc whose time-window contains our 2h prev+cur: {len(time_contain)}")
for _, r in time_contain.head(5).iterrows():
    print(f"    4h ob_vc cur_open {fmt(r.ob_cur_open_ms)}  born {fmt(r.born_ms)}")

# ─── 2. Parent 6h ob_vc check ─────────────────────────
print(f"\n{'='*80}")
print(f"2. PARENT 6h ob_vc check")
print(f"{'='*80}")
h6_long = df[(df.htf == "6h") & (df.direction == "long")].groupby("ob_cur_open_ms").agg(
    born_ms=("born_ms","first"),
    ob_cur_close_ms=("ob_cur_close_ms","first"),
    ob_zone_lo=("ob_zone_lo","first"),
    ob_zone_hi=("ob_zone_hi","first"),
    valid_until_ms=("valid_until_ms","first"),
).reset_index()
h6_pre = h6_long[(h6_long.born_ms <= born_ms) & (h6_long.valid_until_ms > born_ms)]
overlap6 = h6_pre[(h6_pre.ob_zone_lo <= my_z_hi) & (h6_pre.ob_zone_hi >= my_z_lo)]
print(f"6h LONG ob_vc with zone overlap to our 2h FVG: {len(overlap6)}")
for _, r in overlap6.head(5).iterrows():
    age_h = (born_ms - r.born_ms) / 3600000
    print(f"  6h ob_vc born {fmt(r.born_ms)} ({age_h:.1f}h ago)  zone=[{r.ob_zone_lo:.0f}, {r.ob_zone_hi:.0f}]")

contains6 = h6_pre[(h6_pre.ob_zone_lo <= drop_lo_2h) & (h6_pre.ob_zone_hi >= drop_lo_2h)]
print(f"\n6h ob_vc whose zone CONTAINS our drop_lo: {len(contains6)}")
for _, r in contains6.head(5).iterrows():
    age_h = (born_ms - r.born_ms) / 3600000
    print(f"  6h ob_vc born {fmt(r.born_ms)} ({age_h:.1f}h ago)  zone=[{r.ob_zone_lo:.0f}, {r.ob_zone_hi:.0f}]")

# ─── 3. 15m BOS LONG check ───────────────────────────
print(f"\n{'='*80}")
print(f"3. 15m BOS LONG check")
print(f"{'='*80}")
prev_open = prev.open_time
# 15m fractals before prev_open
fhs_15m, fls_15m = detect_williams_n2(cans_15m, n=2)
fh_data = [(int(cans_15m[i+2].open_time), int(cans_15m[i].open_time), float(lvl))
           for (i, lvl, _) in fhs_15m if i+2 < len(cans_15m)]
# Latest 5 FHs before prev_open
pre_fhs = [x for x in fh_data if x[0] < prev_open]
pre_fhs.sort(key=lambda x: x[0])
print(f"Last 5 15m FHs confirmed before prev_open {fmt(prev_open)}:")
for confirm_ts, frac_ts, lvl in pre_fhs[-5:]:
    age_h = (prev_open - confirm_ts) / 3600000
    print(f"  FH @ {fmt(frac_ts)} (confirmed {fmt(confirm_ts)}, {age_h:.1f}h ago)  level={lvl:.0f}")

if pre_fhs:
    latest_confirm, latest_frac, latest_lvl = pre_fhs[-1]
    print(f"\nLatest 15m FH level = {latest_lvl:.0f}")
    print(f"Our prev_open = {fmt(prev_open)}, cur.close = {fmt(born_ms)}")
    # 15m closes in window [prev_open, born_ms]
    ts15 = np.array([c.open_time for c in cans_15m], dtype=np.int64)
    cl15 = np.array([c.close for c in cans_15m], dtype=np.float64)
    h15 = np.array([c.high for c in cans_15m], dtype=np.float64)
    i_lo = int(np.searchsorted(ts15, prev_open, side="left"))
    i_hi = int(np.searchsorted(ts15, born_ms, side="right"))
    bars_in_win = cans_15m[i_lo:i_hi]
    print(f"  15m bars in window: {len(bars_in_win)}")
    closes_above = (cl15[i_lo:i_hi] > latest_lvl).sum()
    highs_above = (h15[i_lo:i_hi] > latest_lvl).sum()
    print(f"  15m closes ABOVE FH level: {closes_above}")
    print(f"  15m highs ABOVE FH level (wick BOS): {highs_above}")
    # When was first close above?
    first_above_idx = np.argmax(cl15[i_lo:i_hi] > latest_lvl) if closes_above > 0 else None
    if closes_above > 0:
        first_bar = cans_15m[i_lo + int(first_above_idx)]
        print(f"  First close > FH at {fmt(first_bar.open_time)}: C={first_bar.close:.0f}")
