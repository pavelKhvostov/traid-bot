"""Sweep PC2 configs (6912 from screening) → find best for Williams pivot prediction.

Pipeline:
  1. Load PC2 screening_results.csv (6912 configs with dir_acc)
  2. Pick top-N configs by dir_acc + diverse subset
  3. For each config:
     a. Build MH features per TF with that config's params
     b. Extract 3-bar features (i-2, i-1, i + deltas) per baseline pivot
     c. Walk-forward train classifier target=confirmed (Williams)
     d. Compute max precision at threshold 0.7+
  4. Rank configs by precision
  5. Pick winner config

Target = confirmed (Williams n=2 pass). High precision (WR) > recall.
User's 22 — bonus catches.
"""
from __future__ import annotations
import sys, time
from pathlib import Path
import pandas as pd
import numpy as np
import warnings; warnings.filterwarnings('ignore')

sys.path.insert(0, str(Path.home()/'smc-lib/mh-ml'))
from mh_features_v2 import compute_mh_parametric

# Load PC2 results
print("Loading PC2 screening...")
pc2 = pd.read_csv(Path.home()/'Desktop/output PC2/screening_results.csv')
print(f"  Total configs: {len(pc2):,}")
print(f"  dir_acc range: {pc2.dir_acc.min():.3f} — {pc2.dir_acc.max():.3f}")

# Pick top 30 configs by dir_acc
TOP_N = 30
top_configs = pc2.nlargest(TOP_N, 'dir_acc').reset_index(drop=True)
print(f"  Selected top-{TOP_N} configs (dir_acc range {top_configs.dir_acc.min():.3f}-{top_configs.dir_acc.max():.3f})")

# Load 1m once
print("\nLoading 1m...")
df_1m = pd.read_csv(Path.home()/'traid-bot/data/BTCUSDT_1m_vic_vadim.csv')
df_1m['open_time'] = pd.to_datetime(df_1m['open_time'], utc=True, format='mixed')
df_1m = df_1m.set_index('open_time').sort_index()
print(f"  {len(df_1m):,} bars")

# Resample to each TF once
TFS_RES = [('1h','1h'),('2h','2h'),('4h','4h'),('12h','12h'),('1D','1d')]
agg = {'open':'first','high':'max','low':'min','close':'last','volume':'sum'}
ohlc_per_tf = {}
print("Resampling...")
for tf_rs, tfl in TFS_RES:
    rs = df_1m[['open','high','low','close','volume']].resample(tf_rs, label='left', closed='left').agg(agg).dropna()
    ohlc_per_tf[tfl] = (rs['open'].values, rs['high'].values, rs['low'].values, rs['close'].values, rs.index)
    print(f"  {tfl}: {len(rs):,} bars")

# Load baseline
base = pd.read_parquet(Path.home()/'Desktop/pred12h_baseline_c1c7.parquet')
base['pivot_open_ts'] = pd.to_datetime(base['pivot_open_ts_ms'], unit='ms', utc=True)
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
base = base.sort_values('pivot_open_ts').reset_index(drop=True)
print(f"\nBaseline: {len(base)} pivots, confirmed: {base['confirmed'].sum()}, target22: {base['is_target22'].sum()}")

from sklearn.ensemble import HistGradientBoostingClassifier

# For each config: build features, train, eval
def map_pc2_to_params(row):
    # PC2 columns: bw2_ema1, bw2_ema2, bw2_sma_out, color_sma, mf_sma, rsi_stoch, stc_stoch
    return dict(
        n1=int(row['bw2_ema1']),
        n2=int(row['bw2_ema2']),
        n3=12,  # not in PC2 screening, keep default
        n4=int(row['bw2_sma_out']),
        sma_compare=int(row['color_sma']),
        mf_sma=int(row['mf_sma']),
        stoch_fast=int(row['rsi_stoch']),
        stoch_slow=int(row['stc_stoch']),
    )

def build_features_for_config(params):
    """Returns df with features per baseline pivot."""
    mh_per_tf = {}
    for tfl, (o,h,l,c,idx) in ohlc_per_tf.items():
        mh = compute_mh_parametric(o,h,l,c, **params)
        mh_per_tf[tfl] = (idx, mh['bw2'], mh['mf'], mh.get('rsi', np.full(len(idx), np.nan)), mh.get('stc', np.full(len(idx), np.nan)))

    rows = []
    for _, r in base.iterrows():
        p_open = r['pivot_open_ts']
        t_im2 = p_open - pd.Timedelta(hours=12)
        t_im1 = p_open
        t_i   = p_open + pd.Timedelta(hours=12)
        row = {'confirmed': r['confirmed'], 'is_target22': r['is_target22'],
               'in_basket': r['in_basket'], 'pivot_open_ts': p_open,
               'direction': r['direction']}
        for tfl in ['1h','2h','4h','12h','1d']:
            idx, bw2, mf, rsi, stc = mh_per_tf[tfl]
            for tag, t in [('im2',t_im2),('im1',t_im1),('i',t_i)]:
                pos = idx.searchsorted(t, side='right') - 1
                if pos < 0 or pos >= len(idx):
                    row[f'bw2_{tfl}_{tag}'] = row[f'mf_{tfl}_{tag}'] = np.nan
                else:
                    row[f'bw2_{tfl}_{tag}'] = float(bw2[pos])
                    row[f'mf_{tfl}_{tag}'] = float(mf[pos])
            row[f'bw2_{tfl}_delta1'] = row[f'bw2_{tfl}_i'] - row[f'bw2_{tfl}_im1']
            row[f'bw2_{tfl}_accel'] = (row[f'bw2_{tfl}_i'] - row[f'bw2_{tfl}_im1']) - (row[f'bw2_{tfl}_im1'] - row[f'bw2_{tfl}_im2'])
            row[f'mf_{tfl}_delta1'] = row[f'mf_{tfl}_i'] - row[f'mf_{tfl}_im1']
            row[f'mf_{tfl}_accel'] = (row[f'mf_{tfl}_i'] - row[f'mf_{tfl}_im1']) - (row[f'mf_{tfl}_im1'] - row[f'mf_{tfl}_im2'])
        rows.append(row)
    return pd.DataFrame(rows)

