"""F2 с relaxed ob_liq (без Williams 5-bar требования).

Relaxed ob_liq:
  1. Direction: LONG (prev bear, cur bull, cur.close > prev.open)
                SHORT (prev bull, cur bear, cur.close < prev.open)
  2. prev_wick > 3 × cur_wick (соответствующей стороны)
  3. prev_wick > prev_body

Williams 5-bar — НЕ требуется.

Зоны: те же что canon ob_liq:
  Зона входа = canon-OB
  liq_zone маркер
"""
from __future__ import annotations

import csv
import pathlib
import sys
from datetime import datetime, timezone, timedelta
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from candle import Candle
from elements.fractal.code import detect_fractal
from elements.fvg.code import detect_fvg
from elements.ob.code import detect_ob
from elements.ob_liq.code import detect_ob_liq
from elements.marubozu.code import detect_marubozu
from elements.rb.code import detect_rb
from elements.rdrb.code import detect_rdrb
from elements.i_rdrb.code import detect_i_rdrb
from elements.block_orders.code import detect_block_orders

CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MSK = timezone(timedelta(hours=3))
MS_HOUR = 3600_000
TF12_MS = 12 * MS_HOUR
TF_D_MS = 24 * MS_HOUR
TF_2D_MS = 48 * MS_HOUR
TF_3D_MS = 72 * MS_HOUR
TF_W_MS = 7 * 24 * MS_HOUR

START_MS = int(datetime(2026, 2, 4, 0, 0, tzinfo=MSK).timestamp() * 1000)
IMPORTANT = {1, 3, 4, 5, 9, 10, 11, 14, 15, 20, 23, 26, 29, 40, 41, 42, 47, 48}


def detect_ob_liq_relaxed(prev: Candle, cur: Candle):
    """Relaxed ob_liq — без Williams 5-bar. Returns (direction, zone, liq_zone) или None."""
    if prev.is_bear and cur.is_bull and cur.close > prev.open:
        prev_lower = min(prev.open, prev.close) - prev.low
        cur_lower = min(cur.open, cur.close) - cur.low
        prev_body = abs(prev.open - prev.close)
        if prev_lower <= 3 * cur_lower: return None
        if prev_lower <= prev_body: return None
        zone = (min(prev.low, cur.low), prev.open)
        liq_zone = (prev.low, cur.low) if prev.low < cur.low else (cur.low, prev.low)
        return "long", zone, liq_zone
    if prev.is_bull and cur.is_bear and cur.close < prev.open:
        prev_upper = prev.high - max(prev.open, prev.close)
        cur_upper = cur.high - max(cur.open, cur.close)
        prev_body = abs(prev.open - prev.close)
        if prev_upper <= 3 * cur_upper: return None
        if prev_upper <= prev_body: return None
        zone = (prev.open, max(prev.high, cur.high))
        liq_zone = (cur.high, prev.high) if cur.high < prev.high else (prev.high, cur.high)
        return "short", zone, liq_zone
    return None


def load_1m():
    rows = []
    with CSV_PATH.open() as f:
        rd = csv.reader(f); next(rd)
        for r in rd:
            t = datetime.fromisoformat(r[0])
            rows.append((int(t.timestamp() * 1000),
                         float(r[1]), float(r[2]), float(r[3]), float(r[4])))
    return rows


def aggregate(d, tf_ms):
    out = []; cb = None; o = h = l = c = 0.0
    for ts, oo, hh, ll, cc in d:
        b = ts - (ts % tf_ms)
        if b != cb:
            if cb is not None: out.append((cb, o, h, l, c))
            cb = b; o, h, l, c = oo, hh, ll, cc
        else:
            h = max(h, hh); l = min(l, ll); c = cc
    if cb is not None: out.append((cb, o, h, l, c))
    return out


