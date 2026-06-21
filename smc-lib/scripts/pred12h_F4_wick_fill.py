"""F4 v2 — HTF zone interaction с CANONICAL wick-fill mitigation.

Правило wick-fill (canonical, см. ~/smc-lib/zone_of_interest.md):
  LONG zone [zone_lo, zone_hi]:
    consumed когда low ≤ zone_lo
    alive zone bounds: [zone_lo, min(zone_hi, min_low_pre_pivot)]
  SHORT zone:
    consumed когда high ≥ zone_hi
    alive zone bounds: [max(zone_lo, max_high_pre_pivot), zone_hi]

Особый случай ob_liq:
  Первое касание (high ≥ zone_lo для SHORT / low ≤ zone_hi для LONG) →
  ob_liq composite consumed → дальше как обычный OB (с тем же wick-fill).

Direction match:
  FH pivot → SHORT zone above (resistance)
  FL pivot → LONG zone below (support)

Test: F4 на 1266 candidates после F1∩F2∩F3.
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
            rows.append((int(t.timestamp() * 1000), float(r[1]), float(r[2]), float(r[3]), float(r[4])))
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


def detect_ob_liq_relaxed(prev, cur):
    if prev.is_bear and cur.is_bull and cur.close > prev.open:
        prev_lower = min(prev.open, prev.close) - prev.low
        cur_lower = min(cur.open, cur.close) - cur.low
        prev_body = abs(prev.open - prev.close)
        if prev_lower > 3 * cur_lower and prev_lower > prev_body:
            return "long", (min(prev.low, cur.low), prev.open)
    elif prev.is_bull and cur.is_bear and cur.close < prev.open:
        prev_upper = prev.high - max(prev.open, prev.close)
        cur_upper = cur.high - max(cur.open, cur.close)
        prev_body = abs(prev.open - prev.close)
        if prev_upper > 3 * cur_upper and prev_upper > prev_body:
            return "short", (prev.open, max(prev.high, cur.high))
    return None


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

last_ts = data[-1][0]
window_start_ms = last_ts - 6 * 365 * 24 * 3600 * 1000
bars12_w = [b for b in bars_by_tf["12h"] if b[0] >= window_start_ms]

# ATR(20) on 12h
hi12 = np.array([b[2] for b in bars12_w]); lo12 = np.array([b[3] for b in bars12_w])
cl12 = np.array([b[4] for b in bars12_w])
prev_cl = np.concatenate([[cl12[0]], cl12[:-1]])
tr12 = np.maximum.reduce([hi12-lo12, np.abs(hi12-prev_cl), np.abs(lo12-prev_cl)])
atr20 = np.zeros_like(tr12)
for i in range(len(tr12)):
    atr20[i] = tr12[:i+1].mean() if i < 19 else tr12[i-19:i+1].mean()

# 1m arrays
ts_arr = np.array([r[0] for r in data], dtype=np.int64)
hi_arr = np.array([r[2] for r in data], dtype=np.float64)
lo_arr = np.array([r[3] for r in data], dtype=np.float64)


def first_consumed_idx(zone_lo, zone_hi, direction, formation_ts):
    """First 1m idx where zone is fully consumed (wick reaches opposite border).
    LONG: consumed when low ≤ zone_lo.
    SHORT: consumed when high ≥ zone_hi.
    Returns len(ts_arr) if never consumed."""
    i0 = int(np.searchsorted(ts_arr, formation_ts, side='left'))
    if i0 >= len(ts_arr): return len(ts_arr)
    if direction == "long":
        mask = lo_arr[i0:] <= zone_lo
    else:
        mask = hi_arr[i0:] >= zone_hi
    nz = int(np.argmax(mask))
    if not mask[nz]: return len(ts_arr)
    return i0 + nz


def first_touch_idx(zone_lo, zone_hi, direction, formation_ts):
    """First 1m idx where zone first touched (any wick into zone).
    Used for ob_liq first-touch consumption + zone shrinking."""
    i0 = int(np.searchsorted(ts_arr, formation_ts, side='left'))
    if i0 >= len(ts_arr): return len(ts_arr)
    if direction == "long":
        # LONG zone above price after formation, but want zone touch from above
        # touch = low ≤ zone_hi (wick zashёl)
        mask = lo_arr[i0:] <= zone_hi
    else:
        # SHORT zone above price; touch from below = high ≥ zone_lo
        mask = hi_arr[i0:] >= zone_lo
    nz = int(np.argmax(mask))
    if not mask[nz]: return len(ts_arr)
    return i0 + nz


def map_dir(d):
    if d in ("long", "bottom"): return "long"
    if d in ("short", "top"): return "short"
    return d


# Build zones
print("Detecting HTF zones...")
zones = []


def add_zone(tf, kind, direction, lo, hi, formation_ts, ob_liq=False):
    if hi < lo: lo, hi = hi, lo
    d = map_dir(direction)
    consumed = first_consumed_idx(lo, hi, d, formation_ts)
    first_t = first_touch_idx(lo, hi, d, formation_ts)
    zones.append({"tf": tf, "kind": kind, "direction": d,
                  "lo": lo, "hi": hi, "formation_ts": formation_ts,
                  "consumed_idx": consumed,
                  "first_touch_idx": first_t,
                  "ob_liq": ob_liq})


for tf_name, cands in cans_by_tf.items():
    tf_ms = tf_ms_map[tf_name]
    n_c = len(cands)

    # Fractals — sweep
    for i in range(2, n_c - 2):
        f = detect_fractal(cands[i-2:i+3], n=2)
        if f is None: continue
        confirm_ts = cands[i].open_time + 3 * tf_ms
        # treat as 0-width zone at level
        add_zone(tf_name, "FRACTAL_LVL", "short" if f.direction == "high" else "long",
                 f.level, f.level, confirm_ts)

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
        dirn = "short" if rb.direction == "top" else "long"
        add_zone(tf_name, "RB", dirn, rb.zone[0], rb.zone[1], ft_ts)

    # marubozu body
    for c in cands:
        m = detect_marubozu(c)
        if m is None: continue
        ft_ts = c.open_time + tf_ms
        add_zone(tf_name, "MARU_body", m.direction, m.zone[0], m.zone[1], ft_ts)

    # ob_liq relaxed (special case: first-touch consumption)
    for i in range(n_c - 1):
        res = detect_ob_liq_relaxed(cands[i], cands[i+1])
        if res is None: continue
        direction, zone = res
        ft_ts = cands[i+1].open_time + tf_ms
        add_zone(tf_name, "OB_LIQ", direction, zone[0], zone[1], ft_ts, ob_liq=True)
        # Also add underlying OB (canon) — to be used after ob_liq consumption
        ob = detect_ob(cands[i], cands[i+1])
        if ob is not None:
            add_zone(tf_name, "OB_underlying", ob.direction, ob.zone[0], ob.zone[1], ft_ts)

    # RDRB POI
    for i in range(n_c - 2):
        r = detect_rdrb(cands[i], cands[i+1], cands[i+2])
        if r is None: continue
        ft_ts = cands[i+2].open_time + tf_ms
        add_zone(tf_name, "RDRB_POI", r.direction, r.poi[0], r.poi[1], ft_ts)

    # block_orders
    for i in range(n_c - 2):
        bo = detect_block_orders(cands[i:i+min(8, n_c - i)])
        if bo is None: continue
        last_idx = i + bo.n_initial + bo.n_counter
        if last_idx >= n_c: continue
        ft_ts = cands[last_idx - 1].open_time + tf_ms
        add_zone(tf_name, "BLOCK_ORD", bo.direction, bo.zone[0], bo.zone[1], ft_ts)

print(f"  Total zones: {len(zones)}")


def dir_matches(fr_dir, zone_dir):
    return (fr_dir == "high" and zone_dir == "short") or (fr_dir == "low" and zone_dir == "long")


def color(b):
    if b[4] > b[1]: return "bull"
    if b[4] < b[1]: return "bear"
    return "doji"


# Ground truth indices
cands_full = [Candle(open=b[1], high=b[2], low=b[3], close=b[4], open_time=b[0]) for b in bars12_w]
gt_fractals = []
for i in range(2, len(cands_full) - 2):
    f = detect_fractal(cands_full[i-2:i+3], n=2)
    if f is None: continue
    if cands_full[i].open_time < START_MS: continue
    gt_fractals.append({"dir": f.direction, "level": f.level, "idx": i})
imp_idx_set = {gt_fractals[n-1]["idx"] for n in IMPORTANT}


# Build candidates with F1+F2+F3
print("\nBuilding candidates after F1+F2+F3...")
f1f2f3 = []
for i in range(2, len(bars12_w) - 2):
    bi = bars12_w[i]; bi1 = bars12_w[i-1]; bi2 = bars12_w[i-2]
    bip1 = bars12_w[i+1]; bip2 = bars12_w[i+2]
    pre_fh = bi[2] > bi1[2] and bi[2] > bi2[2]
    pre_fl = bi[3] < bi1[3] and bi[3] < bi2[3]
    if not (pre_fh or pre_fl): continue

    for direction in (("high",) if pre_fh else ()) + (("low",) if pre_fl else ()):
        if direction == "high":
            confirmed = bi[2] > bip1[2] and bi[2] > bip2[2]
            relevant_wick = bi[2] - max(bi[1], bi[4])
        else:
            confirmed = bi[3] < bip1[3] and bi[3] < bip2[3]
            relevant_wick = min(bi[1], bi[4]) - bi[3]
        rng = bi[2] - bi[3] if bi[2] > bi[3] else 1e-9
        body = abs(bi[4] - bi[1])
        c0, c1, c2 = color(bi), color(bi1), color(bi2)

        # F1
        left_lo = max(0, i-5); left_hi = i
        if direction == "high":
            f1 = bi[2] > max(b[2] for b in bars12_w[left_lo:left_hi]) if left_hi > left_lo else True
        else:
            f1 = bi[3] < min(b[3] for b in bars12_w[left_lo:left_hi]) if left_hi > left_lo else True
        if not f1: continue
        # F2
        opp = c0 != c1 and "doji" not in (c0, c1)
        three_same = c0 == c1 == c2 and c0 != "doji"
        if not (opp or three_same): continue
        # F3
        if body / rng > 0.80 or relevant_wick / rng < 0.03: continue

        f1f2f3.append({
            "idx": i, "direction": direction, "confirmed": confirmed,
            "is_important": i in imp_idx_set,
            "pivot_low": bi[3], "pivot_high": bi[2], "pivot_open_ts": bi[0],
        })

print(f"  Total after F1+F2+F3: {len(f1f2f3)}")


# Compute F4 with wick-fill mitigation
print("\nComputing F4 (wick-fill mitigation)...")


def check_f4_wickfill(f, mode="overlap"):
    """Check if pivot interacts with any UNTOUCHED HTF zone (wick-fill canon).

    mode: 'overlap' = pivot.range overlaps current shrunk zone
          'level'   = pivot.level (high for FH / low for FL) ∈ current shrunk zone
    """
    pivot_open_ts = f["pivot_open_ts"]
    pivot_open_idx = int(np.searchsorted(ts_arr, pivot_open_ts, side='left'))
    pivot_lo, pivot_hi = f["pivot_low"], f["pivot_high"]
    pivot_level = f["pivot_high"] if f["direction"] == "high" else f["pivot_low"]

    for z in zones:
        # ignore underlying OBs in main loop — they activate only post-ob_liq consumption
        if z["kind"] == "OB_underlying": continue
        if z["formation_ts"] >= pivot_open_ts: continue
        if not dir_matches(f["direction"], z["direction"]): continue

        # ob_liq: special — first touch consumes; after that as canon OB
        if z["ob_liq"]:
            # If first_touch < pivot_open → ob_liq composite consumed, фрактал не "касается ob_liq"
            # then fall through to underlying OB (find it)
            if z["first_touch_idx"] < pivot_open_idx:
                # ob_liq itself is consumed BEFORE pivot, check underlying OB
                continue  # underlying OB handled below in separate loop
            # else: ob_liq still untouched, check normal way

        # zone consumption check — strict < means consumed BEFORE pivot starts
        if z["consumed_idx"] < pivot_open_idx: continue

        # compute current zone bounds at pivot_open via wick-fill
        i0 = int(np.searchsorted(ts_arr, z["formation_ts"], side='left'))
        if z["direction"] == "long":
            if i0 < pivot_open_idx:
                min_low_before = float(lo_arr[i0:pivot_open_idx].min())
                current_hi = min(z["hi"], min_low_before)
            else:
                current_hi = z["hi"]
            current_lo = z["lo"]
        else:
            if i0 < pivot_open_idx:
                max_hi_before = float(hi_arr[i0:pivot_open_idx].max())
                current_lo = max(z["lo"], max_hi_before)
            else:
                current_lo = z["lo"]
            current_hi = z["hi"]

        # zone must still have positive (or zero for points) size
        if current_lo > current_hi: continue

        # interaction check
        if mode == "overlap":
            if max(current_lo, pivot_lo) <= min(current_hi, pivot_hi):
                return True
        else:  # level
            if current_lo <= pivot_level <= current_hi:
                return True

    return False


# Now do the same loop but also handle ob_liq -> underlying OB transition
def check_f4_with_ob_liq_fallback(f, mode="overlap"):
    """As check_f4_wickfill but if main check fails, retry with OB_underlying zones
    for ob_liq composites that have been consumed (first touched)."""
    if check_f4_wickfill(f, mode):
        return True
    pivot_open_ts = f["pivot_open_ts"]
    pivot_open_idx = int(np.searchsorted(ts_arr, pivot_open_ts, side='left'))
    pivot_lo, pivot_hi = f["pivot_low"], f["pivot_high"]
    pivot_level = f["pivot_high"] if f["direction"] == "high" else f["pivot_low"]

    # Look at OB_underlying zones (only those whose paired ob_liq has been first-touched)
    # For simplicity: include any OB_underlying that's alive at pivot_open
    for z in zones:
        if z["kind"] != "OB_underlying": continue
        if z["formation_ts"] >= pivot_open_ts: continue
        if not dir_matches(f["direction"], z["direction"]): continue
        if z["consumed_idx"] < pivot_open_idx: continue

        # Apply wick-fill mitigation
        i0 = int(np.searchsorted(ts_arr, z["formation_ts"], side='left'))
        if z["direction"] == "long":
            if i0 < pivot_open_idx:
                min_low_before = float(lo_arr[i0:pivot_open_idx].min())
                current_hi = min(z["hi"], min_low_before)
            else:
                current_hi = z["hi"]
            current_lo = z["lo"]
        else:
            if i0 < pivot_open_idx:
                max_hi_before = float(hi_arr[i0:pivot_open_idx].max())
                current_lo = max(z["lo"], max_hi_before)
            else:
                current_lo = z["lo"]
            current_hi = z["hi"]
        if current_lo > current_hi: continue

        if mode == "overlap":
            if max(current_lo, pivot_lo) <= min(current_hi, pivot_hi):
                return True
        else:
            if current_lo <= pivot_level <= current_hi:
                return True
    return False


# Apply
print("  computing for each candidate...")
for i, f in enumerate(f1f2f3):
    if i % 200 == 0:
        print(f"    {i}/{len(f1f2f3)}", flush=True)
    f["F4_overlap"] = check_f4_with_ob_liq_fallback(f, "overlap")
    f["F4_level"] = check_f4_with_ob_liq_fallback(f, "level")


def stat(name, pred):
    yes = [c for c in f1f2f3 if pred(c)]
    if not yes:
        print(f"  {name:<60} keep=  0 → empty")
        return
    conf_yes = sum(1 for c in yes if c["confirmed"])
    imp_yes = sum(1 for c in yes if c["is_important"])
    prec = conf_yes / len(yes) * 100
    print(f"  {name:<60} keep={len(yes):>4} conf={conf_yes:>3} ({prec:>5.1f}%)  imp_kept={imp_yes:>2}/18")


print(f"\n{'='*120}")
print(f" F4 v2 = HTF zone interaction (wick-fill canon)")
print(f"{'='*120}")
stat("baseline F1∩F2∩F3", lambda c: True)
stat("F4 overlap (pivot.range × wick-fill alive zone)", lambda c: c["F4_overlap"])
stat("F4 level (pivot.level ∈ wick-fill alive zone)", lambda c: c["F4_level"])
stat("F4 NOT overlap (anti-filter)", lambda c: not c["F4_overlap"])
stat("F4 NOT level (anti-filter)", lambda c: not c["F4_level"])

# Detail: which imp lost?
print(f"\n--- Important fractals в F1∩F2∩F3 — кого теряет F4? ---")
gt_idx_to_num = {gt_fractals[n-1]["idx"]: n for n in IMPORTANT}
for c in f1f2f3:
    if not c["is_important"]: continue
    num = gt_idx_to_num.get(c["idx"], "?")
    print(f"  #{num}  idx={c['idx']}  {c['direction']:<5} pivot=[{c['pivot_low']:.1f}, {c['pivot_high']:.1f}]  "
          f"F4_overlap={'Y' if c['F4_overlap'] else '✗'}  F4_level={'Y' if c['F4_level'] else '✗'}")
