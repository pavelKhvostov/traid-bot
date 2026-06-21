"""
End-to-end driver: load 1m → build datasets → train 5 LR → report.

Usage:
    python3 -m force_model_v2.run [--start 2025-01-01] [--end 2026-01-01] [--test-split 2025-09-01]
    python3 -m force_model_v2.run --sanity   # 1y sanity check
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

from force_model_v2.dataset import build_datasets  # noqa: E402
from force_model_v2.train import train_all, coefficients_summary  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default=None, help="UTC start date (YYYY-MM-DD)")
    parser.add_argument("--end", default=None, help="UTC end date (YYYY-MM-DD)")
    parser.add_argument("--test-split", default=None, help="Walk-forward test split UTC date (train<ts<=test)")
    parser.add_argument("--sanity", action="store_true", help="1y sanity check (2025-01-01..2026-01-01)")
    parser.add_argument("--C", type=float, default=1.0, help="L2 inverse regularization (default 1.0)")
    parser.add_argument("--zone-only", action="store_true",
                        help="Выкинуть candle context features (body/range/direction/prior_trend) — чистый сигнал силы зон")
    parser.add_argument("--out-dir", default=str(Path.home() / "Desktop"), help="output dir for coefficients csv")
    args = parser.parse_args()

    if args.sanity:
        args.start = "2025-01-01"
        args.end = "2026-01-01"
        args.test_split = "2025-09-01"  # 8/4 month split

    print(f"Load BTC 1m: start={args.start}, end={args.end}")
    df_1m = load_btc_1m(start=args.start, end=args.end)
    print(f"  rows: {len(df_1m):,} from {df_1m.index[0]} to {df_1m.index[-1]}")

    datasets, labels_12h = build_datasets(df_1m)

    print("\nDataset sizes:")
    for elem, df in datasets.items():
        pos = df["target"].mean() if not df.empty else None
        print(f"  {elem:14s}: {len(df):,} rows  pos_rate={pos:.3f}" if pos is not None
              else f"  {elem:14s}: 0 rows")

    test_split_ts = pd.Timestamp(args.test_split, tz="UTC") if args.test_split else None

    mode_tag = "zone_only" if args.zone_only else "full"
    print(f"\nTraining 5 logistic regressions (L2, mode={mode_tag}):")
    results = train_all(datasets, C=args.C, test_split_ts=test_split_ts, zone_only=args.zone_only)

    summary = coefficients_summary(results)
    out_path = Path(args.out_dir) / f"force_model_v2_coefficients_{mode_tag}.csv"
    summary.to_csv(out_path, index=False)
    print(f"\nCoefficients saved → {out_path}")

    # Top-10 most positive / negative per element
    print("\nTop coefficients per element:")
    for elem, res in results.items():
        if "coefficients" not in res:
            continue
        coefs = res["coefficients"]
        sorted_coefs = sorted(coefs.items(), key=lambda kv: kv[1], reverse=True)
        top = sorted_coefs[:5]
        bot = sorted_coefs[-5:]
        print(f"\n  [{elem}] intercept={res['intercept']:+.3f}  n_coefs={res['n_coefficients']}")
        print(f"    TOP +:")
        for (feat, tf), w in top:
            print(f"      {feat:20s} @ {tf:4s} = {w:+.4f}")
        print(f"    TOP -:")
        for (feat, tf), w in reversed(bot):
            print(f"      {feat:20s} @ {tf:4s} = {w:+.4f}")


if __name__ == "__main__":
    main()
