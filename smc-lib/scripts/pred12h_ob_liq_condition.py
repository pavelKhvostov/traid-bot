"""Условие 3 кандидат: взаимодействие pivot 12h с ob_liq зонами.

Тестируем 2 варианта:
  - FIRST_TOUCH: pivot 12h — ПЕРВАЯ свеча, входящая в liq_zone (зона свежая)
  - NOT_FIRST: pivot входит в liq_zone, но ранее уже были касания

Direction-matched:
  FH pivot (top) ← SHORT ob_liq (liq_zone выше)
  FL pivot (bot) ← LONG ob_liq (liq_zone ниже)

ob_liq detected на HTFs {12h, D, 2D, 3D, W}.

Сравнение: liq_zone (узкая маркер-зона) vs OB.zone (широкая drop/rally area) interaction.
"""
from __future__ import annotations
import csv, pathlib, sys
from datetime import datetime, timezone, timedelta
import numpy as np

sys.path.insert(0, str(pathlib.Path.home() / "smc-lib"))
from candle import Candle
from elements.fractal.code import detect_fractal
from elements.ob_liq.code import detect_ob_liq

CSV = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MSK = timezone(timedelta(hours=3))
MS_M = 60_000
MS_H = 60*MS_M
TF12 = 12*MS_H
TFD = 24*MS_H
TF2D = 48*MS_H
TF3D = 72*MS_H
TFW  = 7*24*MS_H
MON_ANCHOR = 1483315200000
START = int(datetime(2026,2,4,0,0,tzinfo=MSK).timestamp()*1000)
IMP = {1,3,4,5,9,10,11,14,15,20,23,26,29,40,41,42,47,48}
MISSED_IMP_NS = {3, 10, 11, 14, 15, 23, 26, 29, 47, 48}

print("Loading 1m...")
rows = []
with CSV.open() as f:
    rd = csv.reader(f); next(rd)
    for r in rd:
        t = datetime.fromisoformat(r[0])
        rows.append((int(t.timestamp()*1000), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))

def aggregate(d, tfms, anchor=0):
    out=[]; cb=None; o=h=l=c=0.0; v=0.0
    for ts,oo,hh,ll,cc,vv in d:
        b = ts - ((ts - anchor) % tfms)
        if b!=cb:
            if cb is not None: out.append((cb,o,h,l,c,v))
            cb=b; o,h,l,c=oo,hh,ll,cc; v=vv
        else:
            h=max(h,hh); l=min(l,ll); c=cc; v+=vv
    if cb is not None: out.append((cb,o,h,l,c,v))
    return out

bars12 = aggregate(rows, TF12)
last_ts = rows[-1][0]
window_start = last_ts - 6*365*24*3600*1000
bars12_w = [b for b in bars12 if b[0] >= window_start]
n12_full = len(bars12)
t12 = np.array([b[0] for b in bars12], dtype=np.int64)
h12 = np.array([b[2] for b in bars12])
l12 = np.array([b[3] for b in bars12])

bars_by_tf = {"12h":bars12, "D":aggregate(rows,TFD), "2D":aggregate(rows,TF2D),
              "3D":aggregate(rows,TF3D), "W":aggregate(rows,TFW,MON_ANCHOR)}
cans_by_tf = {tf:[Candle(open=b[1],high=b[2],low=b[3],close=b[4],open_time=b[0]) for b in bb] for tf,bb in bars_by_tf.items()}
tfms_map = {"12h":TF12,"D":TFD,"2D":TF2D,"3D":TF3D,"W":TFW}

# Detect ob_liq across all HTFs
print("Detecting ob_liq на HTFs {12h, D, 2D, 3D, W}...")
all_ob_liq = []
for tf, cans in cans_by_tf.items():
    tfms = tfms_map[tf]
    for i in range(2, len(cans) - 2):
        # ob_liq needs (prev-2, prev-1, prev, cur, cur+1) = 5 candles
        # Use i-2, i-1, i, i+1, i+2 — prev=i, cur=i+1
        ol = detect_ob_liq(cans[i], cans[i+1])
        if ol is None: continue
        ready = cans[i+2].open_time + tfms   # подтверждается на закрытии cur+1 = i+2 close
        all_ob_liq.append({
            "tf": tf, "direction": ol.direction,
            "zone_lo": ol.zone[0], "zone_hi": ol.zone[1],
            "liq_lo": ol.liq_zone[0], "liq_hi": ol.liq_zone[1],
            "ready_ms": ready,
        })
