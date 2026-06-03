"""Подбор настроек TrendLine (Hull MA) для поимки 3 user-указанных missed:
  #11 2026-02-28 03:00 LOW — через 12h TL
  #26 2026-03-25 03:00 HIGH — через 12h TL
  #47 2026-04-29 15:00 LOW — через D TL

Варианты:
  HMA length: 30, 49, 78 (default ASVK), 100, 150, 200
  Mode: HMA only (canon ASVK по умолчанию)
  Use: HMA или SHULL (HMA shifted -2)
  HMA value: end-of-bar OR live (prev-bar close) — strict-causal

Sweep direction-matched:
  FH (top): high > HMA AND close < HMA
  FL (bot): low < HMA AND close > HMA

Цель: найти конфиг где все 3 ловятся + WR не падает критично.
"""
from __future__ import annotations
import csv, pathlib, sys, math
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
MISSED_IMP_NS = {11, 14, 15, 26, 29, 47, 48}   # после C1+C2+C3+C4

# Targets — 3 указанные missed
TARGETS = {
    11: ("12h", "low"),
    26: ("12h", "high"),
    47: ("D",   "low"),
}

print("Loading 1m...")
rows = []
with CSV.open() as f:
    rd = csv.reader(f); next(rd)
    for r in rd:
        t = datetime.fromisoformat(r[0])
        rows.append((int(t.timestamp()*1000), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))

def aggregate(d, tfms):
    out=[]; cb=None; o=h=l=c=0.0; v=0.0
    for ts,oo,hh,ll,cc,vv in d:
        b = ts - (ts % tfms)
        if b!=cb:
            if cb is not None: out.append((cb,o,h,l,c,v))
            cb=b; o,h,l,c=oo,hh,ll,cc; v=vv
        else:
            h=max(h,hh); l=min(l,ll); c=cc; v+=vv
    if cb is not None: out.append((cb,o,h,l,c,v))
    return out

bars12 = aggregate(rows, TF12)
bars_d = aggregate(rows, TFD)
n12 = len(bars12); nd = len(bars_d)
t12 = np.array([b[0] for b in bars12], dtype=np.int64)
td  = np.array([b[0] for b in bars_d], dtype=np.int64)
h12 = np.array([b[2] for b in bars12]); l12 = np.array([b[3] for b in bars12]); c12 = np.array([b[4] for b in bars12])
hd  = np.array([b[2] for b in bars_d]);  ld  = np.array([b[3] for b in bars_d]);  cd  = np.array([b[4] for b in bars_d])

