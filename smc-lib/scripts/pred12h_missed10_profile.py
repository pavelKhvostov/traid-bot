"""Профиль 10 пропущенных imp (после Условий 1+2).

Для каждого: время, направление, размер бара, расположение close,
ATR-norm range, distance to EMA, volume features, и т.д.

Цель: найти признаки, отличающие эти 10 от 803 "в работе" not-imp.
Из них — кандидат в Условие 3.
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

bars12 = agg_ohlcv(rows, TF12)
last_ts = rows[-1][0]
window_start = last_ts - 6*365*24*3600*1000
bars12_w = [b for b in bars12 if b[0] >= window_start]
n12_full = len(bars12)
t12 = np.array([b[0] for b in bars12], dtype=np.int64)
h12 = np.array([b[2] for b in bars12]); l12 = np.array([b[3] for b in bars12])
o12 = np.array([b[1] for b in bars12]); c12 = np.array([b[4] for b in bars12])
v12 = np.array([b[5] for b in bars12])

# ATR(14) на 12h
def atr(highs, lows, closes, period=14):
    n = len(highs); a = np.full(n, np.nan)
    tr = np.zeros(n)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        tr[i] = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
    a[period-1] = tr[:period].mean()
    for i in range(period, n):
        a[i] = (a[i-1]*(period-1) + tr[i]) / period
    return a
atr12 = atr(h12, l12, c12)

# EMA 20 / 50 / 200 на 12h
def ema(values, period):
    out = np.full(len(values), np.nan); k = 2/(period+1)
    out[period-1] = values[:period].mean()
    for i in range(period, len(values)):
        out[i] = values[i]*k + out[i-1]*(1-k)
    return out
ema20 = ema(c12, 20); ema50 = ema(c12, 50); ema200 = ema(c12, 200)

# Avg volume 14
def sma(values, period):
    out = np.full(len(values), np.nan)
    for i in range(period-1, len(values)):
        out[i] = values[i-period+1:i+1].mean()
    return out
vol_avg14 = sma(v12, 14)

# maxV для Условия 1
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
imp_iw_dir = {(gt[n-1]["i_w"], gt[n-1]["dir"]): n for n in IMP if n-1 < len(gt)}
for p in pivots:
    p["is_imp"] = (p["i_w"], p["direction"]) in imp_iw_dir
    p["imp_n"] = imp_iw_dir.get((p["i_w"], p["direction"]))

# Условие 1
for p in pivots:
    ig = p["i_g"]; d = p["direction"]
    p["cond1"] = bool(sw_maxV_short[ig]) if d == "high" else bool(sw_maxV_long[ig])

# Условие 2 = P11_count union
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

# Compute features per pivot
print("Computing features for missed imp profile...")
for p in pivots:
    ig = p["i_g"]
    bi = bars12[ig]; bi1 = bars12[ig-1]
    pt = bi[0]
    rng = bi[2] - bi[3]
    body = abs(bi[4]-bi[1])
    p["range"] = rng
    p["body"] = body
    p["body_pct_range"] = body/rng if rng>0 else 0
    if p["direction"] == "high":
        p["rel_wick"] = (bi[2] - max(bi[1],bi[4]))/rng
        p["opp_wick"] = (min(bi[1],bi[4]) - bi[3])/rng
    else:
        p["rel_wick"] = (min(bi[1],bi[4]) - bi[3])/rng
        p["opp_wick"] = (bi[2] - max(bi[1],bi[4]))/rng
    # close position within range (0=low, 1=high)
    p["close_pos"] = (bi[4]-bi[3])/rng if rng>0 else 0.5
    # ATR-norm range
    a = atr12[ig-1] if ig-1>=0 and not np.isnan(atr12[ig-1]) else np.nan
    p["atr"] = a
    p["range_atr"] = rng/a if a and a>0 else np.nan
    # Volume vs avg
    va = vol_avg14[ig-1] if ig-1>=0 and not np.isnan(vol_avg14[ig-1]) else np.nan
    p["vol"] = bi[5]
    p["vol_norm"] = bi[5]/va if va and va>0 else np.nan
    # gap
    p["gap"] = (bi[1] - bi1[4])/bi1[4] * 100  # %
    # distance to EMAs (signed, % of price)
    e20 = ema20[ig-1]; e50 = ema50[ig-1]; e200 = ema200[ig-1]
    p["dist_ema20"] = (bi[4]-e20)/e20*100 if e20 and not np.isnan(e20) else np.nan
    p["dist_ema50"] = (bi[4]-e50)/e50*100 if e50 and not np.isnan(e50) else np.nan
    p["dist_ema200"] = (bi[4]-e200)/e200*100 if e200 and not np.isnan(e200) else np.nan
    # session (MSK hour)
    dt = datetime.fromtimestamp(pt/1000, MSK)
    p["msk_hour"] = dt.hour
    p["weekday"] = dt.weekday()
    # range_atr categorization: large bar?
    # min_v relation
    # bar pos in week
    p["is_weekend"] = dt.weekday() >= 5

# Identify 10 missed imp
missed = [p for p in pivots if p["is_imp"] and not p["in_basket"]]
missed.sort(key=lambda p: p["imp_n"])
print(f"\nПропущено {len(missed)} imp\n")

# Distribution of comparison: not-imp not-in-basket (= 793 in residual minus 10 imp)
not_imp_rest = [p for p in pivots if not p["is_imp"] and not p["in_basket"]]
print(f"Сравнение группа (not-imp, not in basket): {len(not_imp_rest)}")

# Per-pivot details
features = ["range_atr","body_pct_range","rel_wick","opp_wick","close_pos","vol_norm","gap","dist_ema20","dist_ema50","dist_ema200","msk_hour"]

print(f"\n{'#':<3} {'time MSK':<17} {'dir':<5} ", end="")
for f in features: print(f"{f:>11} ", end="")
print()
print("-"*200)
for p in missed:
    ts_iso = datetime.fromtimestamp(p["pivot_open_ts"]/1000, MSK).strftime('%Y-%m-%d %H:%M')
    print(f"#{p['imp_n']:<2} {ts_iso:<17} {p['direction']:<5} ", end="")
    for f in features:
        v = p.get(f, np.nan)
        if isinstance(v, float) and not np.isnan(v):
            print(f"{v:>10.2f}  ", end="")
        elif isinstance(v, int):
            print(f"{v:>10}  ", end="")
        else:
            print(f"{'nan':>10}  ", end="")
    print()

# Stats: для каждой feature mean/median у missed vs rest
print(f"\n{'='*120}")
print(f"AGGREGATE: mean ± std для missed (n=10) vs not-imp not-in-basket (n={len(not_imp_rest)}):")
print(f"{'='*120}")
print(f"{'feature':<18} {'missed mean':>12} {'missed med':>12} {'rest mean':>12} {'rest med':>12} {'gap (m-r)':>12}")
for f in features:
    if f == "msk_hour":
        # categorical: show distribution
        from collections import Counter
        m_c = Counter(p[f] for p in missed)
        r_c = Counter(p[f] for p in not_imp_rest)
        print(f"{f:<18} missed hours: {sorted(m_c.items())}")
        print(f"{'':<18} rest hours top: {r_c.most_common(5)}")
        continue
    mv = [p[f] for p in missed if not np.isnan(p.get(f, np.nan))]
    rv = [p[f] for p in not_imp_rest if not np.isnan(p.get(f, np.nan))]
    if not mv or not rv: continue
    mm, mmed = np.mean(mv), np.median(mv)
    rm, rmed = np.mean(rv), np.median(rv)
    print(f"{f:<18} {mm:>12.3f} {mmed:>12.3f} {rm:>12.3f} {rmed:>12.3f} {mm-rm:>+12.3f}")
