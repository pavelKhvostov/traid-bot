"""Phase 3.2 — per-zone binary labels (ranker target).

For each (snapshot × active_zone) pair, emit a row with:
  - group_id (= t0, used by LightGBM ranker for group boundaries)
  - zone meta (element, tf, side, lo, hi, age, mit_count, ...)
  - was_strong (1 if this zone was the day's strong level, else 0)

Joins with per-snapshot labels (build_labels.py output) to determine "was_strong":
  was_strong = 1 iff this zone's (element, tf, lo, hi) matches the
                snapshot's target_zone_* fields.
"""
from __future__ import annotations

import sys
import json
import time
import bisect
import pathlib
import argparse

import pandas as pd

SMC_LIB = pathlib.Path.home() / "smc-lib"
sys.path.insert(0, str(SMC_LIB))


def zone_side(z: dict) -> str:
    return z.get("flipped_direction") or z.get("direction", "long")


def zone_match(z: dict, t_elem: str, t_tf: str, t_lo: float, t_hi: float) -> bool:
    """Match by (element, tf, exact zone bounds)."""
    if z.get("element") != t_elem or z.get("tf") != t_tf:
        return False
    zint = z.get("zone")  # match on INITIAL zone bounds (not active after wick-fill)
    if zint is None:
        return False
    return abs(zint[0] - t_lo) < 1e-6 and abs(zint[1] - t_hi) < 1e-6


def emit_zone_row(snap: dict, z: dict, was_strong: int, price: float) -> dict:
    zint = z.get("active_zone") or z.get("zone")
    init_zint = z.get("zone") or [0.0, 0.0]
    side = zone_side(z)
    z_center = (zint[0] + zint[1]) / 2 if zint else 0.0
    dist_pct = (z_center - price) / price * 100 if price > 0 else 0.0
    return {
        "group_id": snap["t0"],
        "t0_iso_msk": snap["t0_iso_msk"],
        "current_price": price,
        "element": z.get("element", "unknown"),
        "tf": z.get("tf", ""),
        "side": side,
        "is_flip": 1 if z.get("flipped_direction") else 0,
        "zone_lo_init": init_zint[0],
        "zone_hi_init": init_zint[1],
        "zone_lo_active": zint[0] if zint else 0.0,
        "zone_hi_active": zint[1] if zint else 0.0,
        "zone_width_pct": (zint[1] - zint[0]) / price * 100 if (zint and price > 0) else 0.0,
        "dist_pct_signed": dist_pct,
        "dist_pct_abs": abs(dist_pct),
        "age_bars": float(z.get("age_bars", z.get("armed_age_bars", 0))),
        "mit_count": float(z.get("mit_count", 0)),
        "is_inside_zone": 1 if (zint and zint[0] <= price <= zint[1]) else 0,
        "was_strong": was_strong,
    }


def main(batch_dir: pathlib.Path, snap_labels_path: pathlib.Path, out_path: pathlib.Path):
    snap_labels = pd.read_parquet(snap_labels_path)
    snap_labels = snap_labels.set_index("t0")
    print(f"Loaded {len(snap_labels)} per-snapshot labels", file=sys.stderr, flush=True)

    files = sorted(batch_dir.glob("*.json"))
    print(f"Processing {len(files)} snapshots...", file=sys.stderr, flush=True)

    # Lazy-load 1m CSV only if any snapshot is missing current_price
    bars_1m = None
    bars_1m_ts = None

    rows = []
    t0_start = time.time()
    for f in files:
        snap = json.loads(f.read_text())
        t0 = snap["t0"]
        if t0 not in snap_labels.index:
            continue  # snapshot had no forward data (skipped in Phase 3.1)
        target = snap_labels.loc[t0]
        price = snap.get("current_price")
        if price is None or price == 0:
            if bars_1m is None:
                from projects.прометей.detectors.snapshot_builder import load_1m_csv
                bars_1m = load_1m_csv()
                bars_1m_ts = [b[0] for b in bars_1m]
            t0_ms = t0 * 1000
            idx = bisect.bisect_right(bars_1m_ts, t0_ms - 60_000) - 1
            price = bars_1m[idx][4] if idx >= 0 else 0.0
        price = float(price)
        t_elem = target["target_zone_element"]
        t_tf = target["target_zone_tf"]
        t_lo = target["target_zone_lo"]
        t_hi = target["target_zone_hi"]
        has_target = target["target_direction"] != "no_react"

        all_zones = list(snap.get("active_zones", []))
        all_zones += list(snap.get("breakers", []))
        all_zones += list(snap.get("mitigation_blocks", []))

        match_count = 0
        for z in all_zones:
            is_strong = 1 if (has_target and zone_match(z, t_elem, t_tf, t_lo, t_hi)) else 0
            if is_strong:
                match_count += 1
            rows.append(emit_zone_row(snap, z, is_strong, price))
        # Sanity: each snapshot should have at most a few matches (zone deduped by bounds)
        if has_target and match_count == 0:
            print(f"  ⚠ snap {snap['t0_iso_msk']}: target zone not found in active_zones",
                  file=sys.stderr, flush=True)

    df = pd.DataFrame(rows)
    print(
        f"  built {len(df)} (snap × zone) rows in {time.time() - t0_start:.1f}s",
        file=sys.stderr, flush=True,
    )

    # Save
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path, index=False)

    # Distribution report
    n_pos = (df["was_strong"] == 1).sum()
    n_groups = df["group_id"].nunique()
    avg_group_size = len(df) / n_groups if n_groups else 0
    print(
        f"Saved: {out_path}\n"
        f"  shape: {df.shape}\n"
        f"  groups (snapshots): {n_groups}\n"
        f"  avg zones/group: {avg_group_size:.0f}\n"
        f"  positive rate (was_strong=1): {n_pos} ({n_pos / len(df) * 100:.2f}%)\n"
        f"  positives per group:\n"
        + df.groupby("group_id")["was_strong"].sum().describe().round(1).to_string(),
        file=sys.stderr,
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("batch_dir")
    ap.add_argument("--snap_labels", required=True, help="per-snapshot labels parquet")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    batch_dir = pathlib.Path(args.batch_dir).resolve()
    if args.out:
        out = pathlib.Path(args.out)
    else:
        out = SMC_LIB / "projects/прометей/labels" / f"{batch_dir.name}_zone_labels.parquet"
    main(batch_dir, pathlib.Path(args.snap_labels), out)
