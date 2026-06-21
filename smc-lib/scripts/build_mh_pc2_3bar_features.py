"""Build MH features с PC2-best config для (i-2, i-1, i) 3-bar pattern prediction.

PC2 best config:
  n1=7, n2=14, n4=3, sma_compare=22, mf_sma=60, stoch_fast=50, stoch_slow=60

Per 12h pivot bar i (open_ts):
  Three timestamps: i-2.close, i-1.close, i.close
  For each TF in {1h, 2h, 4h, 12h, 1d}:
    Compute MH parametric (bw2, mf, rsi, stc) at each timestamp
  Plus deltas (i - i-1, i-1 - i-2) per indicator per TF
  Plus cumulative «bars_since» (zero cross / OB/OS exit) per TF

Output: ~/Desktop/pc2_3bar_features.parquet
"""
from __future__ import annotations
import sys, time, warnings
from pathlib import Path
import numpy as np
import pandas as pd
warnings.filterwarnings('ignore')

sys.path.insert(0, str(Path.home()/'smc-lib/mh-ml'))
from mh_features_v2 import compute_mh_parametric, _ema_np, _sma_np

PC2_PARAMS = dict(n1=7, n2=14, n3=12, n4=3,
                   sma_compare=22, mf_sma=60,
                   stoch_fast=50, stoch_slow=60)
TFS = ['15min','30min','1h','2h','4h','12h','1D']
TF_LABEL = {'15min':'15m','30min':'30m','1h':'1h','2h':'2h','4h':'4h','12h':'12h','1D':'1d'}

print("Loading 1m...")
df_1m = pd.read_csv(Path.home()/'traid-bot/data/BTCUSDT_1m_vic_vadim.csv')
df_1m['open_time'] = pd.to_datetime(df_1m['open_time'], utc=True, format='mixed')
df_1m = df_1m.set_index('open_time').sort_index()
print(f"  {len(df_1m):,} bars, {df_1m.index[0]} → {df_1m.index[-1]}")

# Resample to each TF and compute MH with PC2 params
print("\nComputing MH (PC2 params) on each TF...")
mh_per_tf = {}
agg = {'open':'first','high':'max','low':'min','close':'last','volume':'sum'}
for tf in TFS:
    t0 = time.time()
    rs = df_1m[['open','high','low','close','volume']].resample(tf, label='left', closed='left').agg(agg).dropna()
    o, h, l, c = rs['open'].values, rs['high'].values, rs['low'].values, rs['close'].values
    mh = compute_mh_parametric(o, h, l, c, **PC2_PARAMS)
    # Extract: bw2, mf, rsi, stc (from mh dict)
    df_tf = pd.DataFrame({
        'bw2': mh['bw2'], 'mf': mh['mf'],
        'rsi': mh.get('rsi', np.full(len(rs), np.nan)),
        'stc': mh.get('stc', np.full(len(rs), np.nan)),
    }, index=rs.index)
    mh_per_tf[tf] = df_tf
    print(f"  {TF_LABEL.get(tf,tf):>5s}: {len(df_tf):>6,} bars, {time.time()-t0:.0f}s")

# For each baseline pivot, get features at (i-2, i-1, i) 12h closes
print("\nLoading baseline pivots...")
base = pd.read_parquet(Path.home()/'Desktop/pred12h_baseline_c1c7.parquet')
base['pivot_open_ts'] = pd.to_datetime(base['pivot_open_ts_ms'], unit='ms', utc=True)
base['pivot_open_ts'] = pd.to_datetime(base['pivot_open_ts'], utc=True).astype('datetime64[ns, UTC]')

# 22 user-targets
TARGETS = [
    ('2026-02-08 15:00','FH'),('2026-02-12 15:00','FL'),('2026-02-15 03:00','FH'),
    ('2026-02-21 15:00','FH'),('2026-02-24 15:00','FL'),('2026-02-25 15:00','FH'),
    ('2026-02-28 03:00','FL'),('2026-03-04 15:00','FH'),('2026-03-08 15:00','FL'),
    ('2026-03-17 03:00','FH'),('2026-03-22 15:00','FL'),('2026-03-25 03:00','FH'),
    ('2026-03-29 15:00','FL'),('2026-04-17 15:00','FH'),
    ('2026-04-27 03:00','FH'),('2026-04-29 15:00','FL'),('2026-05-06 03:00','FH'),
    ('2026-05-08 03:00','FL'),('2026-05-10 15:00','FH'),('2026-05-14 15:00','FH'),
    ('2026-05-23 03:00','FL'),('2026-05-26 15:00','FH'),
]
target_ts_set = {(int(pd.Timestamp(t+'+03:00').timestamp()*1000), 'high' if s=='FH' else 'low') for t,s in TARGETS}
base['is_target22'] = base.apply(lambda r: (r['pivot_open_ts_ms'], r['direction']) in target_ts_set, axis=1)
print(f"  baseline: {len(base)}, target22: {base['is_target22'].sum()}")

