"""Per-TF force snapshot ВСЕХ 12h bars 6y BTC + label (i+1 OR i+2 = Williams).

Output:
  ~/Desktop/force_all_bars_per_tf.parquet

  Columns:
    open_ts_ms, close_ts_ms
    buyer_<tf>, seller_<tf>           — суммы по всем zones (вне разбивки по классу)
    top_long_<tf>, top_short_<tf>     — top strength per side per TF
    avg_age_long_<tf>, avg_age_short_<tf>  — взвешенный возраст по strength
    label                              — -1 (FL forming), 0 (none), +1 (FH forming) в i+1 или i+2
    label_at                           — какой бар (i+1 or i+2) confirmed
"""
from __future__ import annotations
import sys, time
from pathlib import Path
import pandas as pd
import numpy as np

sys.path.insert(0, str(Path.home()/'smc-lib'))
sys.path.insert(0, str(Path.home()/'smc-lib/prediction-algo'))

from data import load_btc_1m
from zones import ALL_TYPES, precompute_zone_events, snapshot_from_events
from force_opinion import SMC_TFS, PROXIMITY_PCT, zone_strength, TF_MIN

print("[1/4] Loading 1m...", flush=True)
df_1m_full = load_btc_1m()
print(f"  {len(df_1m_full):,} bars, range {df_1m_full.index[0]} → {df_1m_full.index[-1]}", flush=True)

# 12h bars
agg = {'open':'first','high':'max','low':'min','close':'last','volume':'sum'}
h12 = df_1m_full.resample('12h', label='left', closed='left').agg(agg).dropna()
print(f"  12h bars: {len(h12)}", flush=True)

# Williams n=2 labels: для каждого bar i смотрим i+1 и i+2 на Williams формирование
H = h12['high'].values; L = h12['low'].values
N = len(h12)
labels = np.zeros(N, dtype=int)  # signed: -1 (FL forming), 0 (none), +1 (FH forming)
label_at = np.zeros(N, dtype=int)  # 1 = i+1, 2 = i+2
# Bar k Williams n=2 FH: H[k] > H[k-2], H[k-1], H[k+1], H[k+2]
# Bar k Williams n=2 FL: L[k] < L[k-2], L[k-1], L[k+1], L[k+2]
def is_williams_fh(k):
    if k < 2 or k > N-3: return False
    return H[k] > H[k-1] and H[k] > H[k-2] and H[k] > H[k+1] and H[k] > H[k+2]
def is_williams_fl(k):
    if k < 2 or k > N-3: return False
    return L[k] < L[k-1] and L[k] < L[k-2] and L[k] < L[k+1] and L[k] < L[k+2]

for T_idx in range(N-4):
    # Check i+1 (= T_idx+1)
    if is_williams_fh(T_idx+1):
        labels[T_idx] = 1; label_at[T_idx] = 1
        continue
    if is_williams_fl(T_idx+1):
        labels[T_idx] = -1; label_at[T_idx] = 1
        continue
    # Check i+2 (= T_idx+2)
    if is_williams_fh(T_idx+2):
        labels[T_idx] = 1; label_at[T_idx] = 2
        continue
    if is_williams_fl(T_idx+2):
        labels[T_idx] = -1; label_at[T_idx] = 2

n_pos = (labels == 1).sum(); n_neg = (labels == -1).sum(); n_zero = (labels == 0).sum()
print(f"  Labels: FH={n_pos} ({n_pos/N*100:.1f}%), FL={n_neg} ({n_neg/N*100:.1f}%), none={n_zero} ({n_zero/N*100:.1f}%)", flush=True)

# Chunked Phase 4 force snapshot для каждого 12h bar.close
print("\n[2/4] Force snapshots — chunked 365d windows + 180d warmup...", flush=True)
CHUNK_DAYS = 365
WARMUP_DAYS = 180
first_ts = h12.index[0]
last_ts = h12.index[-1]
chunks = []
cur = first_ts.normalize()
while cur < last_ts:
    chunks.append((cur, cur + pd.Timedelta(days=CHUNK_DAYS)))
    cur += pd.Timedelta(days=CHUNK_DAYS)
print(f"  {len(chunks)} chunks", flush=True)

rows = []
t_start = time.time()
for ci, (cs, ce) in enumerate(chunks, 1):
    chunk_bars = h12.loc[cs:ce - pd.Timedelta(minutes=1)]
    if len(chunk_bars) == 0: continue
    win_start = cs - pd.Timedelta(days=WARMUP_DAYS)
    win_end = ce + pd.Timedelta(hours=24)
    df_w = df_1m_full.loc[win_start:win_end]
    print(f"[chunk {ci}/{len(chunks)}] {cs.date()}..{ce.date()}: {len(chunk_bars)} bars, 1m={len(df_w):,}", flush=True)
    tpre = time.time()
    events, resampled = precompute_zone_events(df_w, tfs=SMC_TFS, types=ALL_TYPES)
    print(f"  precompute: {time.time()-tpre:.0f}s", flush=True)
    tsnap = time.time()

    for ts_open, _ in chunk_bars.iterrows():
        cut_utc = ts_open + pd.Timedelta(hours=12)
        try:
            zones = snapshot_from_events(events, resampled, df_w, cut_utc)
        except Exception:
            continue
        row = {
            'open_ts_ms': int(ts_open.value // 10**6),
            'close_ts_ms': int(cut_utc.value // 10**6),
        }
        # Find label for this bar
        try:
            bar_idx = h12.index.get_loc(ts_open)
            row['label'] = int(labels[bar_idx])
            row['label_at'] = int(label_at[bar_idx])
        except KeyError:
            row['label'] = 0
            row['label_at'] = 0

        for tf in SMC_TFS:
            tz_near = [z for z in zones if z.tf == tf and abs(z.distance_pct) < PROXIMITY_PCT]
            longs = [(z, zone_strength(z)) for z in tz_near if z.direction.lower()=='long']
            shorts = [(z, zone_strength(z)) for z in tz_near if z.direction.lower()=='short']
            buy = sum(s for _, s in longs)
            sel = sum(s for _, s in shorts)
            row[f'buyer_{tf}'] = buy
            row[f'seller_{tf}'] = sel
            # top
            row[f'top_long_{tf}'] = max((s for _, s in longs), default=0)
            row[f'top_short_{tf}'] = max((s for _, s in shorts), default=0)
            # avg age weighted by strength
            tf_min = TF_MIN.get(tf, 60)
            if longs and buy > 0:
                w_age_long = sum(z.age_bars * tf_min/60.0 * s for z, s in longs) / buy
            else:
                w_age_long = 0
            if shorts and sel > 0:
                w_age_short = sum(z.age_bars * tf_min/60.0 * s for z, s in shorts) / sel
            else:
                w_age_short = 0
            row[f'wage_long_{tf}'] = w_age_long
            row[f'wage_short_{tf}'] = w_age_short
        rows.append(row)

    print(f"  snapshot: {time.time()-tsnap:.0f}s, total elapsed {(time.time()-t_start)/60:.1f}m", flush=True)

print(f"\n[3/4] Saving {len(rows)} rows...", flush=True)
df_r = pd.DataFrame(rows)
OUT = Path.home() / 'Desktop/force_all_bars_per_tf.parquet'
df_r.to_parquet(OUT, index=False)
print(f"\n[DONE] saved to {OUT}")
print(f"Total time: {(time.time()-t_start)/60:.1f} min")
print(f"\nLabel distribution: {df_r['label'].value_counts().sort_index().to_dict()}")
