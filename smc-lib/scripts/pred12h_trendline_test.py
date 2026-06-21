"""Тест TrendLine (Hull MA) как Условие 3 для 12h Pred-фракталов.

User-наблюдение:
  #11 2026-02-28 03:00 LOW — взаимодействие с 12h TrendLine
  #26 2026-03-25 03:00 HIGH — взаимодействие с 12h TrendLine
  #47 2026-04-29 15:00 LOW — взаимодействие с D TrendLine

Тест:
  1. Compute HMA(78) на 12h и на D
  2. Verify 3 указанных pivot — что HMA внутри их range и/или sweep
  3. На baseline 1266 — посчитать sweep HMA (direction-matched) на 12h и D отдельно
  4. Catches_missed / 10 для каждого варианта

Sweep canon (per Правило 2, Sweep model):
  FH (top): high > HMA AND close < HMA   → swept resistance
  FL (bot): low < HMA AND close > HMA    → swept support
"""
from __future__ import annotations
import csv, pathlib, sys
from datetime import datetime, timezone, timedelta
import numpy as np

sys.path.insert(0, str(pathlib.Path.home() / "smc-lib"))
from candle import Candle
from elements.fractal.code import detect_fractal
from indicators.trend_line_asvk import wma

CSV = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MSK = timezone(timedelta(hours=3))
MS_M = 60_000
TF12 = 12*60*MS_M
TFD = 24*60*MS_M
START = int(datetime(2026,2,4,0,0,tzinfo=MSK).timestamp()*1000)
IMP = {1,3,4,5,9,10,11,14,15,20,23,26,29,40,41,42,47,48}

