"""Кандидаты в Условие 3 на baseline F1∩F2∩F3.

Из профиля 10 пропущенных видно сильные дискриминаторы:
  dist_ema200 ≤ −X (далеко ниже EMA200, drawdown context)
  opp_wick   ≤ Y  (нет спайка на противоположной стороне)
  close_pos  ≤ Z  (закрытие в нижней половине range)
И их комбинации.

Условие 3 evaluates independently on full 1266 — basket = (С1) ∪ (С2) ∪ (С3).
"""
from __future__ import annotations
import csv, pathlib, sys
from datetime import datetime, timezone, timedelta
import numpy as np

sys.path.insert(0, str(pathlib.Path.home() / "smc-lib"))
from candle import Candle
from elements.fractal.code import detect_fractal

CSV = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MSK = timezone(timedelta(hours=3))
MS_M = 60_000
TF12 = 12*60*MS_M
START = int(datetime(2026,2,4,0,0,tzinfo=MSK).timestamp()*1000)
IMP = {1,3,4,5,9,10,11,14,15,20,23,26,29,40,41,42,47,48}

print("Loading 1m...")
rows=[]
with CSV.open() as f:
    rd=csv.reader(f); next(rd)
    for r in rd:
        t=datetime.fromisoformat(r[0])
        rows.append((int(t.timestamp()*1000),float(r[1]),float(r[2]),float(r[3]),float(r[4]),float(r[5])))
ts_1m = np.array([r[0] for r in rows], dtype=np.int64)
op_1m = np.array([r[1] for r in rows], dtype=np.float64)
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

bars12 = agg_ohlcv(rows, TF12)
last_ts = rows[-1][0]
window_start = last_ts - 6*365*24*3600*1000
bars12_w = [b for b in bars12 if b[0] >= window_start]
n12_full = len(bars12)
t12 = np.array([b[0] for b in bars12], dtype=np.int64)
h12 = np.array([b[2] for b in bars12]); l12 = np.array([b[3] for b in bars12])
o12 = np.array([b[1] for b in bars12]); c12 = np.array([b[4] for b in bars12])

# EMA200 на 12h
def ema(values, period):
    out = np.full(len(values), np.nan); k = 2/(period+1)
    out[period-1] = values[:period].mean()
    for i in range(period, len(values)):
        out[i] = values[i]*k + out[i-1]*(1-k)
    return out
ema200 = ema(c12, 200)
ema50 = ema(c12, 50)

# maxV → Условие 1
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
imp_iw_dir = {(gt[n-1]["i_w"], gt[n-1]["dir"]): n+1 for n,g in enumerate(gt) if (n+1) in IMP for _ in [None]}
# fix imp_n
imp_iw_dir = {}
for n,g in enumerate(gt):
    if (n+1) in IMP:
        imp_iw_dir[(g["i_w"], g["dir"])] = n+1
for p in pivots:
    p["is_imp"] = (p["i_w"], p["direction"]) in imp_iw_dir
    p["imp_n"] = imp_iw_dir.get((p["i_w"], p["direction"]))

# Условие 1
for p in pivots:
    ig = p["i_g"]; d = p["direction"]
    p["cond1"] = bool(sw_maxV_short[ig]) if d == "high" else bool(sw_maxV_long[ig])

# Условие 2 — P11_count union
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

# Features for С3 candidates
for p in pivots:
    ig = p["i_g"]
    bi = bars12[ig]
    rng = bi[2] - bi[3]
    if p["direction"] == "high":
        p["opp_wick"] = (min(bi[1],bi[4]) - bi[3])/rng if rng>0 else 0
    else:
        p["opp_wick"] = (bi[2] - max(bi[1],bi[4]))/rng if rng>0 else 0
    p["close_pos"] = (bi[4]-bi[3])/rng if rng>0 else 0.5
    e200 = ema200[ig-1] if ig-1>=0 else np.nan
    e50  = ema50[ig-1] if ig-1>=0 else np.nan
    p["dist_ema200"] = (bi[4]-e200)/e200*100 if e200 and not np.isnan(e200) else np.nan
    p["dist_ema50"]  = (bi[4]-e50)/e50*100   if e50  and not np.isnan(e50)  else np.nan

