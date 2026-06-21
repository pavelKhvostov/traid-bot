"""F5 = i-FVG (15m, 20m, 30m) внутри pivot 12h-свечи.
   Семантика: i-FVG сам по себе — reversal сигнал.
   Если внутри pivot есть i-FVG в направлении разворота → сильнейшая confluence."""
from __future__ import annotations
import csv, pathlib, sys
from datetime import datetime, timezone, timedelta
import numpy as np

sys.path.insert(0, str(pathlib.Path.home() / "smc-lib"))
from candle import Candle
from elements.fractal.code import detect_fractal
from elements.fvg.code import detect_fvg
from elements.i_fvg.code import detect_i_fvg
from elements.ob.code import detect_ob
from elements.rb.code import detect_rb
from elements.marubozu.code import detect_marubozu
from elements.rdrb.code import detect_rdrb

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
LOST_BY_F4 = {4,9}
IMP_KEPT = IMP - LOST_BY_F4

print("Loading 1m...")
rows=[]
with CSV.open() as f:
    rd=csv.reader(f); next(rd)
    for r in rd:
        t=datetime.fromisoformat(r[0])
        rows.append((int(t.timestamp()*1000),float(r[1]),float(r[2]),float(r[3]),float(r[4])))

def agg(d, tfms, anchor=0):
    out=[]; cb=None; o=h=l=c=0.0
    for ts,oo,hh,ll,cc in d:
        b = ts - ((ts - anchor) % tfms)
        if b!=cb:
            if cb is not None: out.append((cb,o,h,l,c))
            cb=b; o,h,l,c=oo,hh,ll,cc
        else:
            h=max(h,hh); l=min(l,ll); c=cc
    if cb is not None: out.append((cb,o,h,l,c))
    return out

ts_arr = np.array([r[0] for r in rows], dtype=np.int64)
hi_arr = np.array([r[2] for r in rows], dtype=np.float64)
lo_arr = np.array([r[3] for r in rows], dtype=np.float64)
op_arr = np.array([r[1] for r in rows], dtype=np.float64)
cl_arr = np.array([r[4] for r in rows], dtype=np.float64)

bars12_full = agg(rows, TF12)
last_ts = rows[-1][0]
window_start_ms = last_ts - 6*365*24*3600*1000
bars12_w = [b for b in bars12_full if b[0] >= window_start_ms]

bars_by_tf = {"12h":bars12_full,"D":agg(rows,TFD),"2D":agg(rows,TF2D),"3D":agg(rows,TF3D),"W":agg(rows,TFW,MON_ANCHOR)}
tf_ms_map = {"12h":TF12,"D":TFD,"2D":TF2D,"3D":TF3D,"W":TFW}
cans_by_tf = {tf:[Candle(open=b[1],high=b[2],low=b[3],close=b[4],open_time=b[0]) for b in bb] for tf,bb in bars_by_tf.items()}

def consumed_idx_wick_fill(zone_lo, zone_hi, direction, formation_ts):
    i0 = int(np.searchsorted(ts_arr, formation_ts, side='left'))
    if i0>=len(ts_arr): return len(ts_arr)
    if direction=="long":
        mask = lo_arr[i0:] <= zone_lo
    else:
        mask = hi_arr[i0:] >= zone_hi
    nz = int(np.argmax(mask))
    if not mask[nz]: return len(ts_arr)
    return i0+nz

def consumed_idx_first_touch(zone_lo, zone_hi, direction, formation_ts):
    i0 = int(np.searchsorted(ts_arr, formation_ts, side='left'))
    if i0>=len(ts_arr): return len(ts_arr)
    if direction=="long":
        mask = lo_arr[i0:] <= zone_hi
    else:
        mask = hi_arr[i0:] >= zone_lo
    nz = int(np.argmax(mask))
    if not mask[nz]: return len(ts_arr)
    return i0+nz

def consumed_idx_sweep_level(level, sweep_dir, formation_ts):
    i0 = int(np.searchsorted(ts_arr, formation_ts, side='left'))
    if i0>=len(ts_arr): return len(ts_arr)
    if sweep_dir=="high":
        mask = hi_arr[i0:] >= level
    else:
        mask = lo_arr[i0:] <= level
    nz = int(np.argmax(mask))
    if not mask[nz]: return len(ts_arr)
    return i0+nz

