"""Train classifier на готовых labels parquet (без пересборки features)."""
from __future__ import annotations
import sys, time
from pathlib import Path
import numpy as np
import pandas as pd
import warnings; warnings.filterwarnings('ignore')

combined = pd.read_parquet(Path.home()/'Desktop/pivot_classifier_labels.parquet')
print(f"Loaded {len(combined)} pivot+features rows, columns: {combined.shape[1]}")
print(f"  Positives: {combined['label'].sum()} ({combined['label'].mean()*100:.1f}%)")

DROP = ['pivot_open_ts_ms','direction','confirmed','is_imp','pivot_high','pivot_low',
        'pivot_open_ts','pivot_close_ts','in_basket','c1','c2','c3','c4','c5','c6','c7',
        'bias','label','close_px_at_pivot']
DROP = [c for c in DROP if c in combined.columns]
X_full = combined.drop(columns=DROP).select_dtypes(include=[np.number, bool])
X_full = X_full.astype(float).fillna(0)
y_full = combined['label'].astype(int).values
print(f"Features: {X_full.shape[1]}, samples: {len(X_full)}")

try:
    import lightgbm as lgb
    use_lgb = True
    print("Using LightGBM")
except (ImportError, OSError):
    from sklearn.ensemble import HistGradientBoostingClassifier
    use_lgb = False
    print("Using sklearn HistGradientBoostingClassifier")

ts_arr = combined['pivot_close_ts'].values
cur = pd.Timestamp('2021-05-01', tz='UTC')
t_end = combined['pivot_close_ts'].max()
preds = []
ri = 0
t0 = time.time()
while cur < t_end:
    train_lo = cur - pd.Timedelta(days=365)
    test_hi = cur + pd.Timedelta(days=30)
    train_mask = (combined['pivot_close_ts'] >= train_lo) & (combined['pivot_close_ts'] < cur)
    test_mask = (combined['pivot_close_ts'] >= cur) & (combined['pivot_close_ts'] < test_hi)
    if train_mask.sum() < 50 or test_mask.sum() == 0:
        cur += pd.Timedelta(days=30); continue
    Xtr = X_full[train_mask.values]; ytr = y_full[train_mask.values]
    Xte = X_full[test_mask.values]; yte = y_full[test_mask.values]
    if use_lgb:
        m = lgb.LGBMClassifier(n_estimators=300, max_depth=6, learning_rate=0.05,
                                n_jobs=-1, verbose=-1, class_weight='balanced')
    else:
        from sklearn.ensemble import HistGradientBoostingClassifier
        m = HistGradientBoostingClassifier(max_iter=300, max_depth=6, learning_rate=0.05,
                                            class_weight='balanced')
    m.fit(Xtr, ytr)
    ypp = m.predict_proba(Xte)[:,1]
    pred_df = combined.loc[test_mask, ['pivot_close_ts','direction','label']].copy()
    pred_df['pred_proba'] = ypp
    preds.append(pred_df)
    ri += 1
    if ri % 10 == 0:
        print(f"  retrain {ri}: cur={cur.date()}, n_tr={train_mask.sum()}, n_te={test_mask.sum()}, elapsed={(time.time()-t0)/60:.1f}m")
    cur += pd.Timedelta(days=30)

preds = pd.concat(preds).reset_index(drop=True)
preds.to_parquet(Path.home()/'Desktop/pivot_classifier_preds.parquet')
print(f"\nTotal predictions: {len(preds)}, time: {(time.time()-t0)/60:.1f}m")

print(f"\n=== Precision @ thresholds ===")
for t in [0.30, 0.40, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90]:
    sub = preds[preds['pred_proba'] >= t]
    if len(sub):
        P = sub['label'].mean(); n = len(sub)
        cov = n/len(preds)*100
        print(f"  thr ≥ {t:.2f}: n={n:>4}  P(success)={P*100:.1f}%  cover={cov:.1f}%")

print(f"\n=== By direction at thr ≥ 0.65 ===")
for d in ['high','low']:
    sub = preds[(preds['pred_proba']>=0.65) & (preds['direction']==d)]
    if len(sub):
        print(f"  {d}: n={len(sub)}  P={sub['label'].mean()*100:.1f}%")

# 19 user-targets
user_targets = [
    ('2026-02-08 15:00','high'),('2026-02-12 15:00','low'),('2026-02-15 03:00','high'),
    ('2026-02-21 15:00','high'),('2026-02-24 15:00','low'),('2026-02-25 15:00','high'),
    ('2026-02-28 03:00','low'),('2026-03-04 15:00','high'),('2026-03-08 15:00','low'),
    ('2026-03-22 15:00','low'),('2026-03-29 15:00','low'),('2026-04-17 15:00','high'),
    ('2026-04-22 15:00','high'),('2026-04-27 03:00','high'),('2026-04-29 15:00','low'),
    ('2026-05-06 03:00','high'),('2026-05-08 03:00','low'),('2026-05-14 15:00','high'),
    ('2026-05-23 03:00','low'),
]
print(f"\n=== Predictions on 19 user-labeled targets ===")
for ts_str, sdir in user_targets:
    target_close = (pd.Timestamp(ts_str+'+03:00').tz_convert('UTC') + pd.Timedelta(hours=12))
    target_close = target_close.tz_convert('UTC').astype('datetime64[ns, UTC]') if hasattr(target_close,'astype') else target_close
    sub = preds[(preds['direction']==sdir) & (abs((preds['pivot_close_ts'] - target_close).dt.total_seconds()) < 60)]
    if len(sub):
        r = sub.iloc[0]
        flag = '✓' if r['pred_proba']>=0.5 else '✗'
        print(f"  {ts_str:18s} {sdir:5s}  pred={r['pred_proba']:.3f} {flag}  actual_label={r['label']}")
    else:
        print(f"  {ts_str:18s} {sdir:5s}  NOT in preds (out of WF range)")

print("\n[DONE]")
