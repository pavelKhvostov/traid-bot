"""Построение OR-basket из топ-кандидатов Dx.

Берём комбинацию precision + recall variants и считаем union stats.
Жадно добавляем Dx по принципу: max ΔWR / Δimp без переусложнения.
"""
from __future__ import annotations
import csv, pathlib, sys
from datetime import datetime, timezone, timedelta
import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path.home() / "smc-lib"))
from candle import Candle
from elements.fvg.code import detect_fvg

CSV = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MS_M = 60_000
TF12 = 12 * 60 * MS_M
TFD = 24 * 60 * MS_M
TF2D = 2 * TFD
TF3D = 3 * TFD
TFW = 7 * TFD
MON_ANCHOR = int(datetime(2017, 1, 2, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
TIMEOUT_BARS = 120

# Load 1m
print("Loading...")
rows = []
with CSV.open() as f:
    rd = csv.reader(f); next(rd)
    for r in rd:
        t = datetime.fromisoformat(r[0])
        rows.append((int(t.timestamp() * 1000), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))


def agg(d, tfms, anchor=0):
    out = []; cb = None; o = h = l = c = 0.0; v = 0.0
    for ts, oo, hh, ll, cc, vv in d:
        b = ts - ((ts - anchor) % tfms)
        if b != cb:
            if cb is not None: out.append((cb, o, h, l, c, v))
            cb = b; o, h, l, c, v = oo, hh, ll, cc, vv
        else:
            h = max(h, hh); l = min(l, ll); c = cc; v += vv
    if cb is not None: out.append((cb, o, h, l, c, v))
    return out


bars12 = agg(rows, TF12); n12 = len(bars12)
t12 = np.array([b[0] for b in bars12], dtype=np.int64)
h12 = np.array([b[2] for b in bars12]); l12 = np.array([b[3] for b in bars12]); c12 = np.array([b[4] for b in bars12])

bars_by_tf = {"12h": bars12, "D": agg(rows, TFD), "2D": agg(rows, TF2D),
              "3D": agg(rows, TF3D), "W": agg(rows, TFW, MON_ANCHOR)}
cans_by_tf = {tf: [Candle(open=b[1], high=b[2], low=b[3], close=b[4], open_time=b[0]) for b in bb]
              for tf, bb in bars_by_tf.items()}
tfms_map = {"12h": TF12, "D": TFD, "2D": TF2D, "3D": TF3D, "W": TFW}


def atr_calc(highs, lows, closes, n=14):
    tr = np.zeros(len(highs))
    for i in range(1, len(highs)):
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
    out = np.zeros(len(highs))
    for i in range(n, len(highs)):
        out[i] = tr[i - n + 1:i + 1].mean()
    return out


atr12 = atr_calc(h12, l12, c12, 14)

print("FVGs...")
all_fvg = []
for tf, cans in cans_by_tf.items():
    tfms = tfms_map[tf]
    for i in range(len(cans) - 2):
        fv = detect_fvg(cans[i], cans[i + 1], cans[i + 2])
        if fv is None: continue
        ready = cans[i + 2].open_time + tfms
        all_fvg.append({
            "tf": tf, "direction": fv.direction,
            "zlo": fv.zone[0], "zhi": fv.zone[1],
            "c3_ms": cans[i + 2].open_time,
            "ready_ms": ready,
        })
print(f"  {len(all_fvg)} FVGs")

print("Events...")
for z in all_fvg:
    sp = int(np.searchsorted(t12, z["ready_ms"], side='left'))
    z["events"] = []
    if sp >= n12: continue
    zlo, zhi = z["zlo"], z["zhi"]; w = zhi - zlo
    if w <= 0: continue
    for k in range(sp, n12):
        if z["direction"] == "short":
            h, c = h12[k], c12[k]
            if h < zlo: continue
            pen = min((h - zlo) / w * 100, 999)
            ci = (c >= zlo and c <= zhi)
            co_far = (c < zlo)
        else:
            l, c = l12[k], c12[k]
            if l > zhi: continue
            pen = min((zhi - l) / w * 100, 999)
            ci = (c >= zlo and c <= zhi)
            co_far = (c > zhi)
        z["events"].append((k, pen, ci, co_far))


def active_until(z, lc):
    if lc == "L0": return None
    if lc == "L1":
        for k, pen, ci, co in z["events"]:
            if pen >= 50: return k + 1
        return None
    if lc == "L2":
        for k, pen, ci, co in z["events"]:
            if pen >= 100: return k + 1
        return None
    if lc == "L3":
        for k, pen, ci, co in z["events"]:
            if ci: return k + 1
        return None
    if lc == "L4":
        sp = int(np.searchsorted(t12, z["ready_ms"], side='left'))
        return sp + TIMEOUT_BARS
    return None


def is_sweep(pen, ci, co, mode):
    if mode == "S50":  return pen >= 50  and co
    if mode == "S70":  return pen >= 70  and co
    if mode == "S100": return pen >= 100 and co
    if mode == "W50":  return pen >= 50
    if mode == "W100": return pen >= 100
    if mode == "CINS": return pen >= 50  and ci
    return False


def fvg_passes_filter(z, k, ft):
    if ft == "ANY": return True
    age = (t12[k] - z["c3_ms"]) // TF12
    w = z["zhi"] - z["zlo"]
    atr = atr12[k] if atr12[k] > 0 else 1.0
    if ft == "HTF": return z["tf"] in ("D","2D","3D","W")
    if ft == "12h": return z["tf"] == "12h"
    if ft == "AGE50": return age >= 50
    if ft == "WIDE": return w / atr >= 0.7
    if ft == "HTF_AGE50": return z["tf"] in ("D","2D","3D","W") and age >= 50
    if ft == "HTF_WIDE": return z["tf"] in ("D","2D","3D","W") and w / atr >= 0.7
    if ft == "AGE50_WIDE": return age >= 50 and w / atr >= 0.7
    return False


def evaluate_dx(lc, sm, ft):
    fires = set()
    for z in all_fvg:
        au = active_until(z, lc)
        for k, pen, ci, co in z["events"]:
            if au is not None and k >= au: break
            if not is_sweep(pen, ci, co, sm): continue
            if not fvg_passes_filter(z, k, ft): continue
            fires.add((k, z["direction"]))
            break  # first-only
    return fires


df_base = pd.read_parquet(pathlib.Path.home() / "Desktop/pred12h_baseline_c1c7.parquet")
df_base["pivot_open_ts_ms"] = df_base["pivot_open_ts_ms"].astype("int64")
ts_to_idx = {int(t): k for k, t in enumerate(t12)}

# Pivot map
pivot_map = {}
all_pivots = set()
all_imp = set()
for _, p in df_base.iterrows():
    ts_ms = int(p["pivot_open_ts_ms"])
    if ts_ms not in ts_to_idx: continue
    k = ts_to_idx[ts_ms]
    expected = "short" if p["direction"] == "high" else "long"
    key = (k, expected)
    pivot_map[key] = (bool(p["confirmed"]), bool(p["is_imp"]), p["direction"], ts_ms)
    all_pivots.add(key)
    if bool(p["is_imp"]):
        all_imp.add(key)


def stats_for_pivot_set(pivot_set):
    matched = [pivot_map[k] for k in pivot_set if k in pivot_map]
    n = len(matched)
    conf = sum(1 for c, _, _, _ in matched if c)
    imp = sum(1 for _, i, _, _ in matched if i)
    wr = 100 * conf / n if n else 0.0
    return n, conf, wr, imp


# ─── Candidate Dx variants (вручную отобранные best) ───
CANDIDATES = [
    ("D_default", "L0", "S50", "ANY"),       # текущий C4 для сравнения
    ("D_S100W",   "L0", "S100", "WIDE"),     # full-sweep wide
    ("D_S50AW",   "L0", "S50", "AGE50_WIDE"),# aged-wide классический
    ("D_S70A",    "L0", "S70", "AGE50"),     # aged deeper sweep
    ("D_S100A",   "L0", "S100", "AGE50"),    # aged full-sweep
    ("D_HTFW",    "L0", "S50", "HTF_WIDE"),  # HTF wide
    ("D_W50A",    "L1", "W50", "AGE50"),     # ⭐ ловит #48
    ("D_W100A",   "L2", "W100", "AGE50"),    # ловит 5 imp
    ("D_W50HA",   "L1", "W50", "HTF_AGE50"), # alt #48 catcher
    ("D_W100",    "L0", "W100", "ANY"),      # 9 imp макс recall
]

print("\n" + "="*100)
print("Кандидаты Dx — standalone stats")
print("="*100)
print(f"{'Name':<12} {'Lc':<3} {'Sw':<5} {'Filter':<12} {'n':>4} {'conf':>5} {'WR':>6} {'imp':>4}  catches #48?")
imp48_ms = int(datetime(2026, 5, 6, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
imp48_idx = ts_to_idx.get(imp48_ms)
imp48_key = (imp48_idx, "short") if imp48_idx is not None else None

cand_fires = {}
for name, lc, sm, ft in CANDIDATES:
    fires = evaluate_dx(lc, sm, ft)
    # Only count pivots
    pivots_hit = fires & all_pivots
    cand_fires[name] = pivots_hit
    n, conf, wr, imp = stats_for_pivot_set(pivots_hit)
    catches48 = "✓" if imp48_key in pivots_hit else " "
    print(f"{name:<12} {lc:<3} {sm:<5} {ft:<12} {n:>4} {conf:>5} {wr:>5.1f}% {imp:>4}  {catches48}")


# ─── Greedy OR-basket construction ───
print("\n" + "="*100)
print("Greedy OR-basket: добавляем Dx максимизирующий unique imp при WR ≥ 65%")
print("="*100)

# Start with strongest precision
basket = set()
order = []
remaining = set(CANDIDATES) - {("D_default","L0","S50","ANY")}

# Pick D_S100W first as anchor (highest WR)
def add_and_report(name, lc, sm, ft):
    global basket, order
    pivots = cand_fires[name]
    new = pivots - basket
    basket |= pivots
    order.append((name, lc, sm, ft))
    n, conf, wr, imp = stats_for_pivot_set(basket)
    new_n = len(new)
    new_imp = sum(1 for k in new if pivot_map.get(k, (False,False,None,None))[1])
    return n, conf, wr, imp, new_n, new_imp


print(f"\n{'Step':<6} {'Add Dx':<12} {'+pivs':>5} {'+imp':>5} {'basket_n':>9} {'basket_conf':>11} {'basket_WR':>10} {'basket_imp':>11}")

# Hand-curate path: precision → recall layering
for name, lc, sm, ft in [
    ("D_S100W",  "L0", "S100", "WIDE"),
    ("D_S50AW",  "L0", "S50",  "AGE50_WIDE"),
    ("D_S70A",   "L0", "S70",  "AGE50"),
    ("D_HTFW",   "L0", "S50",  "HTF_WIDE"),
    ("D_W50A",   "L1", "W50",  "AGE50"),
    ("D_W100A",  "L2", "W100", "AGE50"),
]:
    n, conf, wr, imp, new_n, new_imp = add_and_report(name, lc, sm, ft)
    print(f"+{len(order):<5} {name:<12} {new_n:>5} {new_imp:>5} {n:>9} {conf:>11} {wr:>9.1f}% {imp:>11}")


# Final basket comparison
print("\n" + "="*100)
print("ФИНАЛЬНАЯ КОРЗИНА C4_v2 vs C4_default")
print("="*100)
n_v2, c_v2, wr_v2, imp_v2 = stats_for_pivot_set(basket)
default = cand_fires["D_default"]
n_d, c_d, wr_d, imp_d = stats_for_pivot_set(default)
print(f"  C4 default:  n={n_d:>4}  conf={c_d:>4}  WR={wr_d:5.1f}%  imp={imp_d}")
print(f"  C4_v2 (OR):  n={n_v2:>4}  conf={c_v2:>4}  WR={wr_v2:5.1f}%  imp={imp_v2}")
print(f"  Δ:          n={n_v2-n_d:+d}  conf={c_v2-c_d:+d}  WR={wr_v2-wr_d:+.1f}pp  imp={imp_v2-imp_d:+d}")

# Which imp does each variant uniquely catch?
print("\n=== Imp catches per Dx ===")
all_caught_imp = {}
for name in cand_fires:
    if name == "D_default": continue
    imp_caught = [k for k in cand_fires[name] if k in all_imp]
    for k in imp_caught:
        all_caught_imp.setdefault(k, []).append(name)

print(f"\nUnique imp catches breakdown:")
MSK = timezone(timedelta(hours=3))
for k, names in sorted(all_caught_imp.items(), key=lambda x: x[0][0]):
    bar_idx, fdir = k
    pdir = pivot_map[k][2]
    ts_ms = pivot_map[k][3]
    dt = datetime.fromtimestamp(ts_ms/1000, MSK).strftime("%Y-%m-%d %H:%M")
    conf = "✓" if pivot_map[k][0] else "✗"
    print(f"  {conf} {dt} ({pdir}): caught by {','.join(names)}")

# Compare with default
default_caught = [k for k in default if k in all_imp]
print(f"\nDefault C4 imp catches:")
for k in default_caught:
    bar_idx, fdir = k
    pdir = pivot_map[k][2]
    ts_ms = pivot_map[k][3]
    dt = datetime.fromtimestamp(ts_ms/1000, MSK).strftime("%Y-%m-%d %H:%M")
    conf = "✓" if pivot_map[k][0] else "✗"
    print(f"  {conf} {dt} ({pdir})")
