"""Phase 5 — Fibonacci levels из existing fractal events.

Для baseline2: добавляем Fib retrace/extension levels как feature source.

Алгоритм:
  1. Из events.parquet берём все Williams fractals (element_type=fractal).
  2. На каждом TF строим swing pairs: FH→FL (down swing) или FL→FH (up swing).
     Pair = последовательные противоположные fractals.
  3. Для каждого swing computем 12 fib levels:
     retrace: 0, 23.6, 38.2, 50, 61.8, 78.6, 100
     extension: 127.2, 138.2, 161.8, 200, 261.8
  4. Output: fib_levels.parquet с колонками:
     ts (born timestamp = swing.end), tf, swing_direction (up/down),
     swing_start_price, swing_end_price, swing_size_pct, fib_pct, level_price
"""
from __future__ import annotations
import sys
import time
import argparse
import pathlib
import pandas as pd
import numpy as np

SMC_LIB = pathlib.Path.home() / "smc-lib"
EVENTS_PATH = SMC_LIB / "projects/живой-рынок/data/events_2020-01-01_2026-06-15.parquet"
OUT_PATH = SMC_LIB / "projects/живой-рынок/data/fib_levels_2020-01-01_2026-06-15.parquet"

FIB_LEVELS = [
    ("retrace_000", 0.0),
    ("retrace_236", 0.236),
    ("retrace_382", 0.382),
    ("retrace_500", 0.500),
    ("retrace_618", 0.618),    # golden retrace
    ("retrace_786", 0.786),
    ("retrace_100", 1.000),
    ("ext_1272", 1.272),
    ("ext_1382", 1.382),
    ("ext_1618", 1.618),
    ("ext_2000", 2.000),
    ("ext_2618", 2.618),
]

# Strong TFs — где swings качественнее
TF_PRIORITY = {"1D": 8, "12h": 6, "6h": 4, "4h": 3, "2h": 2, "1h": 1.5, "30m": 1, "15m": 0.5}


def compute_fibs_for_tf(fractals_tf: pd.DataFrame) -> list[dict]:
    """Для одного TF: построить swing pairs и fib levels.

    fractals_tf: DataFrame с колонками [ts, direction (high/low), level], sorted by ts.
    """
    out = []
    if len(fractals_tf) < 2:
        return out

    fr = fractals_tf.sort_values("ts").reset_index(drop=True)
    tf = fr["tf"].iloc[0]

    for i in range(len(fr) - 1):
        f_start = fr.iloc[i]
        # Find next fractal of OPPOSITE direction
        next_opp = fr[(fr["ts"] > f_start["ts"]) & (fr["direction"] != f_start["direction"])]
        if next_opp.empty:
            continue
        f_end = next_opp.iloc[0]

        start_price = float(f_start["level"])
        end_price = float(f_end["level"])
        swing_size = abs(end_price - start_price)
        if swing_size <= 0:
            continue

        if f_start["direction"] == "high" and f_end["direction"] == "low":
            swing_dir = "down"  # high → low
        elif f_start["direction"] == "low" and f_end["direction"] == "high":
            swing_dir = "up"  # low → high
        else:
            continue  # same direction — skip (not a swing pair)

        swing_size_pct = swing_size / ((start_price + end_price) / 2) * 100

        # For each fib pct compute level price
        for fib_name, fib_pct in FIB_LEVELS:
            # level = end + (start - end) * pct
            # pct=0 → end, pct=1 → start, pct>1 → extension beyond start
            level_price = end_price + (start_price - end_price) * fib_pct
            out.append({
                "ts": int(f_end["ts"]),  # fib level "born" когда end fractal подтвердился
                "tf": tf,
                "swing_direction": swing_dir,
                "swing_start_ts": int(f_start["ts"]),
                "swing_end_ts": int(f_end["ts"]),
                "swing_start_price": start_price,
                "swing_end_price": end_price,
                "swing_size_pct": swing_size_pct,
                "fib_name": fib_name,
                "fib_pct": fib_pct,
                "level_price": level_price,
                "tf_weight": TF_PRIORITY.get(tf, 1.0),
            })
    return out


def main():
    print(f"Loading {EVENTS_PATH.name}...", file=sys.stderr, flush=True)
    df = pd.read_parquet(EVENTS_PATH)
    fr = df[(df["element_type"] == "fractal") & (df["action"] == "born")].copy()
    print(f"  {len(fr):,} fractal birth events", file=sys.stderr, flush=True)

    # Filter only meaningful TFs for fib (4h+ recommended; 1h+ usable)
    keep_tfs = ("1h", "2h", "4h", "6h", "12h", "1D")
    fr = fr[fr["tf"].isin(keep_tfs)]
    print(f"  filtered to {keep_tfs}: {len(fr):,}", file=sys.stderr, flush=True)

    all_fib = []
    t0 = time.time()
    for tf, sub in fr.groupby("tf"):
        t_tf = time.time()
        fib_levels = compute_fibs_for_tf(sub)
        all_fib.extend(fib_levels)
        print(f"  [{tf}] {len(fib_levels):,} fib levels in {time.time() - t_tf:.1f}s",
              file=sys.stderr, flush=True)

    print(f"\nTotal fib levels: {len(all_fib):,} in {time.time() - t0:.1f}s",
          file=sys.stderr, flush=True)

    fib_df = pd.DataFrame(all_fib)
    fib_df.to_parquet(OUT_PATH, index=False)
    print(f"Saved: {OUT_PATH} ({OUT_PATH.stat().st_size / 1024 / 1024:.1f} MB)",
          file=sys.stderr, flush=True)
    print(f"\nBy TF:", file=sys.stderr, flush=True)
    print(fib_df["tf"].value_counts().to_string(), file=sys.stderr, flush=True)
    print(f"\nBy fib name:", file=sys.stderr, flush=True)
    print(fib_df["fib_name"].value_counts().to_string(), file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
