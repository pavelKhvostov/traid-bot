"""
End-to-end driver для force_model_v3.

Usage:
    python3 -m force_model_v3.run --sanity                              # 1y check
    python3 -m force_model_v3.run --start 2025-01-01 --end 2026-01-01 --test-split 2025-09-01
    python3 -m force_model_v3.run --sanity --zone-only                  # без candle context
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pandas as pd

SMC_LIB = Path(os.environ.get("SMCLIB_ROOT", str(Path.home() / "smc-lib")))
sys.path.insert(0, str(SMC_LIB / "prediction-algo"))

from data import load_btc_1m  # noqa: E402

from force_model_v3.dataset import build_datasets  # noqa: E402
from force_model_v3.train import train_all, coefficients_summary  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start", default=None)
    p.add_argument("--end", default=None)
    p.add_argument("--test-split", default=None)
    p.add_argument("--sanity", action="store_true")
    p.add_argument("--C", type=float, default=1.0)
    p.add_argument("--zone-only", action="store_true")
    p.add_argument("--out-dir", default=str(Path.home() / "Desktop"))
    args = p.parse_args()

    if args.sanity:
        args.start = "2025-01-01"
        args.end = "2026-01-01"
        args.test_split = "2025-09-01"

    print(f"Load BTC 1m: start={args.start}, end={args.end}")
    df_1m = load_btc_1m(start=args.start, end=args.end)
    print(f"  rows: {len(df_1m):,}")

    datasets, _ = build_datasets(df_1m)

    print("\nDataset sizes (rows by element, with side breakdown):")
    for elem, df in datasets.items():
        if df.empty:
            print(f"  {elem:14s}: 0 rows")
            continue
        pos = df["target"].mean()
        sh = int((df["side"] == "short").sum())
        ln = int((df["side"] == "long").sum())
        print(f"  {elem:14s}: {len(df):,} rows  pos_rate={pos:.3f}  short={sh}  long={ln}")

    test_split_ts = pd.Timestamp(args.test_split, tz="UTC") if args.test_split else None

    mode = "zone_only" if args.zone_only else "full"
    print(f"\nTraining 5 LR (L2, mode={mode}, target=is_FH for short / is_FL for long):")
    results = train_all(datasets, C=args.C, test_split_ts=test_split_ts, zone_only=args.zone_only)

    summary = coefficients_summary(results)
    out = Path(args.out_dir) / f"force_model_v3_coefficients_{mode}.csv"
    summary.to_csv(out, index=False)
    print(f"\nCoefficients → {out}")

    print("\nTop coefficients per element:")
    for elem, res in results.items():
        if "coefficients" not in res:
            continue
        coefs = res["coefficients"]
        sorted_coefs = sorted(coefs.items(), key=lambda kv: kv[1], reverse=True)
        print(f"\n  [{elem}] intercept={res['intercept']:+.3f}  n_coefs={res['n_coefficients']}")
        print(f"    TOP +:")
        for (feat, tf), w in sorted_coefs[:5]:
            print(f"      {feat:20s} @ {tf:4s} = {w:+.4f}")
        print(f"    TOP -:")
        for (feat, tf), w in sorted_coefs[-5:][::-1]:
            print(f"      {feat:20s} @ {tf:4s} = {w:+.4f}")


if __name__ == "__main__":
    main()
