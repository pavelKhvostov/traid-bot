"""F2: i.range взаимодействует с UNTOUCHED HTF зоной интереса.

Канонические зоны интереса (per zone_of_interest.md):
  - OB                   (canon 2-candle)
  - block_orders         (N₁ + N₂ composite)
  - RB                   (rejection block, single candle)
  - ob_liq               (canon OB + Williams 5-bar)
  - marubozu (body)      + marubozu_open (точка)
  - FVG
  - RDRB (POI)
  - i-RDRB (= rdrb.poi)

ТФ: 12h, D, 2D, 3D, W (Mon-anchor)

Conditions (anti-look-ahead):
  - zone.formation_ts < i.open_ts
  - zone.first_touch_ts >= i.open_ts (untouched до i)
  - i.range [low, high] пересекает zone

Direction matching:
  - FH (top) ↔ "short" / "top" zone (overhead)
  - FL (bottom) ↔ "long" / "bottom" zone (support)
  - + вариант "any-direction" для сравнения
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
for tf, c in cans_by_tf.items():
    print(f"  {tf}: {len(c)} bars")


# 1m arrays
ts_arr = np.array([r[0] for r in data], dtype=np.int64)
hi_arr = np.array([r[2] for r in data], dtype=np.float64)
lo_arr = np.array([r[3] for r in data], dtype=np.float64)


def first_touch_zone(zone_lo, zone_hi, after_ts):
    i0 = int(np.searchsorted(ts_arr, after_ts, side='left'))
    if i0 >= len(ts_arr): return None
    mask = (lo_arr[i0:] <= zone_hi) & (hi_arr[i0:] >= zone_lo)
    nz = int(np.argmax(mask))
    if not mask[nz]: return None
    return int(ts_arr[i0 + nz])


def first_touch_point(level, after_ts):
    return first_touch_zone(level, level, after_ts)


def fmt(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(MSK).strftime('%m-%d %H:%M')


# === Build zones across all TFs and elements ===
zones = []


def map_dir(d):
    """Canonicalize direction names to 'long'/'short'."""
    if d in ("long", "bottom"): return "long"
    if d in ("short", "top"): return "short"
    return d


def add_zone(tf, kind, direction, lo, hi, formation_ts):
    if hi < lo: lo, hi = hi, lo
    ft = first_touch_zone(lo, hi, formation_ts)
    zones.append({"tf": tf, "kind": kind, "direction": map_dir(direction),
                  "lo": lo, "hi": hi,
                  "formation_ts": formation_ts, "first_touch_ts": ft})


print("Detecting elements on all TFs...")
for tf_name, cands in cans_by_tf.items():
    tf_ms = tf_ms_map[tf_name]
    n_c = len(cands)

    # OB (2-candle)
    for i in range(n_c - 1):
        ob = detect_ob(cands[i], cands[i+1])
        if ob is None: continue
        ft_ts = cands[i+1].open_time + tf_ms  # confirmation = cur.close
        add_zone(tf_name, "OB", ob.direction, ob.zone[0], ob.zone[1], ft_ts)

    # FVG (3-candle)
    for i in range(n_c - 2):
        f = detect_fvg(cands[i], cands[i+1], cands[i+2])
        if f is None: continue
        ft_ts = cands[i+2].open_time + tf_ms
        add_zone(tf_name, "FVG", f.direction, f.zone[0], f.zone[1], ft_ts)

    # RB (single)
    for i, c in enumerate(cands):
        rb = detect_rb(c)
        if rb is None: continue
        ft_ts = c.open_time + tf_ms
        add_zone(tf_name, "RB", rb.direction, rb.zone[0], rb.zone[1], ft_ts)

    # marubozu (body + open point)
    for i, c in enumerate(cands):
        m = detect_marubozu(c)
        if m is None: continue
        ft_ts = c.open_time + tf_ms
        add_zone(tf_name, "MARU_body", m.direction, m.zone[0], m.zone[1], ft_ts)
        # open point as small zone
        add_zone(tf_name, "MARU_open", m.direction, c.open, c.open, ft_ts)

    # ob_liq (5-candle)
    for i in range(2, n_c - 2):
        obl = detect_ob_liq(cands[i], cands[i+1])
        if obl is None: continue
        ft_ts = cands[i+2].open_time + tf_ms
        add_zone(tf_name, "OB_LIQ", obl.direction, obl.zone[0], obl.zone[1], ft_ts)
        add_zone(tf_name, "OB_LIQ_liq", obl.direction, obl.liq_zone[0], obl.liq_zone[1], ft_ts)

    # RDRB (3-candle) — use POI as canonical zone
    for i in range(n_c - 2):
        r = detect_rdrb(cands[i], cands[i+1], cands[i+2])
        if r is None: continue
        ft_ts = cands[i+2].open_time + tf_ms
        add_zone(tf_name, "RDRB_POI", r.direction, r.poi[0], r.poi[1], ft_ts)

    # i-RDRB (4-candle) — uses inherited rdrb.poi (NB: direction = opposite of underlying RDRB)
    for i in range(n_c - 3):
        ir = detect_i_rdrb(cands[i], cands[i+1], cands[i+2], cands[i+3])
        if ir is None: continue
        ft_ts = cands[i+3].open_time + tf_ms
        add_zone(tf_name, "I_RDRB_POI", ir.direction, ir.rdrb.poi[0], ir.rdrb.poi[1], ft_ts)

    # block_orders (variable composite) — iterate possible starts, take longest valid block
    for i in range(n_c - 2):
        # Try block with up to 7 forward candles in window
        max_extent = min(8, n_c - i)
        bo = detect_block_orders(cands[i:i+max_extent])
        if bo is None: continue
        # ft_ts = close of last candle in block (last counter)
        last_idx = i + bo.n_initial + bo.n_counter
        if last_idx >= n_c: continue
        ft_ts = cands[last_idx - 1].open_time + tf_ms
        add_zone(tf_name, "BLOCK_ORD", bo.direction, bo.zone[0], bo.zone[1], ft_ts)


print(f"\nTotal zones built: {len(zones)}")
by_kind = {}
for z in zones:
    by_kind[z["kind"]] = by_kind.get(z["kind"], 0) + 1
for k in sorted(by_kind):
    print(f"  {k}: {by_kind[k]}")


# === Detect 12h fractals from START ===
fractals = []
for i in range(2, len(cans_by_tf["12h"]) - 2):
    f = detect_fractal(cans_by_tf["12h"][i-2:i+3], n=2)
    if f is None: continue
    c = cans_by_tf["12h"][i]
    if c.open_time < START_MS: continue
    fractals.append({"dir": f.direction, "level": f.level, "idx": i,
                     "center_ts": c.open_time,
                     "decision_ts": c.open_time + TF12_MS,
                     "pivot_low": c.low, "pivot_high": c.high})


# F1
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


# === F2 zone interactions ===
def dir_matches(fractal_dir, zone_dir):
    if fractal_dir == "high":
        return zone_dir == "short"
    return zone_dir == "long"


def find_zones(f, untouched=True, match_dir=True, tfs=None):
    pivot_open = f["center_ts"]
    pivot_lo, pivot_hi = f["pivot_low"], f["pivot_high"]
    out = []
    for z in zones:
        if tfs is not None and z["tf"] not in tfs: continue
        if z["formation_ts"] >= pivot_open: continue
        if untouched and z["first_touch_ts"] is not None and z["first_touch_ts"] < pivot_open:
            continue
        if match_dir and not dir_matches(f["dir"], z["direction"]):
            continue
        if max(z["lo"], pivot_lo) <= min(z["hi"], pivot_hi):
            out.append(z)
    return out


all_tfs = {"12h", "D", "2D", "3D", "W"}
htf_only = {"D", "2D", "3D", "W"}

for f in fractals:
    f["F2_match_untouched"] = find_zones(f, untouched=True, match_dir=True, tfs=all_tfs)
    f["F2_match_touched_ok"] = find_zones(f, untouched=False, match_dir=True, tfs=all_tfs)
    f["F2_any_dir_untouched"] = find_zones(f, untouched=True, match_dir=False, tfs=all_tfs)
    f["F2_any_dir_touched"] = find_zones(f, untouched=False, match_dir=False, tfs=all_tfs)
    f["F2_match_HTF_only"] = find_zones(f, untouched=True, match_dir=True, tfs=htf_only)


# Print table
post_F1 = [f for f in fractals if f["F1_pass"]]
print(f"\n{'='*180}")
print(f" F2: zone interactions (после F1, {len(post_F1)} fractals)")
print(f"{'='*180}")
print(f"{'#':>3} {'★':>1} {'tp':>3} {'center':<14} {'level':>6} "
      f"{'match_unt':>9} {'match_all':>9} {'any_unt':>7} {'any_all':>7} {'HTF_only':>8} "
      f"{'zone-list (match_unt)':<60}")
print("-" * 180)
for f in post_F1:
    star = "★" if f["is_important"] else " "
    glyph = "FH" if f["dir"] == "high" else "FL"
    zl = ", ".join(f"{z['tf']}/{z['kind']}/{z['direction'][0]}" for z in f["F2_match_untouched"][:5])
    if len(f["F2_match_untouched"]) > 5: zl += f" +{len(f['F2_match_untouched'])-5}"
    print(f"{f['num']:>3} {star:>1} {glyph:>3} {fmt(f['center_ts']):<14} {f['level']:>6.0f} "
          f"{len(f['F2_match_untouched']):>9} "
          f"{len(f['F2_match_touched_ok']):>9} "
          f"{len(f['F2_any_dir_untouched']):>7} "
          f"{len(f['F2_any_dir_touched']):>7} "
          f"{len(f['F2_match_HTF_only']):>8} "
          f"{zl:<60}")


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
    if imp_lost > 0 and imp_lost <= 8:
        lost_ids = [f["num"] for f in post_F1 if f["is_important"] and not pred(f)]
        print(f"      lost: {lost_ids}")


print(f"\n{'='*120}")
print(f" F1 ∩ F2 — все варианты")
print(f"{'='*120}")
eval_filter("F2 = match_dir UNTOUCHED (all TFs 12h..W)", lambda f: len(f["F2_match_untouched"]) >= 1)
eval_filter("F2 = match_dir UNTOUCHED OR touched-ok", lambda f: len(f["F2_match_touched_ok"]) >= 1)
eval_filter("F2 = any-dir UNTOUCHED", lambda f: len(f["F2_any_dir_untouched"]) >= 1)
eval_filter("F2 = any-dir ANY status (просто overlap с zone)", lambda f: len(f["F2_any_dir_touched"]) >= 1)
eval_filter("F2 = match_dir UNTOUCHED, HTF only (D..W, без 12h)", lambda f: len(f["F2_match_HTF_only"]) >= 1)

print()
eval_filter("F2 = ≥2 untouched matches", lambda f: len(f["F2_match_untouched"]) >= 2)
eval_filter("F2 = ≥3 untouched matches", lambda f: len(f["F2_match_untouched"]) >= 3)


# Per-element breakdown
print(f"\n--- по типу элемента (untouched match-dir) ---")
for kind in sorted(by_kind):
    eval_filter(f"F2 = at least one {kind}",
                lambda f, k=kind: any(z["kind"] == k for z in f["F2_match_untouched"]))
