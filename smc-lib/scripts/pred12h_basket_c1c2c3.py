"""Корзина после добавления С3+С4+С5+С6+С7.

С1 = sweep maxV(i-1) на 1m
С2 = union P11_count {8,12,16,24}×15m direction-matched
С3 = FIRST 50%-sweep ob_liq (liq_zone OR OB.zone), direction-matched
С4 = FIRST 50%-sweep FVG multi-TF (12h+D+2D+3D+W), direction-matched
С5 = sweep TrendLine HMA-78 (12h ∪ D) LIVE, direction-matched
С6 = sweep TrendLine HMA-200 D LIVE, direction-matched
С7 = FIRST 50%-sweep block_orders multi-TF (12h+D+2D+3D+W), direction-matched

Все условия independent на baseline 1267.
"""
from __future__ import annotations
import csv, pathlib, sys
from datetime import datetime, timezone, timedelta
import numpy as np

sys.path.insert(0, str(pathlib.Path.home() / "smc-lib"))
from candle import Candle
from elements.fractal.code import detect_fractal
from elements.ob_liq.code import detect_ob_liq
from elements.fvg.code import detect_fvg
from elements.block_orders.code import detect_block_orders
from indicators.trend_line_asvk import wma
import math

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

print("Loading 1m...")
rows = []
with CSV.open() as f:
    rd = csv.reader(f); next(rd)
    for r in rd:
        t = datetime.fromisoformat(r[0])
        rows.append((int(t.timestamp()*1000), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
ts_1m = np.array([r[0] for r in rows], dtype=np.int64)
op_1m = np.array([r[1] for r in rows], dtype=np.float64)
cl_1m = np.array([r[4] for r in rows], dtype=np.float64)
vol_1m = np.array([r[5] for r in rows], dtype=np.float64)
is_bull_1m = cl_1m > op_1m
is_bear_1m = cl_1m < op_1m

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

# === С1: maxV(i-1) sweep ===
maxv = np.full(n12_full, np.nan)
for k in range(n12_full):
    b_start = t12[k]; b_end = b_start + TF12
    i_lo = int(np.searchsorted(ts_1m, b_start, side='left'))
    i_hi = int(np.searchsorted(ts_1m, b_end, side='left'))
    if i_hi <= i_lo: continue
    bull_mask = is_bull_1m[i_lo:i_hi]; bear_mask = is_bear_1m[i_lo:i_hi]
    v_slice = vol_1m[i_lo:i_hi]; c_slice = cl_1m[i_lo:i_hi]
    max_bull = v_slice[bull_mask].max() if bull_mask.any() else 0
    max_bear = v_slice[bear_mask].max() if bear_mask.any() else 0
    if max_bull == 0 and max_bear == 0: continue
    if max_bull >= max_bear:
        idx_local = np.where((v_slice == max_bull) & bull_mask)[0][0]
    else:
        idx_local = np.where((v_slice == max_bear) & bear_mask)[0][0]
    maxv[k] = c_slice[idx_local]
sw_maxV_short = np.zeros(n12_full, dtype=bool)
sw_maxV_long  = np.zeros(n12_full, dtype=bool)
for i in range(1, n12_full):
    mv = maxv[i-1]
    if np.isnan(mv): continue
    if h12[i] > mv and c12[i] < mv: sw_maxV_short[i] = True
    if l12[i] < mv and c12[i] > mv: sw_maxV_long[i] = True

# === С3: ob_liq FIRST 50%-sweep (liq OR OB.zone), direction-matched ===
all_ob_liq = []
for tf, cans in cans_by_tf.items():
    tfms = tfms_map[tf]
    for i in range(len(cans) - 1):
        ol = detect_ob_liq(cans[i], cans[i+1])
        if ol is None: continue
        ready = cans[i+1].open_time + tfms
        all_ob_liq.append({"tf":tf, "direction":ol.direction,
                           "zone_lo":ol.zone[0], "zone_hi":ol.zone[1],
                           "liq_lo":ol.liq_zone[0], "liq_hi":ol.liq_zone[1],
                           "ready_ms":ready})

c_arr = c12

def first_sweep50_idx(z, use_liq_zone):
    sp = int(np.searchsorted(t12, z["ready_ms"], side='left'))
    if sp >= n12_full: return None
    if use_liq_zone: zlo, zhi = z["liq_lo"], z["liq_hi"]
    else:            zlo, zhi = z["zone_lo"], z["zone_hi"]
    mid = (zlo + zhi) / 2
    for k in range(sp, n12_full):
        if z["direction"] == "short":
            if h12[k] >= mid and c_arr[k] < zlo: return k
        else:
            if l12[k] <= mid and c_arr[k] > zhi: return k
    return None
for z in all_ob_liq:
    z["fs50_liq"] = first_sweep50_idx(z, True)
    z["fs50_ob"]  = first_sweep50_idx(z, False)

# === С4: FVG FIRST 50%-sweep multi-TF ===
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
def fvg_first_50sweep_idx(z):
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
    z["fs50"] = fvg_first_50sweep_idx(z)

# === С5: TrendLine HMA-78 (12h ∪ D) LIVE sweep ===
def hma(values, n):
    half = wma(values, n//2)
    full = wma(values, n)
    diff = [(2*half[i]-full[i]) if (half[i] is not None and full[i] is not None) else 0.0 for i in range(len(values))]
    sqrt_n = int(round(math.sqrt(n)))
    return wma(diff, sqrt_n)
closes_12 = [b[4] for b in bars12]
closes_d  = [b[4] for b in bars_by_tf["D"]]
hma_12 = hma(closes_12, 78)
hma_d  = hma(closes_d, 78)
hma_d_200 = hma(closes_d, 200)   # С6
td_arr = np.array([b[0] for b in bars_by_tf["D"]], dtype=np.int64)
def d_idx_for(ts):
    idx = int(np.searchsorted(td_arr, ts, side='right')) - 1
    return idx if 0 <= idx < len(bars_by_tf["D"]) else None

# === С7: block_orders FIRST 50%-sweep multi-TF ===
all_bo = []
for tf, cans in cans_by_tf.items():
    tfms = tfms_map[tf]
    for i in range(len(cans)):
        for L in range(3, 9):
            if i + L > len(cans): break
            bo = detect_block_orders(cans[i:i+L])
            if bo is None: continue
            ready = cans[i].open_time + L*tfms
            zb, zt = bo.zone
            all_bo.append({"tf":tf, "direction":bo.direction,
                           "zone_lo":zb, "zone_hi":zt, "ready_ms":ready})
            break

def bo_first_50sweep_idx(z):
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
for z in all_bo:
    z["fs50"] = bo_first_50sweep_idx(z)

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

# С1 flag
for p in pivots:
    ig = p["i_g"]; d = p["direction"]
    p["c1"] = bool(sw_maxV_short[ig]) if d == "high" else bool(sw_maxV_long[ig])

# С2 flag — P11 union
def aggreg_for_c2(d_rows, tfms):
    return aggregate(d_rows, tfms)
for p in pivots:
    pt = int(p["pivot_open_ts"])
    pt_end = pt + TF12
    i_hi = int(np.searchsorted(ts_1m, pt_end, side='left'))
    flags = []
    for N, thr in [(8, 0.65), (12, 0.75), (16, 0.65), (24, 0.65)]:
        cut = int(np.searchsorted(ts_1m, pt_end - N*15*MS_M, side='left'))
        sub = rows[cut:i_hi]
        sub_15m = aggregate(sub, 15*MS_M)
        if not sub_15m: flags.append(False); continue
        if p["direction"] == "high":
            cnt = sum(1 for b in sub_15m if b[4] < b[1])
        else:
            cnt = sum(1 for b in sub_15m if b[4] > b[1])
        flags.append(cnt/len(sub_15m) >= thr)
    p["c2"] = any(flags)

# С3 flag: FIRST 50%-sweep ob_liq (liq OR OB), direction-matched
def c3_check(p):
    pdir = "short" if p["direction"]=="high" else "long"
    pi = p["i_g"]
    pt = t12[pi]
    pivot_hi = h12[pi]; pivot_lo = l12[pi]; pivot_close = c12[pi]
    for z in all_ob_liq:
        if z["direction"] != pdir: continue
        if z["ready_ms"] > pt: continue
        # liq_zone
        if z["fs50_liq"] == pi:
            return True
        if z["fs50_ob"] == pi:
            return True
    return False
for p in pivots:
    p["c3"] = c3_check(p)

def c4_check(p):
    pdir = "short" if p["direction"]=="high" else "long"
    pi = p["i_g"]
    pt = t12[pi]
    for z in all_fvg:
        if z["direction"] != pdir: continue
        if z["ready_ms"] > pt: continue
        if z["fs50"] == pi:
            return True
    return False
for p in pivots:
    p["c4"] = c4_check(p)

def c5_check(p):
    """LIVE: HMA value на pivot bar i = HMA[i-1]."""
    pi = p["i_g"]; bi = bars12[pi]
    # 12h HMA LIVE
    hv12 = hma_12[pi-1] if pi-1 >= 0 else None
    if hv12 is not None:
        if p["direction"] == "high":
            if bi[2] > hv12 and bi[4] < hv12: return True
        else:
            if bi[3] < hv12 and bi[4] > hv12: return True
    # D HMA LIVE
    didx = d_idx_for(bi[0])
    if didx is not None and didx-1 >= 0:
        hvd = hma_d[didx-1]
        if hvd is not None:
            if p["direction"] == "high":
                if bi[2] > hvd and bi[4] < hvd: return True
            else:
                if bi[3] < hvd and bi[4] > hvd: return True
    return False
for p in pivots:
    p["c5"] = c5_check(p)

def c6_check(p):
    """LIVE HMA-200 на D, direction-matched sweep."""
    pi = p["i_g"]; bi = bars12[pi]
    didx = d_idx_for(bi[0])
    if didx is None or didx-1 < 0: return False
    hv = hma_d_200[didx-1]
    if hv is None: return False
    if p["direction"] == "high":
        return bi[2] > hv and bi[4] < hv
    else:
        return bi[3] < hv and bi[4] > hv
for p in pivots:
    p["c6"] = c6_check(p)

def c7_check(p):
    """FIRST 50%-sweep block_orders direction-matched."""
    pdir = "short" if p["direction"]=="high" else "long"
    pi = p["i_g"]; pt = t12[pi]
    for z in all_bo:
        if z["direction"] != pdir: continue
        if z["ready_ms"] > pt: continue
        if z["fs50"] == pi: return True
    return False
for p in pivots:
    p["c7"] = c7_check(p)

baseN = len(pivots); base_conf = sum(1 for p in pivots if p["confirmed"]); base_imp = sum(1 for p in pivots if p["is_imp"])
baseP = base_conf/baseN*100

def stat(name, mask):
    keep = [p for p in pivots if mask(p)]
    if not keep: return f"  {name:<48} keep=  0"
    conf = sum(1 for p in keep if p["confirmed"])
    notconf = len(keep)-conf
    p_pct = conf/len(keep)*100
    imp = sum(1 for p in keep if p["is_imp"])
    d = p_pct - baseP
    return f"  {name:<48} keep={len(keep):>4}  conf={conf:>3}  not={notconf:>3}  P(W)={p_pct:5.1f}%  Δ={d:+5.1f}pp  imp={imp:>2}/18"

print(f"\n{'='*110}")
print(f"BASELINE F1∩F2∩F3: n={baseN}  conf={base_conf}  not={baseN-base_conf}  P(W)={baseP:.1f}%  imp={base_imp}/18")
print(f"{'='*110}\n")
print(f"Условия независимо:\n")
print(stat("С1 (sweep maxV(i-1))", lambda p: p["c1"]))
print(stat("С2 (P11_count union)", lambda p: p["c2"]))
print(stat("С3 (FIRST 50%-sweep ob_liq)", lambda p: p["c3"]))
print(stat("С4 (FIRST 50%-sweep FVG)", lambda p: p["c4"]))
print(stat("С5 (sweep TL HMA-78 12h∪D LIVE)", lambda p: p["c5"]))
print(stat("С6 (sweep TL HMA-200 D LIVE)", lambda p: p["c6"]))
print(stat("С7 (FIRST 50%-sweep block_orders)", lambda p: p["c7"]))

print(f"\nКОРЗИНА = С1 ∪ С2 ∪ С3 ∪ С4 ∪ С5 ∪ С6 ∪ С7:\n")
all_or = lambda p: p["c1"] or p["c2"] or p["c3"] or p["c4"] or p["c5"] or p["c6"] or p["c7"]
print(stat("Basket (C1∪…∪C7)", all_or))
print(stat("Остаток (в работе)", lambda p: not all_or(p)))

# Доп. С6+С7 на остатке после C1..C5
print(f"\nЧто добавили С6 и С7 поверх C1..C5:\n")
prev_basket = {(p["i_w"], p["direction"]) for p in pivots if p["c1"] or p["c2"] or p["c3"] or p["c4"] or p["c5"]}
new_from_c6 = [p for p in pivots if p["c6"] and (p["i_w"], p["direction"]) not in prev_basket]
new_from_c7 = [p for p in pivots if p["c7"] and (p["i_w"], p["direction"]) not in prev_basket]
prev_plus_c6 = prev_basket | {(p["i_w"], p["direction"]) for p in new_from_c6}
new_from_c7_after_c6 = [p for p in pivots if p["c7"] and (p["i_w"], p["direction"]) not in prev_plus_c6]
for label, lst in [("С6 уникальные новые", new_from_c6), ("С7 уникальные новые (после C6)", new_from_c7_after_c6)]:
    if lst:
        conf = sum(1 for p in lst if p["confirmed"])
        imp = sum(1 for p in lst if p["is_imp"])
        print(f"  {label}: {len(lst)}  conf={conf}  P={conf/len(lst)*100:.1f}%  imp_new={imp}")
    else:
        print(f"  {label}: 0")

# Missed
basket = {(p["i_w"], p["direction"]) for p in pivots if all_or(p)}
all_imp_in_pivots = [p for p in pivots if p["is_imp"]]
missed_now = [p for p in all_imp_in_pivots if (p["i_w"], p["direction"]) not in basket]
print(f"\n{'='*110}")
print(f"ОСТАЛОСЬ ПРОПУЩЕНО: {len(missed_now)} imp")
print(f"{'='*110}")
gt_iw = {(g["i_w"],g["dir"]): n+1 for n,g in enumerate(gt)}
for p in sorted(missed_now, key=lambda x: x["pivot_open_ts"]):
    ts_iso = datetime.fromtimestamp(p["pivot_open_ts"]/1000, MSK).strftime('%Y-%m-%d %H:%M')
    imp_n = gt_iw.get((p["i_w"], p["direction"]))
    print(f"  #{imp_n}  {ts_iso} MSK  dir={p['direction']}")