baseN = len(pivots); base_conf = sum(1 for p in pivots if p["confirmed"]); base_imp = sum(1 for p in pivots if p["is_imp"])
baseP = base_conf/baseN*100
print(f"\nBaseline F1∩F2∩F3: n={baseN}, P={baseP:.1f}%, imp={base_imp}/18")

def stat(name, mask):
    keep = [p for p in pivots if mask(p)]
    if not keep: print(f"  {name:<55} keep=  0"); return
    conf = sum(1 for p in keep if p["confirmed"])
    p_pct = conf/len(keep)*100
    imp = sum(1 for p in keep if p["is_imp"])
    missed_caught = sum(1 for p in keep if p["is_imp"] and not (p["cond1"] or p["cond2"]))
    d = p_pct - baseP
    print(f"  {name:<55} keep={len(keep):>4}  conf={conf:>3}  not={len(keep)-conf:>3}  P(W)={p_pct:5.1f}%  Δ={d:+5.1f}  imp={imp:>2}  catches_missed={missed_caught}/10")

print(f"\n{'='*125}")
print(f"Кандидаты Условия 3 (independent на baseline; смотрим catches_missed/10):")
print(f"{'='*125}")

# Single features
for thr in [-5, -7, -10, -15]:
    stat(f"dist_ema200 ≤ {thr}%",
         lambda p,T=thr: not np.isnan(p["dist_ema200"]) and p["dist_ema200"] <= T)
for thr in [-3, -5, -7, -10]:
    stat(f"dist_ema50 ≤ {thr}%",
         lambda p,T=thr: not np.isnan(p["dist_ema50"]) and p["dist_ema50"] <= T)
for thr in [0.10, 0.07, 0.05]:
    stat(f"opp_wick ≤ {thr}",
         lambda p,T=thr: p["opp_wick"] <= T)
stat("close_pos ≤ 0.40", lambda p: p["close_pos"] <= 0.40)
stat("close_pos ≤ 0.30", lambda p: p["close_pos"] <= 0.30)

# Combinations
print(f"\n{'='*125}")
print(f"Комбинации:")
print(f"{'='*125}")
for ema_thr in [-5, -10]:
    for wick_thr in [0.10, 0.15]:
        stat(f"dist_ema200 ≤ {ema_thr}% AND opp_wick ≤ {wick_thr}",
             lambda p,E=ema_thr,W=wick_thr: (not np.isnan(p["dist_ema200"]) and p["dist_ema200"] <= E) and p["opp_wick"] <= W)

# Combined: maxV+P11 already gives 8/18; С3 candidate
print(f"\n{'='*125}")
print(f"Корзина после добавления Условия 3 = (cond1 ∪ cond2 ∪ cond3):")
print(f"{'='*125}")
for ema_thr in [-5, -7, -10]:
    cond3 = lambda p,T=ema_thr: not np.isnan(p["dist_ema200"]) and p["dist_ema200"] <= T
    basket = [p for p in pivots if p["cond1"] or p["cond2"] or cond3(p)]
    conf = sum(1 for p in basket if p["confirmed"])
    imp_caught = sum(1 for p in basket if p["is_imp"])
    print(f"  С3 = dist_ema200 ≤ {ema_thr}%: basket={len(basket)}  P={conf/len(basket)*100:.1f}%  imp_total={imp_caught}/18")

# С3 = combined dist_ema200 ≤ -5% AND opp_wick ≤ 0.15
def cond3_combo(p):
    return (not np.isnan(p["dist_ema200"]) and p["dist_ema200"] <= -5) and p["opp_wick"] <= 0.15
basket = [p for p in pivots if p["cond1"] or p["cond2"] or cond3_combo(p)]
conf = sum(1 for p in basket if p["confirmed"])
imp_caught = sum(1 for p in basket if p["is_imp"])
print(f"  С3 = ema200≤−5% AND opp_wick≤0.15: basket={len(basket)} P={conf/len(basket)*100:.1f}% imp_total={imp_caught}/18")
