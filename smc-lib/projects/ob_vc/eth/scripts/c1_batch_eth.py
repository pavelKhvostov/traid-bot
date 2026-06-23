"""c1 batch cluster on ETH — для всех 4h anchors из s7b.

Outputs: eth_cluster_log_c1.parquet с колонками:
   anchor_ts, class (LIQ/INE/BLOCK), center_lo, center_hi, n_zones, n_tfs
"""
import sys, time, pathlib
import pandas as pd
import numpy as np
sys.path.insert(0, '/home/vadim/smc-lib/поиск-элементов')
from cluster_zone_c1 import cluster_zones_for_anchor

ETH = pathlib.Path("/home/vadim/smc-lib/projects/ob_vc/eth/data")
SNAP = ETH / "eth_snapshots_s7b.parquet"
OUT  = ETH / "eth_cluster_log_c1.parquet"

print(f"Loading snapshots ...", flush=True)
t0 = time.time()
snap = pd.read_parquet(SNAP)
print(f"  {len(snap):,} rows ({time.time()-t0:.1f}s)", flush=True)

# Take only 4h anchors (canon c1)
all_anchors = sorted(snap['anchor_ts'].unique())
FOUR_H_MS = 4 * 3600 * 1000
anchors_4h = [a for a in all_anchors if (a % FOUR_H_MS) == 0]
print(f"All anchors: {len(all_anchors):,}   4h anchors: {len(anchors_4h):,}", flush=True)

rows = []
t0 = time.time()
for i, a in enumerate(anchors_4h):
    out = cluster_zones_for_anchor(snap, int(a))
    for cls, clusters in out.items():
        for c in clusters:
            rows.append({
                'anchor_ts': int(a),
                'class': cls,
                'n_zones': int(c['n_zones']),
                'n_tfs': int(len(c.get('tfs', []))),
                'center_lo': float(c['center_lo']),
                'center_hi': float(c['center_hi']),
                'center_median': float(c.get('center_median', (c['center_lo']+c['center_hi'])/2)),
                'union_zone_lo': float(c['union_zone_lo']),
                'union_zone_hi': float(c['union_zone_hi']),
                'union_active_lo': float(c.get('union_active_lo', c['union_zone_lo'])),
                'union_active_hi': float(c.get('union_active_hi', c['union_zone_hi'])),
                'n_elements': int(len(c.get('elements', []))),
            })
    if (i+1) % 500 == 0:
        elapsed = time.time() - t0
        rate = (i+1) / elapsed
        eta = (len(anchors_4h) - i - 1) / rate
        print(f"  {i+1:>5}/{len(anchors_4h)}  ({rate:.0f}/s, ETA {eta:.0f}s)  rows={len(rows):,}", flush=True)

df = pd.DataFrame(rows)
df.to_parquet(OUT, compression='zstd', compression_level=9, index=False)
print(f"\nSaved {len(df):,} clusters → {OUT}", flush=True)
print(df['class'].value_counts().to_string())
