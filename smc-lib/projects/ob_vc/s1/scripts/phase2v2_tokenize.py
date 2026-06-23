"""ob_vc s1 Phase 2 v2 — Token-set features per event (как C3).

Per labeled ob_vc 2h event:
  ▸ Zone tokens — все active zones из s7b на ts_event (max 600)
      [elem(13), tf(8), role(3), direction, distance%, mit_pct, age_d, width%]
  ▸ Cluster tokens — valid clusters c1 на nearest 4h anchor (max 20)
      [class(LIQ/INE/BLOCK), n_zones, tf_count, distance%, width%]
  ▸ Recent events sequence — last 50 e12 events в 24h окне
      [elem, tf, action, role, distance%, dt_ago_h]
  ▸ Self context — 24-type, direction, n_ltf, R%

Output: features_v2.npz + meta_v2.parquet
"""
import sys, time, pathlib
import pandas as pd, numpy as np

S1 = pathlib.Path.home() / "smc-lib/projects/ob_vc/s1"
LBL  = S1 / "data/labels_2h.parquet"
TYPES = pathlib.Path.home() / "smc-lib/projects/ob_vc/data/ob_vc_24types_classified.parquet"
EVENTS = pathlib.Path.home() / "smc-lib/projects/живой-рынок/data/events_v12_2020-01-01_2026-06-15.parquet"
SNAP   = pathlib.Path.home() / "smc-lib/projects/живой-рынок/data/snapshots_v7b_2020-01-01_2026-06-15.parquet"
CLUSTERS = pathlib.Path.home() / "smc-lib/projects/живой-рынок/data/cluster_log_c1.parquet"
OUT_NPZ = S1 / "data/features_v2.npz"
OUT_META = S1 / "data/meta_v2.parquet"

MAX_ZONES = 600
MAX_CLUSTERS = 20
MAX_EVENTS = 50
LOOKBACK_24H = 24 * 3600 * 1000

ELEM_LIST = ['block_orders','breaker_block','fractal','fvg','i_fvg','i_rdrb',
             'marubozu','mitigation_block','ob','ob_liq','ob_vc','rb','rdrb']
ELEM_TO_IDX = {e: i+1 for i, e in enumerate(ELEM_LIST)}  # 0 = pad
TF_LIST = ['15m','30m','1h','2h','4h','6h','12h','1D']
TF_TO_IDX = {t: i+1 for i, t in enumerate(TF_LIST)}
ROLE_TO_IDX = {'LIQ':1, 'INE':2, 'BLOCK':3}
DIR_LIST = ['long','short','bullish','bearish','top','bottom','low','high']
DIR_TO_IDX = {d: i+1 for i, d in enumerate(DIR_LIST)}
ACTION_LIST = ['born','armed','fill_partial','retire','sweep','first_touch','bos','choch','liq_first_touch']
ACTION_TO_IDX = {a: i+1 for i, a in enumerate(ACTION_LIST)}
CLS_TO_IDX = {'LIQ':1, 'INE':2, 'BLOCK':3}

print("Loading data ...", flush=True)
lbl = pd.read_parquet(LBL)
lbl = lbl[lbl['outcome'].isin(['tp','sl','sl_same_bar'])].copy()
print(f"  labels closed: {len(lbl):,}", flush=True)

types = pd.read_parquet(TYPES)
# 24-types mapping
TYPE_LABELS = sorted(types['type_label'].unique())
TYPE_TO_IDX = {t: i+1 for i, t in enumerate(TYPE_LABELS)}
print(f"  24-types: {len(TYPE_LABELS)}", flush=True)

# Merge type label to labels by ts (ob_vc events have unique ts per source_idx)
types_idx = types.set_index('ts_event')['type_label'].to_dict() if 'ts_event' in types.columns else {}
# Fallback: types may use 'ts' col
if not types_idx and 'ts' in types.columns:
    types_idx = types.set_index('ts')['type_label'].to_dict()
print(f"  types map ready: {len(types_idx):,}", flush=True)
lbl['type_label'] = lbl['ts'].map(types_idx).fillna('UNK')
unk = (lbl['type_label']=='UNK').sum()
print(f"  events with UNK type: {unk} (drop)", flush=True)
lbl = lbl[lbl['type_label'] != 'UNK'].copy()
print(f"  events with type: {len(lbl):,}", flush=True)

print("\nLoading e12 events ...", flush=True)
e = pd.read_parquet(EVENTS).sort_values('ts').reset_index(drop=True)
e_ts = e['ts'].values
print(f"  e12 rows: {len(e):,}", flush=True)