def hma(values, n):
    half = wma(values, n//2)
    full = wma(values, n)
    diff = [(2*half[i]-full[i]) if (half[i] is not None and full[i] is not None) else 0.0 for i in range(len(values))]
    sqrt_n = int(round(math.sqrt(n)))
    return wma(diff, sqrt_n)

def shull(hma_series):
    """Shifted-Hull: значение бара i = HMA(i-2)."""
    out = [None] * len(hma_series)
    for i in range(2, len(hma_series)):
        out[i] = hma_series[i-2]
    return out

closes_12h = [b[4] for b in bars12]
closes_d   = [b[4] for b in bars_d]

# Pre-compute HMA + SHULL for various lengths
LENGTHS = [30, 49, 78, 100, 150, 200]
hma_12 = {L: hma(closes_12h, L) for L in LENGTHS}
hma_d  = {L: hma(closes_d,   L) for L in LENGTHS}
shull_12 = {L: shull(hma_12[L]) for L in LENGTHS}
shull_d  = {L: shull(hma_d[L])  for L in LENGTHS}

# Helper: index in 12h or D containing pivot.open
def d_idx(ts):
    idx = int(np.searchsorted(td, ts, side='right')) - 1
    return idx if 0 <= idx < nd else None

# F1∩F2∩F3 baseline
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
        pivots.append({"i_w":i, "direction":direction, "confirmed":confirmed, "pivot_open_ts":bi[0]})
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

baseN = len(pivots); base_conf = sum(1 for p in pivots if p["confirmed"])
baseP = base_conf/baseN*100
print(f"Baseline F1∩F2∩F3: n={baseN}, P={baseP:.1f}%")
print(f"Targets (user-указанные): #11 (12h FL), #26 (12h FH), #47 (D FL)\n")

def sweep_check_12h(p, hma_series, use_live):
    """LONG-sweep для FL, SHORT-sweep для FH на 12h HMA."""
    idx = p["i_g"]
    if use_live:
        # Live во время бара i = HMA from prev bar (i-1)
        hv = hma_series[idx-1] if idx-1 >= 0 else None
    else:
        hv = hma_series[idx]
    if hv is None: return False
    bi = bars12[idx]
    if p["direction"] == "high":
        return bi[2] > hv and bi[4] < hv
    else:
        return bi[3] < hv and bi[4] > hv

def sweep_check_d(p, hma_series, use_live):
    """LONG-sweep для FL, SHORT-sweep для FH на D HMA."""
    pi = p["i_g"]
    pt = t12[pi]
    didx = d_idx(pt)
    if didx is None: return False
    if use_live:
        hv = hma_series[didx-1] if didx-1 >= 0 else None
    else:
        hv = hma_series[didx]
    if hv is None: return False
    bi = bars12[pi]
    if p["direction"] == "high":
        return bi[2] > hv and bi[4] < hv
    else:
        return bi[3] < hv and bi[4] > hv

# Test all combinations
print(f"{'Variant':<35} {'#11':<5} {'#26':<5} {'#47':<5} {'keep':>5} {'P(W)%':>7} {'catches_missed/7':>17}")
print("-"*90)
results = []
for L in LENGTHS:
    for use_shull, label_shull in [(False, ""), (True, "+SHULL")]:
        for use_live, label_live in [(False, "EOB"), (True, "LIVE")]:
            for tf_label, hma_dict_12, hma_dict_d in [
                ("12h", shull_12 if use_shull else hma_12, None),
                ("D",   None, shull_d if use_shull else hma_d),
                ("12h∪D", shull_12 if use_shull else hma_12, shull_d if use_shull else hma_d),
            ]:
                # Define mask
                def mask(p, L=L, tf_label=tf_label, hma_dict_12=hma_dict_12, hma_dict_d=hma_dict_d, use_live=use_live):
                    sw12 = sweep_check_12h(p, hma_dict_12[L], use_live) if hma_dict_12 else False
                    swd  = sweep_check_d(p, hma_dict_d[L], use_live)  if hma_dict_d else False
                    return sw12 or swd
                # Check targets
                target_pivots = {}
                for n in TARGETS:
                    g = next((g for g in gt if (g["i_w"], g["dir"]) == next((iw_d for iw_d, n2 in imp_iw_dir.items() if n2==n), None)), None)
                    pp = next((p for p in pivots if p["imp_n"] == n), None)
                    target_pivots[n] = pp
                tcs = {n: ("✓" if (pp is not None and mask(pp)) else "✗") for n, pp in target_pivots.items()}
                # Stats on baseline
                keep = [p for p in pivots if mask(p)]
                if not keep: continue
                conf = sum(1 for p in keep if p["confirmed"])
                pct = conf/len(keep)*100
                catches = sum(1 for p in keep if p["is_imp"] and p["imp_n"] in MISSED_IMP_NS)
                var = f"L={L} {tf_label} {label_live}{label_shull}"
                results.append((var, tcs, len(keep), pct, catches))

# Sort: prioritize variants catching all 3 targets, then by WR
def score(r):
    var, tcs, k, pct, c = r
    n_targets = sum(1 for v in tcs.values() if v == "✓")
    return (-n_targets, -pct)
results.sort(key=score)
print(f"{'Variant':<35} {'#11':<5} {'#26':<5} {'#47':<5} {'keep':>5} {'P(W)%':>7} {'missed':>7}")
print("-"*90)
shown = 0
for var, tcs, k, pct, c in results:
    n_t = sum(1 for v in tcs.values() if v == "✓")
    mark = " ⭐" if pct >= 70 else ""
    print(f"{var:<35} {tcs[11]:<5} {tcs[26]:<5} {tcs[47]:<5} {k:>5} {pct:>6.1f} {c:>7}{mark}")
    shown += 1
    if shown >= 35: break
