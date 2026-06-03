"""OR-basket для 12h Pred-фракталов.

Baseline: F1∩F2∩F3 = 1266 / 619 conf / 18 imp (на 6y BTC).

Условия (параллельно, не AND):
  C1 = sweep_FH/FL (untouched HTF fractal) OR OB_sweep (untouched HTF OB)
       на TFs {12h, D, 2D, 3D, W=Mon-anchor}
       sweep = wick через level + close обратно
       direction-matched:
         FH pivot ← HTF FH-sweep OR HTF SHORT-OB-sweep
         FL pivot ← HTF FL-sweep OR HTF LONG-OB-sweep
  C2 = sweep maxV(i-1) на 1m
       maxV = close 1m-свечи с макс dirVolume внутри 12h (bull/bear winner)
       FH: high[i] > maxV[i-1] AND close[i] < maxV[i-1]
       FL: low[i]  < maxV[i-1] AND close[i] > maxV[i-1]

Output: per-condition keep/conf/notconf/P/Δ/imp + union + missed imp.
"""
from __future__ import annotations
import csv, pathlib, sys
from datetime import datetime, timezone, timedelta
import numpy as np

sys.path.insert(0, str(pathlib.Path.home() / "smc-lib"))
from candle import Candle
from elements.fractal.code import detect_fractal
from elements.ob.code import detect_ob

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
IMP = {1,3,4,5,9,10,11,14,15,20,23,26,29,40,41,42,47,48}  # 18 important (indexes in GT fractal list)

print("Loading 1m...")
rows=[]
with CSV.open() as f:
    rd=csv.reader(f); next(rd)
    for r in rd:
        t=datetime.fromisoformat(r[0])
        rows.append((int(t.timestamp()*1000),float(r[1]),float(r[2]),float(r[3]),float(r[4]),float(r[5])))
print(f"  {len(rows)} 1m bars")

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

bars_by_tf = {
    "12h": agg_ohlcv(rows, TF12),
    "D":   agg_ohlcv(rows, TFD),
    "2D":  agg_ohlcv(rows, TF2D),
    "3D":  agg_ohlcv(rows, TF3D),
    "W":   agg_ohlcv(rows, TFW, MON_ANCHOR),
}
tf_ms_map = {"12h":TF12,"D":TFD,"2D":TF2D,"3D":TF3D,"W":TFW}
cans_by_tf = {tf:[Candle(open=b[1],high=b[2],low=b[3],close=b[4],open_time=b[0]) for b in bb] for tf,bb in bars_by_tf.items()}

bars12 = bars_by_tf["12h"]
n12 = len(bars12)
h12 = np.array([b[2] for b in bars12])
l12 = np.array([b[3] for b in bars12])
c12 = np.array([b[4] for b in bars12])
t12 = np.array([b[0] for b in bars12], dtype=np.int64)
print(f"  12h bars: {n12}")

# Window: 6y BTC
last_ts = rows[-1][0]
window_start = last_ts - 6*365*24*3600*1000
w_mask = t12 >= window_start
w_idx = np.where(w_mask)[0]
print(f"  6y window: 12h bars in window = {len(w_idx)}")

# ======= maxV per 12h (1m LTF, close of bar with max dirVolume) =======
print("Computing maxV per 12h (1m LTF)...")
ts_1m = np.array([r[0] for r in rows], dtype=np.int64)
op_1m = np.array([r[1] for r in rows], dtype=np.float64)
cl_1m = np.array([r[4] for r in rows], dtype=np.float64)
vol_1m = np.array([r[5] for r in rows], dtype=np.float64)
is_bull_1m = cl_1m > op_1m
is_bear_1m = cl_1m < op_1m

maxv = np.full(n12, np.nan)
for k in range(n12):
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
print(f"  maxV computed: {np.sum(~np.isnan(maxv))} / {n12}")

