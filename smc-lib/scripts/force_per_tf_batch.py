"""Snapshot per-TF buyer/seller force на каждом из 1272 baseline pivots.

Extends C8_force_batch — сохраняем per-TF breakdown (9 ТФ × buyer/seller = 18 cols)
вместо только агрегата. Используем для empirical calibration TF_WEIGHT.

Output: ~/Desktop/force_per_tf_6y.parquet
  Columns: pivot_open_ts_ms, direction, confirmed, is_imp,
           buyer_1h, seller_1h, buyer_2h, seller_2h, ..., buyer_3d, seller_3d
"""
from __future__ import annotations
import sys, time
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path.home()/'smc-lib'))
sys.path.insert(0, str(Path.home()/'smc-lib/prediction-algo'))

from data import load_btc_1m
from zones import ALL_TYPES, precompute_zone_events, snapshot_from_events
from force_opinion import SMC_TFS, PROXIMITY_PCT, zone_strength

import importlib.util, io, contextlib
spec = importlib.util.spec_from_file_location(
    "basket", Path.home()/'smc-lib/scripts/pred12h_basket_c1c2c3.py')
mod = importlib.util.module_from_spec(spec); sys.modules['basket'] = mod
with contextlib.redirect_stdout(io.StringIO()):
    spec.loader.exec_module(mod)
pivots = mod.pivots
print(f"[1/3] {len(pivots)} baseline pivots", flush=True)

df_1m_full = load_btc_1m()
print(f"[2/3] 1m: {len(df_1m_full):,} bars", flush=True)

CHUNK_DAYS = 365
WARMUP_DAYS = 180
first_ts = pd.Timestamp(min(p['pivot_open_ts'] for p in pivots), unit='ms', tz='UTC')
last_ts = pd.Timestamp(max(p['pivot_open_ts'] for p in pivots), unit='ms', tz='UTC')
chunks = []
cur = first_ts.normalize()
while cur < last_ts:
    chunks.append((cur, cur + pd.Timedelta(days=CHUNK_DAYS)))
    cur += pd.Timedelta(days=CHUNK_DAYS)
print(f"[3/3] {len(chunks)} chunks", flush=True)

rows = []
t_start = time.time()
for ci, (cs, ce) in enumerate(chunks, 1):
    chunk_pivots = [p for p in pivots
                    if cs.value//10**6 <= p['pivot_open_ts'] < ce.value//10**6]
    if not chunk_pivots: continue
    win_start = cs - pd.Timedelta(days=WARMUP_DAYS)
    win_end = ce + pd.Timedelta(hours=24)
    df_w = df_1m_full.loc[win_start:win_end]
    print(f"[chunk {ci}/{len(chunks)}] {cs.date()}..{ce.date()}: {len(chunk_pivots)} pivots", flush=True)
    tpre = time.time()
    events, resampled = precompute_zone_events(df_w, tfs=SMC_TFS, types=ALL_TYPES)
    print(f"  precompute {time.time()-tpre:.0f}s", flush=True)
    tsnap = time.time()
    for p in chunk_pivots:
        cut_utc = pd.Timestamp(p['pivot_open_ts'], unit='ms', tz='UTC') + pd.Timedelta(hours=12)
        try:
            zones = snapshot_from_events(events, resampled, df_w, cut_utc)
        except Exception: continue
        row = {
            'pivot_open_ts_ms': p['pivot_open_ts'],
            'direction': p['direction'],
            'confirmed': p['confirmed'],
            'is_imp': p.get('is_imp', False),
        }
        for tf in SMC_TFS:
            tz = [z for z in zones if z.tf == tf and abs(z.distance_pct) < PROXIMITY_PCT]
            b = sum(zone_strength(z) for z in tz if z.direction.lower()=='long')
            s = sum(zone_strength(z) for z in tz if z.direction.lower()=='short')
            row[f'buyer_{tf}'] = b
            row[f'seller_{tf}'] = s
            # also count of zones for diagnostic
            row[f'n_long_{tf}'] = sum(1 for z in tz if z.direction.lower()=='long')
            row[f'n_short_{tf}'] = sum(1 for z in tz if z.direction.lower()=='short')
        rows.append(row)
    print(f"  snapshot {time.time()-tsnap:.0f}s, total {(time.time()-t_start)/60:.1f}m", flush=True)

df_r = pd.DataFrame(rows)
OUT = Path.home()/'Desktop/force_per_tf_6y.parquet'
df_r.to_parquet(OUT, index=False)
print(f"\n[DONE] {len(df_r)} rows → {OUT}, time {(time.time()-t_start)/60:.1f}m", flush=True)