def map_dir(d):
    if d in ("long","bottom"): return "long"
    if d in ("short","top"): return "short"
    return d

zones = []
def add_zone(tf, kind, model, direction, lo, hi, ft, extra=None):
    if hi<lo: lo,hi=hi,lo
    d = map_dir(direction)
    if model=="wick_fill": cons=consumed_idx_wick_fill(lo,hi,d,ft)
    elif model=="first_touch": cons=consumed_idx_first_touch(lo,hi,d,ft)
    elif model=="sweep_level": cons=consumed_idx_sweep_level(extra["level"],extra["sweep_dir"],ft)
    else: cons=len(ts_arr)
    zones.append({"tf":tf,"kind":kind,"model":model,"direction":d,"lo":lo,"hi":hi,
                  "formation_ts":ft,"consumed_idx":cons,"extra":extra})

print("Building HTF zones...")
for tf_name, cands in cans_by_tf.items():
    tfms = tf_ms_map[tf_name]
    n_c = len(cands)
    for i in range(2,n_c-2):
        f = detect_fractal(cands[i-2:i+3], n=2)
        if f is None: continue
        ft = cands[i].open_time + 3*tfms
        d = "short" if f.direction=="high" else "long"
        add_zone(tf_name,"FRACTAL_LVL","sweep_level",d,f.level,f.level,ft,
                 extra={"sweep_dir":f.direction,"level":f.level})
    for i in range(n_c-1):
        ob = detect_ob(cands[i], cands[i+1])
        if ob is None: continue
        add_zone(tf_name,"OB","wick_fill",ob.direction,ob.zone[0],ob.zone[1],cands[i+1].open_time+tfms)
    for i in range(n_c-2):
        fv = detect_fvg(cands[i],cands[i+1],cands[i+2])
        if fv is None: continue
        add_zone(tf_name,"FVG","wick_fill",fv.direction,fv.zone[0],fv.zone[1],cands[i+2].open_time+tfms)
    for c in cands:
        rb = detect_rb(c)
        if rb is None: continue
        d = "short" if rb.direction=="top" else "long"
        add_zone(tf_name,"RB","first_touch",d,rb.zone[0],rb.zone[1],c.open_time+tfms)
    for c in cans_by_tf[tf_name]:
        m = detect_marubozu(c)
        if m is None: continue
        sd = "low" if m.direction=="long" else "high"
        add_zone(tf_name,"MARU_open","sweep_level",m.direction,c.open,c.open,c.open_time+tfms,
                 extra={"sweep_dir":sd,"level":c.open})
    for i in range(n_c-2):
        r = detect_rdrb(cands[i],cands[i+1],cands[i+2])
        if r is None: continue
        add_zone(tf_name,"RDRB_POI","wick_fill",r.direction,r.poi[0],r.poi[1],cands[i+2].open_time+tfms)
print(f"  zones: {len(zones)}")

cans_full = [Candle(open=b[1],high=b[2],low=b[3],close=b[4],open_time=b[0]) for b in bars12_w]
gt_fractals=[]
for i in range(2,len(cans_full)-2):
    f = detect_fractal(cans_full[i-2:i+3], n=2)
    if f is None: continue
    if cans_full[i].open_time < START: continue
    gt_fractals.append({"idx":i,"dir":f.direction,"level":f.level})
imp_idx_set = {gt_fractals[n-1]["idx"] for n in IMP}
imp_kept_set = {gt_fractals[n-1]["idx"] for n in IMP_KEPT}

def color(b):
    if b[4]>b[1]: return "bull"
    if b[4]<b[1]: return "bear"
    return "doji"