print("Loading 1m...")
rows = []
with CSV.open() as f:
    rd = csv.reader(f); next(rd)
    for r in rd:
        t = datetime.fromisoformat(r[0])
        rows.append((int(t.timestamp()*1000), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
print(f"  {len(rows)} 1m bars")

def aggregate(d, tfms):
    out = []; cb = None; o = h = l = c = 0.0; v = 0.0
    for ts, oo, hh, ll, cc, vv in d:
        b = ts - (ts % tfms)
        if b != cb:
            if cb is not None: out.append((cb, o, h, l, c, v))
            cb = b; o, h, l, c = oo, hh, ll, cc; v = vv
        else:
            h = max(h, hh); l = min(l, ll); c = cc; v += vv
    if cb is not None: out.append((cb, o, h, l, c, v))
    return out

bars12 = aggregate(rows, TF12)
bars_d = aggregate(rows, TFD)
print(f"  12h bars: {len(bars12)}, D bars: {len(bars_d)}")

# Compute HMA(78) на 12h и D
def hma(values, n):
    import math
    half = wma(values, n//2)
    full = wma(values, n)
    diff = [None]*len(values)
    for i in range(len(values)):
        if half[i] is None or full[i] is None: continue
        diff[i] = 2*half[i] - full[i]
    sqrt_n = int(round(math.sqrt(n)))
    diff_clean = [d if d is not None else 0.0 for d in diff]
    hma_out = wma(diff_clean, sqrt_n)
    # nullify before first valid
    first_valid = next((i for i,d in enumerate(diff) if d is not None), 0)
    for i in range(min(first_valid + sqrt_n - 1, len(hma_out))):
        hma_out[i] = None
    return hma_out

HMA_LEN = int(49 * 1.6)   # = 78, дефолт ASVK

# Use close prices for HMA input
closes_12h = [b[4] for b in bars12]
closes_d   = [b[4] for b in bars_d]
hma_12h = hma(closes_12h, HMA_LEN)
hma_d   = hma(closes_d,   HMA_LEN)
print(f"  HMA computed: 12h valid from idx {next((i for i,h in enumerate(hma_12h) if h is not None), -1)}, D valid from idx {next((i for i,h in enumerate(hma_d) if h is not None), -1)}")

# Helper: find D bar containing 12h bar i (D bar open_time <= 12h bar open_time < D bar open_time + 24h)
t12_arr = np.array([b[0] for b in bars12], dtype=np.int64)
td_arr  = np.array([b[0] for b in bars_d], dtype=np.int64)

def d_idx_for_12h(i):
    pt = t12_arr[i]
    idx = int(np.searchsorted(td_arr, pt, side='right')) - 1
    return idx if 0 <= idx < len(td_arr) else None

# === Verify user observations ===
print(f"\n{'='*100}\nVerification: 3 указанные imp\n{'='*100}")
check_dates = [
    ("#11 2026-02-28 03:00 LOW (user: 12h TL)", datetime(2026,2,28,3,0,tzinfo=MSK), "low"),
    ("#26 2026-03-25 03:00 HIGH (user: 12h TL)", datetime(2026,3,25,3,0,tzinfo=MSK), "high"),
    ("#47 2026-04-29 15:00 LOW (user: D TL)",  datetime(2026,4,29,15,0,tzinfo=MSK), "low"),
]
for label, dt_msk, dr in check_dates:
    ts = int(dt_msk.timestamp()*1000)
    i12 = int(np.searchsorted(t12_arr, ts, side='left'))
    if i12 >= len(bars12) or t12_arr[i12] != ts:
        # find exact
        i12 = next((i for i,t in enumerate(t12_arr) if t == ts), None)
    if i12 is None: print(f"  {label}: 12h bar not found"); continue
    bi = bars12[i12]
    h12_val = hma_12h[i12]
    idx_d = d_idx_for_12h(i12)
    hd_val = hma_d[idx_d] if idx_d is not None else None
    print(f"\n  {label}")
    print(f"    12h bar: O={bi[1]:.0f} H={bi[2]:.0f} L={bi[3]:.0f} C={bi[4]:.0f}")
    if h12_val:
        in_range_12 = bi[3] <= h12_val <= bi[2]
        if dr == "high":
            sweep_12 = bi[2] > h12_val and bi[4] < h12_val
            print(f"    HMA_12h={h12_val:.0f}, in_range={in_range_12}, SHORT-sweep (high>HMA & close<HMA): {sweep_12}")
        else:
            sweep_12 = bi[3] < h12_val and bi[4] > h12_val
            print(f"    HMA_12h={h12_val:.0f}, in_range={in_range_12}, LONG-sweep (low<HMA & close>HMA): {sweep_12}")
    if hd_val:
        in_range_d = bi[3] <= hd_val <= bi[2]
        if dr == "high":
            sweep_d = bi[2] > hd_val and bi[4] < hd_val
            print(f"    HMA_D={hd_val:.0f}, in_range={in_range_d}, SHORT-sweep: {sweep_d}")
        else:
            sweep_d = bi[3] < hd_val and bi[4] > hd_val
            print(f"    HMA_D={hd_val:.0f}, in_range={in_range_d}, LONG-sweep: {sweep_d}")

# === Build F1∩F2∩F3 baseline and apply sweep test ===
def color(b):
    if b[4]>b[1]: return "bull"
    if b[4]<b[1]: return "bear"
    return "doji"

last_ts = rows[-1][0]
window_start = last_ts - 6*365*24*3600*1000
bars12_w = [b for b in bars12 if b[0] >= window_start]

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

baseN = len(pivots); base_conf = sum(1 for p in pivots if p["confirmed"]); base_imp = sum(1 for p in pivots if p["is_imp"])
baseP = base_conf/baseN*100
print(f"\n\nBaseline F1∩F2∩F3: n={baseN}, P={baseP:.1f}%, imp={base_imp}/18")

# Already-known missed (after C1+C2 = 10 imp)
# Compute cond1 (maxV) and cond2 (P11) — для tracking «missed» status
import math
# ... но для скорости пропустим — определим missed по индексу из user data:
MISSED_IMP_NS = {3, 10, 11, 14, 15, 23, 26, 29, 47, 48}

# Sweep tests
def sweep_12h_short(p):
    bi = bars12[p["i_g"]]; hv = hma_12h[p["i_g"]]
    if hv is None: return False
    return bi[2] > hv and bi[4] < hv
def sweep_12h_long(p):
    bi = bars12[p["i_g"]]; hv = hma_12h[p["i_g"]]
    if hv is None: return False
    return bi[3] < hv and bi[4] > hv
def sweep_d_short(p):
    bi = bars12[p["i_g"]]
    idx_d = d_idx_for_12h(p["i_g"])
    if idx_d is None: return False
    hv = hma_d[idx_d]
    if hv is None: return False
    return bi[2] > hv and bi[4] < hv
def sweep_d_long(p):
    bi = bars12[p["i_g"]]
    idx_d = d_idx_for_12h(p["i_g"])
    if idx_d is None: return False
    hv = hma_d[idx_d]
    if hv is None: return False
    return bi[3] < hv and bi[4] > hv

# In-range tests (mid touch, более мягкий)
def in_range_12h(p):
    bi = bars12[p["i_g"]]; hv = hma_12h[p["i_g"]]
    if hv is None: return False
    return bi[3] <= hv <= bi[2]
def in_range_d(p):
    bi = bars12[p["i_g"]]
    idx_d = d_idx_for_12h(p["i_g"])
    if idx_d is None: return False
    hv = hma_d[idx_d]
    if hv is None: return False
    return bi[3] <= hv <= bi[2]

def stat(name, mask):
    keep = [p for p in pivots if mask(p)]
    if not keep: print(f"  {name:<55} keep=  0"); return
    conf = sum(1 for p in keep if p["confirmed"])
    p_pct = conf/len(keep)*100
    imp = sum(1 for p in keep if p["is_imp"])
    catches = sum(1 for p in keep if p["is_imp"] and p["imp_n"] in MISSED_IMP_NS)
    d = p_pct - baseP
    mark = " ⭐" if p_pct >= 70 else ""
    print(f"  {name:<55} keep={len(keep):>4}  conf={conf:>3}  P(W)={p_pct:5.1f}%  Δ={d:+5.1f}  imp={imp:>2}/18  catches_missed={catches}/10{mark}")

print(f"\n{'='*100}\nSweep tests на baseline F1∩F2∩F3 (1266 / P=48.9% / 18 imp):\n{'='*100}")
print(f"\n  Direction-matched sweep:")
stat("FH sweep 12h TL (high>HMA & close<HMA)", lambda p: p["direction"]=="high" and sweep_12h_short(p))
stat("FL sweep 12h TL (low<HMA & close>HMA)",  lambda p: p["direction"]=="low"  and sweep_12h_long(p))
stat("ANY sweep 12h TL (dir-matched)",         lambda p: (p["direction"]=="high" and sweep_12h_short(p)) or (p["direction"]=="low" and sweep_12h_long(p)))
print()
stat("FH sweep D TL",                          lambda p: p["direction"]=="high" and sweep_d_short(p))
stat("FL sweep D TL",                          lambda p: p["direction"]=="low"  and sweep_d_long(p))
stat("ANY sweep D TL (dir-matched)",           lambda p: (p["direction"]=="high" and sweep_d_short(p)) or (p["direction"]=="low" and sweep_d_long(p)))
print()
stat("ANY sweep (12h OR D)",                   lambda p: ((p["direction"]=="high" and (sweep_12h_short(p) or sweep_d_short(p))) or
                                                          (p["direction"]=="low"  and (sweep_12h_long(p) or sweep_d_long(p)))))

print(f"\n  In-range (мягче, без sweep-фильтра):")
stat("HMA_12h in [low, high]",  in_range_12h)
stat("HMA_D in [low, high]",    in_range_d)
stat("HMA_12h OR HMA_D in range", lambda p: in_range_12h(p) or in_range_d(p))
