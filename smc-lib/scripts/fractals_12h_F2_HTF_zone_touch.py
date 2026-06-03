"""F2 кандидат — i.range взаимодействует с UNTOUCHED HTF зоной интереса.

Элементы (из smc-lib):
  - OB (canon, 2-candle)
  - FVG
  - marubozu (open level + body zone)
  - ob_liq

ТФ: 12h, D, W (W = Mon-anchor).

Condition (anti-look-ahead):
  - Zone formation_ts < i.open_ts (зона сформирована ДО i)
  - Zone first_touch_ts >= i.open_ts (untouched до прихода i)
  - i.range [low, high] пересекается с zone
  - direction match:
       FH (potential top) — взаимодействие с SHORT-зоной (resistance сверху)
       FL (potential bottom) — взаимодействие с LONG-зоной (support снизу)

Marubozu open trick:
  - Bull marubozu (open at low): open level — magnet снизу → для FL match
  - Bear marubozu (open at high): open level — magnet сверху → для FH match

Output: для каждого fractal — какие зоны прицеплены (по типу/ТФ), и proposed F2 = boolean (хотя бы одна).
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
from elements.marubozu.code import detect_marubozu

CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MSK = timezone(timedelta(hours=3))
MS_HOUR = 3600_000
TF12_MS = 12 * MS_HOUR
TF_D_MS = 24 * MS_HOUR
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

bars12 = aggregate(data, TF12_MS)
barsD = aggregate(data, TF_D_MS)
barsW = aggregate_weekly_mon(data)


def to_candles(bars):
    return [Candle(open=b[1], high=b[2], low=b[3], close=b[4], open_time=b[0]) for b in bars]


can12 = to_candles(bars12); canD = to_candles(barsD); canW = to_candles(barsW)


# 1m arrays для first_touch checking
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
    i0 = int(np.searchsorted(ts_arr, after_ts, side='left'))
    if i0 >= len(ts_arr): return None
    mask = (lo_arr[i0:] <= level) & (hi_arr[i0:] >= level)
    nz = int(np.argmax(mask))
    if not mask[nz]: return None
    return int(ts_arr[i0 + nz])


def fmt(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(MSK).strftime('%m-%d %H:%M')


# === Build HTF zones ===
# Zone = {tf, kind, direction, lo, hi, formation_ts, first_touch_ts}
zones = []


def add_obs(cands, tf_ms, tf_name):
    for i in range(len(cands) - 1):
        ob = detect_ob(cands[i], cands[i+1])
        if ob is None: continue
        formation_ts = cands[i+1].open_time + tf_ms  # cur.close = formation
        ft = first_touch_zone(ob.zone[0], ob.zone[1], formation_ts)
        zones.append({"tf": tf_name, "kind": "OB", "direction": ob.direction,
                      "lo": ob.zone[0], "hi": ob.zone[1],
                      "formation_ts": formation_ts, "first_touch_ts": ft})


def add_fvgs(cands, tf_ms, tf_name):
    for i in range(len(cands) - 2):
        f = detect_fvg(cands[i], cands[i+1], cands[i+2])
        if f is None: continue
        formation_ts = cands[i+2].open_time + tf_ms
        ft = first_touch_zone(f.zone[0], f.zone[1], formation_ts)
        zones.append({"tf": tf_name, "kind": "FVG", "direction": f.direction,
                      "lo": f.zone[0], "hi": f.zone[1],
                      "formation_ts": formation_ts, "first_touch_ts": ft})


def add_marubozu(cands, tf_ms, tf_name):
    for c in cands:
        m = detect_marubozu(c)
        if m is None: continue
        formation_ts = c.open_time + tf_ms
        # body zone
        ft_body = first_touch_zone(m.zone[0], m.zone[1], formation_ts)
        zones.append({"tf": tf_name, "kind": "MARU_body", "direction": m.direction,
                      "lo": m.zone[0], "hi": m.zone[1],
                      "formation_ts": formation_ts, "first_touch_ts": ft_body})
        # open as point magnet
        ft_open = first_touch_point(c.open, formation_ts)
        # represent open level as tiny zone
        zones.append({"tf": tf_name, "kind": "MARU_open", "direction": m.direction,
                      "lo": c.open, "hi": c.open,
                      "formation_ts": formation_ts, "first_touch_ts": ft_open})


print("Building HTF zones...")
for cands, ms, name in [(can12, TF12_MS, "12h"), (canD, TF_D_MS, "D"), (canW, TF_W_MS, "W")]:
    add_obs(cands, ms, name)
    add_fvgs(cands, ms, name)
    add_marubozu(cands, ms, name)
print(f"  total zones: {len(zones)}")

by_tf_kind = {}
for z in zones:
    key = (z["tf"], z["kind"])
    by_tf_kind[key] = by_tf_kind.get(key, 0) + 1
for k, v in sorted(by_tf_kind.items()):
    print(f"    {k[0]}/{k[1]}: {v}")


# === Detect 12h fractals from START ===
fractals = []
for i in range(2, len(can12) - 2):
    f = detect_fractal(can12[i-2:i+3], n=2)
    if f is None: continue
    if can12[i].open_time < START_MS: continue
    fractals.append({"dir": f.direction, "level": f.level, "idx": i,
                     "center_ts": can12[i].open_time,
                     "decision_ts": can12[i].open_time + TF12_MS,
                     "pivot_low": bars12[i][3], "pivot_high": bars12[i][2]})


# F1
def left_ext_5(f):
    bidx = f["idx"]
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


# === F2: HTF zone interaction ===
def fractal_dir_matches_zone(fractal_dir, zone_dir):
    """FH = top → match SHORT-zone (overhead resistance/inefficiency).
       FL = bottom → match LONG-zone (support)."""
    if fractal_dir == "high":
        return zone_dir == "short"
    else:
        return zone_dir == "long"


def find_interacting_zones(f, zones, requires_match=True, tfs_allowed=None):
    """Returns list of zones that interact with this pivot's range under causal conditions."""
    pivot_low = f["pivot_low"]; pivot_high = f["pivot_high"]
    pivot_open_ts = f["center_ts"]  # = bars12[i].open_time
    out = []
    for z in zones:
        if tfs_allowed is not None and z["tf"] not in tfs_allowed: continue
        # formation strictly before pivot opens
        if z["formation_ts"] >= pivot_open_ts: continue
        # untouched up to pivot.open (first_touch must be >= pivot_open_ts)
        if z["first_touch_ts"] is not None and z["first_touch_ts"] < pivot_open_ts:
            continue
        # direction match
        if requires_match and not fractal_dir_matches_zone(f["dir"], z["direction"]):
            continue
        # overlap with pivot range
        if max(z["lo"], pivot_low) <= min(z["hi"], pivot_high):
            out.append(z)
    return out


