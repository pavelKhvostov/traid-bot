"""LTF элементы внутри 12h pivot timespan — F3 кандидат.

Для каждого post-F1∩F2 fractal (35: 18 imp + 17 noise) — детектируем
SMC-элементы на LTF (1h, 2h, 4h, 6h), которые ФОРМИРУЮТСЯ В ПРЕДЕЛАХ
pivot 12h-свечи.

Элементы:
  - OB (canon)
  - FVG
  - ob_liq (relaxed, без Williams)
  - fractal level (Williams N=2)

Direction match:
  FH (top) — нужны SHORT/TOP элементы у pivot.high (resistance)
  FL (bottom) — нужны LONG/BOTTOM элементы у pivot.low (support)

Дополнительно: проверяем что LTF element formed BEFORE pivot closes
(т.е. виден на момент close 12h-pivot).
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

CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MSK = timezone(timedelta(hours=3))
MS_HOUR = 3600_000
TF12_MS = 12 * MS_HOUR

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


print("Loading...")
data = load_1m()

# All LTFs to test
LTF_LIST = [("1h", 1 * MS_HOUR), ("2h", 2 * MS_HOUR), ("4h", 4 * MS_HOUR), ("6h", 6 * MS_HOUR)]
bars_by_tf = {"12h": aggregate(data, TF12_MS)}
for name, ms in LTF_LIST:
    bars_by_tf[name] = aggregate(data, ms)
print(f"  bars: " + ", ".join(f"{n}={len(bars_by_tf[n])}" for n in ["12h"] + [x[0] for x in LTF_LIST]))


def to_candles(bars):
    return [Candle(open=b[1], high=b[2], low=b[3], close=b[4], open_time=b[0]) for b in bars]


cans_by_tf = {tf: to_candles(b) for tf, b in bars_by_tf.items()}


# Detect 12h fractals
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


def f2_pass(f):
    """opp_colors OR three_same_color."""
    bidx = f["idx"]
    b0 = bars_by_tf["12h"][bidx]
    b1 = bars_by_tf["12h"][bidx - 1]
    b2 = bars_by_tf["12h"][bidx - 2]
    def color(b):
        if b[4] > b[1]: return "bull"
        if b[4] < b[1]: return "bear"
        return "doji"
    c0, c1, c2 = color(b0), color(b1), color(b2)
    opp = c0 != c1 and "doji" not in (c0, c1)
    three_same = c0 == c1 == c2 and c0 != "doji"
    return opp or three_same


for n, f in enumerate(fractals, 1):
    f["num"] = n
    f["is_important"] = (n in IMPORTANT)
    f["F1_pass"] = left_ext_5(f)
    f["F2_pass"] = f2_pass(f) if f["F1_pass"] else False


post_F1F2 = [f for f in fractals if f["F1_pass"] and f["F2_pass"]]
print(f"\npost_F1∩F2: {len(post_F1F2)} = {sum(1 for f in post_F1F2 if f['is_important'])} imp + {sum(1 for f in post_F1F2 if not f['is_important'])} noise")


def dir_matches(fr_dir, zone_dir):
    return (fr_dir == "high" and zone_dir in ("short", "top")) or \
           (fr_dir == "low" and zone_dir in ("long", "bottom"))


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


def detect_ltf_zones_inside_pivot(f, tf_name):
    """Все элементы LTF которые открылись внутри 12h pivot timespan и dir-matched.
    Возвращает list строк (kind/direction). Считаем количество."""
    pivot_open = f["center_ts"]
    pivot_close = pivot_open + TF12_MS
    cans = cans_by_tf[tf_name]
    # find LTF candles whose open_time ∈ [pivot_open, pivot_close)
    inside_idx_lo = next((i for i, c in enumerate(cans) if c.open_time >= pivot_open), len(cans))
    inside_idx_hi = next((i for i, c in enumerate(cans) if c.open_time >= pivot_close), len(cans))
    inside_count = inside_idx_hi - inside_idx_lo
    if inside_count < 2: return []

    # for OB/ob_liq we may need 1 candle before pivot starts
    scan_lo = max(0, inside_idx_lo - 1)
    scan_hi = inside_idx_hi  # check pairs within pivot (i, i+1) where both i+1 inside

    matches = []
    # OB / ob_liq_relaxed on pairs (i, i+1) where i+1 inside pivot
    for i in range(scan_lo, scan_hi - 1):
        if i + 1 < inside_idx_lo: continue  # at least cur inside
        if i + 1 >= inside_idx_hi: break
        # OB
        ob = detect_ob(cans[i], cans[i+1])
        if ob and dir_matches(f["dir"], ob.direction):
            matches.append(f"{tf_name}/OB/{ob.direction[0]}")
        # ob_liq relaxed
        res = detect_ob_liq_relaxed(cans[i], cans[i+1])
        if res:
            direction, _ = res
            if dir_matches(f["dir"], direction):
                matches.append(f"{tf_name}/OB_LIQ/{direction[0]}")

    # FVG (3 candles) — all 3 inside or starting from before
    for i in range(scan_lo, scan_hi - 2):
        if i + 2 < inside_idx_lo: continue
        if i + 2 >= inside_idx_hi: break
        fvg = detect_fvg(cans[i], cans[i+1], cans[i+2])
        if fvg and dir_matches(f["dir"], fvg.direction):
            matches.append(f"{tf_name}/FVG/{fvg.direction[0]}")

    # Fractals (Williams N=2) inside — center must be in pivot
    for i in range(max(2, inside_idx_lo), min(len(cans) - 2, inside_idx_hi)):
        fr = detect_fractal(cans[i-2:i+3], n=2)
        if fr is None: continue
        # match dir: FH 12h ↔ FH on LTF; FL ↔ FL
        if fr.direction == f["dir"]:
            matches.append(f"{tf_name}/FRACT/{fr.direction[0]}")

    # Marubozu inside pivot
    for i in range(inside_idx_lo, inside_idx_hi):
        m = detect_marubozu(cans[i])
        if m and dir_matches(f["dir"], m.direction):
            matches.append(f"{tf_name}/MARU/{m.direction[0]}")

    # RB inside pivot
    for i in range(inside_idx_lo, inside_idx_hi):
        rb = detect_rb(cans[i])
        if rb and dir_matches(f["dir"], rb.direction):
            matches.append(f"{tf_name}/RB/{rb.direction[0]}")

    return matches


# Compute LTF confluence per fractal
print("\nDetecting LTF zones inside each pivot...")
for f in post_F1F2:
    all_matches = []
    counts_by_tf = {}
    counts_by_kind = {}
    for tf_name, _ in LTF_LIST:
        ms = detect_ltf_zones_inside_pivot(f, tf_name)
        all_matches.extend(ms)
        counts_by_tf[tf_name] = len(ms)
        for m in ms:
            kind = m.split("/")[1]
            counts_by_kind[kind] = counts_by_kind.get(kind, 0) + 1
    f["ltf_total"] = len(all_matches)
    f["ltf_by_tf"] = counts_by_tf
    f["ltf_by_kind"] = counts_by_kind
    f["ltf_matches"] = all_matches


# Table
print(f"\n{'='*150}")
print(f" LTF zones inside 12h pivot (post-F1∩F2, 35 fractals)")
print(f"{'='*150}")
print(f"  {'#':>3} {'★':>1} {'tp':>3} {'level':>6}  "
      f"{'1h':>3} {'2h':>3} {'4h':>3} {'6h':>3} {'tot':>4}  "
      f"{'OB':>3} {'FVG':>3} {'oLQ':>3} {'FRC':>3} {'MAR':>3} {'RB':>3}  "
      f"{'sample matches':<60}")
print("-" * 150)
for f in post_F1F2:
    star = "★" if f["is_important"] else " "
    glyph = "FH" if f["dir"] == "high" else "FL"
    bt = f["ltf_by_tf"]
    bk = f["ltf_by_kind"]
    sample = ", ".join(f["ltf_matches"][:5])
    if len(f["ltf_matches"]) > 5: sample += f" +{len(f['ltf_matches'])-5}"
    print(f"  {f['num']:>3} {star:>1} {glyph:>3} {f['level']:>6.0f}  "
          f"{bt.get('1h',0):>3} {bt.get('2h',0):>3} {bt.get('4h',0):>3} {bt.get('6h',0):>3} {f['ltf_total']:>4}  "
          f"{bk.get('OB',0):>3} {bk.get('FVG',0):>3} {bk.get('OB_LIQ',0):>3} {bk.get('FRACT',0):>3} "
          f"{bk.get('MARU',0):>3} {bk.get('RB',0):>3}  "
          f"{sample:<60}")


# Aggregate stats imp vs noise
print(f"\n{'='*120}")
print(f" Aggregate stats imp(18) vs noise(17)")
print(f"{'='*120}")


def stat_pair(name, fn):
    imps = [fn(f) for f in post_F1F2 if f["is_important"]]
    nois = [fn(f) for f in post_F1F2 if not f["is_important"]]
    imp_avg = sum(imps) / len(imps) if imps else 0
    noi_avg = sum(nois) / len(nois) if nois else 0
    delta = imp_avg - noi_avg
    print(f"  {name:<50} imp_mean={imp_avg:>5.2f}  noise_mean={noi_avg:>5.2f}  Δ={delta:>+5.2f}")


stat_pair("ltf_total (all elements)", lambda f: f["ltf_total"])
stat_pair("1h count", lambda f: f["ltf_by_tf"].get("1h", 0))
stat_pair("2h count", lambda f: f["ltf_by_tf"].get("2h", 0))
stat_pair("4h count", lambda f: f["ltf_by_tf"].get("4h", 0))
stat_pair("6h count", lambda f: f["ltf_by_tf"].get("6h", 0))
print()
stat_pair("OB count", lambda f: f["ltf_by_kind"].get("OB", 0))
stat_pair("FVG count", lambda f: f["ltf_by_kind"].get("FVG", 0))
stat_pair("OB_LIQ count", lambda f: f["ltf_by_kind"].get("OB_LIQ", 0))
stat_pair("FRACT count", lambda f: f["ltf_by_kind"].get("FRACT", 0))
stat_pair("MARU count", lambda f: f["ltf_by_kind"].get("MARU", 0))
stat_pair("RB count", lambda f: f["ltf_by_kind"].get("RB", 0))


# Filter tests
print(f"\n{'='*120}")
print(f" F3 candidate filters (на post-F1∩F2)")
print(f"{'='*120}")


def eval_filter(name, pred):
    kept = [f for f in post_F1F2 if pred(f)]
    imp = sum(1 for f in kept if f["is_important"])
    noise = len(kept) - imp
    lost = 18 - imp
    recall = imp / 18 * 100
    print(f"  {name:<58} keep={len(kept):>3}  imp={imp:>2}/18  lost={lost:>2}  "
          f"noise={noise:>3}  recall={recall:>5.1f}%")
    if lost > 0 and lost <= 6:
        lost_ids = [f["num"] for f in post_F1F2 if f["is_important"] and not pred(f)]
        print(f"      lost: {lost_ids}")


for thr in [1, 2, 3, 5, 8]:
    eval_filter(f"ltf_total ≥ {thr}", lambda f, t=thr: f["ltf_total"] >= t)
print()
for thr in [1, 2, 3]:
    eval_filter(f"1h count ≥ {thr}", lambda f, t=thr: f["ltf_by_tf"].get("1h", 0) >= t)
print()
for thr in [1, 2]:
    eval_filter(f"4h count ≥ {thr}", lambda f, t=thr: f["ltf_by_tf"].get("4h", 0) >= t)
print()
eval_filter("has FVG (any LTF)", lambda f: f["ltf_by_kind"].get("FVG", 0) >= 1)
eval_filter("has OB (any LTF)", lambda f: f["ltf_by_kind"].get("OB", 0) >= 1)
eval_filter("has OB_LIQ (any LTF)", lambda f: f["ltf_by_kind"].get("OB_LIQ", 0) >= 1)
eval_filter("has FRACT (any LTF)", lambda f: f["ltf_by_kind"].get("FRACT", 0) >= 1)
