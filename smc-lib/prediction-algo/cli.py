"""
predict_zones BTC — финальный CLI.

Что делает:
  1. Подкачивает свежие 1m данные (fetch_btc_1m_missing.py)
  2. На момент NOW снимает snapshot всех активных зон (precompute path)
  3. Тренирует LookupModel на последних train_window_days
  4. Предсказывает P(hit_12h), P(hit_D) на каждой зоне
  5. Выводит top-K выше / ниже / overall + текущую цену + время в MSK

Usage:
    python cli.py                                 # default top-5, train 365d
    python cli.py --top-k 10 --train-days 365
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd

from data import load_btc_1m
from labels import label_zones
from model import LookupModel
from zones import ALL_TYPES, precompute_zone_events, snapshot_from_events


SMC_LIB = Path(os.environ.get("SMCLIB_ROOT", str(Path.home() / "smc-lib")))


def fetch_latest_1m() -> None:
    """Вызвать fetch_btc_1m_missing.py для подкачки актуальных данных."""
    fetch = SMC_LIB / "scripts" / "fetch_btc_1m_missing.py"
    if not fetch.exists():
        print("  (fetch script not found, skipping)")
        return
    print("Fetching latest 1m...")
    res = subprocess.run([sys.executable, str(fetch)], capture_output=True, text=True, timeout=120)
    if res.stdout:
        print(f"  {res.stdout.strip().split(chr(10))[-1]}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--top-k", type=int, default=5, help="top-K зон в каждую сторону")
    p.add_argument("--train-days", type=int, default=365)
    p.add_argument("--training-dataset", default=str(Path.home() / "Desktop" / "btc_full.csv"),
                   help="CSV датасет для обучения модели")
    p.add_argument("--tfs", default="1h,4h,12h,1d")
    p.add_argument("--no-fetch", action="store_true", help="не подкачивать 1m")
    args = p.parse_args()

    if not args.no_fetch:
        fetch_latest_1m()

    print("Loading training dataset...")
    t0 = time.time()
    ds_train = pd.read_csv(args.training_dataset)
    ds_train["cut_off_ts"] = pd.to_datetime(ds_train["cut_off_ts"], utc=True)
    # Берём последние train_days перед NOW
    now = pd.Timestamp.now(tz="UTC")
    train_lo = now - pd.Timedelta(days=args.train_days)
    train_data = ds_train[(ds_train["cut_off_ts"] >= train_lo)]
    print(f"  Train rows: {len(train_data)} (last {args.train_days}d) in {time.time()-t0:.1f}s")

    if len(train_data) < 1000:
        print("  Warning: very small training dataset")

    print("Training LookupModel...")
    t1 = time.time()
    model = LookupModel.fit(train_data, min_count=50, alpha=1.0)
    print(f"  fit in {time.time()-t1:.1f}s")
    print(f"  Global rates: hit_12h={model.global_rates['hit_12h']:.3f}, hit_D={model.global_rates['hit_D']:.3f}")

    print("\nLoading 1m for snapshot...")
    t2 = time.time()
    # 90 дней истории чтобы охватить старые зоны на 1d/12h
    df_1m = load_btc_1m(start=now - pd.Timedelta(days=120))
    print(f"  Loaded {len(df_1m)} 1m rows in {time.time()-t2:.1f}s")

    # cut-off = последняя минута + 1 минута (= сейчас)
    cut_off = df_1m.index[-1] + pd.Timedelta(minutes=1)
    price_now = float(df_1m["close"].iloc[-1])
    cut_msk = cut_off + pd.Timedelta(hours=3)
    print(f"\nCut-off (UTC): {cut_off.strftime('%Y-%m-%d %H:%M')}")
    print(f"Cut-off (MSK): {cut_msk.strftime('%Y-%m-%d %H:%M')}")
    print(f"BTC price:     {price_now:,.2f}")

    print("\nComputing zone snapshot...")
    t3 = time.time()
    tfs = tuple(args.tfs.split(","))
    events, resampled = precompute_zone_events(df_1m, tfs=tfs, types=ALL_TYPES)
    zones = snapshot_from_events(events, resampled, df_1m, cut_off)
    print(f"  {len(zones)} active zones in {time.time()-t3:.1f}s")

    # Подготовим dataframe для predict
    rows = []
    for z in zones:
        rows.append({
            "tf": z.tf, "type": z.type, "direction": z.direction,
            "lo": z.lo, "hi": z.hi, "level": z.level if z.level is not None else float("nan"),
            "width": z.hi - z.lo,
            "side": z.side, "distance_pct": z.distance_pct, "age_bars": z.age_bars,
            "mitigation_model": z.mitigation_model, "born_ts": z.born_ts,
            "hit_12h": False, "hit_D": False, "time_to_hit_minutes": -1,
            "first_hit_horizon": "none", "first_hit_above": False, "first_hit_below": False,
        })
    snap_df = pd.DataFrame(rows)
    preds = model.predict(snap_df)
    snap_df["P_hit_12h"] = preds["P_hit_12h"].to_numpy()
    snap_df["P_hit_D"] = preds["P_hit_D"].to_numpy()
    snap_df["bucket_used"] = preds["bucket_used"].to_numpy()
    snap_df["n_train_bucket"] = preds["n_train"].to_numpy()

    # Print top-K ABOVE и BELOW отсортированные по P_hit_D
    above = snap_df[snap_df["side"] == "above"].sort_values("P_hit_D", ascending=False).head(args.top_k)
    below = snap_df[snap_df["side"] == "below"].sort_values("P_hit_D", ascending=False).head(args.top_k)

    def fmt_row(row, idx):
        lvl = f"lvl={row['level']:>9.2f}" if pd.notna(row["level"]) else " " * 13
        dist_to_top = row["lo"] - price_now if row["side"] == "above" else price_now - row["hi"]
        dist_str = f"{dist_to_top:+.0f}"
        return (
            f"  {idx:>2}. {row['tf']:>4s}  {row['type']:>13s} {row['direction']:>6s}  "
            f"[{row['lo']:>9.2f}, {row['hi']:>9.2f}]  {lvl}  "
            f"P_12h={row['P_hit_12h']:.3f}  P_D={row['P_hit_D']:.3f}  "
            f"dist={dist_str:>7s}$ ({row['distance_pct']:>5.2f}%)  "
            f"age={int(row['age_bars']):>3d}b  bucket={row['bucket_used']:>10s}  n={int(row['n_train_bucket'])}"
        )

    print(f"\n{'='*40} TOP-{args.top_k} ABOVE (resistance) {'='*40}")
    for i, (_, r) in enumerate(above.iterrows(), 1):
        print(fmt_row(r, i))

    print(f"\n{'='*40} TOP-{args.top_k} BELOW (support) {'='*40}")
    for i, (_, r) in enumerate(below.iterrows(), 1):
        print(fmt_row(r, i))

    # Pivot-like: closest above + closest below by P
    print(f"\n{'='*30} SUMMARY {'='*30}")
    print(f"  BTC = {price_now:,.2f} @ {cut_msk.strftime('%Y-%m-%d %H:%M')} MSK")
    if not above.empty:
        top1a = above.iloc[0]
        print(f"  Top ABOVE: {top1a['tf']} {top1a['type']} {top1a['direction']} [{top1a['lo']:.2f}, {top1a['hi']:.2f}]  P_D={top1a['P_hit_D']:.3f}  dist={top1a['distance_pct']:.2f}%")
    if not below.empty:
        top1b = below.iloc[0]
        print(f"  Top BELOW: {top1b['tf']} {top1b['type']} {top1b['direction']} [{top1b['lo']:.2f}, {top1b['hi']:.2f}]  P_D={top1b['P_hit_D']:.3f}  dist={top1b['distance_pct']:.2f}%")


if __name__ == "__main__":
    main()
