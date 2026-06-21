"""Mining условий с WR≥70%, ловящих 10 missed imp.

Каждое условие — independent на baseline 1266. Фильтр: WR ≥ 70% AND catches_missed ≥ 1.

Кандидаты:
  A. LTF Williams fractal sweep at pivot bar i (TF ∈ {15m, 30m, 1h, 2h, 4h})
  B. LTF OB sweep at pivot bar i (TF ∈ {1h, 2h, 4h})
  C. LTF maxV sweep (1h, 2h, 4h)
  D. HTF FH/FL sweep per TF отдельно (12h, D, 2D, 3D, W)
  E. HTF OB sweep per TF отдельно (long / short)
  F. HTF iFVG sweep per TF
  G. HTF block_orders sweep per TF
"""
from __future__ import annotations
import csv, pathlib, sys
from datetime import datetime, timezone, timedelta
import numpy as np

sys.path.insert(0, str(pathlib.Path.home() / "smc-lib"))
from candle import Candle
from elements.fractal.code import detect_fractal
from elements.ob.code import detect_ob
from elements.fvg.code import detect_fvg
from elements.i_fvg.code import detect_i_fvg

CSV = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MSK = timezone(timedelta(hours=3))
MS_M = 60_000
MS_H = 60*MS_M
TF12 = 12*MS_H
TFD  = 24*MS_H
TF2D = 48*MS_H
TF3D = 72*MS_H
TFW  = 7*24*MS_H
MON_ANCHOR = 1483315200000
START = int(datetime(2026,2,4,0,0,tzinfo=MSK).timestamp()*1000)
IMP = {1,3,4,5,9,10,11,14,15,20,23,26,29,40,41,42,47,48}

WR_MIN = 70.0
KEEP_MIN = 25

print("Loading 1m...")
rows=[]
with CSV.open() as f:
    rd=csv.reader(f); next(rd)
    for r in rd:
        t=datetime.fromisoformat(r[0])
        rows.append((int(t.timestamp()*1000),float(r[1]),float(r[2]),float(r[3]),float(r[4]),float(r[5])))
ts_1m = np.array([r[0] for r in rows], dtype=np.int64)
op_1m = np.array([r[1] for r in rows], dtype=np.float64)
hi_1m = np.array([r[2] for r in rows], dtype=np.float64)
lo_1m = np.array([r[3] for r in rows], dtype=np.float64)
cl_1m = np.array([r[4] for r in rows], dtype=np.float64)
vol_1m = np.array([r[5] for r in rows], dtype=np.float64)
is_bull_1m = cl_1m > op_1m
is_bear_1m = cl_1m < op_1m

def agg_ohlcv(d, tfms, anchor=0):
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

print("Aggregating TFs...")
bars12 = agg_ohlcv(rows, TF12)
last_ts = rows[-1][0]
window_start = last_ts - 6*365*24*3600*1000
bars12_w = [b for b in bars12 if b[0] >= window_start]
n12_full = len(bars12)
t12 = np.array([b[0] for b in bars12], dtype=np.int64)
h12 = np.array([b[2] for b in bars12]); l12 = np.array([b[3] for b in bars12])
c12 = np.array([b[4] for b in bars12])

bars_htf = {"12h":bars12, "D":agg_ohlcv(rows,TFD), "2D":agg_ohlcv(rows,TF2D),
            "3D":agg_ohlcv(rows,TF3D), "W":agg_ohlcv(rows,TFW,MON_ANCHOR)}
bars_ltf = {"15m":agg_ohlcv(rows,15*MS_M), "30m":agg_ohlcv(rows,30*MS_M),
            "1h":agg_ohlcv(rows,MS_H),     "2h":agg_ohlcv(rows,2*MS_H),
            "4h":agg_ohlcv(rows,4*MS_H)}