def aggregate_weekly_mon(d):
    week_ms = 7 * 24 * 3600 * 1000
    mon_anchor = 1483315200000
    out = []; cb = None; o = h = l = c = 0.0
    for ts, oo, hh, ll, cc in d:
        offset = (ts - mon_anchor) % week_ms
        b = ts - offset
        if b != cb:
            if cb is not None: out.append((cb, o, h, l, c))
            cb = b; o, h, l, c = oo, hh, ll, cc
        else:
            h = max(h, hh); l = min(l, ll); c = cc
    if cb is not None: out.append((cb, o, h, l, c))
    return out


print("Loading...")
data = load_1m()

bars_by_tf = {
    "12h": aggregate(data, TF12_MS),
    "D":   aggregate(data, TF_D_MS),
    "2D":  aggregate(data, TF_2D_MS),
    "3D":  aggregate(data, TF_3D_MS),
    "W":   aggregate_weekly_mon(data),
}
tf_ms_map = {"12h": TF12_MS, "D": TF_D_MS, "2D": TF_2D_MS, "3D": TF_3D_MS, "W": TF_W_MS}
cans_by_tf = {tf: [Candle(open=b[1], high=b[2], low=b[3], close=b[4], open_time=b[0])
                   for b in bars] for tf, bars in bars_by_tf.items()}

ts_arr = np.array([r[0] for r in data], dtype=np.int64)
hi_arr = np.array([r[2] for r in data], dtype=np.float64)
lo_arr = np.array([r[3] for r in data], dtype=np.float64)
cl_arr = np.array([r[4] for r in data], dtype=np.float64)


def first_touch_simple(zone_lo, zone_hi, formation_ts):
    """Simple: любое overlap = touched."""
    i0 = int(np.searchsorted(ts_arr, formation_ts, side='left'))
    if i0 >= len(ts_arr): return None
    mask = (lo_arr[i0:] <= zone_hi) & (hi_arr[i0:] >= zone_lo)
    nz = int(np.argmax(mask))
    if not mask[nz]: return None
    return int(ts_arr[i0 + nz])


def first_close_mitigation(zone_lo, zone_hi, direction, formation_ts):
    """SMC canon: close > zone_hi (SHORT) или close < zone_lo (LONG)."""
    i0 = int(np.searchsorted(ts_arr, formation_ts, side='left'))
    if i0 >= len(ts_arr): return None
    if direction == "short":
        mask = cl_arr[i0:] > zone_hi
    else:
        mask = cl_arr[i0:] < zone_lo
    nz = int(np.argmax(mask))
    if not mask[nz]: return None
    return int(ts_arr[i0 + nz])


def first_sweep_level(level, direction, formation_ts):
    i0 = int(np.searchsorted(ts_arr, formation_ts, side='left'))
    if i0 >= len(ts_arr): return None
    if direction == "high":
        mask = hi_arr[i0:] > level
    else:
        mask = lo_arr[i0:] < level
    nz = int(np.argmax(mask))
    if not mask[nz]: return None
    return int(ts_arr[i0 + nz])


def map_dir(d):
    if d in ("long", "bottom"): return "long"
    if d in ("short", "top"): return "short"
    return d


