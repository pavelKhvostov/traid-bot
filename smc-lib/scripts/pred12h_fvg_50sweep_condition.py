"""Тест: FVG как зона интереса с 50%-sweep (по аналогии с ob_liq).

FVG зоны (по канону):
  LONG FVG: [c1.high, c3.low] (поддержка, ниже цены)
  SHORT FVG: [c3.high, c1.low] (сопротивление, выше цены)

50%-sweep direction-matched:
  FH pivot (top) ← SHORT FVG: high ≥ midpoint AND close < zone_lo
  FL pivot (bot) ← LONG FVG:  low ≤ midpoint AND close > zone_hi

Multi-TF FVG: 12h, D, 2D, 3D, W.
Сравнить ANY / FIRST 50%-sweep / NOT-FIRST 50%-sweep.
"""
from __future__ import annotations
import csv, pathlib, sys
from datetime import datetime, timezone, timedelta
import numpy as np

sys.path.insert(0, str(pathlib.Path.home() / "smc-lib"))
from candle import Candle
from elements.fractal.code import detect_fractal
from elements.fvg.code import detect_fvg

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
MISSED_IMP_NS = {3, 11, 14, 15, 23, 26, 29, 47, 48}   # after C1, C2, C3

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
c12 = np.array([b[4] for b in bars12])

bars_by_tf = {"12h":bars12, "D":aggregate(rows,TFD), "2D":aggregate(rows,TF2D),
              "3D":aggregate(rows,TF3D), "W":aggregate(rows,TFW,MON_ANCHOR)}
cans_by_tf = {tf:[Candle(open=b[1],high=b[2],low=b[3],close=b[4],open_time=b[0]) for b in bb] for tf,bb in bars_by_tf.items()}
tfms_map = {"12h":TF12,"D":TFD,"2D":TF2D,"3D":TF3D,"W":TFW}

# Detect FVG across HTFs
print("Detecting FVG на HTFs {12h, D, 2D, 3D, W}...")
all_fvg = []
for tf, cans in cans_by_tf.items():
    tfms = tfms_map[tf]
    for i in range(len(cans) - 2):
        fv = detect_fvg(cans[i], cans[i+1], cans[i+2])
        if fv is None: continue
        ready = cans[i+2].open_time + tfms
        all_fvg.append({"tf":tf, "direction":fv.direction,
                        "zone_lo":fv.zone[0], "zone_hi":fv.zone[1],
                        "ready_ms":ready})
print(f"  Total FVG: {len(all_fvg)}")
by_tf_count = {}
for z in all_fvg:
    by_tf_count[z["tf"]] = by_tf_count.get(z["tf"], 0) + 1
for tf in ["12h","D","2D","3D","W"]:
    print(f"    {tf}: {by_tf_count.get(tf, 0)}")

# Pre-compute first 50%-sweep idx per FVG
def first_50sweep_idx(z):
    sp = int(np.searchsorted(t12, z["ready_ms"], side='left'))
    if sp >= n12_full: return None
    zlo, zhi = z["zone_lo"], z["zone_hi"]
    mid = (zlo + zhi) / 2
    for k in range(sp, n12_full):
        if z["direction"] == "short":
            if h12[k] >= mid and c12[k] < zlo: return k
        else:
            if l12[k] <= mid and c12[k] > zhi: return k
    return None
for z in all_fvg:
    z["fs50"] = first_50sweep_idx(z)

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
        pivots.append({"i_w":i, "direction":direction, "confirmed":confirmed, "pivot_open_ts":bi[0]})
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

# Direction-matched FVG sweep checks (50%-depth)
def pivot_50sweep(p):
    pdir = "short" if p["direction"]=="high" else "long"
    pi = p["i_g"]
    pt = t12[pi]
    pivot_hi = h12[pi]; pivot_lo = l12[pi]; pivot_close = c12[pi]
    any_sweep = False; first_sweep = False
    for z in all_fvg:
        if z["direction"] != pdir: continue
        if z["ready_ms"] > pt: continue
        zlo, zhi = z["zone_lo"], z["zone_hi"]
        mid = (zlo + zhi) / 2
        if pdir == "short":
            sweep_ok = pivot_hi >= mid and pivot_close < zlo
        else:
            sweep_ok = pivot_lo <= mid and pivot_close > zhi
        if not sweep_ok: continue
        any_sweep = True
        if z["fs50"] == pi: first_sweep = True
    return any_sweep, first_sweep

for p in pivots:
    a, f = pivot_50sweep(p)
    p["fvg50_any"] = a
    p["fvg50_first"] = f
    p["fvg50_not_first"] = a and not f

def stat(name, mask):
    keep = [p for p in pivots if mask(p)]
    if not keep: print(f"  {name:<55} keep=  0"); return
    conf = sum(1 for p in keep if p["confirmed"])
    p_pct = conf/len(keep)*100
    imp = sum(1 for p in keep if p["is_imp"])
    catches = sum(1 for p in keep if p["is_imp"] and p["imp_n"] in MISSED_IMP_NS)
    d = p_pct - baseP
    mark = " ⭐" if p_pct >= 70 else ""
    print(f"  {name:<55} keep={len(keep):>4}  conf={conf:>3}  P(W)={p_pct:5.1f}%  Δ={d:+5.1f}  imp={imp:>2}/18  catches_missed={catches}/9{mark}")

print(f"{'='*100}\nFVG 50%-SWEEP (multi-TF: 12h+D+2D+3D+W):\n{'='*100}")
stat("ANY 50%-sweep FVG",          lambda p: p["fvg50_any"])
stat("FIRST 50%-sweep FVG",        lambda p: p["fvg50_first"])
stat("NOT-FIRST 50%-sweep FVG",    lambda p: p["fvg50_not_first"])

# Какие missed пойманы
print(f"\n{'='*100}\nДетали: какие imp пойманы:\n{'='*100}")
def show_caught(label, mask):
    caught = [p for p in pivots if mask(p) and p["is_imp"]]
    print(f"\n  {label}: пойманы {len(caught)} imp")
    for p in caught:
        ts_iso = datetime.fromtimestamp(p["pivot_open_ts"]/1000, MSK).strftime('%Y-%m-%d %H:%M')
        is_missed = p["imp_n"] in MISSED_IMP_NS
        marker = " ← MISSED-9" if is_missed else " (уже в basket)"
        print(f"    #{p['imp_n']}  {ts_iso} MSK  dir={p['direction']}{marker}")
show_caught("FIRST 50%-sweep FVG",   lambda p: p["fvg50_first"])
show_caught("ANY 50%-sweep FVG",     lambda p: p["fvg50_any"])