cans_htf = {tf:[Candle(open=b[1],high=b[2],low=b[3],close=b[4],open_time=b[0]) for b in bb] for tf,bb in bars_htf.items()}
cans_ltf = {tf:[Candle(open=b[1],high=b[2],low=b[3],close=b[4],open_time=b[0]) for b in bb] for tf,bb in bars_ltf.items()}
tfms_map = {"15m":15*MS_M,"30m":30*MS_M,"1h":MS_H,"2h":2*MS_H,"4h":4*MS_H,
            "12h":TF12,"D":TFD,"2D":TF2D,"3D":TF3D,"W":TFW}

# maxV(12h(i-1))
maxv = np.full(n12_full, np.nan)
for k in range(n12_full):
    b_start = t12[k]; b_end = b_start + TF12
    i_lo = int(np.searchsorted(ts_1m, b_start, side='left'))
    i_hi = int(np.searchsorted(ts_1m, b_end, side='left'))
    if i_hi <= i_lo: continue
    bull_mask = is_bull_1m[i_lo:i_hi]
    bear_mask = is_bear_1m[i_lo:i_hi]
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

# F1∩F2∩F3
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

# Условие 1 + 2 для tracking "in_basket"
for p in pivots:
    ig = p["i_g"]; d = p["direction"]
    p["cond1"] = bool(sw_maxV_short[ig]) if d == "high" else bool(sw_maxV_long[ig])

for p in pivots:
    pt = int(p["pivot_open_ts"])
    pt_end = pt + TF12
    i_hi = int(np.searchsorted(ts_1m, pt_end, side='left'))
    flags = []
    for N, thr in [(8, 0.65), (12, 0.75), (16, 0.65), (24, 0.65)]:
        cut = int(np.searchsorted(ts_1m, pt_end - N*15*MS_M, side='left'))
        sub = rows[cut:i_hi]
        sub_15m = agg_ohlcv(sub, 15*MS_M)
        if not sub_15m: flags.append(False); continue
        if p["direction"] == "high":
            cnt = sum(1 for b in sub_15m if b[4] < b[1])
        else:
            cnt = sum(1 for b in sub_15m if b[4] > b[1])
        flags.append(cnt/len(sub_15m) >= thr)
    p["cond2"] = any(flags)
    p["in_basket"] = p["cond1"] or p["cond2"]

missed_set = {(p["i_w"], p["direction"]) for p in pivots if p["is_imp"] and not p["in_basket"]}
print(f"\nBaseline 1266. Уже в корзине: 463. Missed imp: {len(missed_set)}")

baseP = sum(1 for p in pivots if p["confirmed"])/len(pivots)*100

# === Helpers для sweep flags ===
def fractal_sweep_flags_at_pivot(htf_cans, tf_name, kind, pivot_bar_start, pivot_bar_end):
    """Возвращает: pivot sweep flag по untouched HTF fractal level."""
    # Build list of HTF fractals
    tfms = tfms_map[tf_name]
    fr_list = []
    for i in range(2, len(htf_cans)-2):
        f = detect_fractal(htf_cans[i-2:i+3], n=2)
        if f is None: continue
        if f.direction != kind: continue
        fr_list.append({"level":f.level, "ready":htf_cans[i+2].open_time + tfms})
    return fr_list

def make_sweep_flag_per_pivot(fr_list, kind):
    """Для каждого pivot returns True if sweeps an untouched fractal level on bar i."""
    levels = [(f["ready"], f["level"]) for f in fr_list]
    levels.sort()
    # Cumulative untouched: at any time t, the set of untouched levels = those ready ≤ t and not yet swept
    # Simplified: для каждого pivot bar i, проверяем все levels с ready ≤ pivot_start, untouched до pivot_start.
    # Untouched: ни одна свеча 12h до pivot bar i не sweepнула этот level (с close beyond level).
    out = {}
    for p in pivots:
        ig = p["i_g"]
        pivot_open = t12[ig]; pivot_end = pivot_open + TF12
        any_sweep = False
        for ready, lvl in levels:
            if ready >= pivot_open: continue
            # Untouched check: для всех 12h bars от ready до pivot_start, проверяем close-pierce
            sp = int(np.searchsorted(t12, ready, side='left'))
            untouched = True
            for k in range(sp, ig):
                if kind == "high":
                    if c12[k] > lvl: untouched = False; break
                else:
                    if c12[k] < lvl: untouched = False; break
            if not untouched: continue
            # Sweep on bar i: wick через + close обратно
            if kind == "high":
                if h12[ig] > lvl and c12[ig] < lvl: any_sweep = True; break
            else:
                if l12[ig] < lvl and c12[ig] > lvl: any_sweep = True; break
        out[(p["i_w"], p["direction"])] = any_sweep
    return out