# Labels: 72h move ≥2% direction w/o opposite excursion
print("Building labels...")
import time
# Pre-extract 1m arrays
hi_arr = df_1m['high'].values; lo_arr = df_1m['low'].values; cl_arr = df_1m['close'].values
ts_idx = df_1m.index

def idx_at_ts(t):
    return ts_idx.searchsorted(t)

def make_label(close_ts, close_px, direction):
    a = idx_at_ts(close_ts)
    e_lim = idx_at_ts(close_ts + pd.Timedelta(hours=72))
    e = min(e_lim, len(hi_arr))
    if a >= e: return None
    if direction == 'high':
        tgt = close_px*0.98; opp = close_px*1.02
        for i in range(a, e):
            if hi_arr[i] >= opp: return 0
            if lo_arr[i] <= tgt: return 1
        return 0
    else:
        tgt = close_px*1.02; opp = close_px*0.98
        for i in range(a, e):
            if lo_arr[i] <= opp: return 0
            if hi_arr[i] >= tgt: return 1
        return 0

# Build features per pivot
print("\nExtracting features per pivot (i-2, i-1, i)...")
rows = []
for _, r in base.iterrows():
    p_open = r['pivot_open_ts']
    # close moments on 12h TF
    t_im2 = p_open - pd.Timedelta(hours=12)   # i-2.close = i-1.open
    t_im1 = p_open                             # i-1.close = i.open
    t_i   = p_open + pd.Timedelta(hours=12)    # i.close

    row = {
        'pivot_open_ts_ms': r['pivot_open_ts_ms'],
        'direction': r['direction'],
        'confirmed': r['confirmed'],
        'is_imp': r.get('is_imp', False),
        'is_target22': r['is_target22'],
        'in_basket': r['in_basket'],
    }

    # Label
    a = idx_at_ts(t_i)
    if a > 0 and a < len(cl_arr):
        close_px = float(cl_arr[a-1])
        row['label'] = make_label(t_i, close_px, r['direction'])
    else:
        row['label'] = None

    # For each TF and each of 3 timestamps, get bw2/mf/rsi/stc
    for tf in TFS:
        tfl = TF_LABEL.get(tf, tf)
        df_tf = mh_per_tf[tf]
        for tag, t in [('im2', t_im2), ('im1', t_im1), ('i', t_i)]:
            pos = df_tf.index.searchsorted(t, side='right') - 1
            if pos < 0 or pos >= len(df_tf):
                for col in ['bw2','mf','rsi','stc']:
                    row[f'{col}_{tfl}_{tag}'] = np.nan
            else:
                for col in ['bw2','mf','rsi','stc']:
                    row[f'{col}_{tfl}_{tag}'] = float(df_tf.iloc[pos][col])
        # deltas
        for col in ['bw2','mf','rsi','stc']:
            row[f'{col}_{tfl}_delta1'] = row[f'{col}_{tfl}_i'] - row[f'{col}_{tfl}_im1']
            row[f'{col}_{tfl}_delta2'] = row[f'{col}_{tfl}_im1'] - row[f'{col}_{tfl}_im2']
            row[f'{col}_{tfl}_accel'] = row[f'{col}_{tfl}_delta1'] - row[f'{col}_{tfl}_delta2']

    rows.append(row)

df_feat = pd.DataFrame(rows)
print(f"\nFeature matrix: {df_feat.shape}")
print(f"  Label distribution: {df_feat['label'].value_counts().to_dict()}")
print(f"  target22 → label=1: {df_feat[df_feat['is_target22']]['label'].sum()}/22")

OUT = Path.home()/'Desktop/pc2_3bar_features.parquet'
df_feat.to_parquet(OUT, index=False)
print(f"\nSaved → {OUT}")
print(f"Features cols: {len([c for c in df_feat.columns if c not in ['pivot_open_ts_ms','direction','confirmed','is_imp','is_target22','in_basket','label']])}")
