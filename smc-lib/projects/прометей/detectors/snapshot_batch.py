"""Batch snapshot generator for Прометей.

Iterates t0 across a date range at 4h cadence (Phase 1 baseline).
Per Rule 14: anchor = 0 UTC → 4h cadence emits at 0/4/8/12/16/20 UTC
                                = 3/7/11/15/19/23 MSK (6 snapshots/day).

Loads 1m CSV ONCE, aggregates each TF ONCE, then slices per cutoff.

Usage:
    python3 snapshot_batch.py START_DATE END_DATE [TFs]
    e.g. python3 snapshot_batch.py 2022-01-01 2026-06-14
         python3 snapshot_batch.py 2022-01-01 2026-06-14 "1h,4h,12h,1D"
"""
from __future__ import annotations

import sys
import time
import pathlib
import collections
from datetime import datetime, timedelta, timezone

SMC_LIB = pathlib.Path.home() / "smc-lib"
sys.path.insert(0, str(SMC_LIB))

from projects.прометей.detectors.snapshot_builder import (  # noqa: E402
    load_1m_csv,
    sanity_check_data,
    aggregate_to_tf,
    bars_with_ts_up_to_cutoff,
    detect_active_obs_on_tf,
    detect_active_fvgs_on_tf,
    detect_active_marubozu_on_tf,
    detect_active_block_orders_on_tf,
    detect_active_rdrb_on_tf,
    detect_active_i_rdrb_on_tf,
    detect_active_ob_liq_on_tf,
    detect_active_i_fvg_on_tf,
    detect_fractals_on_tf,
    detect_choch_bos_on_tf,
    detect_active_breaker_blocks_on_tf,
    detect_active_mitigation_blocks_on_tf,
    detect_active_inducements_on_tf,
    save_snapshot,
    TF_MS,
    ANCHOR_MS,
    MAX_BARS_BACK,
    MSK,
    SNAPSHOTS_DIR,
)


CADENCE_HOURS = 4
CADENCE_MS = CADENCE_HOURS * 3600 * 1000


def iter_cutoffs(start_utc_ms: int, end_utc_ms: int) -> list[int]:
    """Generate 4h-aligned cutoffs (anchor 0 UTC) inside [start, end]."""
    out = []
    # Align start to next 4h boundary
    aligned = start_utc_ms - (start_utc_ms % CADENCE_MS)
    if aligned < start_utc_ms:
        aligned += CADENCE_MS
    t = aligned
    while t <= end_utc_ms:
        out.append(t)
        t += CADENCE_MS
    return out


def build_snapshot_fast(
    tf_aggregates: dict[str, list],
    t0_ms: int,
    bars_1m_ts: list[int],
    bars_1m: list,
    symbol: str = "BTCUSDT",
) -> dict:
    """Build snapshot using PRE-AGGREGATED tf bars (no re-aggregation per t0)."""
    import bisect
    t0_iso_msk = datetime.fromtimestamp(t0_ms / 1000, tz=MSK).strftime("%Y-%m-%d %H:%M MSK")
    # current_price = close of last 1m bar closed before t0
    cur_price = None
    idx = bisect.bisect_right(bars_1m_ts, t0_ms - 60_000) - 1
    if idx >= 0:
        cur_price = bars_1m[idx][4]
    snapshot = {
        "t0": t0_ms // 1000,
        "t0_iso_msk": t0_iso_msk,
        "symbol": symbol,
        "current_price": cur_price,
        "active_zones": [],
        "fractals": {},
        "structural": {},
        "breakers": [],
        "mitigation_blocks": [],
        "inducements": [],
    }

    for tf_label, tf_bars in tf_aggregates.items():
        tf_ms = TF_MS[tf_label]
        candles, ts_list = bars_with_ts_up_to_cutoff(
            tf_bars, t0_ms, tf_ms, max_bars_back=MAX_BARS_BACK.get(tf_label),
        )
        if len(candles) < 5:
            continue

        snapshot["active_zones"].extend(detect_active_obs_on_tf(candles, ts_list, tf_label))
        snapshot["active_zones"].extend(detect_active_fvgs_on_tf(candles, ts_list, tf_label))
        snapshot["active_zones"].extend(detect_active_marubozu_on_tf(candles, ts_list, tf_label))
        snapshot["active_zones"].extend(detect_active_block_orders_on_tf(candles, ts_list, tf_label))
        snapshot["active_zones"].extend(detect_active_rdrb_on_tf(candles, ts_list, tf_label))
        snapshot["active_zones"].extend(detect_active_i_rdrb_on_tf(candles, ts_list, tf_label))
        snapshot["active_zones"].extend(detect_active_ob_liq_on_tf(candles, ts_list, tf_label))
        snapshot["active_zones"].extend(detect_active_i_fvg_on_tf(candles, ts_list, tf_label))
        snapshot["fractals"][tf_label] = detect_fractals_on_tf(candles, ts_list, tf_label)
        snapshot["structural"][tf_label] = detect_choch_bos_on_tf(candles, ts_list, tf_label)
        snapshot["breakers"].extend(detect_active_breaker_blocks_on_tf(candles, ts_list, tf_label))
        snapshot["mitigation_blocks"].extend(detect_active_mitigation_blocks_on_tf(candles, ts_list, tf_label))
        snapshot["inducements"].extend(detect_active_inducements_on_tf(candles, ts_list, tf_label))

    return snapshot