def stat(name, masks):
    keep = [p for p in pivots if masks.get((p["i_w"], p["direction"]), False)] if isinstance(masks, dict) else [p for p in pivots if masks(p)]
    if not keep: return None
    conf = sum(1 for p in keep if p["confirmed"])
    p_pct = conf/len(keep)*100
    if p_pct < WR_MIN or len(keep) < KEEP_MIN: return None
    imp = sum(1 for p in keep if p["is_imp"])
    catches = sum(1 for p in keep if (p["i_w"],p["direction"]) in missed_set)
    if catches == 0: return None
    return (name, len(keep), conf, len(keep)-conf, p_pct, p_pct-baseP, imp, catches)

def show(rs):
    rs = [r for r in rs if r]
    rs.sort(key=lambda r: (-r[7], -r[4]))
    if not rs:
        print("  (none meet WR≥70% + catches≥1)"); return
    print(f"  {'name':<55} keep  conf  not  P(W)%   Δ      imp  catches/10")
    for n,k,c,nc,p_,d_,imp_,catch in rs:
        print(f"  {n:<55} {k:>4}  {c:>4}  {nc:>3}  {p_:5.1f}  {d_:+5.1f}  {imp_:>2}  {catch:>2}")

# === A. LTF Williams fractal sweep at pivot bar i ===
print(f"\n{'='*120}\nA. LTF Williams fractal sweep at pivot i (direction-matched: FH ← swept HTF FH; FL ← swept HTF FL)\n{'='*120}")
results_A = []
for tf_name in ["15m","30m","1h","2h","4h"]:
    cs = cans_ltf[tf_name]
    for kind in ["high","low"]:
        fr_list = fractal_sweep_flags_at_pivot(cs, tf_name, kind, None, None)
        # Build sweep flag per pivot: pivot bar i sweeps untouched LTF fractal of `kind` direction
        sweep_per_pivot = {}
        # Pre-sort fr_list by ready time
        levels = [(f["ready"], f["level"]) for f in fr_list]
        levels.sort()
        for p in pivots:
            if (kind=="high" and p["direction"]!="high") or (kind=="low" and p["direction"]!="low"):
                sweep_per_pivot[(p["i_w"], p["direction"])] = False; continue
            ig = p["i_g"]
            pivot_open = t12[ig]
            pivot_high = h12[ig]; pivot_low = l12[ig]; pivot_close = c12[ig]
            any_sweep = False
            for ready, lvl in levels:
                if ready >= pivot_open: continue
                # Quick untouched check on 1m
                i0 = int(np.searchsorted(ts_1m, ready, side='left'))
                i_p = int(np.searchsorted(ts_1m, pivot_open, side='left'))
                if kind == "high":
                    if i_p > i0 and cl_1m[i0:i_p].max() > lvl: continue
                else:
                    if i_p > i0 and cl_1m[i0:i_p].min() < lvl: continue
                if kind == "high":
                    if pivot_high > lvl and pivot_close < lvl: any_sweep = True; break
                else:
                    if pivot_low < lvl and pivot_close > lvl: any_sweep = True; break
            sweep_per_pivot[(p["i_w"], p["direction"])] = any_sweep
        results_A.append(stat(f"LTF_fractal_sweep {tf_name} {kind}", sweep_per_pivot))
