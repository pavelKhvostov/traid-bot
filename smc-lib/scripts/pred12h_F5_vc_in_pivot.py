"""F5 = VC (Volume Confirmation) внутри pivot 12h-свечи.
   VC = LTF FVG (15m/20m) ⊆ HTF OB (1h/2h) того же направления.

   Counter VC = направление OB противоположно направлению pivot:
     pivot FH (top) → SHORT VC (SHORT OB с SHORT FVG внутри неё, sub-zone reversal)
     pivot FL (bot) → LONG VC
"""
from __future__ import annotations
import csv, pathlib, sys
from datetime import datetime, timezone, timedelta
import numpy as np

sys.path.insert(0, str(pathlib.Path.home() / "smc-lib"))
from candle import Candle
from elements.fractal.code import detect_fractal
from elements.fvg.code import detect_fvg
from elements.ob.code import detect_ob
from elements.rb.code import detect_rb
from elements.marubozu.code import detect_marubozu
from elements.rdrb.code import detect_rdrb
from elements.ob_vc.vc_predicate import has_vc

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

def consumed_idx_wick_fill(zl,zh,d,ft):
    i0 = int(np.searchsorted(ts_arr, ft, side='left'))
    if i0>=len(ts_arr): return len(ts_arr)
    m = lo_arr[i0:]<=zl if d=="long" else hi_arr[i0:]>=zh
    nz = int(np.argmax(m))
    return len(ts_arr) if not m[nz] else i0+nz
def consumed_idx_first_touch(zl,zh,d,ft):
    i0 = int(np.searchsorted(ts_arr, ft, side='left'))
    if i0>=len(ts_arr): return len(ts_arr)
    m = lo_arr[i0:]<=zh if d=="long" else hi_arr[i0:]>=zl
    nz = int(np.argmax(m))
    return len(ts_arr) if not m[nz] else i0+nz
def consumed_idx_sweep_level(lvl, sd, ft):
    i0 = int(np.searchsorted(ts_arr, ft, side='left'))
    if i0>=len(ts_arr): return len(ts_arr)
    m = hi_arr[i0:]>=lvl if sd=="high" else lo_arr[i0:]<=lvl
    nz = int(np.argmax(m))
    return len(ts_arr) if not m[nz] else i0+nz
def map_dir(d):
    if d in ("long","bottom"): return "long"
    if d in ("short","top"): return "short"
    return d

zones=[]
def add_zone(tf,kind,model,direction,lo,hi,ft,extra=None):
    if hi<lo: lo,hi=hi,lo
    d = map_dir(direction)
    if model=="wick_fill": cons=consumed_idx_wick_fill(lo,hi,d,ft)
    elif model=="first_touch": cons=consumed_idx_first_touch(lo,hi,d,ft)
    elif model=="sweep_level": cons=consumed_idx_sweep_level(extra["level"],extra["sweep_dir"],ft)
    else: cons=len(ts_arr)
    zones.append({"tf":tf,"kind":kind,"model":model,"direction":d,"lo":lo,"hi":hi,
                  "formation_ts":ft,"consumed_idx":cons,"extra":extra})

print("Building HTF zones (F4 stack)...")
for tf_name, cands in cans_by_tf.items():
    tfms = tf_ms_map[tf_name]; n_c=len(cands)
    for i in range(2,n_c-2):
        f=detect_fractal(cands[i-2:i+3], n=2)
        if f:
            d="short" if f.direction=="high" else "long"
            add_zone(tf_name,"FRACTAL_LVL","sweep_level",d,f.level,f.level,cands[i].open_time+3*tfms,
                     extra={"sweep_dir":f.direction,"level":f.level})
    for i in range(n_c-1):
        ob=detect_ob(cands[i],cands[i+1])
        if ob: add_zone(tf_name,"OB","wick_fill",ob.direction,ob.zone[0],ob.zone[1],cands[i+1].open_time+tfms)
    for i in range(n_c-2):
        fv=detect_fvg(cands[i],cands[i+1],cands[i+2])
        if fv: add_zone(tf_name,"FVG","wick_fill",fv.direction,fv.zone[0],fv.zone[1],cands[i+2].open_time+tfms)
    for c in cands:
        rb=detect_rb(c)
        if rb:
            d="short" if rb.direction=="top" else "long"
            add_zone(tf_name,"RB","first_touch",d,rb.zone[0],rb.zone[1],c.open_time+tfms)
        m=detect_marubozu(c)
        if m:
            sd="low" if m.direction=="long" else "high"
            add_zone(tf_name,"MARU_open","sweep_level",m.direction,c.open,c.open,c.open_time+tfms,
                     extra={"sweep_dir":sd,"level":c.open})
    for i in range(n_c-2):
        r=detect_rdrb(cands[i],cands[i+1],cands[i+2])
        if r: add_zone(tf_name,"RDRB_POI","wick_fill",r.direction,r.poi[0],r.poi[1],cands[i+2].open_time+tfms)

