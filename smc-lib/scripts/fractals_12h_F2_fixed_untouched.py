"""F2 с правильным "untouched" — для OB и других зон с границей на cur.close:
  first re-entry after price exited the zone (а не сразу).

Применяется ко всем элементам (OB, FVG, ob_liq, marubozu, RB, block_orders,
RDRB POI, i_RDRB POI, fractal levels) на 12h/D/2D/3D/W.
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

# 1m
ts_arr = np.array([r[0] for r in data], dtype=np.int64)
hi_arr = np.array([r[2] for r in data], dtype=np.float64)
lo_arr = np.array([r[3] for r in data], dtype=np.float64)


cl_arr = np.array([r[4] for r in data], dtype=np.float64)


def first_reentry_zone(zone_lo, zone_hi, direction, formation_ts):
    """SMC-canon mitigation: zone violated when CLOSE breaks border (not wick).

    SHORT zone: violated when 1m close > zone_hi (close above resistance)
    LONG zone:  violated when 1m close < zone_lo (close below support)

    Wick touches don't invalidate (test ≠ break).
    """
    i0 = int(np.searchsorted(ts_arr, formation_ts, side='left'))
    if i0 >= len(ts_arr): return None
    if direction == "short":
        mask = cl_arr[i0:] > zone_hi
    else:
        mask = cl_arr[i0:] < zone_lo
    nz = int(np.argmax(mask))
    if not mask[nz]: return None
    return int(ts_arr[i0 + nz])


def first_touch_zone_simple(zone_lo, zone_hi, formation_ts):
    """Простая версия для FVG, RDRB POI, fractal points — overlap test."""
    i0 = int(np.searchsorted(ts_arr, formation_ts, side='left'))
    if i0 >= len(ts_arr): return None
    mask = (lo_arr[i0:] <= zone_hi) & (hi_arr[i0:] >= zone_lo)
    nz = int(np.argmax(mask))
    if not mask[nz]: return None
    return int(ts_arr[i0 + nz])


def first_sweep_level(level, direction, formation_ts):
    """Для fractal — wick beyond level."""
    i0 = int(np.searchsorted(ts_arr, formation_ts, side='left'))
    if i0 >= len(ts_arr): return None
    if direction == "high":
        mask = hi_arr[i0:] > level
    else:
        mask = lo_arr[i0:] < level
    nz = int(np.argmax(mask))
    if not mask[nz]: return None
    return int(ts_arr[i0 + nz])


def fmt(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(MSK).strftime('%m-%d %H:%M')


def map_dir(d):
    if d in ("long", "bottom"): return "long"
    if d in ("short", "top"): return "short"
    return d


# === Build zones with proper untouched logic ===
zones = []


def add_ob(tf, kind, direction, lo, hi, formation_ts):
    """OB-like zone: use re-entry logic."""
    if hi < lo: lo, hi = hi, lo
    ft = first_reentry_zone(lo, hi, map_dir(direction), formation_ts)
    zones.append({"tf": tf, "kind": kind, "direction": map_dir(direction),
                  "lo": lo, "hi": hi, "formation_ts": formation_ts,
                  "first_touch_ts": ft})


def add_fvg_like(tf, kind, direction, lo, hi, formation_ts):
    """FVG-like — простой overlap test (зона "in gap" сразу актуальна, нет boundary issue)."""
    if hi < lo: lo, hi = hi, lo
    ft = first_touch_zone_simple(lo, hi, formation_ts)
    zones.append({"tf": tf, "kind": kind, "direction": map_dir(direction),
                  "lo": lo, "hi": hi, "formation_ts": formation_ts,
                  "first_touch_ts": ft})


def add_fractal_lvl(tf, level, direction, confirm_ts):
    """Fractal — sweep-based."""
    ft = first_sweep_level(level, direction, confirm_ts)
    zones.append({"tf": tf, "kind": "FRACTAL_LVL",
                  "direction": "short" if direction == "high" else "long",
                  "lo": level, "hi": level, "formation_ts": confirm_ts,
                  "first_touch_ts": ft})


print("Detecting elements...")
for tf_name, cands in cans_by_tf.items():
    tf_ms = tf_ms_map[tf_name]
    n_c = len(cands)

    # Fractals (points)
    for i in range(2, n_c - 2):
        f = detect_fractal(cands[i-2:i+3], n=2)
        if f is None: continue
        confirm_ts = cands[i].open_time + 3 * tf_ms
        add_fractal_lvl(tf_name, f.level, f.direction, confirm_ts)

    # OB
    for i in range(n_c - 1):
        ob = detect_ob(cands[i], cands[i+1])
        if ob is None: continue
        ft_ts = cands[i+1].open_time + tf_ms
        add_ob(tf_name, "OB", ob.direction, ob.zone[0], ob.zone[1], ft_ts)

    # FVG (gap — simple overlap)
    for i in range(n_c - 2):
        f = detect_fvg(cands[i], cands[i+1], cands[i+2])
        if f is None: continue
        ft_ts = cands[i+2].open_time + tf_ms
        add_fvg_like(tf_name, "FVG", f.direction, f.zone[0], f.zone[1], ft_ts)

    # RB (wick zone — like OB, boundary at body)
    for c in cands:
        rb = detect_rb(c)
        if rb is None: continue
        ft_ts = c.open_time + tf_ms
        add_ob(tf_name, "RB", rb.direction, rb.zone[0], rb.zone[1], ft_ts)

    # Marubozu (body — boundary at open) — use re-entry
    for c in cands:
        m = detect_marubozu(c)
        if m is None: continue
        ft_ts = c.open_time + tf_ms
        add_ob(tf_name, "MARU_body", m.direction, m.zone[0], m.zone[1], ft_ts)
        # Open point — re-entry
        add_ob(tf_name, "MARU_open", m.direction, c.open, c.open, ft_ts)

    # ob_liq
    for i in range(2, n_c - 2):
        obl = detect_ob_liq(cands[i], cands[i+1])
        if obl is None: continue
        ft_ts = cands[i+2].open_time + tf_ms
        add_ob(tf_name, "OB_LIQ", obl.direction, obl.zone[0], obl.zone[1], ft_ts)
        add_ob(tf_name, "OB_LIQ_liq", obl.direction, obl.liq_zone[0], obl.liq_zone[1], ft_ts)

    # RDRB / i-RDRB
    for i in range(n_c - 2):
        r = detect_rdrb(cands[i], cands[i+1], cands[i+2])
        if r is None: continue
        ft_ts = cands[i+2].open_time + tf_ms
        add_ob(tf_name, "RDRB_POI", r.direction, r.poi[0], r.poi[1], ft_ts)
    for i in range(n_c - 3):
        ir = detect_i_rdrb(cands[i], cands[i+1], cands[i+2], cands[i+3])
        if ir is None: continue
        ft_ts = cands[i+3].open_time + tf_ms
        add_ob(tf_name, "I_RDRB_POI", ir.direction, ir.rdrb.poi[0], ir.rdrb.poi[1], ft_ts)

    # block_orders
    for i in range(n_c - 2):
        bo = detect_block_orders(cands[i:i+min(8, n_c - i)])
        if bo is None: continue
        last_idx = i + bo.n_initial + bo.n_counter
        if last_idx >= n_c: continue
        ft_ts = cands[last_idx - 1].open_time + tf_ms
        add_ob(tf_name, "BLOCK_ORD", bo.direction, bo.zone[0], bo.zone[1], ft_ts)


print(f"Total zones: {len(zones)}")
by_kind = {}
for z in zones: by_kind[z["kind"]] = by_kind.get(z["kind"], 0) + 1
for k in sorted(by_kind): print(f"  {k}: {by_kind[k]}")


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


# === F2 ===
def dir_matches(fd, zd):
    return (fd == "high" and zd == "short") or (fd == "low" and zd == "long")


def find_zones(f, match_dir=True, tfs=None, use_level=True):
    """use_level=True: pivot.level must be inside zone (strict).
       use_level=False: pivot.range [low, high] overlaps zone (loose)."""
    pivot_open = f["center_ts"]
    pivot_lo, pivot_hi = f["pivot_low"], f["pivot_high"]
    pivot_level = f["level"]
    out = []
    for z in zones:
        if tfs is not None and z["tf"] not in tfs: continue
        if z["formation_ts"] >= pivot_open: continue
        if z["first_touch_ts"] is not None and z["first_touch_ts"] < pivot_open:
            continue
        if match_dir and not dir_matches(f["dir"], z["direction"]):
            continue
        if use_level:
            if not (z["lo"] <= pivot_level <= z["hi"]):
                continue
        else:
            if max(z["lo"], pivot_lo) > min(z["hi"], pivot_hi):
                continue
        out.append(z)
    return out


all_tfs = {"12h", "D", "2D", "3D", "W"}

for f in fractals:
    f["F2_zones"] = find_zones(f, match_dir=True, tfs=all_tfs, use_level=True)
    f["F2_pass"] = len(f["F2_zones"]) >= 1
    f["F2_zones_loose"] = find_zones(f, match_dir=True, tfs=all_tfs, use_level=False)


# === Rescue features ===
# R1: pivot.level — new HTF extreme vs all CONFIRMED same-type HTF fractals
# Get all confirmed HTF fractals for D/2D/3D/W
htf_fr = {tf: [] for tf in ("D", "2D", "3D", "W")}
for tf in ("D", "2D", "3D", "W"):
    cands = cans_by_tf[tf]
    tf_ms = tf_ms_map[tf]
    for i in range(2, len(cands) - 2):
        fr = detect_fractal(cands[i-2:i+3], n=2)
        if fr is None: continue
        htf_fr[tf].append({"dir": fr.direction, "level": fr.level,
                           "confirm_ts": cands[i].open_time + 3 * tf_ms})


def rescue_new_htf_extreme(f):
    """pivot.level выше всех ранее CONFIRMED same-type fractal levels на D/2D/3D/W."""
    for tf in ("D", "2D", "3D", "W"):
        for fr in htf_fr[tf]:
            if fr["confirm_ts"] > f["center_ts"]: continue  # not yet confirmed
            if fr["dir"] != f["dir"]: continue
            if f["dir"] == "high":
                if fr["level"] >= f["level"]: return False  # есть прошлый HH/equal
            else:
                if fr["level"] <= f["level"]: return False  # есть прошлый LL/equal
    return True


def rescue_new_n_day(f, N_days=30):
    """pivot.level выше max high (или ниже min low) последних N D-bars."""
    barsD = bars_by_tf["D"]
    d_idx = next((j for j, b in enumerate(barsD) if b[0] + TF_D_MS > f["center_ts"]), len(barsD)) - 1
    if d_idx < N_days: return False
    win = barsD[d_idx - N_days:d_idx]
    if f["dir"] == "high":
        return f["level"] > max(b[2] for b in win)
    else:
        return f["level"] < min(b[3] for b in win)


for f in fractals:
    f["rescue_new_htf"] = rescue_new_htf_extreme(f)
    f["rescue_new_30d"] = rescue_new_n_day(f, 30)
    f["rescue_new_60d"] = rescue_new_n_day(f, 60)


post_F1 = [f for f in fractals if f["F1_pass"]]

print(f"\n{'='*180}")
print(f" F1 ∩ F2 (после FIX untouched logic)")
print(f"{'='*180}")
print(f"{'#':>3} {'★':>1} {'tp':>3} {'center':<14} {'level':>6} {'F2':>3} {'cnt':>3}  {'zones':<60}")
print("-" * 180)
for f in post_F1:
    star = "★" if f["is_important"] else " "
    glyph = "FH" if f["dir"] == "high" else "FL"
    zl = ", ".join(f"{z['tf']}/{z['kind']}/{z['direction'][0]}" for z in f["F2_zones"][:5])
    if len(f["F2_zones"]) > 5: zl += f" +{len(f['F2_zones'])-5}"
    print(f"{f['num']:>3} {star:>1} {glyph:>3} {fmt(f['center_ts']):<14} {f['level']:>6.0f} "
          f"{'Y' if f['F2_pass'] else '·':>3} "
          f"{len(f['F2_zones']):>3}  {zl:<60}")


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
print(f" F1 ∩ F2 evaluation")
print(f"{'='*120}")
eval_filter("F2 STRICT = pivot.level ∈ untouched zone", lambda f: f["F2_pass"])
eval_filter("F2 STRICT = ≥2 such zones", lambda f: len(f["F2_zones"]) >= 2)
eval_filter("F2 STRICT = ≥3 such zones", lambda f: len(f["F2_zones"]) >= 3)
eval_filter("F2 LOOSE = pivot.range overlaps untouched zone", lambda f: len(f["F2_zones_loose"]) >= 1)

print(f"\n--- Rescue tests (parallel OR с F2 STRICT) ---")
eval_filter("Rescue R1: new HTF extreme (vs all confirmed HTF fr)", lambda f: f["rescue_new_htf"])
eval_filter("Rescue R2: new 30D high/low", lambda f: f["rescue_new_30d"])
eval_filter("Rescue R3: new 60D high/low", lambda f: f["rescue_new_60d"])
print()
eval_filter("F2_STRICT OR R1", lambda f: f["F2_pass"] or f["rescue_new_htf"])
eval_filter("F2_STRICT OR R2 (30D)", lambda f: f["F2_pass"] or f["rescue_new_30d"])
eval_filter("F2_STRICT OR R3 (60D)", lambda f: f["F2_pass"] or f["rescue_new_60d"])

# Detail
print(f"\n--- Rescue detail for the lost #48 ---")
for f in post_F1:
    if f["num"] != 48: continue
    print(f"  #48 FH 82850: F2={f['F2_pass']} R1={f['rescue_new_htf']} R2={f['rescue_new_30d']} R3={f['rescue_new_60d']}")