def evaluate_config(params, verbose=False):
    df = build_features_for_config(params)
    df['pivot_open_ts'] = pd.to_datetime(df['pivot_open_ts'], utc=True)
    feat_cols = [c for c in df.columns if c not in ['confirmed','is_target22','in_basket','pivot_open_ts','direction']]
    X_full = df[feat_cols].fillna(0).values
    y_full = df['confirmed'].astype(int).values

    # Walk-forward
    preds = []
    cur = pd.Timestamp('2021-05-01', tz='UTC')
    t_end = df['pivot_open_ts'].max()
    while cur < t_end:
        train_lo = cur - pd.Timedelta(days=365)
        test_hi = cur + pd.Timedelta(days=30)
        train_mask = (df['pivot_open_ts'] >= train_lo) & (df['pivot_open_ts'] < cur)
        test_mask = (df['pivot_open_ts'] >= cur) & (df['pivot_open_ts'] < test_hi)
        if train_mask.sum() < 50 or test_mask.sum() == 0:
            cur += pd.Timedelta(days=30); continue
        m = HistGradientBoostingClassifier(max_iter=200, max_depth=5, learning_rate=0.05, class_weight='balanced')
        m.fit(X_full[train_mask.values], y_full[train_mask.values])
        ypp = m.predict_proba(X_full[test_mask.values])[:,1]
        sub = df.loc[test_mask, ['confirmed','is_target22']].copy()
        sub['pred'] = ypp
        preds.append(sub)
        cur += pd.Timedelta(days=30)
    preds = pd.concat(preds).reset_index(drop=True)
    # Max precision при разных thresholds
    results = {}
    for thr in [0.5, 0.6, 0.7, 0.8, 0.9]:
        sub = preds[preds['pred'] >= thr]
        if len(sub) < 20:
            results[thr] = (0, 0, 0)
            continue
        prec = sub['confirmed'].mean()
        tgt = sub['is_target22'].sum()
        results[thr] = (len(sub), prec, tgt)
    return results

print(f"\nEvaluating {TOP_N} top PC2 configs...")
t0 = time.time()
all_results = []
for i, row in top_configs.iterrows():
    params = map_pc2_to_params(row)
    t1 = time.time()
    try:
        res = evaluate_config(params)
    except Exception as e:
        print(f"  [{i+1}] ERROR: {e}"); continue
    elapsed = time.time() - t1
    # Pick max precision among thr 0.7/0.8/0.9 with reasonable n
    best_thr, best_prec, best_n, best_tgt = 0, 0, 0, 0
    for thr, (n, prec, tgt) in res.items():
        if n >= 30 and prec > best_prec:
            best_thr = thr; best_prec = prec; best_n = n; best_tgt = tgt
    cfg_str = f"({row['bw2_ema1']},{row['bw2_ema2']},{row['bw2_sma_out']},{row['color_sma']},{row['mf_sma']},{row['rsi_stoch']},{row['stc_stoch']})"
    all_results.append({
        'cfg': cfg_str, 'dir_acc': row['dir_acc'],
        'best_thr': best_thr, 'best_prec': best_prec,
        'best_n': best_n, 'best_tgt22': best_tgt,
        'time': elapsed,
    })
    print(f"  [{i+1}/{TOP_N}] {cfg_str:35s} dir_acc={row['dir_acc']:.3f}  best_thr={best_thr} prec={best_prec*100:.1f}% n={best_n} tgt22={best_tgt}/22 ({elapsed:.0f}s)")

print(f"\nTotal sweep time: {(time.time()-t0)/60:.1f} min")
res_df = pd.DataFrame(all_results).sort_values('best_prec', ascending=False)
print(f"\n=== TOP-10 CONFIGS by WR (precision при threshold ≥ 0.7) ===\n")
print(res_df.head(10).to_string(index=False))

OUT = Path.home()/'Desktop/pc2_config_sweep_results.parquet'
res_df.to_parquet(OUT)
print(f"\nSaved → {OUT}")