print(f"  Total ob_liq: {len(all_ob_liq)}")
by_tf_count = {}
for z in all_ob_liq:
    by_tf_count[z["tf"]] = by_tf_count.get(z["tf"], 0) + 1
for tf,c in by_tf_count.items(): print(f"    {tf}: {c}")

# F1∩F2∩F3 baseline
def color(b):
    if b[4]>b[1]: return "bull"
    if b[4]<b[1]: return "bear"
    return "doji"
pivots = []
for i in range(2, len(bars12_w)-2):
    bi=bars12_w[i]; bi1=bars12_w[i-1]; bi2=bars12_w[i-2]
    bip1=bars12_w[i+1]; bip2=bars12_w[i+2]
    pre_fh = bi[2]>bi1[2] and bi[2]>bi2[2]
    pre_fl = bi[3]<bi1[3] and bi[3]<bi2[3]
    if not(pre_fh or pre_fl): continue
    for direction in (("high",) if pre_fh else ()) + (("low",) if pre_fl else ()):
        if direction=="high":
            confirmed=bi[2]>bip1[2] and bi[2]>bip2[2]; rwick=bi[2]-max(bi[1],bi[4])
        else:
            confirmed=bi[3]<bip1[3] and bi[3]<bip2[3]; rwick=min(bi[1],bi[4])-bi[3]
        rng=bi[2]-bi[3] if bi[2]>bi[3] else 1e-9
        body=abs(bi[4]-bi[1])
        c0,c1,c2=color(bi),color(bi1),color(bi2)
        left_lo=max(0,i-5); left_hi=i
        if direction=="high":
            f1=bi[2]>max(b[2] for b in bars12_w[left_lo:left_hi]) if left_hi>left_lo else True
        else:
            f1=bi[3]<min(b[3] for b in bars12_w[left_lo:left_hi]) if left_hi>left_lo else True
        if not f1: continue
        opp=c0!=c1 and "doji" not in (c0,c1); three=c0==c1==c2 and c0!="doji"
        if not (opp or three): continue
        if body/rng>0.80 or rwick/rng<0.03: continue
        pivots.append({"i_w":i, "direction":direction, "confirmed":confirmed,
                       "pivot_open_ts":bi[0]})
ts_to_i_full = {int(b[0]): k for k,b in enumerate(bars12)}
for p in pivots:
    p["i_g"] = ts_to_i_full[int(p["pivot_open_ts"])]
cans_w = [Candle(open=b[1],high=b[2],low=b[3],close=b[4],open_time=b[0]) for b in bars12_w]
gt = []
for i in range(2, len(cans_w)-2):
    f = detect_fractal(cans_w[i-2:i+3], n=2)
    if f is None or cans_w[i].open_time < START: continue
    gt.append({"i_w":i, "dir":f.direction})
imp_iw_dir = {}
for n,g in enumerate(gt):
    if (n+1) in IMP:
        imp_iw_dir[(g["i_w"], g["dir"])] = n+1
for p in pivots:
    p["is_imp"] = (p["i_w"], p["direction"]) in imp_iw_dir
    p["imp_n"] = imp_iw_dir.get((p["i_w"], p["direction"]))

baseN = len(pivots); base_conf = sum(1 for p in pivots if p["confirmed"]); base_imp = sum(1 for p in pivots if p["is_imp"])
baseP = base_conf/baseN*100
print(f"\nBaseline F1∩F2∩F3: n={baseN}, P={baseP:.1f}%, imp={base_imp}/18\n")

# Helper: для каждой ob_liq определить «first 12h bar to enter zone after formation»
# Затем для каждого pivot — проверить:
#  (a) pivot.range ∩ liq_zone ≠ ∅ (interaction)
#  (b) если interaction: pivot — first to interact? (first_touch=True если pivot.i_g == first_idx)

def compute_first_touch_idx(zone_lo, zone_hi, ready_ms, use_liq_zone=True):
    """Возвращает index 12h-бара, который первым входит в зону после ready_ms.
    use_liq_zone=True: zone = liq_zone (узкая). False: zone = OB.zone (широкая)."""
    sp = int(np.searchsorted(t12, ready_ms, side='left'))
    if sp >= n12_full: return None
    for k in range(sp, n12_full):
        if l12[k] <= zone_hi and h12[k] >= zone_lo:
            return k
    return None