# ======= HTF fractals + OBs across all TFs =======
print("Detecting HTF fractals + OBs across TFs...")
htf_fhs = []   # {tf, level, ready_ms}
htf_fls = []
htf_obs_short = []  # {tf, zone_top, zone_bottom, ready_ms}
htf_obs_long = []
for tf_name, cans in cans_by_tf.items():
    tfms = tf_ms_map[tf_name]
    # Williams fractals N=2
    for i in range(2, len(cans)-2):
        f = detect_fractal(cans[i-2:i+3], n=2)
        if f is None: continue
        rt = cans[i+2].open_time + tfms  # ready after i+2 closes
        if f.direction == "high":
            htf_fhs.append({"tf":tf_name, "level":f.level, "ready_ms":rt})
        else:
            htf_fls.append({"tf":tf_name, "level":f.level, "ready_ms":rt})
    # OBs
    for i in range(len(cans)-1):
        ob = detect_ob(cans[i], cans[i+1])
        if ob is None: continue
        rt = cans[i+1].open_time + tfms
        zb, zt = ob.zone
        if ob.direction == "short":
            htf_obs_short.append({"tf":tf_name,"zone_top":zt,"zone_bottom":zb,"ready_ms":rt})
        else:
            htf_obs_long.append({"tf":tf_name,"zone_top":zt,"zone_bottom":zb,"ready_ms":rt})
print(f"  HTF FH={len(htf_fhs)}  FL={len(htf_fls)}  SHORT_OB={len(htf_obs_short)}  LONG_OB={len(htf_obs_long)}")

# ======= Sweep flags on 12h candles =======
# Untouched: для каждой зоны/уровня находим ПЕРВУЮ свечу с условием sweep, помечаем.
def fractal_sweep_flag(fractals, kind):  # kind = "FH" or "FL"
    flag = np.zeros(n12, dtype=bool)
    for f in fractals:
        rt = f["ready_ms"]; lvl = f["level"]
        sp = int(np.searchsorted(t12, rt, side='left'))
        if sp >= n12: continue
        for i in range(sp, n12):
            if kind == "FH":
                if h12[i] > lvl and c12[i] < lvl: flag[i] = True; break
                if c12[i] > lvl: break  # пробит close → больше не untouched
            else:
                if l12[i] < lvl and c12[i] > lvl: flag[i] = True; break
                if c12[i] < lvl: break
    return flag

def ob_sweep_flag(obs, direction):  # direction = "short" or "long"
    flag = np.zeros(n12, dtype=bool)
    for z in obs:
        rt = z["ready_ms"]; zt = z["zone_top"]; zb = z["zone_bottom"]
        sp = int(np.searchsorted(t12, rt, side='left'))
        if sp >= n12: continue
        # Уровень = противоположная граница (то, на чём sweep)
        # SHORT OB: цена снизу, тестирует zone_top. SHORT-sweep = wick > zone_top + close < zone_top
        # LONG OB: цена сверху, тестирует zone_bottom. LONG-sweep = wick < zone_bottom + close > zone_bottom
        level = zt if direction == "short" else zb
        for i in range(sp, n12):
            if direction == "short":
                if h12[i] > level and c12[i] < level: flag[i] = True; break
                if c12[i] > level: break
            else:
                if l12[i] < level and c12[i] > level: flag[i] = True; break
                if c12[i] < level: break
    return flag

sw_FH  = fractal_sweep_flag(htf_fhs, "FH")
sw_FL  = fractal_sweep_flag(htf_fls, "FL")
sw_OBS = ob_sweep_flag(htf_obs_short, "short")
sw_OBL = ob_sweep_flag(htf_obs_long,  "long")
print(f"  sweep flags @ 12h: FH={sw_FH.sum()} FL={sw_FL.sum()} OBS={sw_OBS.sum()} OBL={sw_OBL.sum()}")

# C1 by direction
C1_FH = sw_FH | sw_OBS  # for FH pivot
C1_FL = sw_FL | sw_OBL  # for FL pivot

# C2 by direction
sw_maxV_short = np.zeros(n12, dtype=bool)
sw_maxV_long  = np.zeros(n12, dtype=bool)
for i in range(1, n12):
    mv = maxv[i-1]
    if np.isnan(mv): continue
    if h12[i] > mv and c12[i] < mv: sw_maxV_short[i] = True
    if l12[i] < mv and c12[i] > mv: sw_maxV_long[i] = True

# ======= F1∩F2∩F3 baseline =======
def color(b):
    if b[4]>b[1]: return "bull"
    if b[4]<b[1]: return "bear"
    return "doji"

bars12_w = [b for b in bars12 if b[0] >= window_start]
def f1f2f3_pivots():
    out = []
    n = len(bars12_w)
    for i in range(2, n-2):
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
            out.append({"i_w":i,"direction":direction,"confirmed":confirmed,
                        "pivot_open_ts":bi[0]})
    return out

pivots = f1f2f3_pivots()
print(f"\nF1∩F2∩F3 baseline: {len(pivots)} pivots")

