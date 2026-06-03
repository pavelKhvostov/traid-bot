"""EVoT(rNorm) — продолжение экспериментов с LTF placements.

Идеи:
  P6: pre-extremum [open_i, time_of_extremum] — climax approach
  P7: pre/post extremum split + (signed) дельта pre-post
  P8: window вокруг экстремума ±K минут
  P9: последние K часов БАРА (i-1) — pre-pivot tail
  P10: EVoT bar (i-1) ВЕСЬ
  P11: LTF 15m count: последние N 15m свечей внутри pivot — доля dir-matched
  P12: jump между pre-extremum и post-extremum (классический buying climax + selling)

Direction-matched: FH ← rNorm ≤ −τ, FL ← rNorm ≥ +τ.

Baseline: F1∩F2∩F3 = 1266 / P=48.9% / 18 imp.
Остаток: 910 / 38.6% / 13 imp.
Цель: WR ≥ 70%.
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
MIN_KEEP = 30

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
                       "pivot_open_ts":bi[0], "pivot_high":bi[2], "pivot_low":bi[3]})
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
rem_pivots = [p for p in pivots if not p["cond1"]]
remN = len(rem_pivots); rem_conf = sum(1 for p in rem_pivots if p["confirmed"]); rem_imp = sum(1 for p in rem_pivots if p["is_imp"])
remP = rem_conf/remN*100
print(f"\nBaseline: n={baseN} P={baseP:.1f}% imp=18")
print(f"Остаток: n={remN} P={remP:.1f}% imp=13/18")

def evot(i_lo, i_hi):
    if i_hi <= i_lo: return np.nan
    vs = vol_1m[i_lo:i_hi]
    bull = vs[is_bull_1m[i_lo:i_hi]].sum()
    bear = vs[is_bear_1m[i_lo:i_hi]].sum()
    denom = bull + bear
    if denom == 0: return np.nan
    return (bull - bear) / denom

def signed(p, val):
    if np.isnan(val): return -999
    return -val if p["direction"] == "high" else val

# Compute placements
print("Computing placements...")
for p in pivots:
    pt = int(p["pivot_open_ts"])
    pt_end = pt + TF12
    pt_prev = pt - TF12
    i_lo = int(np.searchsorted(ts_1m, pt, side='left'))
    i_hi = int(np.searchsorted(ts_1m, pt_end, side='left'))
    i_prev_lo = int(np.searchsorted(ts_1m, pt_prev, side='left'))
    i_prev_hi = i_lo  # = pt
    # extremum within pivot
    if p["direction"] == "high":
        hi_slice = hi_1m[i_lo:i_hi]
        ext_local = int(np.argmax(hi_slice)) if len(hi_slice) > 0 else 0
    else:
        lo_slice = lo_1m[i_lo:i_hi]
        ext_local = int(np.argmin(lo_slice)) if len(lo_slice) > 0 else 0
    ext_idx = i_lo + ext_local
    p["ext_idx"] = ext_idx
    # P6: pre-extremum [open_i, ext_idx]
    p["P6_pre_ext"] = evot(i_lo, ext_idx)
    # P7: pre & post — затем дельта
    p["P7_post_ext"] = evot(ext_idx, i_hi)
    # P8: ±K minutes around extremum
    for K in [15, 30, 60, 120]:
        a = max(i_lo, ext_idx - K)
        b = min(i_hi, ext_idx + K)
        p[f"P8_around_{K}m"] = evot(a, b)
    # P9: last K hours of (i-1)
    for K in [1, 2, 3, 6]:
        cut = int(np.searchsorted(ts_1m, pt - K*60*MS_M, side='left'))
        p[f"P9_prev_last{K}h"] = evot(cut, i_lo)
    # P10: whole (i-1)
    p["P10_prev_full"] = evot(i_prev_lo, i_prev_hi)
    # P11: LTF 15m bar count — последние N 15m свечей внутри pivot, доля dir-matched
    # dir-matched: для FH = bearish 15m close (close<open), для FL = bullish
    for N in [4, 8, 12, 16, 24]:  # 4*15m=1h, 8*15m=2h, ..., 24*15m=6h
        cut = int(np.searchsorted(ts_1m, pt_end - N*15*MS_M, side='left'))
        # Aggregate to 15m bars
        sub = rows[cut:i_hi]
        sub_15m = agg_ohlcv(sub, 15*MS_M)
        if not sub_15m:
            p[f"P11_count_{N}x15m"] = np.nan; continue
        if p["direction"] == "high":
            cnt = sum(1 for b in sub_15m if b[4] < b[1])
        else:
            cnt = sum(1 for b in sub_15m if b[4] > b[1])
        p[f"P11_count_{N}x15m"] = cnt / len(sub_15m)  # доля

def stat_on(base, name, mask_fn, base_p_label):
    keep = [p for p in base if mask_fn(p)]
    if not keep: return None
    conf = sum(1 for p in keep if p["confirmed"])
    p_pct = conf/len(keep)*100
    imp = sum(1 for p in keep if p["is_imp"])
    delta = p_pct - (baseP if base_p_label=="full" else remP)
    return (name, len(keep), conf, len(keep)-conf, p_pct, delta, imp)

def mk_evot_mask(key, tau):
    def m(p):
        v = p[key]
        if np.isnan(v): return False
        s = -v if p["direction"] == "high" else v
        return s >= tau
    return m

def mk_count_mask(key, tau):
    def m(p):
        v = p[key]
        if np.isnan(v): return False
        return v >= tau
    return m

def print_table(base, base_p_label, header):
    label_n = baseN if base_p_label=="full" else remN
    label_p = baseP if base_p_label=="full" else remP
    label_imp = base_imp if base_p_label=="full" else rem_imp
    print(f"\n  {header} (база n={label_n}, P={label_p:.1f}%, imp={label_imp})")
    print(f"  {'placement':<32} {'τ':>5}  keep  conf  not  P(W)%   Δpp    imp")
    evot_keys = (["P6_pre_ext","P7_post_ext","P10_prev_full"]
                 + [f"P8_around_{K}m" for K in [15,30,60,120]]
                 + [f"P9_prev_last{K}h" for K in [1,2,3,6]])
    count_keys = [f"P11_count_{N}x15m" for N in [4,8,12,16,24]]
    taus_evot = [-0.1, 0.0, 0.05, 0.1, 0.15, 0.2, 0.3]
    taus_frac = [0.55, 0.65, 0.75, 0.85]
    for key in evot_keys:
        for tau in taus_evot:
            r = stat_on(base, key, mk_evot_mask(key, tau), base_p_label)
            if r is None: continue
            n,c,nc,p_,d_,imp_ = r[1:]
            if n < MIN_KEEP: continue
            mark = " ⭐" if p_ >= 70 else ""
            print(f"  {key:<32} {tau:+5.2f}  {n:>4}  {c:>4}  {nc:>3}  {p_:5.1f}  {d_:+5.1f}  {imp_:>2}{mark}")
    for key in count_keys:
        for tau in taus_frac:
            r = stat_on(base, key, mk_count_mask(key, tau), base_p_label)
            if r is None: continue
            n,c,nc,p_,d_,imp_ = r[1:]
            if n < MIN_KEEP: continue
            mark = " ⭐" if p_ >= 70 else ""
            print(f"  {key:<32} {tau:+5.2f}  {n:>4}  {c:>4}  {nc:>3}  {p_:5.1f}  {d_:+5.1f}  {imp_:>2}{mark}")

print_table(pivots, "full", "На FULL baseline (P=48.9%):")
print_table(rem_pivots, "rem", "На ОСТАТКЕ после Условия 1 (P=38.6%):")

# === COMBINED P6 (pre-ext) + P7 (post-ext) divergence ===
# Классический buying climax: pre-ext bullish (для FH), post-ext bearish.
# Direction-matched signed: для FH хотим pre > +τ AND post < -τ (или signed(pre) ≤ -τ, signed(post) ≥ +τ?)
# Используем неподписанные: для FH: pre_ext > +α AND post_ext < -β
print(f"\n  Climax + reversal divergence (pre/post extremum, на ОСТАТКЕ P=38.6%):")
print(f"  {'rule':<60} keep  conf  not  P(W)%   Δpp    imp")
for alpha in [0.0, 0.1, 0.2]:
    for beta in [0.0, 0.1, 0.2]:
        def climax(p, a=alpha, b=beta):
            pre = p["P6_pre_ext"]; post = p["P7_post_ext"]
            if np.isnan(pre) or np.isnan(post): return False
            if p["direction"] == "high":
                return pre >= +a and post <= -b
            else:
                return pre <= -a and post >= +b
        keep = [p for p in rem_pivots if climax(p)]
        if len(keep) < MIN_KEEP: continue
        conf = sum(1 for p in keep if p["confirmed"])
        p_pct = conf/len(keep)*100
        imp = sum(1 for p in keep if p["is_imp"])
        d = p_pct - remP
        mark = " ⭐" if p_pct >= 70 else ""
        name = f"climax pre≥{alpha:+.1f} ∧ post≤{-beta:+.1f}"
        print(f"  {name:<60} {len(keep):>4}  {conf:>4}  {len(keep)-conf:>3}  {p_pct:5.1f}  {d:+5.1f}  {imp:>2}{mark}")