# Для каждого pivot — найти все ob_liq direction-matched, где pivot входит в liq_zone, и определить first_touch flag.
# direction-matched: FH ← SHORT ob_liq; FL ← LONG ob_liq

# Build lookup: для каждого pivot.i_g, какие ob_liq «активны»
print("Indexing ob_liq interactions per pivot...")
# Pre-sort: для каждой ob_liq pre-compute first_touch_idx и all touched indices
for z in all_ob_liq:
    z["first_idx_liq"] = compute_first_touch_idx(z["liq_lo"], z["liq_hi"], z["ready_ms"], True)
    z["first_idx_ob"]  = compute_first_touch_idx(z["zone_lo"], z["zone_hi"], z["ready_ms"], False)

# Sweep canon: touch + revert (close outside zone)
#   SHORT ob_liq (zone выше): high ≥ zone_lo AND close < zone_lo
#   LONG ob_liq (zone ниже): low  ≤ zone_hi AND close > zone_hi
# 50%-вариант: wick должен пробить минимум на середину зоны (deep sweep)
#   SHORT: high ≥ (zone_lo + zone_hi)/2 AND close < zone_lo
#   LONG:  low  ≤ (zone_lo + zone_hi)/2 AND close > zone_hi
# Direction-matched: FH pivot ← SHORT ob_liq; FL pivot ← LONG ob_liq

def pivot_sweep_interactions(p, use_liq_zone=True, depth_50=False):
    """Возвращает list of (ob_liq dict, is_first_sweep)."""
    pdir = "short" if p["direction"]=="high" else "long"
    pi = p["i_g"]
    pt = t12[pi]
    pivot_hi = h12[pi]; pivot_lo = l12[pi]; pivot_close = c_arr[pi]
    out = []
    for z in all_ob_liq:
        if z["direction"] != pdir: continue
        if z["ready_ms"] > pt: continue
        if use_liq_zone:
            zlo, zhi = z["liq_lo"], z["liq_hi"]
            first_sweep_idx = z[("first_sweep50_idx_liq" if depth_50 else "first_sweep_idx_liq")]
        else:
            zlo, zhi = z["zone_lo"], z["zone_hi"]
            first_sweep_idx = z[("first_sweep50_idx_ob" if depth_50 else "first_sweep_idx_ob")]
        # SWEEP check: touch + revert (close outside)
        if pdir == "short":
            touch_lvl = (zlo + zhi)/2 if depth_50 else zlo
            sweep_ok = pivot_hi >= touch_lvl and pivot_close < zlo
        else:
            touch_lvl = (zlo + zhi)/2 if depth_50 else zhi
            sweep_ok = pivot_lo <= touch_lvl and pivot_close > zhi
        if not sweep_ok: continue
        is_first = (first_sweep_idx == pi)
        out.append((z, is_first))
    return out

# Pre-compute: для каждой ob_liq найти первую 12h свечу с SWEEP (не просто touch)
c_arr = np.array([b[4] for b in bars12])
def compute_first_sweep_idx(z, use_liq_zone=True, depth_50=False):
    sp = int(np.searchsorted(t12, z["ready_ms"], side='left'))
    if sp >= n12_full: return None
    if use_liq_zone: zlo, zhi = z["liq_lo"], z["liq_hi"]
    else:            zlo, zhi = z["zone_lo"], z["zone_hi"]
    mid = (zlo + zhi) / 2
    for k in range(sp, n12_full):
        if z["direction"] == "short":
            lvl = mid if depth_50 else zlo
            if h12[k] >= lvl and c_arr[k] < zlo: return k
        else:
            lvl = mid if depth_50 else zhi
            if l12[k] <= lvl and c_arr[k] > zhi: return k
    return None
for z in all_ob_liq:
    z["first_sweep_idx_liq"]    = compute_first_sweep_idx(z, True, False)
    z["first_sweep_idx_ob"]     = compute_first_sweep_idx(z, False, False)
    z["first_sweep50_idx_liq"]  = compute_first_sweep_idx(z, True, True)
    z["first_sweep50_idx_ob"]   = compute_first_sweep_idx(z, False, True)

