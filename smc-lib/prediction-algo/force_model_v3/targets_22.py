"""22 target fractals (user-labeled important pivots).

Source: ~/smc-lib/scripts/build_mh_pc2_3bar_features.py:62-71.
Time format: MSK (UTC+3). Convert to UTC by subtracting 3 hours.
"""
from __future__ import annotations

import pandas as pd

TARGETS_22_MSK = [
    ("2026-02-08 15:00", "FH"),
    ("2026-02-12 15:00", "FL"),
    ("2026-02-15 03:00", "FH"),
    ("2026-02-21 15:00", "FH"),
    ("2026-02-24 15:00", "FL"),
    ("2026-02-25 15:00", "FH"),
    ("2026-02-28 03:00", "FL"),
    ("2026-03-04 15:00", "FH"),  # ← MISSED by C1-C7 basket
    ("2026-03-08 15:00", "FL"),  # ← MISSED
    ("2026-03-17 03:00", "FH"),
    ("2026-03-22 15:00", "FL"),
    ("2026-03-25 03:00", "FH"),
    ("2026-03-29 15:00", "FL"),
    ("2026-04-17 15:00", "FH"),
    ("2026-04-27 03:00", "FH"),
    ("2026-04-29 15:00", "FL"),
    ("2026-05-06 03:00", "FH"),  # ← MISSED
    ("2026-05-08 03:00", "FL"),
    ("2026-05-10 15:00", "FH"),
    ("2026-05-14 15:00", "FH"),
    ("2026-05-23 03:00", "FL"),
    ("2026-05-26 15:00", "FH"),
]


def get_targets_utc() -> set[tuple[pd.Timestamp, str]]:
    """Return set of (timestamp_utc, side) tuples. side = 'short' for FH, 'long' for FL."""
    out = set()
    for t_msk, fh_fl in TARGETS_22_MSK:
        ts = pd.Timestamp(t_msk + "+03:00").tz_convert("UTC")
        side = "short" if fh_fl == "FH" else "long"
        out.add((ts, side))
    return out


def filter_target_22(candle_open_ts: pd.Timestamp, side: str) -> bool:
    """Check if (candle, side) is in 22 targets."""
    return (candle_open_ts, side) in get_targets_utc()


SHORT_TARGETS = {ts for ts, s in get_targets_utc() if s == "short"}  # 13 FH
LONG_TARGETS = {ts for ts, s in get_targets_utc() if s == "long"}    # 9 FL
