"""F5 search — найти дополнительный фильтр поверх F4 v3, дающий ≥70% P(Williams confirm)
   с ≤560 keep, при сохранении 16/16 important (после F4-loss #4 #9)."""
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
MS_H = 3600_000
TF12 = 12*MS_H
TFD = 24*MS_H
TF2D = 48*MS_H
TF3D = 72*MS_H
TFW  = 7*24*MS_H
MON_ANCHOR = 1483315200000

START = int(datetime(2026,2,4,0,0,tzinfo=MSK).timestamp()*1000)
IMP = {1,3,4,5,9,10,11,14,15,20,23,26,29,40,41,42,47,48}
LOST_BY_F4 = {4, 9}
IMP_KEPT = IMP - LOST_BY_F4   # 16 important остающихся после F4

print("Loading 1m data...")
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

bars_by_tf = {
    "12h": agg(rows, TF12),
    "D":   agg(rows, TFD),
    "2D":  agg(rows, TF2D),
    "3D":  agg(rows, TF3D),
    "W":   agg(rows, TFW, MON_ANCHOR),
}
tf_ms_map = {"12h":TF12,"D":TFD,"2D":TF2D,"3D":TF3D,"W":TFW}
cans_by_tf = {tf:[Candle(open=b[1],high=b[2],low=b[3],close=b[4],open_time=b[0]) for b in bb] for tf,bb in bars_by_tf.items()}

last_ts = rows[-1][0]
window_start_ms = last_ts - 6*365*24*3600*1000
bars12_w = [b for b in bars_by_tf["12h"] if b[0] >= window_start_ms]

ts_arr = np.array([r[0] for r in rows], dtype=np.int64)
hi_arr = np.array([r[2] for r in rows], dtype=np.float64)
lo_arr = np.array([r[3] for r in rows], dtype=np.float64)

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
    if hi < lo: lo,hi = hi,lo
    d = map_dir(direction)
    if model=="wick_fill":
        cons = consumed_idx_wick_fill(lo,hi,d,ft)
    elif model=="first_touch":
        cons = consumed_idx_first_touch(lo,hi,d,ft)
    elif model=="sweep_level":
        cons = consumed_idx_sweep_level(extra["level"], extra["sweep_dir"], ft)
    else:
        cons = len(ts_arr)
    zones.append({"tf":tf,"kind":kind,"model":model,"direction":d,
                  "lo":lo,"hi":hi,"formation_ts":ft,"consumed_idx":cons,"extra":extra})

print("Building HTF zones...")
for tf_name, cands in cans_by_tf.items():
    tfms = tf_ms_map[tf_name]
    n_c = len(cands)
    # fractals
    for i in range(2, n_c-2):
        f = detect_fractal(cands[i-2:i+3], n=2)
        if f is None: continue
        ft = cands[i].open_time + 3*tfms
        d = "short" if f.direction=="high" else "long"
        add_zone(tf_name, "FRACTAL_LVL", "sweep_level", d, f.level, f.level, ft,
                 extra={"sweep_dir":f.direction,"level":f.level})
    # OB
    for i in range(n_c-1):
        ob = detect_ob(cands[i], cands[i+1])
        if ob is None: continue
        add_zone(tf_name, "OB", "wick_fill", ob.direction, ob.zone[0], ob.zone[1],
                 cands[i+1].open_time + tfms)
    # FVG
    for i in range(n_c-2):
        fv = detect_fvg(cands[i], cands[i+1], cands[i+2])
        if fv is None: continue
        add_zone(tf_name, "FVG", "wick_fill", fv.direction, fv.zone[0], fv.zone[1],
                 cands[i+2].open_time + tfms)
    # RB
    for c in cands:
        rb = detect_rb(c)
        if rb is None: continue
        d = "short" if rb.direction=="top" else "long"
        add_zone(tf_name, "RB", "first_touch", d, rb.zone[0], rb.zone[1], c.open_time+tfms)
    # marubozu
    for c in cands:
        m = detect_marubozu(c)
        if m is None: continue
        sd = "low" if m.direction=="long" else "high"
        add_zone(tf_name, "MARU_open", "sweep_level", m.direction, c.open, c.open,
                 c.open_time + tfms, extra={"sweep_dir":sd,"level":c.open})
    # RDRB POI
    for i in range(n_c-2):
        r = detect_rdrb(cands[i], cands[i+1], cands[i+2])
        if r is None: continue
        add_zone(tf_name, "RDRB_POI", "wick_fill", r.direction, r.poi[0], r.poi[1],
                 cands[i+2].open_time + tfms)