# Map pivot.pivot_open_ts → global 12h index
ts_to_i = {int(b[0]): k for k,b in enumerate(bars12)}
for p in pivots:
    p["i_g"] = ts_to_i[int(p["pivot_open_ts"])]

# Ground truth важных: 56 фракталов с 2026-02-04, indexes IMP = 1-based
# Build GT list = Williams-confirmed 12h fractals starting from 2026-02-04
cans_w = [Candle(open=b[1],high=b[2],low=b[3],close=b[4],open_time=b[0]) for b in bars12_w]
gt = []
for i in range(2, len(cans_w)-2):
    f = detect_fractal(cans_w[i-2:i+3], n=2)
    if f is None or cans_w[i].open_time < START: continue
    gt.append({"i_w":i, "dir":f.direction})
imp_iw = {gt[n-1]["i_w"] for n in IMP if n-1 < len(gt)}
imp_iw_dir = {(gt[n-1]["i_w"], gt[n-1]["dir"]) for n in IMP if n-1 < len(gt)}
print(f"  GT total = {len(gt)}, imp set = {len(imp_iw)}")

# tag baseline pivots
for p in pivots:
    p["is_imp"] = (p["i_w"], p["direction"]) in imp_iw_dir

# ======= Apply C1 and C2 to each baseline pivot =======
for p in pivots:
    ig = p["i_g"]; d = p["direction"]
    if d == "high":
        p["c1"] = bool(C1_FH[ig])
        p["c2"] = bool(sw_maxV_short[ig])
    else:
        p["c1"] = bool(C1_FL[ig])
        p["c2"] = bool(sw_maxV_long[ig])

baseN = len(pivots)
base_conf = sum(1 for p in pivots if p["confirmed"])
base_notconf = baseN - base_conf
baseP = base_conf/baseN*100
base_imp = sum(1 for p in pivots if p["is_imp"])
print(f"\n{'='*100}")
print(f"BASELINE F1∩F2∩F3: n={baseN}  conf={base_conf}  not_conf={base_notconf}  P(W)={baseP:.1f}%  imp={base_imp}/18")
print(f"{'='*100}\n")

def stat(name, mask_fn):
    keep = [p for p in pivots if mask_fn(p)]
    if not keep:
        print(f"  {name:<35} keep=  0"); return
    conf = sum(1 for p in keep if p["confirmed"])
    notconf = len(keep)-conf
    p_pct = conf/len(keep)*100
    delta = p_pct - baseP
    imp = sum(1 for p in keep if p["is_imp"])
    print(f"  {name:<35} keep={len(keep):>4}  conf={conf:>3}  not_conf={notconf:>3}  P(W)={p_pct:5.1f}%  Δ={delta:+5.1f}pp  imp={imp:>2}/18")

print("Per-condition stats (OR-basket кандидаты):\n")
stat("C1 (sweep_FH/FL OR OB_sweep)",      lambda p: p["c1"])
stat("C2 (sweep maxV(i-1))",              lambda p: p["c2"])
print()
print("Union (basket = good if C_a OR C_b):\n")
stat("C1 ∪ C2",                            lambda p: p["c1"] or p["c2"])
print()
print("Sniper (AND, для сравнения со старым подходом):\n")
stat("C1 ∩ C2",                            lambda p: p["c1"] and p["c2"])

# Missed by union
union_set = {(p["i_w"], p["direction"]) for p in pivots if (p["c1"] or p["c2"])}
missed_imp = [p for p in pivots if p["is_imp"] and (p["i_w"], p["direction"]) not in union_set]
print(f"\n{'='*100}")
print(f"Imp пойманы union (C1 ∪ C2): {base_imp - len(missed_imp)}/18")
if missed_imp:
    print(f"Imp ПРОПУЩЕНЫ union'ом ({len(missed_imp)}):")
    for p in missed_imp:
        ts_iso = datetime.fromtimestamp(p["pivot_open_ts"]/1000, MSK).strftime('%Y-%m-%d %H:%M')
        # find imp index
        gt_iw = {(g["i_w"],g["dir"]): n+1 for n,g in enumerate(gt)}
        imp_n = gt_iw.get((p["i_w"], p["direction"]))
        # determine which conditions actually failed
        flags = f"C1={p['c1']} C2={p['c2']}"
        print(f"  #{imp_n}  {ts_iso} MSK  dir={p['direction']}  conf={p['confirmed']}  {flags}")
