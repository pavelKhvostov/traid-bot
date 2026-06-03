"""Условие 2 = union P11_count{8,12,16,24}x15m direction-matched.

Пороги per-вариант, дающие WR ≥ 70% на FULL baseline:
  P11_8x15m  ≥ 0.65  → 143 / 74.8% / 5 imp
  P11_12x15m ≥ 0.75  →  62 / 74.2% / 2 imp
  P11_16x15m ≥ 0.65  →  86 / 69.8% / 3 imp  (близко к 70%)
  P11_24x15m ≥ 0.65  →  60 / 73.3% / 1 imp

P11_count = доля 15m свечей за окно, направленных ПРОТИВ pivot.
  Для FH (top): bearish close (close < open)
  Для FL (bottom): bullish close (close > open)

Цель: посчитать корзину basket = Условие 1 ∪ Условие 2, остаток, новые imp.
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

P11_THRESHOLDS = {
    "P11_8x15m":  0.65,   # 2h window
    "P11_12x15m": 0.75,   # 3h window
    "P11_16x15m": 0.65,   # 4h window
    "P11_24x15m": 0.65,   # 6h window
}

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
h12 = np.array([b[2] for b in bars12]); l12 = np.array([b[3] for b in bars12]); c12 = np.array([b[4] for b in bars12])

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
imp_iw_dir = {(gt[n-1]["i_w"], gt[n-1]["dir"]) for n in IMP if n-1 < len(gt)}
for p in pivots:
    p["is_imp"] = (p["i_w"], p["direction"]) in imp_iw_dir

for p in pivots:
    ig = p["i_g"]; d = p["direction"]
    p["cond1"] = bool(sw_maxV_short[ig]) if d == "high" else bool(sw_maxV_long[ig])

baseN = len(pivots); base_conf = sum(1 for p in pivots if p["confirmed"]); base_imp = sum(1 for p in pivots if p["is_imp"])
baseP = base_conf/baseN*100

# Compute P11 for each window
print("Computing P11_count...")
for p in pivots:
    pt = int(p["pivot_open_ts"])
    pt_end = pt + TF12
    i_hi = int(np.searchsorted(ts_1m, pt_end, side='left'))
    for N in [8, 12, 16, 24]:
        cut = int(np.searchsorted(ts_1m, pt_end - N*15*MS_M, side='left'))
        sub = rows[cut:i_hi]
        sub_15m = agg_ohlcv(sub, 15*MS_M)
        if not sub_15m:
            p[f"P11_{N}x15m"] = np.nan; continue
        if p["direction"] == "high":
            cnt = sum(1 for b in sub_15m if b[4] < b[1])
        else:
            cnt = sum(1 for b in sub_15m if b[4] > b[1])
        p[f"P11_{N}x15m"] = cnt / len(sub_15m)

# Условие 2 = union P11_8 ≥0.65 OR P11_12 ≥0.75 OR P11_16 ≥0.65 OR P11_24 ≥0.65
def cond2(p):
    if (not np.isnan(p["P11_8x15m"]))  and p["P11_8x15m"]  >= P11_THRESHOLDS["P11_8x15m"]:  return True
    if (not np.isnan(p["P11_12x15m"])) and p["P11_12x15m"] >= P11_THRESHOLDS["P11_12x15m"]: return True
    if (not np.isnan(p["P11_16x15m"])) and p["P11_16x15m"] >= P11_THRESHOLDS["P11_16x15m"]: return True
    if (not np.isnan(p["P11_24x15m"])) and p["P11_24x15m"] >= P11_THRESHOLDS["P11_24x15m"]: return True
    return False

for p in pivots:
    p["cond2"] = cond2(p)
    p["in_basket"] = p["cond1"] or p["cond2"]

# Report
def stat(name, mask, base=pivots, base_p=baseP):
    keep = [p for p in base if mask(p)]
    if not keep: print(f"  {name:<48} keep=  0"); return
    conf = sum(1 for p in keep if p["confirmed"])
    notconf = len(keep)-conf
    p_pct = conf/len(keep)*100
    imp = sum(1 for p in keep if p["is_imp"])
    d = p_pct - base_p
    print(f"  {name:<48} keep={len(keep):>4}  conf={conf:>3}  not={notconf:>3}  P(W)={p_pct:5.1f}%  Δ={d:+5.1f}pp  imp={imp:>2}/18")

print(f"\n{'='*110}\nBASELINE F1∩F2∩F3:")
print(f"{'='*110}")
stat("(baseline)", lambda p: True)

print(f"\n{'='*110}\nКаждое условие отдельно:")
print(f"{'='*110}")
stat("Условие 1: sweep maxV(i-1)",                       lambda p: p["cond1"])
stat("Условие 2: union P11_count {8,12,16,24}x15m",      lambda p: p["cond2"])
stat("  - P11_8x15m ≥ 0.65 (компонент)",                 lambda p: not np.isnan(p["P11_8x15m"])  and p["P11_8x15m"]  >= 0.65)
stat("  - P11_12x15m ≥ 0.75 (компонент)",                lambda p: not np.isnan(p["P11_12x15m"]) and p["P11_12x15m"] >= 0.75)
stat("  - P11_16x15m ≥ 0.65 (компонент)",                lambda p: not np.isnan(p["P11_16x15m"]) and p["P11_16x15m"] >= 0.65)
stat("  - P11_24x15m ≥ 0.65 (компонент)",                lambda p: not np.isnan(p["P11_24x15m"]) and p["P11_24x15m"] >= 0.65)

print(f"\n{'='*110}\nКОРЗИНА basket = Условие 1 ∪ Условие 2:")
print(f"{'='*110}")
stat("В корзине (cond1 ∪ cond2)", lambda p: p["in_basket"])

# Что добавило Условие 2 поверх Условия 1 (= NEW from residual 910)
rem_after_c1 = [p for p in pivots if not p["cond1"]]
remP = sum(1 for p in rem_after_c1 if p["confirmed"])/len(rem_after_c1)*100
print(f"\nЧТО ДОБАВИЛО Условие 2 на ОСТАТКЕ после Условия 1 (910 / P={remP:.1f}%):")
new_from_rem = [p for p in rem_after_c1 if p["cond2"]]
if new_from_rem:
    conf_n = sum(1 for p in new_from_rem if p["confirmed"])
    imp_n = sum(1 for p in new_from_rem if p["is_imp"])
    p_pct = conf_n/len(new_from_rem)*100
    print(f"  Уникальные новые в корзину: keep={len(new_from_rem)}  conf={conf_n}  not={len(new_from_rem)-conf_n}  P(W)={p_pct:.1f}%  imp_new={imp_n}")

# Остаток после basket
rem_after_basket = [p for p in pivots if not p["in_basket"]]
remN_b = len(rem_after_basket)
rem_conf_b = sum(1 for p in rem_after_basket if p["confirmed"])
rem_notconf_b = remN_b - rem_conf_b
rem_imp_b = sum(1 for p in rem_after_basket if p["is_imp"])
print(f"\n{'='*110}\nОСТАТОК после basket (для дальнейших условий):")
print(f"{'='*110}")
print(f"  n={remN_b}  conf={rem_conf_b}  not={rem_notconf_b}  P(W)={rem_conf_b/remN_b*100:.1f}%  imp={rem_imp_b}/18")

# Подведём итог по basket
print(f"\n{'='*110}\nИТОГ:")
print(f"{'='*110}")
basket_n = sum(1 for p in pivots if p["in_basket"])
basket_conf = sum(1 for p in pivots if p["in_basket"] and p["confirmed"])
basket_imp = sum(1 for p in pivots if p["in_basket"] and p["is_imp"])
print(f"  Корзина:  {basket_n} / {baseN} ({basket_n/baseN*100:.1f}% от baseline)")
print(f"           conf={basket_conf}  P(W) корзины={basket_conf/basket_n*100:.1f}%  imp={basket_imp}/18")
print(f"  Остаток: {remN_b} / {baseN}  ({remN_b/baseN*100:.1f}% от baseline)")
print(f"           conf={rem_conf_b}  P(W) остатка={rem_conf_b/remN_b*100:.1f}%  imp={rem_imp_b}/18")
print(f"  Пропущенные imp ({18 - basket_imp}):")
missed = [p for p in pivots if p["is_imp"] and not p["in_basket"]]
gt_iw = {(g["i_w"],g["dir"]): n+1 for n,g in enumerate(gt)}
for p in missed:
    ts_iso = datetime.fromtimestamp(p["pivot_open_ts"]/1000, MSK).strftime('%Y-%m-%d %H:%M')
    imp_n = gt_iw.get((p["i_w"], p["direction"]))
    print(f"    #{imp_n}  {ts_iso} MSK  dir={p['direction']}")