print(f"  zones: {len(zones)}")

# ATR per TF (для F5b)
def atr_for_tf(tf_name, period=14):
    b = bars_by_tf[tf_name]
    trs = []
    for i in range(1,len(b)):
        h, l, prev_c = b[i][2], b[i][3], b[i-1][4]
        trs.append(max(h-l, abs(h-prev_c), abs(l-prev_c)))
    return np.array(trs)

atr12_arr = atr_for_tf("12h")
bars12_ts = np.array([b[0] for b in bars_by_tf["12h"]], dtype=np.int64)
def atr_at(ts, period=14):
    # ATR за period 12h до timestamp
    i = int(np.searchsorted(bars12_ts, ts, side='right')) - 1
    if i < period: return atr12_arr[:max(1,i)].mean() if i>0 else 1.0
    return atr12_arr[i-period:i].mean()

def color(b):
    if b[4]>b[1]: return "bull"
    if b[4]<b[1]: return "bear"
    return "doji"

# Ground truth indices
cans_full = [Candle(open=b[1],high=b[2],low=b[3],close=b[4],open_time=b[0]) for b in bars12_w]
gt_fractals = []
for i in range(2, len(cans_full)-2):
    f = detect_fractal(cans_full[i-2:i+3], n=2)
    if f is None: continue
    if cans_full[i].open_time < START: continue
    gt_fractals.append({"dir":f.direction,"level":f.level,"idx":i})
imp_idx_set = {gt_fractals[n-1]["idx"] for n in IMP}
imp_kept_set = {gt_fractals[n-1]["idx"] for n in IMP_KEPT}
imp_lost_set = {gt_fractals[n-1]["idx"] for n in LOST_BY_F4}

# Rebuild F1∩F2∩F3
print("Building F1∩F2∩F3 candidates...")
f1f2f3 = []
for i in range(2, len(bars12_w)-2):
    bi = bars12_w[i]; bi1=bars12_w[i-1]; bi2=bars12_w[i-2]
    bip1=bars12_w[i+1]; bip2=bars12_w[i+2]
    pre_fh = bi[2]>bi1[2] and bi[2]>bi2[2]
    pre_fl = bi[3]<bi1[3] and bi[3]<bi2[3]
    if not (pre_fh or pre_fl): continue
    for direction in (("high",) if pre_fh else ()) + (("low",) if pre_fl else ()):
        if direction=="high":
            confirmed = bi[2]>bip1[2] and bi[2]>bip2[2]
            relevant_wick = bi[2] - max(bi[1],bi[4])
        else:
            confirmed = bi[3]<bip1[3] and bi[3]<bip2[3]
            relevant_wick = min(bi[1],bi[4]) - bi[3]
        rng = bi[2]-bi[3] if bi[2]>bi[3] else 1e-9
        body = abs(bi[4]-bi[1])
        c0,c1,c2 = color(bi),color(bi1),color(bi2)
        left_lo = max(0, i-5); left_hi = i
        if direction=="high":
            f1 = bi[2]>max(b[2] for b in bars12_w[left_lo:left_hi]) if left_hi>left_lo else True
        else:
            f1 = bi[3]<min(b[3] for b in bars12_w[left_lo:left_hi]) if left_hi>left_lo else True
        if not f1: continue
        opp = c0!=c1 and "doji" not in (c0,c1)
        three = c0==c1==c2 and c0!="doji"
        if not (opp or three): continue
        if body/rng>0.80 or relevant_wick/rng<0.03: continue
        f1f2f3.append({"idx":i,"direction":direction,"confirmed":confirmed,
                       "is_important":i in imp_idx_set,
                       "imp_kept":i in imp_kept_set,
                       "imp_lost":i in imp_lost_set,
                       "bar":bi,"prev":bi1,"prev2":bi2,
                       "rng":rng,"body":body,"wick":relevant_wick,
                       "pivot_low":bi[3],"pivot_high":bi[2],
                       "pivot_open_ts":bi[0]})