print("Building F1∩F2∩F3...")
f1f2f3=[]
for i in range(2,len(bars12_w)-2):
    bi=bars12_w[i]; bi1=bars12_w[i-1]; bi2=bars12_w[i-2]
    bip1=bars12_w[i+1]; bip2=bars12_w[i+2]
    pre_fh = bi[2]>bi1[2] and bi[2]>bi2[2]
    pre_fl = bi[3]<bi1[3] and bi[3]<bi2[3]
    if not(pre_fh or pre_fl): continue
    for direction in (("high",) if pre_fh else ()) + (("low",) if pre_fl else ()):
        if direction=="high":
            confirmed = bi[2]>bip1[2] and bi[2]>bip2[2]
            rwick = bi[2]-max(bi[1],bi[4])
        else:
            confirmed = bi[3]<bip1[3] and bi[3]<bip2[3]
            rwick = min(bi[1],bi[4])-bi[3]
        rng = bi[2]-bi[3] if bi[2]>bi[3] else 1e-9
        body = abs(bi[4]-bi[1])
        c0,c1,c2 = color(bi),color(bi1),color(bi2)
        left_lo=max(0,i-5); left_hi=i
        if direction=="high":
            f1 = bi[2]>max(b[2] for b in bars12_w[left_lo:left_hi]) if left_hi>left_lo else True
        else:
            f1 = bi[3]<min(b[3] for b in bars12_w[left_lo:left_hi]) if left_hi>left_lo else True
        if not f1: continue
        opp = c0!=c1 and "doji" not in (c0,c1)
        three = c0==c1==c2 and c0!="doji"
        if not (opp or three): continue
        if body/rng>0.80 or rwick/rng<0.03: continue
        f1f2f3.append({"idx":i,"direction":direction,"confirmed":confirmed,
                       "is_important":i in imp_idx_set,
                       "imp_kept":i in imp_kept_set,
                       "rng":rng,"body":body,"wick":rwick,
                       "pivot_low":bi[3],"pivot_high":bi[2],
                       "pivot_open_ts":bi[0]})
print(f"  F1∩F2∩F3 = {len(f1f2f3)}")

def dir_matches(fr_dir, zone_dir):
    return (fr_dir=="high" and zone_dir=="short") or (fr_dir=="low" and zone_dir=="long")

def f4_pass(f):
    pivot_open_ts = f["pivot_open_ts"]
    pivot_open_idx = int(np.searchsorted(ts_arr, pivot_open_ts, side='left'))
    pivot_level = f["pivot_high"] if f["direction"]=="high" else f["pivot_low"]
    main_kinds = {"FRACTAL_LVL","OB","FVG","RB","MARU_open","RDRB_POI"}
    for z in zones:
        if z["kind"] not in main_kinds: continue
        if z["formation_ts"] >= pivot_open_ts: continue
        if not dir_matches(f["direction"], z["direction"]): continue
        if z["consumed_idx"] < pivot_open_idx: continue
        i0 = int(np.searchsorted(ts_arr, z["formation_ts"], side='left'))
        if z["model"]=="wick_fill":
            if z["direction"]=="long":
                cur_hi = min(z["hi"], float(lo_arr[i0:pivot_open_idx].min())) if i0<pivot_open_idx else z["hi"]
                cur_lo = z["lo"]
            else:
                cur_lo = max(z["lo"], float(hi_arr[i0:pivot_open_idx].max())) if i0<pivot_open_idx else z["lo"]
                cur_hi = z["hi"]
        else:
            cur_lo,cur_hi = z["lo"],z["hi"]
        if cur_lo>cur_hi: continue
        if cur_lo <= pivot_level <= cur_hi: return True
    return False

# === i-FVG internal search ===
def find_internal_ifvgs(pivot_open_ts):
    """Search i-FVG on TF in (15m, 20m, 30m) inside pivot 12h window.
       Returns list of {tf_min, direction}."""
    end = pivot_open_ts + TF12
    i_lo = int(np.searchsorted(ts_arr, pivot_open_ts, side='left'))
    i_hi = int(np.searchsorted(ts_arr, end, side='left'))
    slc = list(zip(ts_arr[i_lo:i_hi], op_arr[i_lo:i_hi],
                   hi_arr[i_lo:i_hi], lo_arr[i_lo:i_hi], cl_arr[i_lo:i_hi]))
    found = []
    for tf_min in (15, 20, 30):
        tfms = tf_min*MS_M
        bb = agg(slc, tfms)
        if len(bb) < 5: continue
        cs = [Candle(open=b[1],high=b[2],low=b[3],close=b[4],open_time=b[0]) for b in bb]
        # Detect all FVGs first
        fvgs = []
        for k in range(len(cs)-2):
            fv = detect_fvg(cs[k], cs[k+1], cs[k+2])
            if fv: fvgs.append({"idx":k,"fvg":fv,"cs":(cs[k],cs[k+1],cs[k+2])})
        # Pair scan: для каждого B FVG ищем A FVG противоположного направления
        for j in range(len(fvgs)):
            b = fvgs[j]
            for kk in range(j-1, max(-1, j-30), -1):
                a = fvgs[kk]
                if a["fvg"].direction == b["fvg"].direction: continue
                between_lo = a["idx"]+3
                between_hi = b["idx"]
                if between_hi <= between_lo: continue
                between = cs[between_lo:between_hi]
                try:
                    ifvg = detect_i_fvg(a["cs"][0],a["cs"][1],a["cs"][2], between,
                                        b["cs"][0],b["cs"][1],b["cs"][2])
                except Exception:
                    ifvg = None
                if ifvg:
                    found.append({"tf":tf_min,"direction":ifvg.direction})
                    break
    return found

