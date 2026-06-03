"""C8 batch: Phase 4 force snapshot per baseline pivot (F1∩F2∩F3).

Для каждого из ~1272 12h-баров в baseline (6y BTC):
  - precompute_zone_events на полное окно (один раз)
  - snapshot_from_events на момент close пивот-бара
  - извлечь: total_NET, 3D_NET, n_TFs_buyer_wins, BIAS, top_LONG_str, top_SHORT_str

Output: ~/Desktop/pred12h_C8_force_6y.parquet (~1272 rows × ~15 cols)

Затем grid search C8 поверх parquet (мгновенно).
"""
from __future__ import annotations
import sys
import time
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path.home() / 'smc-lib'))
sys.path.insert(0, str(Path.home() / 'smc-lib/prediction-algo'))

from data import load_btc_1m
from zones import ALL_TYPES, precompute_zone_events, snapshot_from_events
from force_opinion import (
    SMC_TFS, PROXIMITY_PCT, zone_strength, _classify_bias, TFForce
)

import importlib.util
spec = importlib.util.spec_from_file_location(
    "basket", Path.home() / 'smc-lib/scripts/pred12h_basket_c1c2c3.py'
)
mod = importlib.util.module_from_spec(spec); sys.modules['basket'] = mod
import io, contextlib
with contextlib.redirect_stdout(io.StringIO()):
    spec.loader.exec_module(mod)
pivots = mod.pivots
print(f"[1/4] Baseline pivots loaded: {len(pivots)}")

print("[2/4] Loading 1m...")
df_1m = load_btc_1m()
print(f"  total 1m bars: {len(df_1m):,}")
print(f"  range: {df_1m.index[0]} -> {df_1m.index[-1]}")

print("[3/4] Precomputing zone events (one-shot, ~5-15 min)...")
t0 = time.time()
events, resampled = precompute_zone_events(df_1m, tfs=SMC_TFS, types=ALL_TYPES)
print(f"  done in {(time.time()-t0)/60:.1f} min")

print(f"[4/4] Phase 4 snapshot per pivot ({len(pivots)} runs)...")
rows = []
t1 = time.time()
for k, p in enumerate(pivots):
    cut_utc = pd.Timestamp(p["pivot_open_ts"], unit='ms', tz='UTC') + pd.Timedelta(hours=12)
    try:
        zones = snapshot_from_events(events, resampled, df_1m, cut_utc)
    except Exception:
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
    # top zones
    longs_near = sorted([(z, zone_strength(z)) for z in zones
                         if z.direction.lower()=='long' and abs(z.distance_pct)<2.5],
                        key=lambda x: -x[1])
    shorts_near = sorted([(z, zone_strength(z)) for z in zones
                          if z.direction.lower()=='short' and abs(z.distance_pct)<2.5],
                         key=lambda x: -x[1])
    top_long_str = longs_near[0][1] if longs_near else 0
    top_short_str = shorts_near[0][1] if shorts_near else 0
    rows.append({
        'pivot_open_ts_ms': p["pivot_open_ts"],
        'direction': p["direction"],          # 'high' / 'low'
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
        'top_long_str': top_long_str,
        'top_short_str': top_short_str,
        'n_zones': len(zones),
        # C8 helpers
        'force_match': (p["direction"]=='high' and total_net<0) or (p["direction"]=='low' and total_net>0),
    })
    if (k+1) % 200 == 0:
        elapsed = (time.time()-t1)/60
        eta = elapsed / (k+1) * (len(pivots)-k-1)
        print(f"  {k+1}/{len(pivots)}  elapsed={elapsed:.1f}m  ETA={eta:.1f}m")

df_r = pd.DataFrame(rows)
OUT = Path.home() / 'Desktop/pred12h_C8_force_6y.parquet'
df_r.to_parquet(OUT, index=False)
print(f"\n[DONE] saved {len(df_r):,} rows to {OUT}")
print(f"Total time: {(time.time()-t0)/60:.1f} min")
print(f"\nQuick stats:")
print(f"  Confirmed: {df_r['confirmed'].sum()}/{len(df_r)} = {df_r['confirmed'].mean()*100:.1f}%")
print(f"  Force-match: {df_r['force_match'].sum()}/{len(df_r)} = {df_r['force_match'].mean()*100:.1f}%")
print(f"\n  Confirmed AMONG force-match: "
      f"{df_r[df_r['force_match']]['confirmed'].sum()}/{df_r['force_match'].sum()} = "
      f"{df_r[df_r['force_match']]['confirmed'].mean()*100:.1f}%")
