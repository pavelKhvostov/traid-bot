"""Pivot classifier pipeline:
  - Universe: 1272 baseline pivots (F1∩F2∩F3 на 12h, 6y BTC)
  - Label: pivot.direction совпал с реальным движением ≥2% в 6×12h БЕЗ
           predшествующего -2% excursion в противоположную сторону
  - Features: Phase 4 force + MH v2 + RSI cumulative @ pivot.close
  - Train: walk-forward LightGBM, 1y rolling train, monthly retrain
  - Eval: holdout 24 user-labeled даты + global precision/recall

Output:
  ~/Desktop/pivot_classifier_labels.parquet  — labels + features merged
  ~/Desktop/pivot_classifier_preds.parquet   — walk-forward predictions
  ~/Desktop/pivot_classifier_metrics.txt     — отчёт
"""
from __future__ import annotations
import sys, time, warnings
from pathlib import Path
import numpy as np
import pandas as pd
warnings.filterwarnings('ignore')

sys.path.insert(0, str(Path.home()/'smc-lib/mh-ml'))

# Load 1m
print("[1/6] Loading 1m...", flush=True)
df_1m = pd.read_csv(Path.home()/'traid-bot/data/BTCUSDT_1m_vic_vadim.csv')
df_1m['open_time'] = pd.to_datetime(df_1m['open_time'], utc=True, format='mixed')
df_1m = df_1m.set_index('open_time').sort_index()
ts_s = (df_1m.index.astype('int64').values // 10**6)
hi_1m = df_1m['high'].values; lo_1m = df_1m['low'].values
print(f"  {len(df_1m):,} bars")

# === Step 1: Build labels for baseline pivots ===
print("[2/6] Building labels (72h window, no SL excursion)...", flush=True)
base = pd.read_parquet(Path.home()/'Desktop/pred12h_baseline_c1c7.parquet')
base['pivot_close_ts'] = pd.to_datetime(base['pivot_open_ts_ms'], unit='ms', utc=True) + pd.Timedelta(hours=12)

WINDOW_H = 72
def idx_at(t_s): return int(np.searchsorted(ts_s, t_s, side='left'))

def label_outcome(close_ts, close_px, direction):
    """Return 1 if direction (high→DOWN, low→UP) reached 2% w/o opposite 2% first.

    direction='high' means FH = expect DOWN move (SHORT win = -2%)
    direction='low'  means FL = expect UP move (LONG win = +2%)
    """
    start_s = int(close_ts.timestamp())
    end_s = start_s + WINDOW_H * 3600
    a = idx_at(start_s); e = min(idx_at(end_s), len(hi_1m))
    if a >= e: return None
    if direction == 'high':
        tgt = close_px * 0.98   # DOWN 2%
        opp = close_px * 1.02   # UP 2% = opposite excursion
        for i in range(a, e):
            if hi_1m[i] >= opp: return 0  # opposite hit first
            if lo_1m[i] <= tgt: return 1  # target reached
        return 0  # neither
    else:
        tgt = close_px * 1.02   # UP 2%
        opp = close_px * 0.98   # DOWN 2%
        for i in range(a, e):
            if lo_1m[i] <= opp: return 0
            if hi_1m[i] >= tgt: return 1
        return 0

# Compute close price at each pivot.close
labels = []
for _, r in base.iterrows():
    ts = r['pivot_close_ts']
    idx = idx_at(int(ts.timestamp()))
    if idx >= len(hi_1m) or idx == 0: labels.append(None); continue
    close_px = float(df_1m['close'].values[idx-1])
    lbl = label_outcome(ts, close_px, r['direction'])
    labels.append(lbl)
base['label'] = labels
base['close_px_at_pivot'] = [float(df_1m['close'].values[max(0,idx_at(int(t.timestamp()))-1)]) for t in base['pivot_close_ts']]
print(f"  labels: {base['label'].notna().sum()}/{len(base)}")
print(f"  positives (= direction won): {base['label'].sum()}/{base['label'].notna().sum()} = {base['label'].mean()*100:.1f}%")
print(f"  by direction:")
print(base.groupby('direction')['label'].agg(['sum','count','mean']))

# === Step 2: Build MH features ===
print("\n[3/6] Building MH v2 features (3064 columns)...", flush=True)
from mh_features_v2 import build_features_v2
t0 = time.time()
feat = build_features_v2(df_1m)
print(f"  shape {feat.shape}, took {time.time()-t0:.0f}s")

# === Step 3: Subsample MH features to 12h pivot close moments ===
print("\n[4/6] Subsampling features at pivot close + merging Phase 4 force...", flush=True)
feat_idx = feat.copy()
feat_idx.index = pd.to_datetime(feat_idx.index, utc=True).astype('datetime64[ns, UTC]')

base['pivot_close_ts'] = pd.to_datetime(base['pivot_close_ts'], utc=True).astype('datetime64[ns, UTC]')
base = base.sort_values('pivot_close_ts').reset_index(drop=True)

# Get MH feature values at pivot.close via merge_asof
feat_idx = feat_idx.reset_index().rename(columns={'index':'ts','open_time':'ts'})
if 'open_time' in feat_idx.columns: feat_idx = feat_idx.rename(columns={'open_time':'ts'})
ts_col = 'ts' if 'ts' in feat_idx.columns else feat_idx.columns[0]
feat_idx[ts_col] = pd.to_datetime(feat_idx[ts_col], utc=True).astype('datetime64[ns, UTC]')
feat_idx = feat_idx.sort_values(ts_col)
merged_feat = pd.merge_asof(
    base[['pivot_close_ts']].sort_values('pivot_close_ts'),
    feat_idx,
    left_on='pivot_close_ts', right_on=ts_col,
    direction='backward',
)
# Re-align with base order
base = base.sort_values('pivot_close_ts').reset_index(drop=True)
merged_feat = merged_feat.reset_index(drop=True)
feat_at_pivots = merged_feat.drop(columns=['pivot_close_ts', ts_col], errors='ignore')

# Phase 4 force
force = pd.read_parquet(Path.home()/'Desktop/pred12h_C8_force_6y.parquet')
force_cols = ['total_net','d3_net','n_wins','bias','top_long_str','top_short_str','force_match']
base = base.merge(force[['pivot_open_ts_ms','direction'] + force_cols],
                  on=['pivot_open_ts_ms','direction'], how='left')
# One-hot BIAS
bias_dummies = pd.get_dummies(base['bias'], prefix='bias').astype(int)
base = pd.concat([base, bias_dummies], axis=1)

# Direction-aware features (FH-perspective vs FL-perspective)
base['dir_high'] = (base['direction']=='high').astype(int)
base['dir_low']  = (base['direction']=='low').astype(int)
# dir-aligned zone strength
base['dir_str']  = np.where(base['direction']=='high', base['top_short_str'], base['top_long_str'])
base['opp_str']  = np.where(base['direction']=='high', base['top_long_str'], base['top_short_str'])

# Combine
combined = pd.concat([base.reset_index(drop=True), feat_at_pivots.reset_index(drop=True)], axis=1)
print(f"  combined shape: {combined.shape}")

# Drop rows without label
combined = combined[combined['label'].notna()].copy()
combined['label'] = combined['label'].astype(int)
print(f"  with valid labels: {len(combined)}")

OUT_LABELS = Path.home()/'Desktop/pivot_classifier_labels.parquet'
combined.to_parquet(OUT_LABELS)
print(f"  saved → {OUT_LABELS}")

# === Step 4: Walk-forward LightGBM ===
print("\n[5/6] Walk-forward classifier (1y rolling, monthly retrain)...", flush=True)
try:
    import lightgbm as lgb
    use_lgb = True
    print("  using LightGBM")
except (ImportError, OSError) as e:
    from sklearn.ensemble import HistGradientBoostingClassifier
    use_lgb = False
    print(f"  LGBM unavailable ({type(e).__name__}), using sklearn HistGradientBoostingClassifier")

# Feature columns: numeric features only (drop ts, id, direction text, bias text)
DROP = ['pivot_open_ts_ms','direction','confirmed','is_imp','pivot_high','pivot_low',
        'pivot_open_ts','pivot_close_ts','in_basket','c1','c2','c3','c4','c5','c6','c7',
        'bias','label','close_px_at_pivot']
DROP = [c for c in DROP if c in combined.columns]
X_full = combined.drop(columns=DROP).select_dtypes(include=[np.number, bool])
y_full = combined['label'].values
X_full = X_full.astype(float).fillna(0)
print(f"  features: {X_full.shape[1]}, samples: {len(X_full)}")

# Walk-forward: train 1y, predict next 1mo
ts_arr = combined['pivot_close_ts'].values
t_start = pd.Timestamp('2021-05-01', tz='UTC')
t_end = combined['pivot_close_ts'].max()

preds = []
cur = t_start
ri = 0
t0 = time.time()
while cur < t_end:
    train_lo = cur - pd.Timedelta(days=365)
    test_lo = cur
    test_hi = cur + pd.Timedelta(days=30)
    train_mask = (combined['pivot_close_ts'] >= train_lo) & (combined['pivot_close_ts'] < cur)
    test_mask = (combined['pivot_close_ts'] >= test_lo) & (combined['pivot_close_ts'] < test_hi)
    n_tr = train_mask.sum(); n_te = test_mask.sum()
    if n_tr < 50 or n_te == 0:
        cur += pd.Timedelta(days=30); continue
    Xtr = X_full[train_mask.values]; ytr = y_full[train_mask.values]
    Xte = X_full[test_mask.values]; yte = y_full[test_mask.values]
    if use_lgb:
        m = lgb.LGBMClassifier(n_estimators=200, max_depth=6, learning_rate=0.05,
                                n_jobs=-1, verbose=-1, class_weight='balanced')
        m.fit(Xtr, ytr)
        ypp = m.predict_proba(Xte)[:,1]
    else:
        m = HistGradientBoostingClassifier(max_iter=200, max_depth=6, learning_rate=0.05,
                                            class_weight='balanced')
        m.fit(Xtr, ytr)
        ypp = m.predict_proba(Xte)[:,1]
    pred_df = combined.loc[test_mask, ['pivot_close_ts','direction','label']].copy()
    pred_df['pred_proba'] = ypp
    preds.append(pred_df)
    ri += 1
    if ri % 5 == 0:
        print(f"  retrain {ri}: cur={cur.date()}, n_tr={n_tr}, n_te={n_te}, elapsed={time.time()-t0:.0f}s")
    cur += pd.Timedelta(days=30)

preds = pd.concat(preds).reset_index(drop=True)
print(f"\n  total predictions: {len(preds)}")
OUT_P = Path.home()/'Desktop/pivot_classifier_preds.parquet'
preds.to_parquet(OUT_P)

# === Step 5: Evaluate ===
print("\n[6/6] Evaluation...", flush=True)
def eval_at(thr):
    sub = preds[preds['pred_proba'] >= thr]
    n = len(sub)
    if n == 0: return None
    P = sub['label'].mean()
    return n, P

print(f"\nPrecision at different confidence thresholds:")
for t in [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]:
    res = eval_at(t)
    if res:
        n, p = res
        print(f"  thr ≥ {t:.1f}: n={n:>4}  precision={p*100:.1f}%  cover={n/len(preds)*100:.1f}%")

# Validate on 24 user-labeled
user_targets = [
    '2026-02-08 15:00','2026-02-12 15:00','2026-02-15 03:00','2026-02-21 15:00',
    '2026-02-24 15:00','2026-02-25 15:00','2026-02-28 03:00','2026-03-04 15:00',
    '2026-03-08 15:00','2026-03-22 15:00','2026-03-29 15:00','2026-04-17 15:00',
    '2026-04-22 15:00','2026-04-27 03:00','2026-04-29 15:00','2026-05-06 03:00',
    '2026-05-08 03:00','2026-05-14 15:00','2026-05-23 03:00',
]
ut_ts = [pd.Timestamp(t+'+03:00').tz_convert('UTC').astype('datetime64[ns, UTC]') if hasattr(pd.Timestamp(t+'+03:00').tz_convert('UTC'),'astype') else pd.Timestamp(t+'+03:00').tz_convert('UTC') for t in user_targets]
ut_ts_utc = [pd.Timestamp(t+'+03:00') for t in user_targets]
print(f"\nValidate on user-labeled (19 in baseline range):")
for ts in ut_ts_utc:
    pivot_close_utc = (ts.tz_convert('UTC') + pd.Timedelta(hours=12))
    sub = preds[abs((preds['pivot_close_ts'] - pivot_close_utc).dt.total_seconds()) < 5]
    if len(sub) == 0:
        print(f"  {ts.strftime('%Y-%m-%d %H:%M MSK')}: NOT in pred set (pre-2021-05 or post)")
    else:
        r = sub.iloc[0]
        print(f"  {ts.strftime('%Y-%m-%d %H:%M MSK')}  dir={r['direction']:5s} label={r['label']} pred={r['pred_proba']:.3f}")

print("\n[DONE]")
