"""ob_vc s1 Phase 2 — Feature engineering per labeled event.

Per labeled 2h ob_vc event:
  CONTEXT features (НА момент ts_event, NO LOOKAHEAD):

  [1] Cluster c1 context (взять nearest 4h anchor ≤ ts_event):
      - n_LIQ_clusters, n_INE_clusters, n_BLOCK_clusters (active valid)
      - distance to nearest LIQ/INE/BLOCK cluster (price-direction-aware)
      - cluster cover above / below entry price

  [2] Snapshot s7b context (взять nearest 1h anchor):
      - active zones count per role (LIQ/INE/BLOCK)
      - distance to nearest fractal LIQ above/below
      - count zones within ±0.5% от entry

  [3] Recent events e12 (lookback 24h):
      - count sweep events (any tf)
      - count fill_partial / retire events
      - last fractal sweep distance / time

  [4] Self attributes:
      - n_ltf_triggers (1, 2, 3+)
      - direction
      - R% (zone width)

Output: ~/smc-lib/projects/ob_vc/s1/data/features_2h.parquet
"""
import pathlib, time, sys
import pandas as pd, numpy as np

DATA = pathlib.Path.home() / "smc-lib/projects/живой-рынок/data"
S1_DATA = pathlib.Path.home() / "smc-lib/projects/ob_vc/s1/data"
LABELS = S1_DATA / "labels_2h.parquet"
EVENTS = DATA / "events_v12_2020-01-01_2026-06-15.parquet"
SNAP   = DATA / "snapshots_v7b_2020-01-01_2026-06-15.parquet"
CLUSTERS = DATA / "cluster_log_c1.parquet"
OUT    = S1_DATA / "features_2h.parquet"

FOUR_H_MS = 4 * 3600 * 1000
ONE_H_MS  = 3600 * 1000
LOOKBACK_24H = 24 * 3600 * 1000

print("Loading labels ...", flush=True)
lbl = pd.read_parquet(LABELS)
lbl = lbl[lbl['outcome'].isin(['tp','sl','sl_same_bar'])].copy()  # only closed
print(f"  closed events: {len(lbl):,}", flush=True)

print("Loading events e12 ...", flush=True)
e = pd.read_parquet(EVENTS)
# Pre-index by ts for fast scan
e_sorted = e.sort_values('ts').reset_index(drop=True)
e_ts = e_sorted['ts'].values

print("Loading snapshots s7b ...", flush=True)
snap = pd.read_parquet(SNAP)
# Index by anchor_ts for fast lookup
snap_anchors = sorted(snap['anchor_ts'].unique())
snap_grp = {int(k): g for k, g in snap.groupby('anchor_ts', sort=False)}

print("Loading clusters c1 ...", flush=True)
clu = pd.read_parquet(CLUSTERS)
clu_anchors = sorted(clu['anchor_ts'].unique())
clu_grp = {int(k): g for k, g in clu.groupby('anchor_ts', sort=False)}

print(f"\nExtracting features for {len(lbl):,} events ...", flush=True)
t0 = time.time()
features = []
clu_anchors_arr = np.array(clu_anchors)
snap_anchors_arr = np.array(snap_anchors)

