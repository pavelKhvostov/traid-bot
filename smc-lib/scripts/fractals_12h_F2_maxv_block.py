"""maxV-block как фактор для FL fractals в нашей выборке 56.

Правило (LONG-side только, для FL):
  На паре 12h-свечей (pair_start, pair_start+1) где fractal center входит в pair:
    min(open, close обеих) > max(maxV обеих)
  Pair candidates вокруг fractal center idx:
    (idx-1, idx)
    (idx, idx+1)
  Если хотя бы одна pair выполняет правило → maxV_block = True

  Для FH фрактала — пока правила нет (user дал только LONG), feature всегда False.

Затем проверяем как F-кандидат: помогает ли отдельно или в комбинации с F1 (left_ext_5).
"""
from __future__ import annotations

import csv
import pathlib
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from candle import Candle
from elements.fractal.code import detect_fractal
from indicators.vic_asvk import calculate_vic_bar

CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MSK = timezone(timedelta(hours=3))
MS_HOUR = 3600_000
TF12_MS = 12 * MS_HOUR
START_MS = int(datetime(2026, 2, 4, 0, 0, tzinfo=MSK).timestamp() * 1000)
IMPORTANT = {1, 3, 4, 5, 9, 10, 11, 14, 15, 20, 23, 26, 29, 40, 41, 42, 47, 48}
FRESH_EXTREME_FL = {4, 9, 15, 29, 41, 47}  # important FL без zone interaction


