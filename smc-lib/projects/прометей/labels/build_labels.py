"""Прометей Phase 3 — target labeling.

Per spec.md §3 + user lock (2026-06-15):
  Q1: Strong level = Option A (nearest reaction zone)
  Q2: Direction = ternary (LONG / SHORT / NO)

For each snapshot (cutoff t0), looks forward [t0, t0 + HORIZON_HRS] on 1m bars
and identifies the FIRST active zone that produced a "reaction":

  Touch (canon §2 model 1 for zonal elements):
      bar.low ≤ zone_hi  AND  bar.high ≥ zone_lo

  Reaction:
    LONG zone (support)  → high after touch ≥ touch_low × (1 + MAG_PCT)
                           within REACT_HRS of touch
    SHORT zone (resist)  → low after touch ≤ touch_high × (1 - MAG_PCT)
                           within REACT_HRS of touch

  Strong level = zone with EARLIEST touch_ts that subsequently reacted.

  Q2 direction:
    "long"  = strong-level was LONG side (price rejected up)
    "short" = strong-level was SHORT side (price rejected down)
    "no_react" = no zone touched OR no touched zone reacted within horizon

Output per snapshot:
  - target_direction: "long" | "short" | "no_react"
  - target_magnitude_pct: max favorable move from touch point (0 if no_react)
  - touch_time_hr_from_t0: when zone was touched (NaN if no_react)
  - react_time_hr_from_t0: when reaction confirmed (NaN if no_react)
  - target_zone_element / target_zone_tf / target_zone_lo / target_zone_hi
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

from projects.прометей.detectors.snapshot_builder import load_1m_csv  # noqa: E402


# ─── Defaults locked in Phase 3.0 ───────────────────────────────────────────
HORIZON_HRS = 24
REACT_HRS = 6
MAG_PCT = 1.0  # %, minimum favorable move from touch to count as reaction
MS = 60_000
HORIZON_MS = HORIZON_HRS * 3600 * 1000
REACT_MS = REACT_HRS * 3600 * 1000


def zone_side(z: dict) -> str:
    """Return 'long' (support) or 'short' (resistance) after applying flip."""
    flip = z.get("flipped_direction")
    if flip is not None:
        return flip
    return z.get("direction", "long")


def find_first_reaction(
    snap: dict,
    bars_1m: list[tuple[int, float, float, float, float]],
    bars_1m_ts: list[int],
) -> dict:
    """Walk forward [t0, t0+24h] on 1m bars; find first zone that reacted.

    Returns label dict (see module docstring).
    """
    t0_ms = snap["t0"] * 1000
    horizon_end = t0_ms + HORIZON_MS

    # Slice 1m bars in [t0, horizon_end]
    start_idx = bisect.bisect_left(bars_1m_ts, t0_ms)
    end_idx = bisect.bisect_left(bars_1m_ts, horizon_end)
    fwd_bars = bars_1m[start_idx:end_idx]
    fwd_ts = bars_1m_ts[start_idx:end_idx]
    if not fwd_bars:
        return _no_react_label()

    # Collect all candidate active zones from snapshot (zones + flip-zones)
    zones: list[dict] = []
    zones.extend(snap.get("active_zones", []))
    zones.extend(snap.get("breakers", []))
    zones.extend(snap.get("mitigation_blocks", []))
    if not zones:
        return _no_react_label()

    # For each zone, find first touch bar in window
    best: dict | None = None
    best_touch_ts: int | None = None
    for z in zones:
        z_int = z.get("active_zone") or z.get("zone")
        if z_int is None:
            continue
        zlo, zhi = z_int
        side = zone_side(z)
        # Find first bar where bar.low ≤ zhi AND bar.high ≥ zlo
        touch_idx: int | None = None
        for j, (ts, _o, h, l, _c) in enumerate(fwd_bars):
            if l <= zhi and h >= zlo:
                touch_idx = j
                break
        if touch_idx is None:
            continue

        # Check reaction within REACT_HRS after touch
        touch_ts = fwd_ts[touch_idx]
        touch_bar = fwd_bars[touch_idx]
        react_end_ts = touch_ts + REACT_MS
        react_end_idx = bisect.bisect_right(fwd_ts, react_end_ts)
        react_window = fwd_bars[touch_idx + 1: react_end_idx]
        if not react_window:
            continue

        if side == "long":
            # support: anchor = bar low at touch (closest to zone bottom)
            anchor = min(touch_bar[3], zlo)
            target_price = anchor * (1 + MAG_PCT / 100)
            max_high = max(b[2] for b in react_window)
            if max_high >= target_price:
                # Reaction!
                react_idx = next(
                    (i for i, b in enumerate(react_window) if b[2] >= target_price),
                    0,
                )
                react_ts = fwd_ts[touch_idx + 1 + react_idx]
                mag_pct = (max_high - anchor) / anchor * 100
                cand = {
                    "touch_ts": touch_ts,
                    "react_ts": react_ts,
                    "side": "long",
                    "mag_pct": mag_pct,
                    "zone": z,
                }
                if best_touch_ts is None or touch_ts < best_touch_ts:
                    best = cand
                    best_touch_ts = touch_ts
        else:  # short
            anchor = max(touch_bar[2], zhi)
            target_price = anchor * (1 - MAG_PCT / 100)
            min_low = min(b[3] for b in react_window)
            if min_low <= target_price:
                react_idx = next(
                    (i for i, b in enumerate(react_window) if b[3] <= target_price),
                    0,
                )
                react_ts = fwd_ts[touch_idx + 1 + react_idx]
                mag_pct = (anchor - min_low) / anchor * 100
                cand = {
                    "touch_ts": touch_ts,
                    "react_ts": react_ts,
                    "side": "short",
                    "mag_pct": mag_pct,
                    "zone": z,
                }
                if best_touch_ts is None or touch_ts < best_touch_ts:
                    best = cand
                    best_touch_ts = touch_ts

    if best is None:
        return _no_react_label()

    z = best["zone"]
    # Identity bounds = INITIAL zone (immutable across mitigation). Used for matching.
    init_int = z.get("zone") or [0.0, 0.0]
    active_int = z.get("active_zone") or init_int
    return {
        "target_direction": best["side"],
        "target_magnitude_pct": best["mag_pct"],
        "touch_time_hr_from_t0": (best["touch_ts"] - t0_ms) / 3600000,
        "react_time_hr_from_t0": (best["react_ts"] - t0_ms) / 3600000,
        "target_zone_element": z.get("element", "unknown"),
        "target_zone_tf": z.get("tf", "unknown"),
        "target_zone_lo": init_int[0],          # initial (identity)
        "target_zone_hi": init_int[1],
        "target_zone_active_lo": active_int[0], # active (at t0)
        "target_zone_active_hi": active_int[1],
        "target_zone_age_at_t0": float(z.get("age_bars", z.get("armed_age_bars", 0))),
        "target_zone_mit_count": float(z.get("mit_count", 0)),
    }


def _no_react_label() -> dict:
    return {
        "target_direction": "no_react",
        "target_magnitude_pct": 0.0,
        "touch_time_hr_from_t0": float("nan"),
        "react_time_hr_from_t0": float("nan"),
        "target_zone_element": "",
        "target_zone_tf": "",
        "target_zone_lo": 0.0,
        "target_zone_hi": 0.0,
        "target_zone_active_lo": 0.0,
        "target_zone_active_hi": 0.0,
        "target_zone_age_at_t0": 0.0,
        "target_zone_mit_count": 0.0,
    }


def main(batch_dir: pathlib.Path, out_path: pathlib.Path):
    files = sorted(batch_dir.glob("*.json"))
    if not files:
        print(f"No snapshots in {batch_dir}", file=sys.stderr)
        sys.exit(1)
    print(f"Labeling {len(files)} snapshots from {batch_dir}", file=sys.stderr, flush=True)
    print(
        f"  config: HORIZON_HRS={HORIZON_HRS}, REACT_HRS={REACT_HRS}, MAG_PCT={MAG_PCT}",
        file=sys.stderr, flush=True,
    )

    bars_1m = load_1m_csv()
    bars_1m_ts = [b[0] for b in bars_1m]
    t_max = bars_1m_ts[-1]

    rows = []
    t0 = time.time()
    for f in files:
        snap = json.loads(f.read_text())
        t0_ms = snap["t0"] * 1000
        # Skip cutoffs without 24h of future data
        if t0_ms + HORIZON_MS > t_max:
            continue
        label = find_first_reaction(snap, bars_1m, bars_1m_ts)
        label["t0"] = snap["t0"]
        label["t0_iso_msk"] = snap["t0_iso_msk"]
        rows.append(label)
    df = pd.DataFrame(rows)
    print(
        f"  labeled {len(df)} snapshots in {time.time() - t0:.1f}s",
        file=sys.stderr, flush=True,
    )

    # Save
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path, index=False)

    # Distribution report
    dist = df["target_direction"].value_counts()
    print(
        f"Saved: {out_path}\n"
        f"  rows: {len(df)}\n"
        f"  direction distribution:\n"
        + "\n".join(f"    {k}: {v} ({v / len(df) * 100:.1f}%)" for k, v in dist.items()),
        file=sys.stderr,
    )
    react = df[df["target_direction"] != "no_react"]
    if len(react):
        print(
            f"  magnitude (reacted only): mean={react['target_magnitude_pct'].mean():.2f}% "
            f"median={react['target_magnitude_pct'].median():.2f}% "
            f"max={react['target_magnitude_pct'].max():.2f}%\n"
            f"  touch_time_hr: median={react['touch_time_hr_from_t0'].median():.2f}h\n"
            f"  react_time_hr: median={react['react_time_hr_from_t0'].median():.2f}h",
            file=sys.stderr,
        )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("batch_dir")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    batch_dir = pathlib.Path(args.batch_dir).resolve()
    if args.out:
        out = pathlib.Path(args.out)
    else:
        out = SMC_LIB / "projects/прометей/labels" / f"{batch_dir.name}_labels.parquet"
    main(batch_dir, out)
