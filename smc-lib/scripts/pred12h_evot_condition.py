"""EVoT ASVK как кандидат в Условие 2 OR-basket (поверх Условия 1 = sweep maxV(i-1)).

EVoT(rNorm) на 1m в окне W:
  bullMinute = volume(1m) если close > open, иначе 0
  bearMinute = volume(1m) если close < open, иначе 0
  rNorm = (Σbull − Σbear) / (Σbull + Σbear) ∈ [−1, +1]

Direction-matched (на pivot candle i):
  FH (top, ожидаем разворот вниз) → rNorm ≤ −τ (bearish dominance)
  FL (bottom, ожидаем разворот вверх) → rNorm ≥ +τ (bullish dominance)

Окна (strictly causal на (i-2, i-1, i)):
  W1 = бар i только
  W2 = (i-1, i)
  W3 = (i-2, i-1, i)

Пороги τ ∈ {0.0, 0.1, 0.2, 0.3, 0.4, 0.5}.

Baseline: F1∩F2∩F3 = 1266 / 619 / 18-18 / P=48.9%.
Уже в корзине (Условие 1 = sweep maxV(i-1)): 356 → остаток 910 / ~13 imp.

Цель: найти условие с WR ≥ 70%.
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
print(f"  {len(rows)} 1m bars")

ts_1m = np.array([r[0] for r in rows], dtype=np.int64)
op_1m = np.array([r[1] for r in rows], dtype=np.float64)
cl_1m = np.array([r[4] for r in rows], dtype=np.float64)
vol_1m = np.array([r[5] for r in rows], dtype=np.float64)

def agg(d, tfms, anchor=0):
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

bars12 = agg(rows, TF12)
last_ts = rows[-1][0]
window_start = last_ts - 6*365*24*3600*1000
bars12_w = [b for b in bars12 if b[0] >= window_start]
print(f"  12h bars in 6y window: {len(bars12_w)}")

# ======= maxV для Условия 1 (то же что в pred12h_C1_C2_orbasket) =======
print("Computing maxV per 12h (для Условия 1)...")
is_bull_1m = cl_1m > op_1m
is_bear_1m = cl_1m < op_1m
n12_full = len(bars12)
t12 = np.array([b[0] for b in bars12], dtype=np.int64)
h12 = np.array([b[2] for b in bars12])
l12 = np.array([b[3] for b in bars12])
c12 = np.array([b[4] for b in bars12])
maxv = np.full(n12_full, np.nan)
for k in range(n12_full):
    b_start = t12[k]; b_end = b_start + TF12
    i_lo = int(np.searchsorted(ts_1m, b_start, side='left'))
    i_hi = int(np.searchsorted(ts_1m, b_end, side='left'))
    if i_hi <= i_lo: continue
    bull_mask = is_bull_1m[i_lo:i_hi]
    bear_mask = is_bear_1m[i_lo:i_hi]
    v_slice = vol_1m[i_lo:i_hi]
    c_slice = cl_1m[i_lo:i_hi]
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

# ======= F1∩F2∩F3 baseline =======
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

# imp tag
cans_w = [Candle(open=b[1],high=b[2],low=b[3],close=b[4],open_time=b[0]) for b in bars12_w]
gt = []
for i in range(2, len(cans_w)-2):
    f = detect_fractal(cans_w[i-2:i+3], n=2)
    if f is None or cans_w[i].open_time < START: continue
    gt.append({"i_w":i, "dir":f.direction})
imp_iw_dir = {(gt[n-1]["i_w"], gt[n-1]["dir"]) for n in IMP if n-1 < len(gt)}
for p in pivots:
    p["is_imp"] = (p["i_w"], p["direction"]) in imp_iw_dir

# tag Условие 1 (= sweep maxV(i-1))
for p in pivots:
    ig = p["i_g"]; d = p["direction"]
    p["cond1"] = bool(sw_maxV_short[ig]) if d == "high" else bool(sw_maxV_long[ig])

baseN = len(pivots); base_conf = sum(1 for p in pivots if p["confirmed"]); base_imp = sum(1 for p in pivots if p["is_imp"])
baseP = base_conf/baseN*100
print(f"\nBaseline F1∩F2∩F3: n={baseN} conf={base_conf} P={baseP:.1f}% imp={base_imp}/18")
remN = sum(1 for p in pivots if not p["cond1"])
rem_conf = sum(1 for p in pivots if not p["cond1"] and p["confirmed"])
rem_imp = sum(1 for p in pivots if not p["cond1"] and p["is_imp"])
print(f"Остаток (после Условия 1): n={remN} conf={rem_conf} P={rem_conf/remN*100:.1f}% imp={rem_imp}/18")

# ======= EVoT(rNorm) для каждого pivot в окнах W1, W2, W3 =======
print("\nComputing EVoT (rNorm) по окнам W1/W2/W3...")

def evot_window(bar_open_ts, bar_count_back):
    """rNorm для окна [bar_open_ts - bar_count_back*12h, bar_open_ts + 12h)."""
    t_lo = bar_open_ts - bar_count_back*TF12
    t_hi = bar_open_ts + TF12
    i_lo = int(np.searchsorted(ts_1m, t_lo, side='left'))
    i_hi = int(np.searchsorted(ts_1m, t_hi, side='left'))
    if i_hi <= i_lo: return np.nan
    vs = vol_1m[i_lo:i_hi]
    bull = vs[is_bull_1m[i_lo:i_hi]].sum()
    bear = vs[is_bear_1m[i_lo:i_hi]].sum()
    denom = bull + bear
    if denom == 0: return np.nan
    return (bull - bear) / denom

for p in pivots:
    pt = int(p["pivot_open_ts"])
    p["evot_W1"] = evot_window(pt, 0)  # bar i
    p["evot_W2"] = evot_window(pt, 1)  # (i-1, i)
    p["evot_W3"] = evot_window(pt, 2)  # (i-2, i-1, i)

# ======= Stats по разным порогам =======
def stat(name, mask_fn, base):
    keep = [p for p in base if mask_fn(p)]
    if not keep: return None
    conf = sum(1 for p in keep if p["confirmed"])
    p_pct = conf/len(keep)*100
    imp = sum(1 for p in keep if p["is_imp"])
    return (name, len(keep), conf, len(keep)-conf, p_pct, p_pct-baseP, imp)

def signed_evot(p, window):
    e = p[window]
    if np.isnan(e): return 0.0
    return -e if p["direction"] == "high" else e  # для FH хотим bear (отрицательный), для FL хотим bull

print(f"\n{'='*120}")
print(f"EVoT direction-matched (для FH: rNorm ≤ −τ; для FL: rNorm ≥ +τ)")
print(f"{'='*120}")
print(f"\nНа FULL baseline (1266 / P=48.9% / 18 imp):\n")
print(f"  {'condition':<45} keep  conf  not  P(W)%  Δpp    imp")
for window in ["evot_W1","evot_W2","evot_W3"]:
    for tau in [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]:
        r = stat(f"EVoT[{window}] dir-match ≥ {tau:.1f}",
                 lambda p, w=window, t=tau: signed_evot(p, w) >= t, pivots)
        if r:
            n,c,nc,p_,d_,imp_ = r[1:]
            mark = " ⭐" if p_ >= 70 else ""
            print(f"  {r[0]:<45} {n:>4}  {c:>4}  {nc:>3}  {p_:5.1f}  {d_:+5.1f}  {imp_:>2}/18{mark}")

print(f"\nНа ОСТАТКЕ (910 / после Условия 1):\n")
rem_pivots = [p for p in pivots if not p["cond1"]]
remP = sum(1 for p in rem_pivots if p["confirmed"])/len(rem_pivots)*100
print(f"  (rem baseline P={remP:.1f}%, imp={rem_imp}/18)")
print(f"  {'condition':<45} keep  conf  not  P(W)%  Δpp    imp_new")
for window in ["evot_W1","evot_W2","evot_W3"]:
    for tau in [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]:
        keep = [p for p in rem_pivots if signed_evot(p, window) >= tau]
        if not keep: continue
        conf = sum(1 for p in keep if p["confirmed"])
        p_pct = conf/len(keep)*100
        imp_caught = sum(1 for p in keep if p["is_imp"])
        delta = p_pct - remP
        mark = " ⭐" if p_pct >= 70 else ""
        print(f"  EVoT[{window}] dir-match ≥ {tau:.1f}{'':<19} {len(keep):>4}  {conf:>4}  {len(keep)-conf:>3}  {p_pct:5.1f}  {delta:+5.1f}  {imp_caught:>2}{mark}")
