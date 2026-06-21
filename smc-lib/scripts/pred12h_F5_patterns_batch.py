"""F5 batch — 8 reversal-формаций внутри pivot 12h на TF 5m/15m/30m/1h.
   Counter-direction only (для FH pivot: bearish patterns; для FL pivot: bullish).
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

# ---- HTF zones for F4 ----
def consumed_idx_wick_fill(zl, zh, d, ft):
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
    zones.append({"tf":tf,"kind":kind,"direction":d,"model":model,"lo":lo,"hi":hi,
                  "formation_ts":ft,"consumed_idx":cons,"extra":extra})

print("Building HTF zones...")
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
print(f"  zones: {len(zones)}")

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
        if not(opp or three): continue
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

# ---------- Pattern detectors (counter-direction). cs[i] = (ts, o, h, l, c) ----------
def _body(b): return abs(b[4]-b[1])
def _rng(b): return max(b[2]-b[3], 1e-9)
def _is_bull(b): return b[4]>b[1]
def _is_bear(b): return b[4]<b[1]
def _upper(b): return b[2]-max(b[1],b[4])
def _lower(b): return min(b[1],b[4])-b[3]

def pat_engulfing_bear(c1,c2):
    return _is_bull(c1) and _is_bear(c2) and c2[1]>=c1[4] and c2[4]<=c1[1] and _body(c2)>_body(c1)
def pat_engulfing_bull(c1,c2):
    return _is_bear(c1) and _is_bull(c2) and c2[1]<=c1[4] and c2[4]>=c1[1] and _body(c2)>_body(c1)

def pat_shooting_star(b):
    body=_body(b); rng=_rng(b)
    return body<=0.30*rng and _upper(b)>=2*body and _lower(b)<=body and body>0
def pat_hammer(b):
    body=_body(b); rng=_rng(b)
    return body<=0.30*rng and _lower(b)>=2*body and _upper(b)<=body and body>0

def pat_evening_star(c1,c2,c3):
    if not _is_bull(c1) or not _is_bear(c3): return False
    b1,b2,b3 = _body(c1),_body(c2),_body(c3)
    if b2>=0.5*b1: return False
    # gap-like + close c3 below midpoint of c1
    mid = (c1[1]+c1[4])/2.0
    return min(c2[1],c2[4])>=max(c1[1],c1[4]) and c3[4]<=mid
def pat_morning_star(c1,c2,c3):
    if not _is_bear(c1) or not _is_bull(c3): return False
    b1,b2,b3 = _body(c1),_body(c2),_body(c3)
    if b2>=0.5*b1: return False
    mid = (c1[1]+c1[4])/2.0
    return max(c2[1],c2[4])<=min(c1[1],c1[4]) and c3[4]>=mid

def pat_three_crows(c1,c2,c3):
    if not(_is_bear(c1) and _is_bear(c2) and _is_bear(c3)): return False
    if not(c2[1]<=c1[1] and c2[1]>=c1[4]): return False
    if not(c3[1]<=c2[1] and c3[1]>=c2[4]): return False
    return c1[4]>c2[4]>c3[4]
def pat_three_soldiers(c1,c2,c3):
    if not(_is_bull(c1) and _is_bull(c2) and _is_bull(c3)): return False
    if not(c2[1]>=c1[1] and c2[1]<=c1[4]): return False
    if not(c3[1]>=c2[1] and c3[1]<=c2[4]): return False
    return c1[4]<c2[4]<c3[4]

def pat_tweezer_top(c1,c2):
    return abs(c1[2]-c2[2])/max(c1[2],1)<=0.001 and _is_bull(c1) and _is_bear(c2)
def pat_tweezer_bottom(c1,c2):
    return abs(c1[3]-c2[3])/max(c1[3],1)<=0.001 and _is_bear(c1) and _is_bull(c2)

def pat_marubozu_bear(b):
    return _is_bear(b) and b[1]==b[2] and b[2]>b[3]
def pat_marubozu_bull(b):
    return _is_bull(b) and b[1]==b[3] and b[2]>b[3]

# Williams sweep counter: micro Williams (3-bar local extreme confirmed by next two bars)
def pat_williams_fh(bb, k):
    # bb is list of bars; FH at index k: b[k].high > b[k±1].high and b[k±2].high
    if k<2 or k+2>=len(bb): return False
    return bb[k][2]>bb[k-1][2] and bb[k][2]>bb[k-2][2] and bb[k][2]>bb[k+1][2] and bb[k][2]>bb[k+2][2]
def pat_williams_fl(bb, k):
    if k<2 or k+2>=len(bb): return False
    return bb[k][3]<bb[k-1][3] and bb[k][3]<bb[k-2][3] and bb[k][3]<bb[k+1][3] and bb[k][3]<bb[k+2][3]

# i-RDRB counter — use detector
def pat_irdrb(c1,c2,c3,c4):
    from elements.i_rdrb.code import detect_i_rdrb
    try:
        return detect_i_rdrb(Candle(open=c1[1],high=c1[2],low=c1[3],close=c1[4],open_time=c1[0]),
                             Candle(open=c2[1],high=c2[2],low=c2[3],close=c2[4],open_time=c2[0]),
                             Candle(open=c3[1],high=c3[2],low=c3[3],close=c3[4],open_time=c3[0]),
                             Candle(open=c4[1],high=c4[2],low=c4[3],close=c4[4],open_time=c4[0]))
    except Exception:
        return None

def scan_pivot(pivot_open_ts, pivot_dir):
    """Return dict: per-(tf, pattern, counter) presence flags."""
    end = pivot_open_ts + TF12
    i_lo = int(np.searchsorted(ts_arr, pivot_open_ts, side='left'))
    i_hi = int(np.searchsorted(ts_arr, end, side='left'))
    slc = list(zip(ts_arr[i_lo:i_hi], op_arr[i_lo:i_hi], hi_arr[i_lo:i_hi], lo_arr[i_lo:i_hi], cl_arr[i_lo:i_hi]))
    # counter-direction patterns required:
    counter_bear = (pivot_dir == "high")  # FH → bear reversal
    res = {}
    for tf_min in (5, 15, 30, 60):
        tfms = tf_min*MS_M
        bb = agg(slc, tfms)
        flags = {"engulf":False,"pin":False,"star":False,"three":False,"tweezer":False,
                 "maru":False,"williams":False,"irdrb":False}
        n = len(bb)
        if n>=2:
            for k in range(n-1):
                pair = (bb[k], bb[k+1])
                if counter_bear:
                    if pat_engulfing_bear(*pair): flags["engulf"]=True
                    if pat_tweezer_top(*pair): flags["tweezer"]=True
                else:
                    if pat_engulfing_bull(*pair): flags["engulf"]=True
                    if pat_tweezer_bottom(*pair): flags["tweezer"]=True
        if n>=1:
            for k in range(n):
                b=bb[k]
                if counter_bear:
                    if pat_shooting_star(b): flags["pin"]=True
                    if pat_marubozu_bear(b): flags["maru"]=True
                else:
                    if pat_hammer(b): flags["pin"]=True
                    if pat_marubozu_bull(b): flags["maru"]=True
        if n>=3:
            for k in range(n-2):
                t=(bb[k],bb[k+1],bb[k+2])
                if counter_bear:
                    if pat_evening_star(*t): flags["star"]=True
                    if pat_three_crows(*t): flags["three"]=True
                else:
                    if pat_morning_star(*t): flags["star"]=True
                    if pat_three_soldiers(*t): flags["three"]=True
        if n>=5:
            for k in range(n):
                if counter_bear:
                    if pat_williams_fh(bb, k): flags["williams"]=True
                else:
                    if pat_williams_fl(bb, k): flags["williams"]=True
        if n>=4:
            for k in range(n-3):
                ir = pat_irdrb(bb[k],bb[k+1],bb[k+2],bb[k+3])
                if ir:
                    # i-RDRB direction = opposite of underlying RDRB.
                    # For counter-bear (FH), нужен i-RDRB SHORT.
                    irdir = ir.rdrb.direction
                    # NB: i-RDRB itself signals reversal in direction of detected pattern composite
                    # Direction of i-RDRB = direction of breakout candle C4 vs C3
                    # use it as: counter_bear → ir resulting reversal direction = down → ir.rdrb.direction=long means underlying RDRB was bull → reversal i-RDRB is bear
                    desired = "long" if counter_bear else "short"
                    if irdir == desired:
                        flags["irdrb"]=True
        for p,v in flags.items():
            res[(tf_min, p)] = v
    return res

print("Computing F4 + pattern batch (this may take a few minutes)...")
for k,f in enumerate(f1f2f3):
    if k%200==0: print(f"  {k}/{len(f1f2f3)}", flush=True)
    f["f4"] = f4_pass(f)
    f["pat"] = scan_pivot(f["pivot_open_ts"], f["direction"])

f4_keep = [c for c in f1f2f3 if c["f4"]]
baseP = sum(1 for c in f4_keep if c["confirmed"])/len(f4_keep)*100
print(f"\nbase F4 v3: {len(f4_keep)} keep, P={baseP:.1f}%, imp 16/16")

def stat(name, pred, base=f4_keep):
    yes=[c for c in base if pred(c)]
    if not yes:
        print(f"  {name:<60} keep=  0"); return
    conf=sum(1 for c in yes if c["confirmed"])
    imp=sum(1 for c in yes if c["imp_kept"])
    p=conf/len(yes)*100
    d=p-baseP
    print(f"  {name:<60} keep={len(yes):>4}  conf={conf:>3} ({p:5.1f}%, {d:+5.1f}pp)  imp={imp:>2}/16")

print(f"\n{'='*120}\n=== По одному паттерну, по TF ===\n{'='*120}")
patterns = ["engulf","pin","star","three","tweezer","maru","williams","irdrb"]
labels = {"engulf":"Engulfing","pin":"Pin/Hammer/ShStar","star":"Morn/Even Star",
          "three":"3 Soldiers/Crows","tweezer":"Tweezer Top/Bot",
          "maru":"Marubozu","williams":"Williams sweep","irdrb":"i-RDRB"}
for p in patterns:
    print(f"--- {labels[p]} ---")
    for tfm in (5,15,30,60):
        stat(f"  TF {tfm}m", lambda c, p=p, tfm=tfm: c["pat"].get((tfm,p), False))
    stat(f"  ANY TF 5-60m", lambda c, p=p: any(c["pat"].get((tfm,p),False) for tfm in (5,15,30,60)))
    print()

print(f"{'='*120}\n=== OR-комбинации (any of N patterns, any TF) ===\n{'='*120}")
def any_pat(c, ps, tfs=(5,15,30,60)):
    return any(c["pat"].get((tf,p),False) for p in ps for tf in tfs)
stat("ANY of 8 patterns × any TF",            lambda c: any_pat(c, patterns))
stat("Engulf OR Pin OR Star",                 lambda c: any_pat(c, ["engulf","pin","star"]))
stat("Engulf OR Pin",                         lambda c: any_pat(c, ["engulf","pin"]))
stat("Engulf OR Williams",                    lambda c: any_pat(c, ["engulf","williams"]))
stat("Engulf OR Three",                       lambda c: any_pat(c, ["engulf","three"]))
stat("Engulf only ≥15m",                      lambda c: any_pat(c, ["engulf"], (15,30,60)))
stat("Pin only ≥15m",                         lambda c: any_pat(c, ["pin"], (15,30,60)))
stat("Engulf+Pin+Star+Three+Tweezer ≥15m",    lambda c: any_pat(c, ["engulf","pin","star","three","tweezer"], (15,30,60)))
