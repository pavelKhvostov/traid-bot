"""Поиск С6 для 4 оставшихся missed после C1∪C2∪C3∪C4∪C5:
  #14 2026-03-04 15:00 HIGH
  #15 2026-03-08 15:00 LOW
  #29 2026-03-29 15:00 LOW
  #48 2026-05-06 03:00 HIGH

Тестируем кандидаты:
  A. block_orders 50%-sweep (FIRST / NOT-FIRST / ANY)
  B. RDRB POI 50%-sweep
  C. i-FVG overlap 50%-sweep
  D. NOT-FIRST 50%-sweep ob_liq
  E. NOT-FIRST 50%-sweep FVG
  F. TrendLine HMA-49 / 30 sweep (короткие)
  G. TrendLine HMA-150 / 200 sweep (длинные)
  H. RB первое касание
"""
from __future__ import annotations
import csv, pathlib, sys, math
from datetime import datetime, timezone, timedelta
import numpy as np

sys.path.insert(0, str(pathlib.Path.home() / "smc-lib"))
from candle import Candle
from elements.fractal.code import detect_fractal
from elements.ob_liq.code import detect_ob_liq
from elements.fvg.code import detect_fvg
from elements.i_fvg.code import detect_i_fvg
from elements.block_orders.code import detect_block_orders
from elements.rdrb.code import detect_rdrb
from elements.rb.code import detect_rb
from indicators.trend_line_asvk import wma

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
MISSED_IMP_NS = {14, 15, 29, 48}   # after C1..C5

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

# === Detect all zone types across HTFs ===
print("Detecting elements across HTFs...")

zones = []  # каждая зона: {kind, tf, direction, lo, hi, ready_ms}
for tf, cans in cans_by_tf.items():
    tfms = tfms_map[tf]
    # block_orders — slide window of varying length
    for i in range(len(cans)):
        # window starts at i = preceding, length up to 8
        for L in range(3, 9):
            if i + L > len(cans): break
            bo = detect_block_orders(cans[i:i+L])
            if bo is None: continue
            # ready после first cross — приближение: open + L*tfms
            ready = cans[i].open_time + L*tfms
            zb, zt = bo.zone
            d = bo.direction
            zones.append({"kind":"block_orders", "tf":tf, "direction":d, "lo":zb, "hi":zt, "ready_ms":ready})
            break
    # RDRB POI
    for i in range(len(cans)-2):
        r = detect_rdrb(cans[i], cans[i+1], cans[i+2])
        if r is None: continue
        ready = cans[i+2].open_time + tfms
        zb, zt = r.poi
        d = "long" if r.direction == "long" else "short"
        zones.append({"kind":"rdrb_poi", "tf":tf, "direction":d, "lo":zb, "hi":zt, "ready_ms":ready})
    # i-FVG overlap: для каждой пары соседних FVG (A раньше, B позже) проверяем i-FVG
    fvgs = []
    for i in range(len(cans)-2):
        fv = detect_fvg(cans[i], cans[i+1], cans[i+2])
        if fv: fvgs.append({"fvg":fv, "c1_idx":i, "c3_idx":i+2})
    for ja in range(len(fvgs)):
        A = fvgs[ja]
        for jb in range(ja+1, min(ja+20, len(fvgs))):
            B = fvgs[jb]
            if B["c1_idx"] <= A["c3_idx"]: continue
            between = cans[A["c3_idx"]+1:B["c1_idx"]]
            try:
                ifvg = detect_i_fvg(cans[A["c1_idx"]], cans[A["c1_idx"]+1], cans[A["c3_idx"]],
                                    between,
                                    cans[B["c1_idx"]], cans[B["c1_idx"]+1], cans[B["c3_idx"]])
            except Exception:
                continue
            if ifvg is None: continue
            overlap_lo, overlap_hi = ifvg.overlap
            ready = cans[B["c3_idx"]].open_time + tfms
            d = ifvg.direction
            zones.append({"kind":"i_fvg", "tf":tf, "direction":d, "lo":overlap_lo, "hi":overlap_hi, "ready_ms":ready})
    # RB
    for i in range(len(cans)):
        rb = detect_rb(cans[i])
        if rb is None: continue
        ready = cans[i].open_time + tfms
        d = "short" if rb.direction == "top" else "long"
        zb, zt = rb.zone
        zones.append({"kind":"rb", "tf":tf, "direction":d, "lo":zb, "hi":zt, "ready_ms":ready})