show(results_A)

# === D. HTF FH/FL sweep per TF отдельно ===
print(f"\n{'='*120}\nD. HTF Williams fractal sweep at pivot i (по TF)\n{'='*120}")
results_D = []
for tf_name in ["12h","D","2D","3D","W"]:
    cs = cans_htf[tf_name]
    for kind in ["high","low"]:
        fr_list = fractal_sweep_flags_at_pivot(cs, tf_name, kind, None, None)
        levels = [(f["ready"], f["level"]) for f in fr_list]
        levels.sort()
        sweep_per_pivot = {}
        for p in pivots:
            if (kind=="high" and p["direction"]!="high") or (kind=="low" and p["direction"]!="low"):
                sweep_per_pivot[(p["i_w"], p["direction"])] = False; continue
            ig = p["i_g"]
            pivot_open = t12[ig]
            pivot_high = h12[ig]; pivot_low = l12[ig]; pivot_close = c12[ig]
            any_sweep = False
            for ready, lvl in levels:
                if ready >= pivot_open: continue
                sp = int(np.searchsorted(t12, ready, side='left'))
                untouched = True
                for k in range(sp, ig):
                    if kind=="high":
                        if c12[k] > lvl: untouched=False; break
                    else:
                        if c12[k] < lvl: untouched=False; break
                if not untouched: continue
                if kind == "high":
                    if pivot_high > lvl and pivot_close < lvl: any_sweep = True; break
                else:
                    if pivot_low < lvl and pivot_close > lvl: any_sweep = True; break
            sweep_per_pivot[(p["i_w"], p["direction"])] = any_sweep
        results_D.append(stat(f"HTF_fractal_sweep {tf_name} {kind}", sweep_per_pivot))
show(results_D)

# === B. LTF OB sweep at pivot ===
print(f"\n{'='*120}\nB. LTF OB sweep at pivot i (FH ← short OB swept; FL ← long OB swept)\n{'='*120}")
results_B = []
for tf_name in ["1h","2h","4h"]:
    cs = cans_ltf[tf_name]
    tfms = tfms_map[tf_name]
    obs = []
    for k in range(len(cs)-1):
        ob = detect_ob(cs[k], cs[k+1])
        if ob: obs.append({"ob":ob, "ready":cs[k+1].open_time + tfms})
    for ob_dir in ["short","long"]:
        sweep_per_pivot = {}
        for p in pivots:
            req = "high" if ob_dir=="short" else "low"
            if p["direction"] != req:
                sweep_per_pivot[(p["i_w"], p["direction"])] = False; continue
            ig = p["i_g"]
            pivot_open = t12[ig]
            pivot_high = h12[ig]; pivot_low = l12[ig]; pivot_close = c12[ig]
            any_sweep = False
            for o in obs:
                if o["ob"].direction != ob_dir: continue
                if o["ready"] >= pivot_open: continue
                zb, zt = o["ob"].zone
                lvl = zt if ob_dir == "short" else zb
                # Untouched: 1m closes don't pierce
                i0 = int(np.searchsorted(ts_1m, o["ready"], side='left'))
                i_p = int(np.searchsorted(ts_1m, pivot_open, side='left'))
                if ob_dir == "short":
                    if i_p > i0 and cl_1m[i0:i_p].max() > lvl: continue
                    if pivot_high > lvl and pivot_close < lvl: any_sweep = True; break
                else:
                    if i_p > i0 and cl_1m[i0:i_p].min() < lvl: continue
                    if pivot_low < lvl and pivot_close > lvl: any_sweep = True; break
            sweep_per_pivot[(p["i_w"], p["direction"])] = any_sweep
        results_B.append(stat(f"LTF_OB_sweep {tf_name} {ob_dir}", sweep_per_pivot))
show(results_B)