def load_1m():
    rows = []
    with CSV_PATH.open() as f:
        rd = csv.reader(f); next(rd)
        for r in rd:
            t = datetime.fromisoformat(r[0])
            rows.append((int(t.timestamp() * 1000),
                         float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
    return rows


print("Loading...")
data = load_1m()

# 12h bars + LTF composition
bars12 = []
ltf_per_bar = {}
cb = None; co = ch = cl = cc = cv = 0.0; cltf = []
for ts, o, h, l, c, v in data:
    b = ts - (ts % TF12_MS)
    if b != cb:
        if cb is not None:
            bars12.append((cb, co, ch, cl, cc, cv))
            ltf_per_bar[cb] = cltf
        cb = b; co, ch, cl, cc, cv = o, h, l, c, v; cltf = [(ts, o, h, l, c, v)]
    else:
        ch = max(ch, h); cl = min(cl, l); cc = c; cv += v
        cltf.append((ts, o, h, l, c, v))
if cb is not None:
    bars12.append((cb, co, ch, cl, cc, cv))
    ltf_per_bar[cb] = cltf

vic_per_bar = {}
for b in bars12:
    v = calculate_vic_bar(ltf_per_bar[b[0]])
    if v is not None: vic_per_bar[b[0]] = v
print(f"  {len(bars12)} 12h bars, {len(vic_per_bar)} VIC")


def maxv_block_long(idx_center):
    """True если хотя бы одна пара (idx_center-1, idx_center) или (idx_center, idx_center+1)
    выполняет правило: min(o,c обеих) > max(maxV обеих)."""
    for start in (idx_center - 1, idx_center):
        if start < 0 or start + 1 >= len(bars12): continue
        b1 = bars12[start]; b2 = bars12[start + 1]
        v1 = vic_per_bar.get(b1[0]); v2 = vic_per_bar.get(b2[0])
        if v1 is None or v2 is None or v1.maxV is None or v2.maxV is None: continue
        floor_v = max(v1.maxV, v2.maxV)
        if min(b1[1], b1[4], b2[1], b2[4]) > floor_v:
            return True, (start, start + 1, floor_v)
    return False, None


# Detect 12h fractals from START
cans = [Candle(open=b[1], high=b[2], low=b[3], close=b[4], open_time=b[0]) for b in bars12]
fractals = []
for i in range(2, len(cans) - 2):
    f = detect_fractal(cans[i-2:i+3], n=2)
    if f is None: continue
    if cans[i].open_time < START_MS: continue
    fractals.append({"dir": f.direction, "level": f.level, "idx": i,
                     "center_ts": cans[i].open_time})


def left_ext_5(f):
    bidx = f["idx"]
    win_lo = max(0, bidx - 5); win_hi = bidx
    slice_ = bars12[win_lo:win_hi]
    if not slice_: return True
    if f["dir"] == "high":
        return f["level"] > max(b[2] for b in slice_)
    else:
        return f["level"] < min(b[3] for b in slice_)


def fmt(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(MSK).strftime('%m-%d %H:%M')


for n, f in enumerate(fractals, 1):
    f["num"] = n
    f["is_important"] = (n in IMPORTANT)
    f["F1_pass"] = left_ext_5(f)
    if f["dir"] == "low":
        pass_, detail = maxv_block_long(f["idx"])
        f["maxv_block"] = pass_
        f["maxv_detail"] = detail
    else:
        f["maxv_block"] = False
        f["maxv_detail"] = None


# === Print FL-only table (правило применимо только к FL) ===
fls = [f for f in fractals if f["dir"] == "low"]
print(f"\n{'='*120}")
print(f" FL fractals (n={len(fls)}) + maxV_block factor")
print(f"{'='*120}")
print(f"{'#':>3} {'★':>1} {'fresh':>5} {'center':<14} {'level':>7} {'F1':>2} {'mxV':>3} {'detail (pair_idx, max(maxV))':<40}")
print("-" * 120)
for f in fls:
    star = "★" if f["is_important"] else " "
    fresh = "FRESH" if f["num"] in FRESH_EXTREME_FL else ""
    det = ""
    if f["maxv_block"] and f["maxv_detail"]:
        s, e, fv = f["maxv_detail"]
        det = f"pair=({s},{e}) floor={fv:.0f}"
    print(f"{f['num']:>3} {star:>1} {fresh:>5} {fmt(f['center_ts']):<14} "
          f"{f['level']:>7.0f} "
          f"{'Y' if f['F1_pass'] else '·':>2} "
          f"{'Y' if f['maxv_block'] else '·':>3} {det:<40}")


# === Evaluation на FL подмножестве ===
fl_important = [f for f in fls if f["is_important"]]
fl_noise = [f for f in fls if not f["is_important"]]
n_imp = len(fl_important); n_noise = len(fl_noise)
print(f"\nFL stats: important={n_imp}, noise={n_noise}")


def eval_on_fls(name, pred):
    kept = [f for f in fls if pred(f)]
    imp_kept = sum(1 for f in kept if f["is_important"])
    imp_lost = n_imp - imp_kept
    noise_kept = len(kept) - imp_kept
    fresh_kept = sum(1 for f in kept if f["num"] in FRESH_EXTREME_FL)
    fresh_total = sum(1 for f in fls if f["num"] in FRESH_EXTREME_FL)
    print(f"  {name:<58} keep={len(kept):>3}  imp_FL={imp_kept:>2}/{n_imp}  "
          f"noise={noise_kept:>3}  fresh_caught={fresh_kept}/{fresh_total}")
    if imp_lost > 0 and imp_lost <= 5:
        lost_ids = [f["num"] for f in fls if f["is_important"] and not pred(f)]
        print(f"      lost important FL: {lost_ids}")


print(f"\n--- single feature ---")
eval_on_fls("F1 (left_ext_5)", lambda f: f["F1_pass"])
eval_on_fls("maxV_block alone", lambda f: f["maxv_block"])

print(f"\n--- F1 ∩ maxV_block (both) ---")
eval_on_fls("F1 AND maxV_block", lambda f: f["F1_pass"] and f["maxv_block"])

print(f"\n--- F1 ∪ maxV_block (либо) ---")
eval_on_fls("F1 OR maxV_block", lambda f: f["F1_pass"] or f["maxv_block"])


# Особо: какие из FRESH-EXTREME FL ловим через maxV_block?
print(f"\n=== Fresh-extreme FL детали ===")
for num in sorted(FRESH_EXTREME_FL):
    f = next((x for x in fls if x["num"] == num), None)
    if f is None: continue
    print(f"  #{f['num']} FL {f['level']:.0f} ({fmt(f['center_ts'])}): "
          f"F1={'Y' if f['F1_pass'] else 'N'}  "
          f"maxV_block={'Y' if f['maxv_block'] else 'N'}  "
          f"detail={f['maxv_detail']}")
