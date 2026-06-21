"""C8 batch (CHUNKED): Phase 4 force snapshot per baseline pivot.

Чанкует по 365-дневным окнам, чтобы snapshot_from_events не сканировал
O(N²) events. Каждый чанк:
  - 1m window: [chunk_start - 180d warmup, chunk_end]
  - precompute zone events на этом окне (включая 180d истории для зон)
  - snapshot per pivot из baseline в окне [chunk_start, chunk_end]

Output: ~/Desktop/pred12h_C8_force_6y.parquet
"""
from __future__ import annotations
import sys, time
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path.home() / 'smc-lib'))
sys.path.insert(0, str(Path.home() / 'smc-lib/prediction-algo'))

from data import load_btc_1m
from zones import ALL_TYPES, precompute_zone_events, snapshot_from_events
from force_opinion import (
    SMC_TFS, PROXIMITY_PCT, zone_strength, _classify_bias, TFForce
)

# Load baseline pivots
import importlib.util, io, contextlib
spec = importlib.util.spec_from_file_location(
    "basket", Path.home() / 'smc-lib/scripts/pred12h_basket_c1c2c3.py'
)
mod = importlib.util.module_from_spec(spec); sys.modules['basket'] = mod
with contextlib.redirect_stdout(io.StringIO()):
    spec.loader.exec_module(mod)
pivots = mod.pivots
print(f"[1/3] Baseline pivots loaded: {len(pivots)}", flush=True)

print("[2/3] Loading 1m...", flush=True)
df_1m_full = load_btc_1m()
print(f"  total: {len(df_1m_full):,} bars, range {df_1m_full.index[0]} -> {df_1m_full.index[-1]}", flush=True)

# Chunk by year
CHUNK_DAYS = 365
WARMUP_DAYS = 180  # history needed для zone aging
first_pivot_ts = min(p['pivot_open_ts'] for p in pivots)
last_pivot_ts = max(p['pivot_open_ts'] for p in pivots)
first_ts = pd.Timestamp(first_pivot_ts, unit='ms', tz='UTC')
last_ts = pd.Timestamp(last_pivot_ts, unit='ms', tz='UTC')
print(f"  pivots range: {first_ts} -> {last_ts}", flush=True)

# Build chunk ranges
chunks = []
cur = first_ts.normalize()
while cur < last_ts:
    chunk_end = cur + pd.Timedelta(days=CHUNK_DAYS)
    chunks.append((cur, chunk_end))
    cur = chunk_end
print(f"[3/3] Will process {len(chunks)} chunks of {CHUNK_DAYS} days each (with {WARMUP_DAYS}d warmup)\n", flush=True)

rows = []
t_start = time.time()
for ci, (chunk_start, chunk_end) in enumerate(chunks, 1):
    t_ch = time.time()
    # Pivots in this chunk
    chunk_pivots = [p for p in pivots
                    if chunk_start.value//10**6 <= p['pivot_open_ts'] < chunk_end.value//10**6]
    if not chunk_pivots:
        print(f"[chunk {ci}/{len(chunks)}] {chunk_start.date()}..{chunk_end.date()}: no pivots, skip", flush=True)
        continue

    # 1m window with warmup
    win_start = chunk_start - pd.Timedelta(days=WARMUP_DAYS)
    df_1m = df_1m_full.loc[win_start:chunk_end + pd.Timedelta(hours=24)]
    print(f"[chunk {ci}/{len(chunks)}] {chunk_start.date()}..{chunk_end.date()}: "
          f"{len(chunk_pivots)} pivots, 1m window {len(df_1m):,} bars", flush=True)

    # Precompute
    t_pre = time.time()
    events, resampled = precompute_zone_events(df_1m, tfs=SMC_TFS, types=ALL_TYPES)
    print(f"  precompute: {time.time()-t_pre:.0f}s", flush=True)

    # Snapshot per pivot
    t_snap = time.time()
    for k, p in enumerate(chunk_pivots):
        cut_utc = pd.Timestamp(p["pivot_open_ts"], unit='ms', tz='UTC') + pd.Timedelta(hours=12)
        try:
            zones = snapshot_from_events(events, resampled, df_1m, cut_utc)
        except Exception as e:
            continue
        per_tf = {}
        total_b = total_s = 0.0
        n_wins = 0
        for tf in SMC_TFS:
            tz = [z for z in zones if z.tf == tf and abs(z.distance_pct) < PROXIMITY_PCT]
            b = sum(zone_strength(z) for z in tz if z.direction.lower() == 'long')
            s = sum(zone_strength(z) for z in tz if z.direction.lower() == 'short')
            per_tf[tf] = TFForce(tf=tf, buyer=b, seller=s)
            total_b += b; total_s += s
            if b - s > 0: n_wins += 1
        total_net = total_b - total_s
        bias = _classify_bias(per_tf, total_net, n_wins)
        tf3d = per_tf.get('3d')
        d3_net = (tf3d.buyer - tf3d.seller) if tf3d else 0
        longs_near = sorted([(z, zone_strength(z)) for z in zones
                             if z.direction.lower()=='long' and abs(z.distance_pct)<2.5],
                            key=lambda x: -x[1])
        shorts_near = sorted([(z, zone_strength(z)) for z in zones
                              if z.direction.lower()=='short' and abs(z.distance_pct)<2.5],
                             key=lambda x: -x[1])
        rows.append({
            'pivot_open_ts_ms': p["pivot_open_ts"],
            'direction': p["direction"],
            'confirmed': p["confirmed"],
            'is_imp': p.get("is_imp", False),
            'price': p.get("pivot_high") if p["direction"]=='high' else p.get("pivot_low"),
            'total_net': total_net,
            'total_buyer': total_b,
            'total_seller': total_s,
            'abs_net': abs(total_net),
            'd3_net': d3_net,
            'n_wins': n_wins,
            'bias': bias,
            'top_long_str': longs_near[0][1] if longs_near else 0,
            'top_short_str': shorts_near[0][1] if shorts_near else 0,
            'n_zones': len(zones),
            'force_match': (p["direction"]=='high' and total_net<0) or (p["direction"]=='low' and total_net>0),
        })

    sn_t = time.time() - t_snap
    rate = sn_t / len(chunk_pivots) if chunk_pivots else 0
    elap = time.time() - t_start
    print(f"  snapshot: {sn_t:.0f}s ({rate:.2f}s/pivot)  total elapsed: {elap/60:.1f} min", flush=True)

df_r = pd.DataFrame(rows)
OUT = Path.home() / 'Desktop/pred12h_C8_force_6y.parquet'
df_r.to_parquet(OUT, index=False)
print(f"\n[DONE] saved {len(df_r):,} rows to {OUT}", flush=True)
print(f"Total time: {(time.time()-t_start)/60:.1f} min", flush=True)
print(f"\nQuick stats:")
print(f"  Confirmed: {df_r['confirmed'].sum()}/{len(df_r)} = {df_r['confirmed'].mean()*100:.1f}%")
print(f"  Force-match: {df_r['force_match'].sum()}/{len(df_r)} = {df_r['force_match'].mean()*100:.1f}%")
print(f"  Confirmed AMONG force-match: "
      f"{df_r[df_r['force_match']]['confirmed'].sum()}/{df_r['force_match'].sum()} = "
      f"{df_r[df_r['force_match']]['confirmed'].mean()*100:.1f}%")
