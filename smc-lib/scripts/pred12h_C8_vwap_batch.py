"""C8 кандидат: VWAP-based predictor.

Для каждого baseline pivot (1272):
  - вычислить anchored VWAP от каждого FH/FL фрактала за последний год
  - найти ближайший anchored VWAP к pivot.close цене
  - сохранить min_distance_pct (расстояние до ближайшего VWAP)
  - + список VWAPs в пределах 0.5%, 1%, 2% от цены

Гипотеза: pivot чаще confirmed когда price касается сильной anchored VWAP
(structural support/resistance).

Output: ~/Desktop/pred12h_C8_vwap_6y.parquet
"""
from __future__ import annotations
import sys, time
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path.home()/'smc-lib'))

# Load baseline pivots
import importlib.util, io, contextlib
spec = importlib.util.spec_from_file_location(
    "basket", Path.home()/'smc-lib/scripts/pred12h_basket_c1c2c3.py')
mod = importlib.util.module_from_spec(spec); sys.modules['basket'] = mod
with contextlib.redirect_stdout(io.StringIO()):
    spec.loader.exec_module(mod)
pivots = mod.pivots
bars12 = mod.bars12  # (ts_ms, o, h, l, c, v)
print(f"[1/3] Loaded {len(pivots)} baseline pivots, {len(bars12)} 12h bars", flush=True)

# Load 1m for VWAP computation
print("[2/3] Loading 1m...", flush=True)
df = pd.read_csv(Path.home()/'traid-bot/data/BTCUSDT_1m_vic_vadim.csv')
df['open_time'] = pd.to_datetime(df['open_time'], utc=True, format='mixed')
df = df.set_index('open_time').sort_index()
ts_s = (df.index.astype('int64').values // 10**6)  # seconds
cls = df['close'].values
vol = df['volume'].values
pv = cls*vol
cpv = np.concatenate([[0], np.cumsum(pv)])
cv  = np.concatenate([[0], np.cumsum(vol)])
print(f"  1m bars: {len(df):,}", flush=True)

def idx_at_s(t_s):
    return int(np.searchsorted(ts_s, t_s, side='left'))

def vwap_from_to(anchor_s, end_s):
    a = idx_at_s(anchor_s); e = min(idx_at_s(end_s)+1, len(cls))
    if e <= a: return None
    p = cpv[e]-cpv[a]; v = cv[e]-cv[a]
    return p/v if v>0 else None

# Build all 12h Williams n=2 FH and FL fractals across full history
H_arr = np.array([b[2] for b in bars12])
L_arr = np.array([b[3] for b in bars12])
N = len(bars12)
fh_list = []  # (i, ts_open_ms)
fl_list = []
for i in range(2, N-2):
    if H_arr[i] == max(H_arr[i-2:i+3]) and H_arr[i]>H_arr[i-1] and H_arr[i]>H_arr[i+1]:
        fh_list.append((i, bars12[i][0]))
    if L_arr[i] == min(L_arr[i-2:i+3]) and L_arr[i]<L_arr[i-1] and L_arr[i]<L_arr[i+1]:
        fl_list.append((i, bars12[i][0]))
print(f"  FH fractals: {len(fh_list)}, FL: {len(fl_list)}", flush=True)

# For each baseline pivot, compute VWAP features
print(f"[3/3] Computing VWAP features per pivot (1272 iters)...", flush=True)
t0 = time.time()
rows = []
LOOKBACK_DAYS = 365  # anchors из последнего года

for k, p in enumerate(pivots):
    cut_close_ms = p["pivot_open_ts"] + 12*3600*1000  # bar close
    cut_close_s = cut_close_ms // 1000
    cur_idx = idx_at_s(cut_close_s) - 1
    if cur_idx < 0 or cur_idx >= len(cls):
        rows.append({'pivot_open_ts_ms':p['pivot_open_ts'],'direction':p['direction'],
                     'confirmed':p['confirmed'],'min_vwap_dist_pct':None,
                     'n_vwap_within_05':0,'n_vwap_within_1':0,'n_vwap_within_2':0,
                     'best_below_dist':None,'best_above_dist':None}); continue
    price = float(cls[cur_idx])
    cutoff_anchor_ms = cut_close_ms - LOOKBACK_DAYS*86400*1000

    # Eligible anchors (older than pivot.close, within lookback)
    fhs = [(i, ts) for (i, ts) in fh_list if cutoff_anchor_ms <= ts < cut_close_ms]
    fls = [(i, ts) for (i, ts) in fl_list if cutoff_anchor_ms <= ts < cut_close_ms]

    all_vwaps = []
    for (i, ts) in fhs + fls:
        anchor_close_ms = ts + 12*3600*1000
        if anchor_close_ms >= cut_close_ms: continue
        vw = vwap_from_to(anchor_close_ms//1000, cut_close_s)
        if vw is None: continue
        all_vwaps.append(vw)

    if not all_vwaps:
        rows.append({'pivot_open_ts_ms':p['pivot_open_ts'],'direction':p['direction'],
                     'confirmed':p['confirmed'],'min_vwap_dist_pct':None,
                     'n_vwap_within_05':0,'n_vwap_within_1':0,'n_vwap_within_2':0,
                     'best_below_dist':None,'best_above_dist':None}); continue

    dists_pct = [abs(vw - price)/price*100 for vw in all_vwaps]
    min_dist = min(dists_pct)
    n_05 = sum(1 for d in dists_pct if d <= 0.5)
    n_1  = sum(1 for d in dists_pct if d <= 1.0)
    n_2  = sum(1 for d in dists_pct if d <= 2.0)
    below = [vw for vw in all_vwaps if vw < price]
    above = [vw for vw in all_vwaps if vw > price]
    best_below = min((price-vw)/price*100 for vw in below) if below else None
    best_above = min((vw-price)/price*100 for vw in above) if above else None

    rows.append({'pivot_open_ts_ms':p['pivot_open_ts'],'direction':p['direction'],
                 'confirmed':p['confirmed'],'min_vwap_dist_pct':min_dist,
                 'n_vwap_within_05':n_05,'n_vwap_within_1':n_1,'n_vwap_within_2':n_2,
                 'best_below_dist':best_below,'best_above_dist':best_above})

    if (k+1) % 200 == 0:
        el = (time.time()-t0)/60
        eta = el/(k+1)*(len(pivots)-k-1)
        print(f"  {k+1}/{len(pivots)}  elapsed={el:.1f}m  ETA={eta:.1f}m", flush=True)

df_r = pd.DataFrame(rows)
OUT = Path.home() / 'Desktop/pred12h_C8_vwap_6y.parquet'
df_r.to_parquet(OUT, index=False)
print(f"\n[DONE] saved {len(df_r):,} rows to {OUT}", flush=True)
print(f"Total: {(time.time()-t0)/60:.1f} min", flush=True)