print(f"  Total zones: {len(zones)}")
by_kind = {}
for z in zones:
    by_kind[z["kind"]] = by_kind.get(z["kind"], 0) + 1
for k,c in by_kind.items(): print(f"    {k}: {c}")

# === HMA на 12h и D для разных lengths ===
def hma(values, n):
    half = wma(values, n//2)
    full = wma(values, n)
    diff = [(2*half[i]-full[i]) if (half[i] is not None and full[i] is not None) else 0.0 for i in range(len(values))]
    sqrt_n = int(round(math.sqrt(n)))
    return wma(diff, sqrt_n)
closes_12 = [b[4] for b in bars12]
closes_d  = [b[4] for b in bars_by_tf["D"]]
hma_12_by_L = {L: hma(closes_12, L) for L in [30, 49, 150, 200]}
hma_d_by_L  = {L: hma(closes_d, L) for L in [30, 49, 150, 200]}
td_arr = np.array([b[0] for b in bars_by_tf["D"]], dtype=np.int64)
def d_idx_for(ts):
    idx = int(np.searchsorted(td_arr, ts, side='right')) - 1
    return idx if 0 <= idx < len(bars_by_tf["D"]) else None

# === F1∩F2∩F3 baseline ===
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

baseN = len(pivots); baseP = sum(1 for p in pivots if p["confirmed"])/baseN*100
print(f"\nBaseline F1∩F2∩F3: n={baseN}, P={baseP:.1f}%, missed_now=4 (#14, #15, #29, #48)\n")

# === 50%-sweep utilities ===
def first_50sweep_idx_zone(z):
    sp = int(np.searchsorted(t12, z["ready_ms"], side='left'))
    if sp >= n12_full: return None
    zlo, zhi = z["lo"], z["hi"]
    mid = (zlo + zhi) / 2
    for k in range(sp, n12_full):
        if z["direction"] == "short":
            if h12[k] >= mid and c12[k] < zlo: return k
        else:
            if l12[k] <= mid and c12[k] > zhi: return k
    return None
for z in zones:
    z["fs50"] = first_50sweep_idx_zone(z)

# Pivot direction-matched check
def pivot_50sweep_zones(p, kind_filter=None):
    """Возвращает (any_match, first_match) для зон выбранного kind."""
    pdir = "short" if p["direction"]=="high" else "long"
    pi = p["i_g"]; pt = t12[pi]
    pivot_hi = h12[pi]; pivot_lo = l12[pi]; pivot_close = c12[pi]
    any_match = False; first_match = False
    for z in zones:
        if kind_filter and z["kind"] != kind_filter: continue
        if z["direction"] != pdir: continue
        if z["ready_ms"] > pt: continue
        zlo, zhi = z["lo"], z["hi"]
        mid = (zlo + zhi) / 2
        if pdir == "short":
            sweep_ok = pivot_hi >= mid and pivot_close < zlo
        else:
            sweep_ok = pivot_lo <= mid and pivot_close > zhi
        if not sweep_ok: continue
        any_match = True
        if z["fs50"] == pi: first_match = True
    return any_match, first_match

# HMA sweep check (direction-matched, LIVE)
def pivot_hma_sweep(p, L, use_d=False):
    pi = p["i_g"]; bi = bars12[pi]
    if use_d:
        didx = d_idx_for(bi[0])
        if didx is None or didx-1 < 0: return False
        hv = hma_d_by_L[L][didx-1]
    else:
        hv = hma_12_by_L[L][pi-1] if pi-1 >= 0 else None
    if hv is None: return False
    if p["direction"] == "high":
        return bi[2] > hv and bi[4] < hv
    else:
        return bi[3] < hv and bi[4] > hv

# === Pre-compute per-pivot zone matches ===
for p in pivots:
    p["bo_any"], p["bo_first"]   = pivot_50sweep_zones(p, "block_orders")
    p["rdrb_any"], p["rdrb_first"] = pivot_50sweep_zones(p, "rdrb_poi")
    p["ifvg_any"], p["ifvg_first"] = pivot_50sweep_zones(p, "i_fvg")
    p["rb_any"], p["rb_first"]   = pivot_50sweep_zones(p, "rb")

def stat(name, mask):
    keep = [p for p in pivots if mask(p)]
    if not keep: return f"  {name:<55} keep=  0"
    conf = sum(1 for p in keep if p["confirmed"])
    p_pct = conf/len(keep)*100
    imp = sum(1 for p in keep if p["is_imp"])
    catches = sum(1 for p in keep if p["is_imp"] and p["imp_n"] in MISSED_IMP_NS)
    d = p_pct - baseP
    mark = " ⭐" if p_pct >= 70 else (" 🔸" if p_pct >= 65 else "")
    return f"  {name:<55} keep={len(keep):>4}  conf={conf:>3}  P(W)={p_pct:5.1f}%  Δ={d:+5.1f}  imp={imp:>2}/18  catches_4missed={catches}{mark}"

print(f"{'='*120}\nКандидаты С6:\n{'='*120}")
print(stat("A. block_orders 50%-sweep ANY", lambda p: p["bo_any"]))
print(stat("A. block_orders 50%-sweep FIRST", lambda p: p["bo_first"]))
print()
print(stat("B. RDRB POI 50%-sweep ANY",     lambda p: p["rdrb_any"]))
print(stat("B. RDRB POI 50%-sweep FIRST",   lambda p: p["rdrb_first"]))
print()
print(stat("C. i-FVG overlap 50%-sweep ANY",  lambda p: p["ifvg_any"]))
print(stat("C. i-FVG overlap 50%-sweep FIRST",lambda p: p["ifvg_first"]))
print()
print(stat("H. RB 50%-sweep ANY",            lambda p: p["rb_any"]))
print(stat("H. RB 50%-sweep FIRST",          lambda p: p["rb_first"]))
print()
print(f"  TrendLine HMA other lengths:")
for L in [30, 49, 150, 200]:
    print(stat(f"  HMA-{L} 12h LIVE sweep",   lambda p, L=L: pivot_hma_sweep(p, L, False)))
    print(stat(f"  HMA-{L} D   LIVE sweep",   lambda p, L=L: pivot_hma_sweep(p, L, True)))
    print(stat(f"  HMA-{L} 12h∪D LIVE sweep", lambda p, L=L: pivot_hma_sweep(p, L, False) or pivot_hma_sweep(p, L, True)))
    print()

# Покажем какие missed ловят лучшие 5 кандидатов
print(f"\n{'='*120}\nДетали: какие missed (из 4) ловит каждый кандидат:\n{'='*120}")
def show_caught(label, mask):
    caught = [p for p in pivots if mask(p) and p["is_imp"] and p["imp_n"] in MISSED_IMP_NS]
    if not caught:
        print(f"  {label}: 0 missed")
        return
    print(f"  {label}: {len(caught)} missed")
    for p in caught:
        ts_iso = datetime.fromtimestamp(p["pivot_open_ts"]/1000, MSK).strftime('%Y-%m-%d %H:%M')
        print(f"    #{p['imp_n']}  {ts_iso} MSK  dir={p['direction']}")

show_caught("A. block_orders 50%-sweep ANY",   lambda p: p["bo_any"])
show_caught("B. RDRB POI 50%-sweep ANY",       lambda p: p["rdrb_any"])
show_caught("C. i-FVG 50%-sweep ANY",          lambda p: p["ifvg_any"])
show_caught("H. RB 50%-sweep ANY",             lambda p: p["rb_any"])
for L in [30, 49, 150, 200]:
    show_caught(f"HMA-{L} 12h∪D LIVE sweep",  lambda p, L=L: pivot_hma_sweep(p, L, False) or pivot_hma_sweep(p, L, True))
