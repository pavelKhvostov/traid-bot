"""F4 v3 — полный canon: правильная mitigation модель для каждого типа зоны.

Models:
  Wick-fill:    OB, block_orders, FVG, i-FVG, RDRB POI, i-RDRB POI
  First-touch:  RB, ob_liq
  Sweep level:  fractal, marubozu (open level)
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
from elements.i_fvg.code import detect_i_fvg
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

# 1m arrays
ts_arr = np.array([r[0] for r in data], dtype=np.int64)
hi_arr = np.array([r[2] for r in data], dtype=np.float64)
lo_arr = np.array([r[3] for r in data], dtype=np.float64)


# Mitigation calculations: precompute consumed_idx per zone (in 1m grid)
def consumed_idx_wick_fill(zone_lo, zone_hi, direction, formation_ts):
    """Wick-fill: LONG consumed when low ≤ zone_lo; SHORT consumed when high ≥ zone_hi."""
    i0 = int(np.searchsorted(ts_arr, formation_ts, side='left'))
    if i0 >= len(ts_arr): return len(ts_arr)
    if direction == "long":
        mask = lo_arr[i0:] <= zone_lo
    else:
        mask = hi_arr[i0:] >= zone_hi
    nz = int(np.argmax(mask))
    if not mask[nz]: return len(ts_arr)
    return i0 + nz


def consumed_idx_first_touch(zone_lo, zone_hi, direction, formation_ts):
    """First-touch: any wick overlap with zone."""
    i0 = int(np.searchsorted(ts_arr, formation_ts, side='left'))
    if i0 >= len(ts_arr): return len(ts_arr)
    if direction == "long":
        mask = lo_arr[i0:] <= zone_hi
    else:
        mask = hi_arr[i0:] >= zone_lo
    nz = int(np.argmax(mask))
    if not mask[nz]: return len(ts_arr)
    return i0 + nz


def consumed_idx_sweep_level(level, direction_for_sweep, formation_ts):
    """Sweep: wick touches/crosses level.
    For 'high' (FH or marubozu open at high): high > level.
    For 'low'  (FL or marubozu open at low):  low < level.
    """
    i0 = int(np.searchsorted(ts_arr, formation_ts, side='left'))
    if i0 >= len(ts_arr): return len(ts_arr)
    if direction_for_sweep == "high":
        mask = hi_arr[i0:] >= level  # touch or beyond (≥)
    else:
        mask = lo_arr[i0:] <= level
    nz = int(np.argmax(mask))
    if not mask[nz]: return len(ts_arr)
    return i0 + nz


def map_dir(d):
    if d in ("long", "bottom"): return "long"
    if d in ("short", "top"): return "short"
    return d


# Build zones
print("Detecting HTF zones with correct mitigation models...")
zones = []


def add_zone(tf, kind, model, direction, lo, hi, formation_ts, extra=None):
    if hi < lo: lo, hi = hi, lo
    d = map_dir(direction)
    if model == "wick_fill":
        consumed = consumed_idx_wick_fill(lo, hi, d, formation_ts)
    elif model == "first_touch":
        consumed = consumed_idx_first_touch(lo, hi, d, formation_ts)
    elif model == "sweep_level":
        # for fractal: direction = high/low (mapped from short/long)
        # for marubozu open: bull marubozu open=low so sweep low; bear marubozu open=high so sweep high
        sweep_dir = extra["sweep_dir"]
        level = extra["level"]
        consumed = consumed_idx_sweep_level(level, sweep_dir, formation_ts)
    else:
        consumed = len(ts_arr)
    zones.append({"tf": tf, "kind": kind, "model": model, "direction": d,
                  "lo": lo, "hi": hi, "formation_ts": formation_ts,
                  "consumed_idx": consumed, "extra": extra})


for tf_name, cands in cans_by_tf.items():
    tf_ms = tf_ms_map[tf_name]
    n_c = len(cands)

    # Fractals — sweep level
    for i in range(2, n_c - 2):
        f = detect_fractal(cands[i-2:i+3], n=2)
        if f is None: continue
        confirm_ts = cands[i].open_time + 3 * tf_ms
        dir_zone = "short" if f.direction == "high" else "long"
        add_zone(tf_name, "FRACTAL_LVL", "sweep_level", dir_zone,
                 f.level, f.level, confirm_ts,
                 extra={"sweep_dir": f.direction, "level": f.level})

    # OB — wick-fill
    for i in range(n_c - 1):
        ob = detect_ob(cands[i], cands[i+1])
        if ob is None: continue
        ft_ts = cands[i+1].open_time + tf_ms
        add_zone(tf_name, "OB", "wick_fill", ob.direction, ob.zone[0], ob.zone[1], ft_ts)

    # FVG — wick-fill
    for i in range(n_c - 2):
        f = detect_fvg(cands[i], cands[i+1], cands[i+2])
        if f is None: continue
        ft_ts = cands[i+2].open_time + tf_ms
        add_zone(tf_name, "FVG", "wick_fill", f.direction, f.zone[0], f.zone[1], ft_ts)

    # RB — first-touch
    for c in cands:
        rb = detect_rb(c)
        if rb is None: continue
        ft_ts = c.open_time + tf_ms
        dirn = "short" if rb.direction == "top" else "long"
        add_zone(tf_name, "RB", "first_touch", dirn, rb.zone[0], rb.zone[1], ft_ts)

    # marubozu — sweep open level
    for c in cands:
        m = detect_marubozu(c)
        if m is None: continue
        ft_ts = c.open_time + tf_ms
        # bull marubozu (open=low): direction LONG (support below), sweep level = open (= low)
        # bear marubozu (open=high): direction SHORT (resistance above), sweep level = open (= high)
        if m.direction == "long":
            sweep_dir = "low"
        else:
            sweep_dir = "high"
        # Zone bounds: body [open, close] for direction targeting
        add_zone(tf_name, "MARU_open", "sweep_level", m.direction,
                 c.open, c.open, ft_ts,
                 extra={"sweep_dir": sweep_dir, "level": c.open})

    # ob_liq relaxed (first-touch) + underlying OB (wick-fill, активна после ob_liq consumption)
    for i in range(n_c - 1):
        res = detect_ob_liq_relaxed(cands[i], cands[i+1])
        if res is None: continue
        direction, zone = res
        ft_ts = cands[i+1].open_time + tf_ms
        add_zone(tf_name, "OB_LIQ", "first_touch", direction, zone[0], zone[1], ft_ts)
        # underlying OB on same pair (if exists) — for use AFTER ob_liq consumed
        ob = detect_ob(cands[i], cands[i+1])
        if ob is not None:
            add_zone(tf_name, "OB_after_liq", "wick_fill", ob.direction, ob.zone[0], ob.zone[1], ft_ts)

    # RDRB POI — wick-fill
    for i in range(n_c - 2):
        r = detect_rdrb(cands[i], cands[i+1], cands[i+2])
        if r is None: continue
        ft_ts = cands[i+2].open_time + tf_ms
        add_zone(tf_name, "RDRB_POI", "wick_fill", r.direction, r.poi[0], r.poi[1], ft_ts)

    # i-RDRB POI — wick-fill (inherits from underlying RDRB)
    for i in range(n_c - 3):
        ir = detect_i_rdrb(cands[i], cands[i+1], cands[i+2], cands[i+3])
        if ir is None: continue
        ft_ts = cands[i+3].open_time + tf_ms
        # NB: i-RDRB direction is opposite of underlying RDRB. POI inherited.
        add_zone(tf_name, "I_RDRB_POI", "wick_fill",
                 ir.rdrb.direction, ir.rdrb.poi[0], ir.rdrb.poi[1], ft_ts)

    # block_orders — wick-fill
    for i in range(n_c - 2):
        bo = detect_block_orders(cands[i:i+min(8, n_c - i)])
        if bo is None: continue
        last_idx = i + bo.n_initial + bo.n_counter
        if last_idx >= n_c: continue
        ft_ts = cands[last_idx - 1].open_time + tf_ms
        add_zone(tf_name, "BLOCK_ORD", "wick_fill", bo.direction, bo.zone[0], bo.zone[1], ft_ts)

    # i-FVG — wick-fill on overlap zone. Bruteforce search.
    # Precompute all FVGs on this TF
    fvg_list = []
    for i in range(n_c - 2):
        f = detect_fvg(cands[i], cands[i+1], cands[i+2])
        if f is None: continue
        fvg_list.append({"idx": i, "fvg": f, "cs": (cands[i], cands[i+1], cands[i+2])})
    # For each B FVG, look back for A FVG with opposite direction
    for j in range(len(fvg_list)):
        b = fvg_list[j]
        for k in range(j - 1, max(-1, j - 50), -1):  # lookback up to 50 FVGs
            a = fvg_list[k]
            if a["fvg"].direction == b["fvg"].direction: continue
            # between candles: between a.idx+3 and b.idx (exclusive)
            between_lo = a["idx"] + 3
            between_hi = b["idx"]
            if between_hi <= between_lo: continue
            between = cands[between_lo:between_hi]
            try:
                ifvg = detect_i_fvg(a["cs"][0], a["cs"][1], a["cs"][2],
                                    between, b["cs"][0], b["cs"][1], b["cs"][2])
            except Exception:
                ifvg = None
            if ifvg:
                # formation = b.c3 close = cands[b.idx+2].open + tf_ms
                ft_ts = cands[b["idx"] + 2].open_time + tf_ms
                add_zone(tf_name, "I_FVG", "wick_fill", ifvg.direction,
                         ifvg.overlap[0], ifvg.overlap[1], ft_ts)
                break  # one A per B


print(f"  Total zones: {len(zones)}")
by_kind = {}
for z in zones: by_kind[z["kind"]] = by_kind.get(z["kind"], 0) + 1
for k in sorted(by_kind): print(f"    {k}: {by_kind[k]}")


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


# Build F1+F2+F3 candidates
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
        f1f2f3.append({"idx": i, "direction": direction, "confirmed": confirmed,
                       "is_important": i in imp_idx_set,
                       "pivot_low": bi[3], "pivot_high": bi[2], "pivot_open_ts": bi[0]})

print(f"  After F1+F2+F3: {len(f1f2f3)}")


# F4 check: pivot interacts with active zone at pivot.open
def check_f4(f, mode="overlap"):
    pivot_open_ts = f["pivot_open_ts"]
    pivot_open_idx = int(np.searchsorted(ts_arr, pivot_open_ts, side='left'))
    pivot_lo, pivot_hi = f["pivot_low"], f["pivot_high"]
    pivot_level = f["pivot_high"] if f["direction"] == "high" else f["pivot_low"]

    main_kinds = {"FRACTAL_LVL", "OB", "FVG", "RB", "MARU_open", "OB_LIQ",
                  "RDRB_POI", "I_RDRB_POI", "BLOCK_ORD", "I_FVG"}

    # Pass 1: main zones
    for z in zones:
        if z["kind"] not in main_kinds: continue
        if z["formation_ts"] >= pivot_open_ts: continue
        if not dir_matches(f["direction"], z["direction"]): continue
        # alive check
        if z["consumed_idx"] < pivot_open_idx: continue

        # compute current bounds at pivot_open
        i0 = int(np.searchsorted(ts_arr, z["formation_ts"], side='left'))
        if z["model"] == "wick_fill":
            if z["direction"] == "long":
                if i0 < pivot_open_idx:
                    min_low = float(lo_arr[i0:pivot_open_idx].min())
                    current_hi = min(z["hi"], min_low)
                else:
                    current_hi = z["hi"]
                current_lo = z["lo"]
            else:
                if i0 < pivot_open_idx:
                    max_hi = float(hi_arr[i0:pivot_open_idx].max())
                    current_lo = max(z["lo"], max_hi)
                else:
                    current_lo = z["lo"]
                current_hi = z["hi"]
        else:
            # first_touch or sweep_level: zone bounds не меняются, либо alive либо нет
            current_lo, current_hi = z["lo"], z["hi"]
        if current_lo > current_hi: continue
        # interaction check
        if mode == "overlap":
            if max(current_lo, pivot_lo) <= min(current_hi, pivot_hi):
                return True
        else:
            if current_lo <= pivot_level <= current_hi:
                return True

    # Pass 2: OB_after_liq fallback — для случаев когда ob_liq consumed
    for z in zones:
        if z["kind"] != "OB_after_liq": continue
        if z["formation_ts"] >= pivot_open_ts: continue
        if not dir_matches(f["direction"], z["direction"]): continue
        if z["consumed_idx"] < pivot_open_idx: continue
        i0 = int(np.searchsorted(ts_arr, z["formation_ts"], side='left'))
        if z["direction"] == "long":
            if i0 < pivot_open_idx:
                min_low = float(lo_arr[i0:pivot_open_idx].min())
                current_hi = min(z["hi"], min_low)
            else:
                current_hi = z["hi"]
            current_lo = z["lo"]
        else:
            if i0 < pivot_open_idx:
                max_hi = float(hi_arr[i0:pivot_open_idx].max())
                current_lo = max(z["lo"], max_hi)
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


print("\nComputing F4 v3 for each candidate...")
for i, f in enumerate(f1f2f3):
    if i % 200 == 0:
        print(f"  {i}/{len(f1f2f3)}", flush=True)
    f["F4_overlap"] = check_f4(f, "overlap")
    f["F4_level"] = check_f4(f, "level")


def stat(name, pred):
    yes = [c for c in f1f2f3 if pred(c)]
    if not yes:
        print(f"  {name:<60} keep=  0 → empty")
        return
    conf = sum(1 for c in yes if c["confirmed"])
    imp = sum(1 for c in yes if c["is_important"])
    prec = conf / len(yes) * 100
    print(f"  {name:<60} keep={len(yes):>4} conf={conf:>3} ({prec:>5.1f}%)  imp={imp:>2}/18")


print(f"\n{'='*120}")
print(f" F4 v3 — correct mitigation models per element")
print(f"{'='*120}")
stat("baseline F1∩F2∩F3", lambda c: True)
stat("F4 overlap", lambda c: c["F4_overlap"])
stat("F4 level", lambda c: c["F4_level"])
stat("F4 NOT overlap", lambda c: not c["F4_overlap"])
stat("F4 NOT level", lambda c: not c["F4_level"])

# Detail на 18 imp
print(f"\n--- Important fractals × F4 v3 ---")
gt_idx_to_num = {gt_fractals[n-1]["idx"]: n for n in IMPORTANT}
for c in sorted([x for x in f1f2f3 if x["is_important"]], key=lambda x: gt_idx_to_num[x["idx"]]):
    num = gt_idx_to_num[c["idx"]]
    print(f"  #{num:<3} {c['direction']:<5} pivot=[{c['pivot_low']:.0f}, {c['pivot_high']:.0f}]  "
          f"F4_overlap={'Y' if c['F4_overlap'] else '✗'}  F4_level={'Y' if c['F4_level'] else '✗'}")
