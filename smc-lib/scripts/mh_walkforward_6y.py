"""Walk-forward MH predictions на BTC 6y (2021-05 → 2026-05).

Использует rolling train window 365d (1 год), retrain каждые 30 дней.
Старт OOS с 2021-05-01 (после 1 года warmup).

Output: ~/Desktop/mh_predictions_6y.csv
"""
from __future__ import annotations
import sys, time
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path.home()/'smc-lib/mh-ml'))
from mh_features import build_features
from mh_labels import build_labels
from mh_train import walk_forward

print("[1/4] Loading 1m BTC...", flush=True)
df_1m = pd.read_csv(Path.home()/'traid-bot/data/BTCUSDT_1m_vic_vadim.csv')
df_1m['open_time'] = pd.to_datetime(df_1m['open_time'], utc=True, format='mixed')
df_1m = df_1m.set_index('open_time').sort_index()
print(f"  1m bars: {len(df_1m):,}, range {df_1m.index[0]} → {df_1m.index[-1]}", flush=True)

print("[2/4] Building features (15m base)...", flush=True)
t0 = time.time()
features = build_features(df_1m)
print(f"  features shape: {features.shape}, took {time.time()-t0:.0f}s", flush=True)

print("[3/4] Building labels...", flush=True)
t0 = time.time()
labels = build_labels(df_1m)
print(f"  labels shape: {labels.shape}, took {time.time()-t0:.0f}s", flush=True)

print("[4/4] Walk-forward 2021-05 → 2026-05 (1y train window, monthly retrain)...", flush=True)
test_start = pd.Timestamp('2021-05-01', tz='UTC')
test_end   = features.index[-1]  # latest available

t0 = time.time()
result = walk_forward(
    features=features,
    labels=labels,
    train_window_days=365,    # 1 year rolling (PC2 use 1825=5y but 1y enough)
    retrain_freq_days=30,
    test_start=test_start,
    test_end=test_end,
    n_jobs=-1,
    verbose=True,
)
print(f"\nWalk-forward done in {(time.time()-t0)/60:.1f} min", flush=True)

# Save predictions
df_p = result.predictions  # DataFrame with pred_*h columns
OUT = Path.home() / 'Desktop/mh_predictions_6y.csv'
df_p.to_csv(OUT)
print(f"\n[DONE] saved {len(df_p):,} predictions to {OUT}", flush=True)
print(f"\nPer-horizon metrics:")
for h, m in result.metrics.items():
    print(f"  H={h}h: MAE={m['mae']:.3f}%, RMSE={m['rmse']:.3f}%, dir_acc={m['dir_acc']:.3f}, N={m['n_samples']}")
print(f"\nn_retrains: {result.n_retrains}, train_window: {result.train_window_days}d, retrain freq: {result.retrain_freq_days}d")