# Pre-compute for all pivots (SWEEP semantics) — стандартный sweep + 50%-sweep
for p in pivots:
    sw_liq = pivot_sweep_interactions(p, use_liq_zone=True, depth_50=False)
    sw_ob  = pivot_sweep_interactions(p, use_liq_zone=False, depth_50=False)
    sw50_liq = pivot_sweep_interactions(p, use_liq_zone=True, depth_50=True)
    sw50_ob  = pivot_sweep_interactions(p, use_liq_zone=False, depth_50=True)
    p["liq_any"] = len(sw_liq) > 0
    p["liq_first"] = any(is_first for z, is_first in sw_liq)
    p["liq_not_first"] = p["liq_any"] and not p["liq_first"]
    p["ob_any"]  = len(sw_ob) > 0
    p["ob_first"] = any(is_first for z, is_first in sw_ob)
    p["ob_not_first"] = p["ob_any"] and not p["ob_first"]
    p["liq50_any"] = len(sw50_liq) > 0
    p["liq50_first"] = any(is_first for z, is_first in sw50_liq)
    p["liq50_not_first"] = p["liq50_any"] and not p["liq50_first"]
    p["ob50_any"] = len(sw50_ob) > 0
    p["ob50_first"] = any(is_first for z, is_first in sw50_ob)
    p["ob50_not_first"] = p["ob50_any"] and not p["ob50_first"]

# Stats
def stat(name, mask):
    keep = [p for p in pivots if mask(p)]
    if not keep: print(f"  {name:<55} keep=  0"); return
    conf = sum(1 for p in keep if p["confirmed"])
    p_pct = conf/len(keep)*100
    imp = sum(1 for p in keep if p["is_imp"])
    catches = sum(1 for p in keep if p["is_imp"] and p["imp_n"] in MISSED_IMP_NS)
    d = p_pct - baseP
    mark = " ⭐" if p_pct >= 70 else ""
    print(f"  {name:<55} keep={len(keep):>4}  conf={conf:>3}  P(W)={p_pct:5.1f}%  Δ={d:+5.1f}  imp={imp:>2}/18  catches_missed={catches}/10{mark}")

print(f"\n{'='*100}\nSWEEP (touch + close back outside) на liq_zone (узкая marker):\n{'='*100}")
stat("ANY sweep liq_zone",                lambda p: p["liq_any"])
stat("FIRST_SWEEP liq_zone",              lambda p: p["liq_first"])
stat("NOT-FIRST sweep liq_zone",          lambda p: p["liq_not_first"])

print(f"\n{'='*100}\nSWEEP на OB.zone (широкая drop/rally area):\n{'='*100}")
stat("ANY sweep OB.zone",                 lambda p: p["ob_any"])
stat("FIRST_SWEEP OB.zone",               lambda p: p["ob_first"])
stat("NOT-FIRST sweep OB.zone",           lambda p: p["ob_not_first"])

print(f"\n{'='*100}\n50%-SWEEP (wick пробил минимум до середины зоны + close вне):\n{'='*100}")
print(f"\n  liq_zone (узкая marker):")
stat("ANY 50%-sweep liq_zone",            lambda p: p["liq50_any"])
stat("FIRST 50%-sweep liq_zone",          lambda p: p["liq50_first"])
stat("NOT-FIRST 50%-sweep liq_zone",      lambda p: p["liq50_not_first"])
print(f"\n  OB.zone (широкая):")
stat("ANY 50%-sweep OB.zone",             lambda p: p["ob50_any"])
stat("FIRST 50%-sweep OB.zone",           lambda p: p["ob50_first"])
stat("NOT-FIRST 50%-sweep OB.zone",       lambda p: p["ob50_not_first"])

# Покажем какие именно imp пойманы 50%-sweep вариантами
print(f"\n{'='*100}\nДетали: какие imp пойманы 50%-sweep вариантами:\n{'='*100}")
def show_caught(label, mask):
    caught = [p for p in pivots if mask(p) and p["is_imp"]]
    print(f"\n  {label}: пойманы {len(caught)} imp")
    for p in caught:
        ts_iso = datetime.fromtimestamp(p["pivot_open_ts"]/1000, MSK).strftime('%Y-%m-%d %H:%M')
        is_missed = p["imp_n"] in MISSED_IMP_NS
        marker = " ← MISSED-10" if is_missed else " (уже в basket C1/C2)"
        print(f"    #{p['imp_n']}  {ts_iso} MSK  dir={p['direction']}{marker}")

show_caught("FIRST 50%-sweep liq_zone",   lambda p: p["liq50_first"])
show_caught("FIRST 50%-sweep OB.zone",    lambda p: p["ob50_first"])
show_caught("ANY 50%-sweep liq_zone",     lambda p: p["liq50_any"])
show_caught("ANY 50%-sweep OB.zone",      lambda p: p["ob50_any"])
