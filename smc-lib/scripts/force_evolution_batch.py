"""Force evolution batch: snapshots @ 6h grid BEFORE каждого baseline pivot.

Для каждого из 1272 baseline pivot's:
  t = pivot.close (= уже в parquet)
  t-6h, t-12h, t-18h, t-24h, t-30h, t-36h (6 prior snapshots)

Output: pivot_id × 7 timesteps × 7 metrics (net, 3d_net, n_wins, bias,
                                              top_long, top_short)

Чанкование 365d + 180d warmup, как обычно.
"""
from __future__ import annotations
import sys, time
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path.home()/'smc-lib'))
sys.path.insert(0, str(Path.home()/'smc-lib/prediction-algo'))

from data import load_btc_1m
from zones import ALL_TYPES, precompute_zone_events, snapshot_from_events
from force_opinion import (
    SMC_TFS, PROXIMITY_PCT, zone_strength, _classify_bias, TFForce
)

import importlib.util, io, contextlib
spec = importlib.util.spec_from_file_location(
    "basket", Path.home()/'smc-lib/scripts/pred12h_basket_c1c2c3.py')
mod = importlib.util.module_from_spec(spec); sys.modules['basket'] = mod
with contextlib.redirect_stdout(io.StringIO()):
    spec.loader.exec_module(mod)
pivots = mod.pivots
print(f"[1/4] {len(pivots)} baseline pivots", flush=True)

df_1m = load_btc_1m()
print(f"[2/4] 1m loaded: {len(df_1m):,}", flush=True)

# Lookback offsets (hours before pivot.close)
OFFSETS_H = [0, -6, -12, -18, -24, -30, -36]  # t, t-6h, ..., t-36h

# Chunk processing
CHUNK_DAYS = 365
WARMUP_DAYS = 180
first_ts = pd.Timestamp(min(p['pivot_open_ts'] for p in pivots), unit='ms', tz='UTC')
last_ts  = pd.Timestamp(max(p['pivot_open_ts'] for p in pivots), unit='ms', tz='UTC')
chunks = []
cur = first_ts.normalize()
while cur < last_ts:
    chunks.append((cur, cur + pd.Timedelta(days=CHUNK_DAYS)))
    cur += pd.Timedelta(days=CHUNK_DAYS)
print(f"[3/4] {len(chunks)} chunks", flush=True)

def snapshot_metrics(events, resampled, df_w, cut_utc):
    try:
        zones = snapshot_from_events(events, resampled, df_w, cut_utc)
    except Exception:
        return None
    per_tf = {}
    total_b = total_s = 0.0
    n_wins = 0
    for tf in SMC_TFS:
        tz = [z for z in zones if z.tf == tf and abs(z.distance_pct) < PROXIMITY_PCT]
        b = sum(zone_strength(z) for z in tz if z.direction.lower()=='long')
        s = sum(zone_strength(z) for z in tz if z.direction.lower()=='short')
        per_tf[tf] = TFForce(tf=tf, buyer=b, seller=s)
        total_b += b; total_s += s
        if b - s > 0: n_wins += 1
    total_net = total_b - total_s
    bias = _classify_bias(per_tf, total_net, n_wins)
    tf3d = per_tf.get('3d')
    d3 = (tf3d.buyer - tf3d.seller) if tf3d else 0
    longs = sorted([(z, zone_strength(z)) for z in zones
                    if z.direction.lower()=='long' and abs(z.distance_pct)<2.5],
                   key=lambda x: -x[1])
    shorts = sorted([(z, zone_strength(z)) for z in zones
                     if z.direction.lower()=='short' and abs(z.distance_pct)<2.5],
                    key=lambda x: -x[1])
    return {
        'net': total_net, 'd3_net': d3, 'n_wins': n_wins, 'bias': bias,
        'top_long': longs[0][1] if longs else 0,
        'top_short': shorts[0][1] if shorts else 0,
    }

rows = []
t_start = time.time()
for ci, (cs, ce) in enumerate(chunks, 1):
    t_ch = time.time()
    chunk_pivots = [p for p in pivots
                    if cs.value//10**6 <= p['pivot_open_ts'] < ce.value//10**6]
    if not chunk_pivots:
        print(f"[chunk {ci}/{len(chunks)}] {cs.date()} skip", flush=True); continue
    win_start = cs - pd.Timedelta(days=WARMUP_DAYS)
    win_end = ce + pd.Timedelta(hours=24)
    df_w = df_1m.loc[win_start:win_end]
    print(f"[chunk {ci}/{len(chunks)}] {cs.date()}..{ce.date()}: {len(chunk_pivots)} pivots, 1m={len(df_w):,}", flush=True)
    tpre = time.time()
    events, resampled = precompute_zone_events(df_w, tfs=SMC_TFS, types=ALL_TYPES)
    print(f"  precompute: {time.time()-tpre:.0f}s", flush=True)
    tsnap = time.time()
    n_snap = 0
    for p in chunk_pivots:
        pivot_close = pd.Timestamp(p['pivot_open_ts'], unit='ms', tz='UTC') + pd.Timedelta(hours=12)
        row = {'pivot_open_ts_ms': p['pivot_open_ts'], 'direction': p['direction'],
               'confirmed': p['confirmed'], 'is_imp': p.get('is_imp', False)}
        for off_h in OFFSETS_H:
            cut_utc = pivot_close + pd.Timedelta(hours=off_h)
            m = snapshot_metrics(events, resampled, df_w, cut_utc)
            if m is None: continue
            for k, v in m.items():
                row[f'{k}_t{"" if off_h==0 else off_h}h'] = v
            n_snap += 1
        rows.append(row)
    print(f"  snapshots: {n_snap}, took {time.time()-tsnap:.0f}s, total elapsed {(time.time()-t_start)/60:.1f}m", flush=True)

df_r = pd.DataFrame(rows)
OUT = Path.home()/'Desktop/force_evolution_6y.parquet'
df_r.to_parquet(OUT, index=False)
print(f"\n[4/4] saved {len(df_r)} rows to {OUT}, total time {(time.time()-t_start)/60:.1f}m")
