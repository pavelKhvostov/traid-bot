"""Cluster Zone v1 (c1) — production cluster generator.

Pipeline:  e12 (events) → s7b (snapshots) → c1 (clusters)

Algorithm:
  1. Load s7b snapshot for anchor
  2. Per active zone: active_center = (last_active_lo + last_active_hi) / 2
  3. Split by 3 SMC classes:
       LIQ   = {fractal}
       INE   = {fvg, i_fvg, marubozu}
       BLOCK = {ob, ob_liq, ob_vc, breaker_block, mitigation_block,
                rdrb, i_rdrb, block_orders, rb}
  4. Per class: sort by active_center ascending
  5. Per class: greedy STRICT bucket  (band +0.2% from first point)
  6. Per class: filter Rule 2 STRICT — ALL 4 TF groups required:
       HTF  ∈ {1D, 12h}
       HMTF ∈ {4h, 6h}
       LMTF ∈ {2h, 1h}
       LTF  ∈ {30m, 15m}

Canon: 2026-06-22
"""
from __future__ import annotations
import argparse, pathlib, sys
import pandas as pd
import numpy as np
from datetime import datetime, timezone

# ─── CANON sets ──────────────────────────────────────────────────────
LIQ_ELEMS   = {'fractal'}
INE_ELEMS   = {'fvg', 'i_fvg', 'marubozu'}
BLOCK_ELEMS = {'ob', 'ob_liq', 'ob_vc', 'breaker_block', 'mitigation_block',
               'rdrb', 'i_rdrb', 'block_orders', 'rb'}
ELEM_TO_CLASS = ({e: 'LIQ'   for e in LIQ_ELEMS}
                  | {e: 'INE'   for e in INE_ELEMS}
                  | {e: 'BLOCK' for e in BLOCK_ELEMS})

TF_GROUPS = {
    'HTF':  {'1D', '12h'},
    'HMTF': {'4h', '6h'},
    'LMTF': {'2h', '1h'},
    'LTF':  {'30m', '15m'},
}
ALL_GROUPS = set(TF_GROUPS.keys())
BAND_PCT = 0.002   # +0.2% movement upward from first point in bucket

DATA = pathlib.Path.home() / "smc-lib/projects/живой-рынок/data"
SNAP_PATH = DATA / "snapshots_v7b_2020-01-01_2026-06-15.parquet"


def tf_group(tf: str) -> str | None:
    for g, tfs in TF_GROUPS.items():
        if tf in tfs:
            return g
    return None


def is_valid_strict(zones_in_cluster) -> bool:
    """STRICT Rule 2: all 4 TF groups must be present."""
    g = {tf_group(z['tf']) for z in zones_in_cluster if tf_group(z['tf'])}
    return g == ALL_GROUPS


def greedy_band_cluster(zones, band_pct=BAND_PCT):
    """Greedy strict bucket from-leftmost on active_center.

    Returns list of clusters; each cluster = list of zone dicts.
    """
    zones = sorted(zones, key=lambda z: z['active_center'])
    clusters = []
    cur = []
    for z in zones:
        if not cur:
            cur = [z]
            continue
        first = cur[0]['active_center']
        if z['active_center'] - first <= band_pct * first:
            cur.append(z)
        else:
            clusters.append(cur)
            cur = [z]
    if cur:
        clusters.append(cur)
    return clusters


def summarize_cluster(c):
    """Build summary dict for one cluster."""
    centers = [z['active_center'] for z in c]
    levels  = [z['level'] for z in c]
    zlos    = [z['zone_lo'] for z in c]
    zhis    = [z['zone_hi'] for z in c]
    last_lo = [z['last_active_lo'] for z in c]
    last_hi = [z['last_active_hi'] for z in c]
    tfs     = sorted({z['tf'] for z in c}, key=lambda t: ['15m','30m','1h','2h','4h','6h','12h','1D'].index(t))
    elems   = sorted({z['element_type'] for z in c})
    grps    = sorted({tf_group(z['tf']) for z in c if tf_group(z['tf'])})
    return {
        'n_zones':         len(c),
        'center_lo':       min(centers),
        'center_hi':       max(centers),
        'center_median':   float(np.median(centers)),
        'union_zone_lo':   min(zlos),
        'union_zone_hi':   max(zhis),
        'union_active_lo': min(last_lo),
        'union_active_hi': max(last_hi),
        'tfs':             tfs,
        'elements':        elems,
        'tf_groups':       grps,
        'zone_ids':        sorted({int(z['zone_id']) for z in c}),
    }


def cluster_zones_for_anchor(snap: pd.DataFrame, anchor_ts: int) -> dict[str, list[dict]]:
    """Compute valid clusters per class for one anchor.

    Returns dict {'LIQ': [...], 'INE': [...], 'BLOCK': [...]}
    Each cluster — dict from summarize_cluster()
    """
    zs = snap[snap['anchor_ts'] == anchor_ts].copy()
    if 'active_center' not in zs.columns:
        zs['active_center'] = (zs['last_active_lo'] + zs['last_active_hi']) / 2.0
    out = {'LIQ': [], 'INE': [], 'BLOCK': []}
    for cls, elems_set in [('LIQ', LIQ_ELEMS), ('INE', INE_ELEMS), ('BLOCK', BLOCK_ELEMS)]:
        sub = zs[zs['element_type'].isin(elems_set)].to_dict('records')
        if not sub:
            continue
        clusters = greedy_band_cluster(sub)
        valid = [c for c in clusters if is_valid_strict(c)]
        for c in valid:
            out[cls].append(summarize_cluster(c))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--anchor", help="UTC datetime YYYY-MM-DDTHH:MM, default = anchor 2026-06-14 04:00 UTC")
    ap.add_argument("--print-each-cluster", action="store_true")
    args = ap.parse_args()

    if args.anchor:
        dt = datetime.fromisoformat(args.anchor).replace(tzinfo=timezone.utc)
    else:
        dt = datetime(2026, 6, 14, 4, 0, tzinfo=timezone.utc)
    anchor_ts = int(dt.timestamp() * 1000)
    print(f"Anchor: {dt} UTC  ({anchor_ts})", file=sys.stderr)

    print(f"Loading {SNAP_PATH.name} ...", file=sys.stderr)
    snap = pd.read_parquet(SNAP_PATH)
    sub = snap[snap['anchor_ts'] == anchor_ts]
    print(f"  zones at anchor: {len(sub)}", file=sys.stderr)

    out = cluster_zones_for_anchor(snap, anchor_ts)

    total = sum(len(v) for v in out.values())
    print(f"\nValid clusters at this anchor:")
    print(f"  LIQ:   {len(out['LIQ'])}")
    print(f"  INE:   {len(out['INE'])}")
    print(f"  BLOCK: {len(out['BLOCK'])}")
    print(f"  ─────────────")
    print(f"  TOTAL: {total}")
    if args.print_each_cluster:
        for cls in ('LIQ', 'INE', 'BLOCK'):
            print(f"\n=== {cls} ({len(out[cls])}) ===")
            for i, c in enumerate(out[cls], 1):
                tfs_str = ','.join(c['tfs'])
                els_str = ','.join(c['elements'])
                print(f"  C{i}: ${c['center_lo']:.0f}-${c['center_hi']:.0f}  "
                      f"n={c['n_zones']}  elements=[{els_str}]  TFs=[{tfs_str}]")


if __name__ == "__main__":
    main()
