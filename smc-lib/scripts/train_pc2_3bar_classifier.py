"""Train classifier на PC2-config 3-bar features для predict pivot success.

Walk-forward 1y train / 1mo retrain. Output:
  - precision per threshold
  - holdout target22 catches
  - feature importance
"""
from __future__ import annotations
import time
from pathlib import Path
import pandas as pd
import numpy as np
import warnings; warnings.filterwarnings('ignore')

df = pd.read_parquet(Path.home()/'Desktop/pc2_3bar_features.parquet')
print(f"Loaded: {df.shape}")
print(f"  Positives: {(df['label']==1).sum()} ({df['label'].mean()*100:.1f}%)")
print(f"  target22: {df['is_target22'].sum()}")

df['pivot_close_ts'] = pd.to_datetime(df['pivot_open_ts_ms'], unit='ms', utc=True) + pd.Timedelta(hours=12)
df['pivot_close_ts'] = pd.to_datetime(df['pivot_close_ts'], utc=True).astype('datetime64[ns, UTC]')
df = df.dropna(subset=['label']).reset_index(drop=True)
df = df.sort_values('pivot_close_ts').reset_index(drop=True)

DROP = ['pivot_open_ts_ms','direction','confirmed','is_imp','is_target22','in_basket','label','pivot_close_ts']
feat_cols = [c for c in df.columns if c not in DROP]
X_full = df[feat_cols].astype(float).fillna(0).values
y_full = df['label'].astype(int).values
print(f"Features: {len(feat_cols)}, samples: {len(X_full)}")

from sklearn.ensemble import HistGradientBoostingClassifier

cur = pd.Timestamp('2021-05-01', tz='UTC')
t_end = df['pivot_close_ts'].max()
preds = []
t0 = time.time(); ri = 0
while cur < t_end:
    train_lo = cur - pd.Timedelta(days=365)
    test_hi = cur + pd.Timedelta(days=30)
    train_mask = (df['pivot_close_ts'] >= train_lo) & (df['pivot_close_ts'] < cur)
    test_mask = (df['pivot_close_ts'] >= cur) & (df['pivot_close_ts'] < test_hi)
    if train_mask.sum() < 50 or test_mask.sum() == 0:
        cur += pd.Timedelta(days=30); continue
    Xtr = X_full[train_mask.values]; ytr = y_full[train_mask.values]
    Xte = X_full[test_mask.values]; yte = y_full[test_mask.values]
    m = HistGradientBoostingClassifier(max_iter=300, max_depth=5, learning_rate=0.05,
                                        class_weight='balanced')
    m.fit(Xtr, ytr)
    ypp = m.predict_proba(Xte)[:,1]
    sub = df.loc[test_mask, ['pivot_close_ts','direction','label','is_target22']].copy()
    sub['pred_proba'] = ypp
    preds.append(sub)
    ri += 1
    if ri % 10 == 0:
        print(f"  retrain {ri}: cur={cur.date()}, elapsed={(time.time()-t0)/60:.1f}m")
    cur += pd.Timedelta(days=30)

preds = pd.concat(preds).reset_index(drop=True)
preds.to_parquet(Path.home()/'Desktop/pc2_3bar_preds.parquet')
print(f"\nTotal preds: {len(preds)}, time {(time.time()-t0)/60:.1f}m")

print(f"\n=== Precision @ thresholds ===")
for thr in [0.30, 0.40, 0.50, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90]:
    sub = preds[preds['pred_proba'] >= thr]
    if len(sub) == 0: continue
    P = sub['label'].mean()
    P_t = sub['is_target22'].mean()
    n_t = sub['is_target22'].sum()
    cov = len(sub)/len(preds)*100
    print(f"  thr ≥ {thr:.2f}: n={len(sub):>4}  precision={P*100:.1f}%  cov={cov:.1f}%  target22_caught={n_t}/22")

print(f"\n=== Target 22 predictions ===")
sub22 = preds[preds['is_target22']]
print(f"  Median pred: {sub22['pred_proba'].median():.3f}")
print(f"  Mean pred: {sub22['pred_proba'].mean():.3f}")
print(f"  Caught at thr ≥ 0.5: {(sub22['pred_proba'] >= 0.5).sum()}/{len(sub22)}")
print(f"  Caught at thr ≥ 0.7: {(sub22['pred_proba'] >= 0.7).sum()}/{len(sub22)}")
print(f"  Caught at thr ≥ 0.8: {(sub22['pred_proba'] >= 0.8).sum()}/{len(sub22)}")

# Feature importance via training on full data
print(f"\nTraining global model для feature importance...")
gm = HistGradientBoostingClassifier(max_iter=500, max_depth=5, learning_rate=0.05, class_weight='balanced')
gm.fit(X_full, y_full)

# Permutation importance (subset for speed)
from sklearn.inspection import permutation_importance
print("Computing permutation importance...")
n_sample = min(500, len(X_full))
idx = np.random.choice(len(X_full), n_sample, replace=False)
result = permutation_importance(gm, X_full[idx], y_full[idx], n_repeats=3, random_state=0, n_jobs=-1)

imp = pd.DataFrame({'feature': feat_cols, 'importance': result.importances_mean})
imp = imp.sort_values('importance', ascending=False)
print(f"\n=== TOP 20 features by permutation importance ===")
for _, r in imp.head(20).iterrows():
    print(f"  {r['feature']:40s} {r['importance']:+.4f}")

# Print 22 predictions
print(f"\n=== Predictions on 22 user-targets ===")
for _, r in sub22.sort_values('pivot_close_ts').iterrows():
    msk = (r['pivot_close_ts'] - pd.Timedelta(hours=9))  # close - 12h + 3h
    msk_str = msk.strftime('%Y-%m-%d %H:%M')
    flag = '✓' if r['pred_proba'] >= 0.5 else '✗'
    print(f"  {msk_str}  dir={r['direction']:5s}  pred={r['pred_proba']:.3f} {flag}")