print("Loading snapshots s7b ...", flush=True)
snap = pd.read_parquet(SNAP)
snap_anchors = np.array(sorted(snap['anchor_ts'].unique()))
snap_grp = {int(k): g for k, g in snap.groupby('anchor_ts', sort=False)}
print(f"  s7b anchors: {len(snap_anchors):,}", flush=True)

print("Loading c1 clusters ...", flush=True)
clu = pd.read_parquet(CLUSTERS)
clu = clu.rename(columns={'class': 'cls'})   # reserved word fix
clu_anchors = np.array(sorted(clu['anchor_ts'].unique()))
clu_grp = {int(k): g for k, g in clu.groupby('anchor_ts', sort=False)}
print(f"  c1 anchors: {len(clu_anchors):,}", flush=True)

# Sort labels by ts (faster access)
lbl = lbl.sort_values('ts').reset_index(drop=True)
N = len(lbl)
print(f"\nTokenizing {N:,} events ...", flush=True)

# Allocate tensors
Z_ELEM = np.zeros((N, MAX_ZONES), dtype=np.int8)
Z_TF   = np.zeros((N, MAX_ZONES), dtype=np.int8)
Z_ROLE = np.zeros((N, MAX_ZONES), dtype=np.int8)
Z_DIR  = np.zeros((N, MAX_ZONES), dtype=np.int8)
Z_CONT = np.zeros((N, MAX_ZONES, 4), dtype=np.float32)  # [distance%, mit_pct, age_d, width%]
Z_MASK = np.zeros((N, MAX_ZONES), dtype=np.float32)

C_CLS    = np.zeros((N, MAX_CLUSTERS), dtype=np.int8)
C_CONT   = np.zeros((N, MAX_CLUSTERS, 4), dtype=np.float32)  # [n_zones, n_tfs, distance%, width%]
C_MASK   = np.zeros((N, MAX_CLUSTERS), dtype=np.float32)

E_ELEM   = np.zeros((N, MAX_EVENTS), dtype=np.int8)
E_TF     = np.zeros((N, MAX_EVENTS), dtype=np.int8)
E_ACTION = np.zeros((N, MAX_EVENTS), dtype=np.int8)
E_ROLE   = np.zeros((N, MAX_EVENTS), dtype=np.int8)
E_CONT   = np.zeros((N, MAX_EVENTS, 2), dtype=np.float32)  # [distance%, dt_ago_h]
E_MASK   = np.zeros((N, MAX_EVENTS), dtype=np.float32)

S_TYPE     = np.zeros(N, dtype=np.int8)     # 24-type
S_DIR      = np.zeros(N, dtype=np.int8)
S_NLTF     = np.zeros(N, dtype=np.int8)
S_WIDTHPCT = np.zeros(N, dtype=np.float32)

y_hit = np.zeros(N, dtype=np.int8)
y_r   = np.zeros(N, dtype=np.float32)
meta_rows = []