def fmt(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(MSK).strftime('%m-%d %H:%M')


# Build zones with TWO touch versions
zones = []


def add_zone(tf, kind, direction, lo, hi, formation_ts, is_level=False):
    if hi < lo: lo, hi = hi, lo
    ft_simple = first_touch_simple(lo, hi, formation_ts)
    if is_level:
        d = "high" if direction == "short" else "low"
        ft_canon = first_sweep_level(lo, d, formation_ts)
    else:
        ft_canon = first_close_mitigation(lo, hi, map_dir(direction), formation_ts)
    zones.append({"tf": tf, "kind": kind, "direction": map_dir(direction),
                  "lo": lo, "hi": hi, "formation_ts": formation_ts,
                  "first_touch_simple": ft_simple,
                  "first_touch_canon": ft_canon})


print("Detecting elements (with RELAXED ob_liq)...")
canon_obliq_count = 0
relaxed_obliq_count = 0
for tf_name, cands in cans_by_tf.items():
    tf_ms = tf_ms_map[tf_name]
    n_c = len(cands)

    # Fractals (points)
    for i in range(2, n_c - 2):
        f = detect_fractal(cands[i-2:i+3], n=2)
        if f is None: continue
        confirm_ts = cands[i].open_time + 3 * tf_ms
        add_zone(tf_name, "FRACTAL_LVL", "short" if f.direction == "high" else "long",
                 f.level, f.level, confirm_ts, is_level=True)

    # OB
    for i in range(n_c - 1):
        ob = detect_ob(cands[i], cands[i+1])
        if ob is None: continue
        ft_ts = cands[i+1].open_time + tf_ms
        add_zone(tf_name, "OB", ob.direction, ob.zone[0], ob.zone[1], ft_ts)

    # FVG
    for i in range(n_c - 2):
        f = detect_fvg(cands[i], cands[i+1], cands[i+2])
        if f is None: continue
        ft_ts = cands[i+2].open_time + tf_ms
        add_zone(tf_name, "FVG", f.direction, f.zone[0], f.zone[1], ft_ts)

    # RB
    for c in cands:
        rb = detect_rb(c)
        if rb is None: continue
        ft_ts = c.open_time + tf_ms
        add_zone(tf_name, "RB", rb.direction, rb.zone[0], rb.zone[1], ft_ts)

    # Marubozu
    for c in cands:
        m = detect_marubozu(c)
        if m is None: continue
        ft_ts = c.open_time + tf_ms
        add_zone(tf_name, "MARU_body", m.direction, m.zone[0], m.zone[1], ft_ts)
        add_zone(tf_name, "MARU_open", m.direction, c.open, c.open, ft_ts)

    # CANON ob_liq (для статистики)
    for i in range(2, n_c - 2):
        obl = detect_ob_liq(cands[i], cands[i+1])
        if obl is None: continue
        canon_obliq_count += 1
        # NB: только canon-вариант помечен как OB_LIQ_canon (если хотим отличить)
        # Но в общем мы заменяем на relaxed ниже, поэтому canon только для подсчёта

    # RELAXED ob_liq — на каждой паре (i, i+1)
    for i in range(n_c - 1):
        res = detect_ob_liq_relaxed(cands[i], cands[i+1])
        if res is None: continue
        direction, zone, liq_zone = res
        ft_ts = cands[i+1].open_time + tf_ms
        relaxed_obliq_count += 1
        add_zone(tf_name, "OB_LIQ_relaxed", direction, zone[0], zone[1], ft_ts)
        add_zone(tf_name, "OB_LIQ_relaxed_liq", direction, liq_zone[0], liq_zone[1], ft_ts)

    # RDRB / i-RDRB
    for i in range(n_c - 2):
        r = detect_rdrb(cands[i], cands[i+1], cands[i+2])
        if r is None: continue
        ft_ts = cands[i+2].open_time + tf_ms
        add_zone(tf_name, "RDRB_POI", r.direction, r.poi[0], r.poi[1], ft_ts)
    for i in range(n_c - 3):
        ir = detect_i_rdrb(cands[i], cands[i+1], cands[i+2], cands[i+3])
        if ir is None: continue
        ft_ts = cands[i+3].open_time + tf_ms
        add_zone(tf_name, "I_RDRB_POI", ir.direction, ir.rdrb.poi[0], ir.rdrb.poi[1], ft_ts)

    # block_orders
    for i in range(n_c - 2):
        bo = detect_block_orders(cands[i:i+min(8, n_c - i)])
        if bo is None: continue
        last_idx = i + bo.n_initial + bo.n_counter
        if last_idx >= n_c: continue
        ft_ts = cands[last_idx - 1].open_time + tf_ms
        add_zone(tf_name, "BLOCK_ORD", bo.direction, bo.zone[0], bo.zone[1], ft_ts)

print(f"  canon ob_liq detections: {canon_obliq_count}")
print(f"  RELAXED ob_liq detections: {relaxed_obliq_count}")
print(f"  total zones: {len(zones)}")


# === 12h fractals (target) ===
fractals = []
for i in range(2, len(cans_by_tf["12h"]) - 2):
    f = detect_fractal(cans_by_tf["12h"][i-2:i+3], n=2)
    if f is None: continue
    c = cans_by_tf["12h"][i]
    if c.open_time < START_MS: continue
    fractals.append({"dir": f.direction, "level": f.level, "idx": i,
                     "center_ts": c.open_time,
                     "pivot_low": c.low, "pivot_high": c.high})


def left_ext_5(f):
    bidx = f["idx"]
    bars12 = bars_by_tf["12h"]
    win_lo = max(0, bidx - 5); win_hi = bidx
    slice_ = bars12[win_lo:win_hi]
    if not slice_: return True
    if f["dir"] == "high":
        return f["level"] > max(b[2] for b in slice_)
    else:
        return f["level"] < min(b[3] for b in slice_)


for n, f in enumerate(fractals, 1):
    f["num"] = n
    f["is_important"] = (n in IMPORTANT)
    f["F1_pass"] = left_ext_5(f)


def dir_matches(fd, zd):
    return (fd == "high" and zd == "short") or (fd == "low" and zd == "long")


def find_zones(f, untouched_mode="simple", match_dir=True, use_level=False, kinds_filter=None):
    """untouched_mode: 'simple' or 'canon'."""
    pivot_open = f["center_ts"]
    pivot_lo, pivot_hi = f["pivot_low"], f["pivot_high"]
    pivot_level = f["level"]
    ft_key = "first_touch_simple" if untouched_mode == "simple" else "first_touch_canon"
    out = []
    for z in zones:
        if kinds_filter is not None and z["kind"] not in kinds_filter: continue
        if z["formation_ts"] >= pivot_open: continue
        if z[ft_key] is not None and z[ft_key] < pivot_open:
            continue
        if match_dir and not dir_matches(f["dir"], z["direction"]):
            continue
        if use_level:
            if not (z["lo"] <= pivot_level <= z["hi"]): continue
        else:
            if max(z["lo"], pivot_lo) > min(z["hi"], pivot_hi): continue
        out.append(z)
    return out


post_F1 = [f for f in fractals if f["F1_pass"]]


def eval_filter(name, pred):
    kept = [f for f in post_F1 if pred(f)]
    imp_kept = sum(1 for f in kept if f["is_important"])
    imp_lost = 18 - imp_kept
    noise_kept = len(kept) - imp_kept
    recall = imp_kept / 18 * 100
    prec = imp_kept / len(kept) * 100 if kept else 0
    f1 = 2 * recall * prec / (recall + prec) if (recall + prec) > 0 else 0
    print(f"  {name:<60} keep={len(kept):>3}  imp={imp_kept:>2}/18  "
          f"lost={imp_lost:>2}  noise={noise_kept:>3}  "
          f"recall={recall:>5.1f}%  prec={prec:>5.1f}%  F1={f1:>5.1f}")
    if imp_lost > 0 and imp_lost <= 10:
        lost_ids = [f["num"] for f in post_F1 if f["is_important"] and not pred(f)]
        print(f"      lost: {lost_ids}")


print(f"\n{'='*120}")
print(f" F2 simple first_touch (изначальный режим) — С relaxed ob_liq")
print(f"{'='*120}")
for f in post_F1:
    f["F2_simple_range"] = len(find_zones(f, "simple", True, use_level=False)) >= 1
    f["F2_simple_level"] = len(find_zones(f, "simple", True, use_level=True)) >= 1
eval_filter("F2 = pivot.range overlap untouched zone (simple)", lambda f: f["F2_simple_range"])
eval_filter("F2 = pivot.level ∈ untouched zone (simple)", lambda f: f["F2_simple_level"])

print(f"\n{'='*120}")
print(f" F2 canon SMC close-mitigation — С relaxed ob_liq")
print(f"{'='*120}")
for f in post_F1:
    f["F2_canon_range"] = find_zones(f, "canon", True, use_level=False)
    f["F2_canon_level"] = find_zones(f, "canon", True, use_level=True)
eval_filter("F2 = ≥1 untouched zone overlap (canon range)", lambda f: len(f["F2_canon_range"]) >= 1)
eval_filter("F2 = ≥1 untouched zone (canon level in zone)", lambda f: len(f["F2_canon_level"]) >= 1)
eval_filter("F2 = ≥2 untouched zones (canon range)", lambda f: len(f["F2_canon_range"]) >= 2)
eval_filter("F2 = ≥2 untouched zones (canon level in zone)", lambda f: len(f["F2_canon_level"]) >= 2)
eval_filter("F2 = ≥3 untouched zones (canon range)", lambda f: len(f["F2_canon_range"]) >= 3)
eval_filter("F2 = ≥3 untouched zones (canon level in zone)", lambda f: len(f["F2_canon_level"]) >= 3)
eval_filter("F2 = ≥5 untouched zones (canon range)", lambda f: len(f["F2_canon_range"]) >= 5)
eval_filter("F2 = ≥5 untouched zones (canon level)", lambda f: len(f["F2_canon_level"]) >= 5)

# Show count distribution for important vs noise
print(f"\n--- Zone count distribution (canon range overlap) ---")
print(f"  {'#':>3} {'★':>1} {'tp':>3} {'level':>6} {'cnt':>4}")
for f in post_F1:
    star = "★" if f["is_important"] else " "
    glyph = "FH" if f["dir"] == "high" else "FL"
    print(f"  {f['num']:>3} {star:>1} {glyph:>3} {f['level']:>6.0f} {len(f['F2_canon_range']):>4}")


# Detail check for #5 specifically
print(f"\n--- Detail for #5 (FH 70983 at 02-15 03:00) ---")
f5 = next(f for f in post_F1 if f["num"] == 5)
print(f"  pivot range: [{f5['pivot_low']:.0f}, {f5['pivot_high']:.0f}]  level={f5['level']:.0f}")
zones_simple = find_zones(f5, "simple", True, use_level=False)
zones_canon = find_zones(f5, "canon", True, use_level=False)
print(f"\n  simple first_touch zones ({len(zones_simple)}):")
for z in zones_simple[:10]:
    print(f"    {z['tf']}/{z['kind']}/{z['direction']} [{z['lo']:.0f}, {z['hi']:.0f}] form={fmt(z['formation_ts'])}")
print(f"\n  canon SMC zones ({len(zones_canon)}):")
for z in zones_canon[:10]:
    print(f"    {z['tf']}/{z['kind']}/{z['direction']} [{z['lo']:.0f}, {z['hi']:.0f}] form={fmt(z['formation_ts'])}")

# Check 2D OB_LIQ_relaxed specifically для #5
print(f"\n  Check 2D OB_LIQ_relaxed near 02-08:")
for z in zones:
    if z["tf"] != "2D": continue
    if z["kind"] not in ("OB_LIQ_relaxed", "OB_LIQ_relaxed_liq"): continue
    if not (fmt(z["formation_ts"]).startswith("02-1") or fmt(z["formation_ts"]).startswith("02-0")): continue
    print(f"    {z['kind']}/{z['direction']} zone=[{z['lo']:.0f}, {z['hi']:.0f}] "
          f"form={fmt(z['formation_ts'])} "
          f"simple_touch={fmt(z['first_touch_simple']) if z['first_touch_simple'] else 'never'} "
          f"canon_touch={fmt(z['first_touch_canon']) if z['first_touch_canon'] else 'never'}")