for i, r in enumerate(lbl.itertuples(index=False)):
    ts_event = int(r.ts)
    entry = float(r.entry)
    direction = r.direction

    # Find nearest c1 anchor (4h) ≤ ts_event
    idx = clu_anchors_arr.searchsorted(ts_event, side='right') - 1
    if idx < 0:
        continue
    c1_ts = int(clu_anchors_arr[idx])
    cl = clu_grp.get(c1_ts)
    feat = {'ts': ts_event, 'direction': direction, 'entry': entry,
            'n_ltf_triggers': int(r.n_ltf_triggers),
            'hit_rr1': int(r.hit_rr1), 'r_result': float(r.r_result),
            'R': float(r.R), 'zone_width_pct': float(r.R / entry * 100)}

    # Cluster features
    if cl is not None and len(cl):
        for cls in ('LIQ','INE','BLOCK'):
            sub = cl[cl['class'] == cls]
            feat[f'n_{cls}_clusters'] = len(sub)
            if len(sub):
                centers = (sub['center_lo'] + sub['center_hi']) / 2
                d = centers - entry
                above = d[d > 0]
                below = d[d < 0]
                feat[f'd_{cls}_above_pct'] = float(above.min() / entry * 100) if len(above) else 99.0
                feat[f'd_{cls}_below_pct'] = float(-below.max() / entry * 100) if len(below) else 99.0
                feat[f'{cls}_total_zones'] = int(sub['n_zones'].sum())
            else:
                feat[f'd_{cls}_above_pct'] = 99.0
                feat[f'd_{cls}_below_pct'] = 99.0
                feat[f'{cls}_total_zones'] = 0
    else:
        for cls in ('LIQ','INE','BLOCK'):
            feat[f'n_{cls}_clusters'] = 0
            feat[f'd_{cls}_above_pct'] = 99.0
            feat[f'd_{cls}_below_pct'] = 99.0
            feat[f'{cls}_total_zones'] = 0

    # Snapshot features (nearest 1h anchor ≤ ts_event)
    sidx = snap_anchors_arr.searchsorted(ts_event, side='right') - 1
    if sidx >= 0:
        sn = snap_grp[int(snap_anchors_arr[sidx])]
        feat['snap_n_LIQ'] = int((sn['role']=='LIQ').sum())
        feat['snap_n_INE'] = int((sn['role']=='INE').sum())
        feat['snap_n_BLOCK'] = int((sn['role']=='BLOCK').sum())
        # zones near entry ±0.5%
        near_mask = (sn['level'] >= entry*0.995) & (sn['level'] <= entry*1.005)
        feat['snap_zones_near'] = int(near_mask.sum())
        # nearest fractal above/below
        fr = sn[sn['element_type']=='fractal']
        if len(fr):
            d = fr['level'].values - entry
            above_d = d[d > 0]
            below_d = d[d < 0]
            feat['frac_above_pct'] = float(above_d.min() / entry * 100) if len(above_d) else 99.0
            feat['frac_below_pct'] = float(-below_d.max() / entry * 100) if len(below_d) else 99.0
        else:
            feat['frac_above_pct'] = 99.0
            feat['frac_below_pct'] = 99.0
    else:
        for k in ['snap_n_LIQ','snap_n_INE','snap_n_BLOCK','snap_zones_near']:
            feat[k] = 0
        feat['frac_above_pct'] = 99.0
        feat['frac_below_pct'] = 99.0

    # Recent events e12 (lookback 24h)
    lo_ts = ts_event - LOOKBACK_24H
    lo_idx = e_ts.searchsorted(lo_ts, side='left')
    hi_idx = e_ts.searchsorted(ts_event, side='left')
    recent = e_sorted.iloc[lo_idx:hi_idx]
    feat['rec_n_events'] = len(recent)
    feat['rec_n_sweep'] = int((recent['action']=='sweep').sum())
    feat['rec_n_fill_partial'] = int((recent['action']=='fill_partial').sum())
    feat['rec_n_retire'] = int((recent['action']=='retire').sum())
    feat['rec_n_LIQ_sweep'] = int(((recent['action']=='sweep') & (recent['role']=='LIQ')).sum())
    feat['rec_n_BLOCK_fill'] = int(((recent['action']=='fill_partial') & (recent['role']=='BLOCK')).sum())
    feat['rec_n_INE_fill'] = int(((recent['action']=='fill_partial') & (recent['role']=='INE')).sum())

    features.append(feat)
    if (i+1) % 500 == 0:
        elapsed = time.time() - t0
        rate = (i+1) / elapsed
        eta = (len(lbl) - i - 1) / rate
        print(f"  {i+1:>4}/{len(lbl)}  ({rate:.0f}/s, ETA {eta:.0f}s)", flush=True)

df = pd.DataFrame(features)
df.to_parquet(OUT, compression='zstd', compression_level=9, index=False)
print(f"\nSaved {len(df):,} rows → {OUT}")
print(f"Features: {df.shape[1]-4} (excl ts/dir/hit_rr1/r_result)")
print()
print("=== Target distribution ===")
print(f"  hit_RR_2 == 1: {df['hit_rr1'].sum():,} ({df['hit_rr1'].mean()*100:.1f}%)")
print(f"  hit_RR_2 == 0: {(1-df['hit_rr1']).sum():,}")
print()
print("=== Sample feature mean per outcome ===")
sample_cols = ['n_BLOCK_clusters','n_LIQ_clusters','n_INE_clusters','rec_n_LIQ_sweep','snap_zones_near','zone_width_pct']
print(df.groupby('hit_rr1')[sample_cols].mean().round(2).to_string())