print(f"  F1∩F2∩F3 = {len(f1f2f3)}")

# F4 v3 computation per candidate
def dir_matches(fr_dir, zone_dir):
    return (fr_dir=="high" and zone_dir=="short") or (fr_dir=="low" and zone_dir=="long")

def f4_check_level(f):
    """F4 level mode + collect details for F5."""
    pivot_open_ts = f["pivot_open_ts"]
    pivot_open_idx = int(np.searchsorted(ts_arr, pivot_open_ts, side='left'))
    pivot_level = f["pivot_high"] if f["direction"]=="high" else f["pivot_low"]
    hits = []
    main_kinds = {"FRACTAL_LVL","OB","FVG","RB","MARU_open","RDRB_POI"}
    for z in zones:
        if z["kind"] not in main_kinds: continue
        if z["formation_ts"] >= pivot_open_ts: continue
        if not dir_matches(f["direction"], z["direction"]): continue
        if z["consumed_idx"] < pivot_open_idx: continue
        # current bounds (wick-fill update)
        i0 = int(np.searchsorted(ts_arr, z["formation_ts"], side='left'))
        if z["model"]=="wick_fill":
            if z["direction"]=="long":
                cur_hi = min(z["hi"], float(lo_arr[i0:pivot_open_idx].min())) if i0<pivot_open_idx else z["hi"]
                cur_lo = z["lo"]
            else:
                cur_lo = max(z["lo"], float(hi_arr[i0:pivot_open_idx].max())) if i0<pivot_open_idx else z["lo"]
                cur_hi = z["hi"]
        else:
            cur_lo, cur_hi = z["lo"], z["hi"]
        if cur_lo > cur_hi: continue
        if cur_lo <= pivot_level <= cur_hi:
            age_bars = (pivot_open_ts - z["formation_ts"]) / tf_ms_map[z["tf"]]
            hits.append({"tf":z["tf"],"kind":z["kind"],"age":age_bars,
                         "model":z["model"],"width":cur_hi-cur_lo})
    return hits

print("Running F4 v3 + collecting hit details...")
for k, f in enumerate(f1f2f3):
    if k%200==0: print(f"  {k}/{len(f1f2f3)}", flush=True)
    f["hits"] = f4_check_level(f)
    f["f4_pass"] = len(f["hits"]) > 0

f4_keep = [c for c in f1f2f3 if c["f4_pass"]]
print(f"\nF4 v3 baseline: {len(f4_keep)} keep, conf={sum(1 for c in f4_keep if c['confirmed'])}, imp_kept={sum(1 for c in f4_keep if c['imp_kept'])}/16")

# === F5 search ===
TF_RANK = {"W":5,"3D":4,"2D":3,"D":2,"12h":1}

def hit_max_tf(hits):
    return max((TF_RANK.get(h["tf"],0) for h in hits), default=0)
def hit_tf_count(hits):
    return len({h["tf"] for h in hits})
def hit_kind_class(h):
    if h["kind"] in ("FRACTAL_LVL","RB","MARU_open"): return "liquidity"
    if h["kind"] in ("FVG",): return "inefficiency"
    return "efficiency"  # OB, RDRB_POI

def stat(name, pred, base=f4_keep, IMP_TARGET=16):
    yes = [c for c in base if pred(c)]
    if not yes:
        print(f"  {name:<60} keep=  0")
        return
    conf = sum(1 for c in yes if c["confirmed"])
    imp = sum(1 for c in yes if c["imp_kept"])
    p = conf/len(yes)*100
    print(f"  {name:<60} keep={len(yes):>4}  conf={conf:>3} ({p:5.1f}%)  imp={imp:>2}/{IMP_TARGET}")

print(f"\n{'='*120}")
print(" F5 candidates (поверх F4 v3, цель: keep ≤ 560, P(conf) ≥ 70%, imp ≥ 15/16)")
print(f"{'='*120}")
print(f"  {'baseline F4 v3':<60} keep={len(f4_keep):>4}  conf={sum(1 for c in f4_keep if c['confirmed']):>3} ({sum(1 for c in f4_keep if c['confirmed'])/len(f4_keep)*100:5.1f}%)  imp={sum(1 for c in f4_keep if c['imp_kept']):>2}/16")

