"""Прямые cumulative MH-features (без ML) → P(W) тест на baseline pivot'ах.

Hypothesis: топ feature importance из PC2 показал `bars_since_mf_zero_32h`,
`cascade_mf_zero_mean_h` — это cumulative «время выше/ниже уровня».
Можно ли использовать как rule напрямую, без HGBR модели?
"""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd
import numpy as np

sys.path.insert(0, str(Path.home()/'smc-lib/mh-ml'))
from mh_features_v2 import build_features_v2 as build_features

print("[1/3] Loading 1m BTC...", flush=True)
df_1m = pd.read_csv(Path.home()/'traid-bot/data/BTCUSDT_1m_vic_vadim.csv')
df_1m['open_time'] = pd.to_datetime(df_1m['open_time'], utc=True, format='mixed')
df_1m = df_1m.set_index('open_time').sort_index()
print(f"  1m bars: {len(df_1m):,}")

print("[2/3] Building MH features (15m base, 165 columns)...", flush=True)
import time
t0 = time.time()
feat = build_features(df_1m)
print(f"  shape: {feat.shape}, took {time.time()-t0:.0f}s")

# Top cumulative features из PC2 importance
TOP_CUM = [
    'bars_since_mf_zero_32h',
    'bars_since_mf_zero_16h',
    'bars_since_mf_zero_8h',
    'bars_since_mf_zero_2h',
    'bars_since_bw2_ob_enter_8h',
    'bars_since_bw2_os_enter_1h',
    'bars_since_rsi_os_exit_2h',
    'bars_since_rsi_ob_exit_1h',
    'bars_since_stc_ob_exit_2h',
    'cascade_mf_zero_mean_h',
    'cascade_bw2_zero_mean_h',
    'cascade_bw2_bull_freshness_h',
    'cross_mf_sma14_8h',
    'roll_std_mf_50_1h',
]
avail = [c for c in TOP_CUM if c in feat.columns]
print(f"\n  Available top-cumulative features: {len(avail)}/{len(TOP_CUM)}")
for c in TOP_CUM:
    if c not in feat.columns: print(f"    MISSING: {c}")

# Load baseline
print("\n[3/3] Lookup features at baseline pivot.close, stratify P(W)...")
base = pd.read_parquet(Path.home()/'Desktop/pred12h_baseline_c1c7.parquet')
base['pivot_close_ts'] = pd.to_datetime(base['pivot_open_ts_ms'], unit='ms', utc=True) + pd.Timedelta(hours=12)

# Use merge_asof for feature lookup at pivot.close
feat_idx = feat.copy()
feat_idx['ts'] = feat_idx.index
feat_idx = feat_idx.reset_index(drop=True)
# Normalize tz
feat_idx['ts'] = pd.to_datetime(feat_idx['ts'], utc=True).astype('datetime64[ns, UTC]')

base = base.sort_values('pivot_close_ts').reset_index(drop=True)
base['pivot_close_ts'] = pd.to_datetime(base['pivot_close_ts'], utc=True).astype('datetime64[ns, UTC]')

merged = pd.merge_asof(
    base[['pivot_open_ts_ms','direction','confirmed','is_imp','in_basket','pivot_close_ts']],
    feat_idx[['ts'] + avail].sort_values('ts'),
    left_on='pivot_close_ts', right_on='ts',
    direction='backward',
)
print(f"  Pivots with MH features: {merged[avail[0]].notna().sum()}/{len(merged)}")

# Stratified P(W) for top cumulative features
def stratify(name, vals):
    print(f"\n--- {name} ---")
    if vals.isna().all():
        print("  all NaN"); return
    # Quantile bins
    quantiles = [0, 0.2, 0.4, 0.6, 0.8, 1.0]
    bins = vals.quantile(quantiles).unique()
    if len(bins) < 3:
        print(f"  too few unique values"); return
    cat = pd.cut(vals, bins=bins, labels=[f'q{i+1}' for i in range(len(bins)-1)], include_lowest=True)
    df = pd.DataFrame({'val':vals, 'q':cat, 'conf':merged['confirmed'], 'dir':merged['direction'], 'in_bsk':merged['in_basket']})
    for q in df['q'].dropna().unique().sort_values():
        sub = df[df['q']==q]
        n = len(sub); c = sub['conf'].sum(); pw = c/n*100 if n else 0
        # by direction
        fh = sub[sub['dir']=='high']; fl = sub[sub['dir']=='low']
        pw_fh = fh['conf'].sum()/len(fh)*100 if len(fh) else 0
        pw_fl = fl['conf'].sum()/len(fl)*100 if len(fl) else 0
        in_b = sub['in_bsk'].sum()
        print(f"  {q:>3s}  range={sub['val'].min():>6.1f}..{sub['val'].max():>6.1f}  n={n:>3d}  P(W)={pw:5.1f}%  FH={pw_fh:.1f}% FL={pw_fl:.1f}%  bsk={in_b}")

for f in avail[:8]:
    stratify(f, merged[f])

# Save merged for further analysis
OUT = Path.home() / 'Desktop/pred12h_mh_cumulative.parquet'
merged.to_parquet(OUT, index=False)
print(f"\n[DONE] merged saved to {OUT}")