for f in fractals:
    f["zones_all"] = find_interacting_zones(f, zones, requires_match=True, tfs_allowed={"12h", "D", "W"})
    f["zones_DW"] = find_interacting_zones(f, zones, requires_match=True, tfs_allowed={"D", "W"})
    f["zones_W"] = find_interacting_zones(f, zones, requires_match=True, tfs_allowed={"W"})
    f["zones_any_dir"] = find_interacting_zones(f, zones, requires_match=False, tfs_allowed={"12h", "D", "W"})
    f["F2_pass"] = len(f["zones_all"]) >= 1
    f["F2_DW_pass"] = len(f["zones_DW"]) >= 1
    f["F2_W_pass"] = len(f["zones_W"]) >= 1
    f["F2_any_dir_pass"] = len(f["zones_any_dir"]) >= 1


# === Print table (after F1) ===
post_F1 = [f for f in fractals if f["F1_pass"]]
print(f"\n{'='*144}")
print(f" F2 = HTF zone interaction (после F1, 41 fractal)")
print(f"{'='*144}")
print(f"{'#':>3} {'★':>1} {'tp':>3} {'center':<14} {'level':>6} {'low':>6} {'high':>6} "
      f"{'F2':>3} {'F2dw':>4} {'F2W':>3} {'F2any':>5} {'zones (tf/kind/dir)':<50}")
print("-" * 144)
for f in post_F1:
    star = "★" if f["is_important"] else " "
    glyph = "FH" if f["dir"] == "high" else "FL"
    zlist = ", ".join(f"{z['tf']}/{z['kind']}/{z['direction'][0]}" for z in f["zones_all"][:4])
    if len(f["zones_all"]) > 4:
        zlist += f" +{len(f['zones_all'])-4}"
    print(f"{f['num']:>3} {star:>1} {glyph:>3} {fmt(f['center_ts']):<14} {f['level']:>6.0f} "
          f"{f['pivot_low']:>6.0f} {f['pivot_high']:>6.0f} "
          f"{'Y' if f['F2_pass'] else '·':>3} "
          f"{'Y' if f['F2_DW_pass'] else '·':>4} "
          f"{'Y' if f['F2_W_pass'] else '·':>3} "
          f"{'Y' if f['F2_any_dir_pass'] else '·':>5} "
          f"{zlist:<50}")


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
print(f" F1 ∩ F2 evaluation")
print(f"{'='*120}")
eval_filter("F2 = any HTF zone (12h/D/W) interaction", lambda f: f["F2_pass"])
eval_filter("F2 = D/W zone only (HTF stricter)", lambda f: f["F2_DW_pass"])
eval_filter("F2 = W zone only (weekly)", lambda f: f["F2_W_pass"])
eval_filter("F2 = any-direction zone interaction (no match)", lambda f: f["F2_any_dir_pass"])


# Specific element breakdowns
def has_zone_kind(f, kind):
    return any(z["kind"] == kind for z in f["zones_all"])

def has_zone_tf(f, tf):
    return any(z["tf"] == tf for z in f["zones_all"])


print()
eval_filter("F2 = at least one FVG zone", lambda f: any(z["kind"] == "FVG" for z in f["zones_all"]))
eval_filter("F2 = at least one OB zone", lambda f: any(z["kind"] == "OB" for z in f["zones_all"]))
eval_filter("F2 = at least one marubozu zone", lambda f: any(z["kind"] in ("MARU_open", "MARU_body") for z in f["zones_all"]))
print()
eval_filter("F2 = 12h zone only", lambda f: any(z["tf"] == "12h" for z in f["zones_all"]))
eval_filter("F2 = D zone only", lambda f: any(z["tf"] == "D" for z in f["zones_all"]))
eval_filter("F2 = W zone only", lambda f: any(z["tf"] == "W" for z in f["zones_all"]))
print()
eval_filter("F2 = ≥2 zone matches", lambda f: len(f["zones_all"]) >= 2)
eval_filter("F2 = ≥3 zone matches", lambda f: len(f["zones_all"]) >= 3)


# Lost important details (if any)
print(f"\n{'='*120}")
print(f" Detail: per-important breakdown")
print(f"{'='*120}")
for f in post_F1:
    if not f["is_important"]: continue
    zlist = "; ".join(f"{z['tf']}/{z['kind']}/{z['direction']}" for z in f["zones_all"])
    print(f"  #{f['num']:<3} {f['dir']:<4} {f['level']:>6.0f}  F2={'Y' if f['F2_pass'] else 'N'}  zones=[{zlist}]")