print("Computing F4 + internal i-FVG...")
for k,f in enumerate(f1f2f3):
    if k%200==0: print(f"  {k}/{len(f1f2f3)}", flush=True)
    f["f4"] = f4_pass(f)
    f["i_fvgs"] = find_internal_ifvgs(f["pivot_open_ts"])

f4_keep = [c for c in f1f2f3 if c["f4"]]

def has_any_ifvg(c): return len(c["i_fvgs"]) > 0
def has_ifvg_tf(c, tf_min): return any(x["tf"]==tf_min for x in c["i_fvgs"])
def has_ifvg_tf_set(c, tfs): return any(x["tf"] in tfs for x in c["i_fvgs"])
def has_counter_ifvg(c):
    # FH (top) → разворот вниз → SHORT i-FVG; FL → LONG i-FVG
    want = "short" if c["direction"]=="high" else "long"
    return any(x["direction"]==want for x in c["i_fvgs"])
def has_aligned_ifvg(c):
    want = "long" if c["direction"]=="high" else "short"
    return any(x["direction"]==want for x in c["i_fvgs"])
def has_counter_ifvg_min_tf(c, tf_min):
    want = "short" if c["direction"]=="high" else "long"
    return any(x["direction"]==want and x["tf"]>=tf_min for x in c["i_fvgs"])

def stat(name, pred, base):
    yes = [c for c in base if pred(c)]
    if not yes:
        print(f"  {name:<60} keep=  0")
        return
    conf = sum(1 for c in yes if c["confirmed"])
    imp = sum(1 for c in yes if c["imp_kept"])
    p = conf/len(yes)*100
    base_p = sum(1 for c in base if c["confirmed"])/len(base)*100
    delta = p - base_p
    print(f"  {name:<60} keep={len(yes):>4}  conf={conf:>3} ({p:5.1f}%, {delta:+5.1f}pp)  imp={imp:>2}/16")

print(f"\n{'='*120}")
print(f" F5 = i-FVG inside pivot. База F4 v3 = {len(f4_keep)} keep, P={sum(1 for c in f4_keep if c['confirmed'])/len(f4_keep)*100:.1f}%, imp 16/16")
print(f"{'='*120}")
stat("F5 any i-FVG (15/20/30m)",               has_any_ifvg, f4_keep)
stat("F5 i-FVG 15m",                           lambda c: has_ifvg_tf(c,15), f4_keep)
stat("F5 i-FVG 20m",                           lambda c: has_ifvg_tf(c,20), f4_keep)
stat("F5 i-FVG 30m",                           lambda c: has_ifvg_tf(c,30), f4_keep)
stat("F5 i-FVG ≥20m (20 or 30)",               lambda c: has_ifvg_tf_set(c,{20,30}), f4_keep)
print()
stat("F5 counter i-FVG any",                   has_counter_ifvg, f4_keep)
stat("F5 counter i-FVG ≥20m",                  lambda c: has_counter_ifvg_min_tf(c,20), f4_keep)
stat("F5 counter i-FVG 30m",                   lambda c: has_counter_ifvg_min_tf(c,30), f4_keep)
print()
stat("F5 aligned i-FVG any",                   has_aligned_ifvg, f4_keep)
print()
print(" Без F4 (на 1266 F1∩F2∩F3):")
stat("any i-FVG (no F4)",                      has_any_ifvg, f1f2f3)
stat("counter i-FVG (no F4)",                  has_counter_ifvg, f1f2f3)
stat("counter i-FVG ≥20m (no F4)",             lambda c: has_counter_ifvg_min_tf(c,20), f1f2f3)