t0 = time.time()
for i, r in enumerate(lbl.itertuples(index=False)):
    ts_ev = int(r.ts)
    entry = float(r.entry)
    R = float(r.R)
    direction = r.direction

    y_hit[i] = int(r.hit_rr1)
    y_r[i]   = float(r.r_result)
    S_TYPE[i] = TYPE_TO_IDX.get(r.type_label, 0)
    S_DIR[i]  = DIR_TO_IDX.get(direction, 0)
    S_NLTF[i] = int(min(r.n_ltf_triggers, 11))
    S_WIDTHPCT[i] = R / entry * 100

    # --- Zones from s7b (nearest 1h anchor ≤ ts_ev) ---
    sidx = snap_anchors.searchsorted(ts_ev, side='right') - 1
    if sidx >= 0:
        sn = snap_grp[int(snap_anchors[sidx])]
        # Sort by abs distance from entry, take top MAX_ZONES
        sn = sn.copy()
        sn['_dist'] = (sn['level'] - entry).abs()
        sn = sn.nsmallest(MAX_ZONES, '_dist').reset_index(drop=True)
        n = len(sn)
        for j, z in enumerate(sn.itertuples(index=False)):
            Z_ELEM[i, j] = ELEM_TO_IDX.get(z.element_type, 0)
            Z_TF[i, j]   = TF_TO_IDX.get(z.tf, 0)
            Z_ROLE[i, j] = ROLE_TO_IDX.get(z.role, 0)
            Z_DIR[i, j]  = DIR_TO_IDX.get(z.direction, 0)
            Z_CONT[i, j, 0] = (z.level - entry) / entry * 100        # distance signed %
            Z_CONT[i, j, 1] = z.mit_pct                              # mit
            Z_CONT[i, j, 2] = z.age_ms / (24 * 3600_000)             # age days
            zw = (z.zone_hi - z.zone_lo) / entry * 100
            Z_CONT[i, j, 3] = zw
        Z_MASK[i, :n] = 1.0

    # --- Clusters from c1 (nearest 4h anchor ≤ ts_ev) ---
    cidx = clu_anchors.searchsorted(ts_ev, side='right') - 1
    if cidx >= 0:
        cl = clu_grp[int(clu_anchors[cidx])]
        cl = cl.copy()
        cl['_d'] = ((cl['center_lo'] + cl['center_hi'])/2 - entry).abs()
        cl = cl.nsmallest(MAX_CLUSTERS, '_d').reset_index(drop=True)
        for j, c in enumerate(cl.itertuples(index=False)):
            C_CLS[i, j] = CLS_TO_IDX.get(c.cls, 0)
            center = (c.center_lo + c.center_hi) / 2
            width = (c.union_zone_hi - c.union_zone_lo) / entry * 100
            C_CONT[i, j, 0] = c.n_zones / 10.0
            C_CONT[i, j, 1] = c.n_tfs / 8.0
            C_CONT[i, j, 2] = (center - entry) / entry * 100
            C_CONT[i, j, 3] = width
        C_MASK[i, :len(cl)] = 1.0

    # --- Recent e12 events ---
    lo_ts = ts_ev - LOOKBACK_24H
    lo_idx = e_ts.searchsorted(lo_ts, side='left')
    hi_idx = e_ts.searchsorted(ts_ev, side='left')
    rec = e.iloc[lo_idx:hi_idx]
    if len(rec) > MAX_EVENTS:
        # take most recent
        rec = rec.iloc[-MAX_EVENTS:]
    for j, ev in enumerate(rec.itertuples(index=False)):
        E_ELEM[i, j]   = ELEM_TO_IDX.get(ev.element_type, 0)
        E_TF[i, j]     = TF_TO_IDX.get(ev.tf, 0)
        E_ACTION[i, j] = ACTION_TO_IDX.get(ev.action, 0)
        E_ROLE[i, j]   = ROLE_TO_IDX.get(ev.role, 0)
        E_CONT[i, j, 0] = (ev.level - entry) / entry * 100
        E_CONT[i, j, 1] = (ts_ev - ev.ts) / 3600_000.0
    E_MASK[i, :len(rec)] = 1.0

    meta_rows.append({'ts': ts_ev, 'type_label': r.type_label,
                      'direction': direction, 'hit_rr1': int(r.hit_rr1),
                      'r_result': float(r.r_result), 'entry': entry, 'R': R})

    if (i+1) % 500 == 0:
        elapsed = time.time() - t0
        rate = (i+1) / elapsed
        eta = (N - i - 1) / rate
        print(f"  {i+1:>4}/{N}  ({rate:.0f}/s, ETA {eta:.0f}s)", flush=True)

meta = pd.DataFrame(meta_rows)
meta.to_parquet(OUT_META, compression='zstd', compression_level=9, index=False)
np.savez_compressed(OUT_NPZ,
    Z_ELEM=Z_ELEM, Z_TF=Z_TF, Z_ROLE=Z_ROLE, Z_DIR=Z_DIR, Z_CONT=Z_CONT, Z_MASK=Z_MASK,
    C_CLS=C_CLS, C_CONT=C_CONT, C_MASK=C_MASK,
    E_ELEM=E_ELEM, E_TF=E_TF, E_ACTION=E_ACTION, E_ROLE=E_ROLE, E_CONT=E_CONT, E_MASK=E_MASK,
    S_TYPE=S_TYPE, S_DIR=S_DIR, S_NLTF=S_NLTF, S_WIDTHPCT=S_WIDTHPCT,
    y_hit=y_hit, y_r=y_r,
    type_labels=np.array(TYPE_LABELS), elem_list=np.array(ELEM_LIST),
    tf_list=np.array(TF_LIST), action_list=np.array(ACTION_LIST))
import os
print(f"\n✓ Saved {N:,} events")
print(f"  features:  {OUT_NPZ}  ({os.path.getsize(OUT_NPZ)/1024/1024:.1f} MB)")
print(f"  meta:      {OUT_META}")
print(f"  Elapsed:   {time.time()-t0:.1f}s")
print(f"\nTarget distribution:")
print(f"  hit_rr1=1: {int(y_hit.sum())} ({y_hit.mean()*100:.1f}%)")
print(f"  hit_rr1=0: {int(N - y_hit.sum())}")
print(f"\n24-type distribution (top 8):")
unique, counts = np.unique(S_TYPE[S_TYPE>0], return_counts=True)
order = np.argsort(-counts)[:8]
for idx in order:
    t_id = unique[idx]
    print(f"  {TYPE_LABELS[t_id-1]:<25}{counts[idx]}")