def main(
    start_date: str,
    end_date: str,
    tf_panel: tuple[str, ...] = ("15m", "30m", "1h", "2h", "4h", "6h", "12h", "1D"),
):
    """Iterate cutoffs at 4h cadence and emit one snapshot each."""
    bars_1m = load_1m_csv()
    sanity_check_data(bars_1m)

    # Aggregate each TF ONCE
    print(f"Aggregating {len(tf_panel)} TFs...", file=sys.stderr, flush=True)
    t_agg = time.time()
    tf_aggregates: dict[str, list] = {}
    for tf in tf_panel:
        tf_aggregates[tf] = aggregate_to_tf(bars_1m, TF_MS[tf], anchor_ms=ANCHOR_MS)
        print(
            f"  {tf}: {len(tf_aggregates[tf])} bars",
            file=sys.stderr, flush=True,
        )
    print(f"Aggregation done in {time.time() - t_agg:.1f}s", file=sys.stderr, flush=True)
    # Pre-compute ts arr for 1m bars (binary search index)
    bars_1m_ts = [b[0] for b in bars_1m]

    # Cutoff range (interpret dates as MSK midnight)
    start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=MSK)
    end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=MSK) + timedelta(days=1)
    cutoffs = iter_cutoffs(
        int(start_dt.timestamp() * 1000),
        int(end_dt.timestamp() * 1000),
    )
    print(
        f"Cutoffs: {len(cutoffs)} (4h cadence, "
        f"{start_dt.date()} → {end_dt.date()})",
        file=sys.stderr, flush=True,
    )

    # Batch run
    batch_dir = SNAPSHOTS_DIR / f"batch_{start_date}_{end_date}"
    batch_dir.mkdir(exist_ok=True)
    t_batch = time.time()
    counts = collections.Counter()
    for i, t0 in enumerate(cutoffs):
        snap = build_snapshot_fast(tf_aggregates, t0, bars_1m_ts, bars_1m)
        save_snapshot(snap, out_dir=batch_dir)
        counts["active_zones"] += len(snap["active_zones"])
        counts["fractals"] += sum(len(v) for v in snap["fractals"].values())
        counts["breakers"] += len(snap["breakers"])
        counts["mitigation_blocks"] += len(snap["mitigation_blocks"])
        counts["inducements"] += len(snap["inducements"])

        if (i + 1) % 50 == 0:
            elapsed = time.time() - t_batch
            rate = (i + 1) / elapsed
            eta = (len(cutoffs) - i - 1) / rate if rate > 0 else float("inf")
            print(
                f"  [{i + 1}/{len(cutoffs)}] {rate:.1f} snap/s, ETA {eta / 60:.1f} min",
                file=sys.stderr, flush=True,
            )

    print(
        f"Batch done in {(time.time() - t_batch) / 60:.1f} min\n"
        f"  Output: {batch_dir}\n"
        f"  Totals across {len(cutoffs)} snapshots:\n"
        f"    active_zones: {counts['active_zones']:,}\n"
        f"    fractals: {counts['fractals']:,}\n"
        f"    breakers: {counts['breakers']:,}\n"
        f"    mitigation_blocks: {counts['mitigation_blocks']:,}\n"
        f"    inducements: {counts['inducements']:,}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__, file=sys.stderr)
        sys.exit(1)
    start = sys.argv[1]
    end = sys.argv[2]
    tfs_arg = sys.argv[3] if len(sys.argv) > 3 else None
    tf_panel = tuple(tfs_arg.split(",")) if tfs_arg else (
        "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1D",
    )
    main(start, end, tf_panel)