# F5a: max HTF rank ≥ ...
stat("F5a max_tf ≥ D (D, 2D, 3D, W)",         lambda c: hit_max_tf(c["hits"]) >= 2)
stat("F5a max_tf ≥ 2D",                       lambda c: hit_max_tf(c["hits"]) >= 3)
stat("F5a max_tf ≥ 3D",                       lambda c: hit_max_tf(c["hits"]) >= 4)
stat("F5a max_tf == W",                       lambda c: hit_max_tf(c["hits"]) >= 5)

# F5b: число различных TF в hits
stat("F5b tf_count ≥ 2 (multi-TF confluence)", lambda c: hit_tf_count(c["hits"]) >= 2)
stat("F5b tf_count ≥ 3",                       lambda c: hit_tf_count(c["hits"]) >= 3)

# F5c: содержит hit класса liquidity
stat("F5c contains liquidity class (FRACTAL/RB/MARU)", lambda c: any(hit_kind_class(h)=="liquidity" for h in c["hits"]))
stat("F5c contains fractal hit specifically",  lambda c: any(h["kind"]=="FRACTAL_LVL" for h in c["hits"]))

# F5d: pivot range / ATR(14)
def rng_over_atr(c, k=1.0):
    atr = atr_at(c["pivot_open_ts"])
    return c["rng"] / atr >= k
stat("F5d range/ATR ≥ 1.0",                    lambda c: rng_over_atr(c, 1.0))
stat("F5d range/ATR ≥ 1.2",                    lambda c: rng_over_atr(c, 1.2))
stat("F5d range/ATR ≥ 1.5",                    lambda c: rng_over_atr(c, 1.5))

# F5e: wick ≥ X × body  (sweep-like pivot)
stat("F5e wick ≥ 1.0 × body",                  lambda c: c["wick"] >= 1.0*c["body"])
stat("F5e wick ≥ 1.5 × body",                  lambda c: c["wick"] >= 1.5*c["body"])
stat("F5e wick ≥ 2.0 × body",                  lambda c: c["wick"] >= 2.0*c["body"])

# F5f: COMBINATIONS
stat("F5f (max_tf ≥ D) AND (tf_count ≥ 2)",    lambda c: hit_max_tf(c["hits"])>=2 and hit_tf_count(c["hits"])>=2)
stat("F5f (max_tf ≥ 2D) AND wick ≥ 1.5×body",  lambda c: hit_max_tf(c["hits"])>=3 and c["wick"]>=1.5*c["body"])
stat("F5f (max_tf ≥ D) AND range/ATR ≥ 1.2",   lambda c: hit_max_tf(c["hits"])>=2 and rng_over_atr(c,1.2))
stat("F5f (tf_count ≥ 2) AND wick ≥ 1.5×body", lambda c: hit_tf_count(c["hits"])>=2 and c["wick"]>=1.5*c["body"])
stat("F5f (max_tf ≥ D) AND wick ≥ body",       lambda c: hit_max_tf(c["hits"])>=2 and c["wick"]>=c["body"])
stat("F5f (max_tf ≥ D) AND liquidity-hit",     lambda c: hit_max_tf(c["hits"])>=2 and any(hit_kind_class(h)=="liquidity" for h in c["hits"]))
stat("F5f (fractal-hit) AND wick ≥ body",      lambda c: any(h["kind"]=="FRACTAL_LVL" for h in c["hits"]) and c["wick"]>=c["body"])

# Triple combos
stat("F5g triple: max_tf ≥ D & tf_count ≥ 2 & wick ≥ body",
     lambda c: hit_max_tf(c["hits"])>=2 and hit_tf_count(c["hits"])>=2 and c["wick"]>=c["body"])
stat("F5g triple: max_tf ≥ D & tf_count ≥ 2 & range/ATR ≥ 1.2",
     lambda c: hit_max_tf(c["hits"])>=2 and hit_tf_count(c["hits"])>=2 and rng_over_atr(c,1.2))