cans_full = [Candle(open=b[1],high=b[2],low=b[3],close=b[4],open_time=b[0]) for b in bars12_w]
gt=[]
for i in range(2,len(cans_full)-2):
    f=detect_fractal(cans_full[i-2:i+3], n=2)
    if f is None or cans_full[i].open_time<START: continue
    gt.append({"idx":i,"dir":f.direction,"level":f.level})
imp_idx_set = {gt[n-1]["idx"] for n in IMP}
imp_kept_set = {gt[n-1]["idx"] for n in IMP_KEPT}

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
        f1f2f3.append({"idx":i,"direction":direction,"confirmed":confirmed,
                       "is_important":i in imp_idx_set, "imp_kept":i in imp_kept_set,
                       "rng":rng,"body":body,"wick":rwick,
                       "pivot_low":bi[3],"pivot_high":bi[2],"pivot_open_ts":bi[0]})
print(f"  F1∩F2∩F3 = {len(f1f2f3)}")

def dir_matches(fr,zd): return (fr=="high" and zd=="short") or (fr=="low" and zd=="long")

def f4_pass(f):
    pot=f["pivot_open_ts"]; poi=int(np.searchsorted(ts_arr,pot,side='left'))
    pl=f["pivot_high"] if f["direction"]=="high" else f["pivot_low"]
    main={"FRACTAL_LVL","OB","FVG","RB","MARU_open","RDRB_POI"}
    for z in zones:
        if z["kind"] not in main: continue
        if z["formation_ts"]>=pot: continue
        if not dir_matches(f["direction"],z["direction"]): continue
        if z["consumed_idx"]<poi: continue
        i0=int(np.searchsorted(ts_arr,z["formation_ts"],side='left'))
        if z["model"]=="wick_fill":
            if z["direction"]=="long":
                ch=min(z["hi"],float(lo_arr[i0:poi].min())) if i0<poi else z["hi"]
                cl=z["lo"]
            else:
                cl=max(z["lo"],float(hi_arr[i0:poi].max())) if i0<poi else z["lo"]
                ch=z["hi"]
        else:
            cl,ch=z["lo"],z["hi"]
        if cl>ch: continue
        if cl<=pl<=ch: return True
    return False

# ===== VC inside pivot =====
# Для каждого pivot собираем OB на (1h, 2h) внутри pivot.window,
# затем для каждой OB ищем LTF FVG (15m, 20m) и применяем has_vc.

OB_TFS = (60, 120)   # минуты: 1h, 2h
FVG_TFS = (15, 20)   # минуты: 15m, 20m

def find_vc_in_pivot(pivot_open_ts):
    """Возвращает список найденных VC: {ob_tf, fvg_tf, direction, ob_zone, fvg_zone}."""
    end = pivot_open_ts + TF12
    i_lo = int(np.searchsorted(ts_arr, pivot_open_ts, side='left'))
    i_hi = int(np.searchsorted(ts_arr, end, side='left'))
    slc = list(zip(ts_arr[i_lo:i_hi], op_arr[i_lo:i_hi], hi_arr[i_lo:i_hi], lo_arr[i_lo:i_hi], cl_arr[i_lo:i_hi]))
    found = []
    # detect HTF OBs
    ob_lists = {}
    for tf_min in OB_TFS:
        tfms = tf_min*MS_M
        bb = agg(slc, tfms)
        if len(bb) < 2: continue
        cs = [Candle(open=b[1],high=b[2],low=b[3],close=b[4],open_time=b[0]) for b in bb]
        obs = []
        for k in range(len(cs)-1):
            ob = detect_ob(cs[k], cs[k+1])
            if ob: obs.append({"ob":ob,"start_ts":cs[k].open_time,
                               "end_ts":cs[k+1].open_time + tfms})
        ob_lists[tf_min] = obs
    # detect LTF FVGs
    fvg_lists = {}
    for tf_min in FVG_TFS:
        tfms = tf_min*MS_M
        bb = agg(slc, tfms)
        if len(bb) < 3: continue
        cs = [Candle(open=b[1],high=b[2],low=b[3],close=b[4],open_time=b[0]) for b in bb]
        fvgs = []
        for k in range(len(cs)-2):
            fv = detect_fvg(cs[k], cs[k+1], cs[k+2])
            if fv: fvgs.append({"fvg":fv,"c3_ts":cs[k+2].open_time, "c1_ts":cs[k].open_time})
        fvg_lists[tf_min] = fvgs
    # combine: для каждой OB пары проверить все FVG того же направления, чьё окно
    # пересекается с окном активной OB (LTF FVG формируется внутри HTF OB window).
    for ob_tf, obs in ob_lists.items():
        for ob_rec in obs:
            ob = ob_rec["ob"]
            for fvg_tf, fvgs in fvg_lists.items():
                for fv_rec in fvgs:
                    fv = fv_rec["fvg"]
                    # временное окно: LTF FVG должна формироваться в окне OB
                    if fv_rec["c3_ts"] < ob_rec["start_ts"] or fv_rec["c1_ts"] > ob_rec["end_ts"]:
                        continue
                    if has_vc(ob, fv):
                        found.append({"ob_tf":ob_tf,"fvg_tf":fvg_tf,
                                      "direction":ob.direction,
                                      "ob_zone":ob.zone,"fvg_zone":fv.zone})
    return found