# === E. HTF OB sweep per TF ===
print(f"\n{'='*120}\nE. HTF OB sweep at pivot i (по TF, direction-matched)\n{'='*120}")
results_E = []
for tf_name in ["12h","D","2D","3D","W"]:
    cs = cans_htf[tf_name]
    tfms = tfms_map[tf_name]
    obs = []
    for k in range(len(cs)-1):
        ob = detect_ob(cs[k], cs[k+1])
        if ob: obs.append({"ob":ob, "ready":cs[k+1].open_time + tfms})
    for ob_dir in ["short","long"]:
        sweep_per_pivot = {}
        for p in pivots:
            req = "high" if ob_dir=="short" else "low"
            if p["direction"] != req:
                sweep_per_pivot[(p["i_w"], p["direction"])] = False; continue
            ig = p["i_g"]
            pivot_open = t12[ig]
            pivot_high = h12[ig]; pivot_low = l12[ig]; pivot_close = c12[ig]
            any_sweep = False
            for o in obs:
                if o["ob"].direction != ob_dir: continue
                if o["ready"] >= pivot_open: continue
                zb, zt = o["ob"].zone
                lvl = zt if ob_dir == "short" else zb
                sp = int(np.searchsorted(t12, o["ready"], side='left'))
                untouched = True
                for k in range(sp, ig):
                    if ob_dir == "short":
                        if c12[k] > lvl: untouched=False; break
                    else:
                        if c12[k] < lvl: untouched=False; break
                if not untouched: continue
                if ob_dir == "short":
                    if pivot_high > lvl and pivot_close < lvl: any_sweep = True; break
                else:
                    if pivot_low < lvl and pivot_close > lvl: any_sweep = True; break
            sweep_per_pivot[(p["i_w"], p["direction"])] = any_sweep
        results_E.append(stat(f"HTF_OB_sweep {tf_name} {ob_dir}", sweep_per_pivot))
show(results_E)

# === F. HTF FVG sweep per TF (just FVG levels, untouched) ===
print(f"\n{'='*120}\nF. HTF FVG sweep at pivot i (по TF, direction-matched)\n{'='*120}")
results_F = []
for tf_name in ["12h","D","2D","3D","W"]:
    cs = cans_htf[tf_name]
    tfms = tfms_map[tf_name]
    fvgs = []
    for k in range(len(cs)-2):
        fv = detect_fvg(cs[k], cs[k+1], cs[k+2])
        if fv: fvgs.append({"fvg":fv, "ready":cs[k+2].open_time + tfms})
    for fvg_dir in ["short","long"]:
        sweep_per_pivot = {}
        for p in pivots:
            req = "high" if fvg_dir=="short" else "low"
            if p["direction"] != req:
                sweep_per_pivot[(p["i_w"], p["direction"])] = False; continue
            ig = p["i_g"]
            pivot_open = t12[ig]
            pivot_high = h12[ig]; pivot_low = l12[ig]; pivot_close = c12[ig]
            any_sweep = False
            for f in fvgs:
                if f["fvg"].direction != fvg_dir: continue
                if f["ready"] >= pivot_open: continue
                zb, zt = f["fvg"].zone
                lvl = zt if fvg_dir == "short" else zb
                sp = int(np.searchsorted(t12, f["ready"], side='left'))
                untouched = True
                for k in range(sp, ig):
                    if fvg_dir == "short":
                        if c12[k] > lvl: untouched=False; break
                    else:
                        if c12[k] < lvl: untouched=False; break
                if not untouched: continue
                if fvg_dir == "short":
                    if pivot_high > lvl and pivot_close < lvl: any_sweep = True; break
                else:
                    if pivot_low < lvl and pivot_close > lvl: any_sweep = True; break
            sweep_per_pivot[(p["i_w"], p["direction"])] = any_sweep
        results_F.append(stat(f"HTF_FVG_sweep {tf_name} {fvg_dir}", sweep_per_pivot))
show(results_F)