print("Computing F4 + VC search inside pivot (это займёт несколько минут)...")
for k,f in enumerate(f1f2f3):
    if k%200==0: print(f"  {k}/{len(f1f2f3)}", flush=True)
    f["f4"] = f4_pass(f)
    f["vcs"] = find_vc_in_pivot(f["pivot_open_ts"])

f4_keep = [c for c in f1f2f3 if c["f4"]]
baseP = sum(1 for c in f4_keep if c["confirmed"])/len(f4_keep)*100
print(f"\nbase F4 v3: {len(f4_keep)} keep, P={baseP:.1f}%, imp 16/16")

def has_vc_any(c): return len(c["vcs"])>0
def has_vc_counter(c):
    want = "short" if c["direction"]=="high" else "long"
    return any(v["direction"]==want for v in c["vcs"])
def has_vc_aligned(c):
    want = "long" if c["direction"]=="high" else "short"
    return any(v["direction"]==want for v in c["vcs"])
def has_vc_counter_ob_tf(c, ob_tf):
    want = "short" if c["direction"]=="high" else "long"
    return any(v["direction"]==want and v["ob_tf"]==ob_tf for v in c["vcs"])
def has_vc_counter_fvg_tf(c, fvg_tf):
    want = "short" if c["direction"]=="high" else "long"
    return any(v["direction"]==want and v["fvg_tf"]==fvg_tf for v in c["vcs"])

def stat(name, pred, base=f4_keep):
    yes=[c for c in base if pred(c)]
    if not yes:
        print(f"  {name:<60} keep=  0"); return
    conf=sum(1 for c in yes if c["confirmed"])
    imp=sum(1 for c in yes if c["imp_kept"])
    p=conf/len(yes)*100
    d=p-baseP
    print(f"  {name:<60} keep={len(yes):>4}  conf={conf:>3} ({p:5.1f}%, {d:+5.1f}pp)  imp={imp:>2}/16")

print(f"\n{'='*120}\n F5 = VC inside pivot. База F4 v3 = {len(f4_keep)} keep / P {baseP:.1f}% / imp 16/16\n{'='*120}")
stat("ANY VC inside pivot",                    has_vc_any)
stat("COUNTER VC (any TF combo)",              has_vc_counter)
stat("COUNTER VC, OB=1h",                      lambda c: has_vc_counter_ob_tf(c,60))
stat("COUNTER VC, OB=2h",                      lambda c: has_vc_counter_ob_tf(c,120))
stat("COUNTER VC, FVG=15m",                    lambda c: has_vc_counter_fvg_tf(c,15))
stat("COUNTER VC, FVG=20m",                    lambda c: has_vc_counter_fvg_tf(c,20))
stat("COUNTER VC, OB=1h AND FVG=15m",          lambda c: any(v["direction"]==("short" if c["direction"]=="high" else "long") and v["ob_tf"]==60 and v["fvg_tf"]==15 for v in c["vcs"]))
stat("COUNTER VC, OB=2h AND FVG=15m",          lambda c: any(v["direction"]==("short" if c["direction"]=="high" else "long") and v["ob_tf"]==120 and v["fvg_tf"]==15 for v in c["vcs"]))
stat("COUNTER VC, OB=2h AND FVG=20m",          lambda c: any(v["direction"]==("short" if c["direction"]=="high" else "long") and v["ob_tf"]==120 and v["fvg_tf"]==20 for v in c["vcs"]))
stat("ALIGNED VC (any TF) — counter-test",     has_vc_aligned)
print()
print(f" Без F4 (на 1266 F1∩F2∩F3):")
all_base = f1f2f3
baseP2 = sum(1 for c in all_base if c["confirmed"])/len(all_base)*100
def stat2(name, pred, base=all_base, baseP=baseP2):
    yes=[c for c in base if pred(c)]
    if not yes:
        print(f"  {name:<60} keep=  0"); return
    conf=sum(1 for c in yes if c["confirmed"])
    imp=sum(1 for c in yes if c["imp_kept"]) + sum(1 for c in yes if c["is_important"] and not c["imp_kept"])
    p=conf/len(yes)*100
    d=p-baseP
    print(f"  {name:<60} keep={len(yes):>4}  conf={conf:>3} ({p:5.1f}%, {d:+5.1f}pp)  imp={imp:>2}/18")
stat2("COUNTER VC any (no F4)", has_vc_counter)
stat2("COUNTER VC OB=2h FVG=20m (no F4)",
      lambda c: any(v["direction"]==("short" if c["direction"]=="high" else "long") and v["ob_tf"]==120 and v["fvg_tf"]==20 for v in c["vcs"]))
