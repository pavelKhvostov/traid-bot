"""Phase 2 Step 2 — build 8 binary targets + continuation on 1h cadence (BTC).

Targets:
  y_long_2/3/4/5pct_24h: max(high[t+1..t+24]) / close[t] - 1 >= threshold
  y_short_2/3/4/5pct_24h: (close[t] - min(low[t+1..t+24])) / close[t] >= threshold

Continuation (binary):
  Computed only when |intraday_signed_move| >= 0.3% (otherwise NaN)
  intraday = close[t] / day_open[t] - 1
  remaining = close[t+24] / close[t] - 1
  cont_target = sign(remaining) == sign(intraday)

Range quantile targets (used in Group B model):
  range_up = max(high[t+1..t+24]) / close[t] - 1
  range_down = (close[t] - min(low[t+1..t+24])) / close[t]
  (квантили вычисляются обучением LightGBM с objective=quantile, не здесь)

Plus regime target placeholder (TODO: будет определён в Step 4 — нужна labelling methodology).

Output: data/labels_1h.parquet
"""
from __future__ import annotations
import time
from pathlib import Path

import numpy as np
import pandas as pd

# ─── Paths ──────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
PHASE1_DATA = ROOT / "phase1_reproduce" / "data"
OUT_PATH = DATA_DIR / "labels_1h.parquet"

# ─── Config ─────────────────────────────────────────
ASSET = "BTCUSDT"
TF = "1h"
HORIZON_BARS = 24      # 24h horizon
THRESHOLDS = [2.0, 3.0, 4.0, 5.0]  # % move

TRAIN_START = pd.Timestamp("2020-01-01", tz="UTC")
TRAIN_END = pd.Timestamp("2024-12-31 23:59:59", tz="UTC")
HOLDOUT_START = pd.Timestamp("2025-01-01", tz="UTC")
HOLDOUT_END = pd.Timestamp("2026-05-31 23:59:59", tz="UTC")


def load_1h() -> pd.DataFrame:
    src = PHASE1_DATA / f"{ASSET}_1h.csv"
    df = pd.read_csv(src)
    df["open_time"] = pd.to_datetime(df["open_time"], utc=True)
    df = df.set_index("open_time").sort_index()
    # close_time = open_time + 1h ⇒ snapshot = close_time
    return df


def build_targets(df: pd.DataFrame) -> pd.DataFrame:
    """For each bar i, compute strong-move targets looking forward [i+1..i+24]."""
    t0 = time.time()
    n = len(df)
    print(f"1h bars total: {n:,}")

    close = df["close"].to_numpy()
    high = df["high"].to_numpy()
    low = df["low"].to_numpy()

    # Pre-compute rolling forward max(high), min(low) over [i+1..i+24]
    # max(high[i+1..i+H]) → shift then rolling
    high_s = pd.Series(high)
    low_s = pd.Series(low)
    fwd_max_high = high_s.shift(-1).rolling(HORIZON_BARS, min_periods=HORIZON_BARS).max()
    fwd_min_low = low_s.shift(-1).rolling(HORIZON_BARS, min_periods=HORIZON_BARS).min()
    # ⚠ rolling().max() with shift(-1) reads from i+1 to i+H — but rolling looks BACK
    # → with shift(-1) and rolling(H) on shifted series: at position i (post-shift), window contains shifted[i-H+1..i] = high[i-H+2..i+1]
    # Better: shift(-H) approach. Simpler: explicit loop.

    # Use explicit window construction (correct):
    fwd_max_high_arr = np.full(n, np.nan)
    fwd_min_low_arr = np.full(n, np.nan)
    for i in range(n - HORIZON_BARS):
        fwd_max_high_arr[i] = high[i + 1 : i + 1 + HORIZON_BARS].max()
        fwd_min_low_arr[i] = low[i + 1 : i + 1 + HORIZON_BARS].min()

    # Magnitude (raw % move)
    range_up_pct = (fwd_max_high_arr / close - 1) * 100
    range_down_pct = (close - fwd_min_low_arr) / close * 100  # positive = down move size

    out = pd.DataFrame(
        {
            "snapshot_close_time": df.index + pd.Timedelta(hours=1),  # bar close moment
            "open_time": df.index,
            "close": close,
            "range_up_pct_24h": range_up_pct,
            "range_down_pct_24h": range_down_pct,
        }
    ).set_index("snapshot_close_time")

    # 8 binary targets
    for thr in THRESHOLDS:
        out[f"y_long_{int(thr)}pct_24h"] = pd.array(range_up_pct >= thr, dtype="Int8")
        out[f"y_short_{int(thr)}pct_24h"] = pd.array(range_down_pct >= thr, dtype="Int8")

    # Continuation target
    # day_open[t] = close at start of UTC day; signed intraday move
    day = out["open_time"].dt.floor("D")
    out["day"] = day
    day_open = df["open"].copy()
    day_open.index = df.index
    # for each bar, find open of current UTC day
    day_first = df.groupby(df.index.floor("D"))["open"].first().rename("day_open")
    out = out.join(day_first, on="day")
    out["intraday_signed_move_pct"] = (out["close"] / out["day_open"] - 1) * 100

    # remaining 24h signed move
    fwd_close_arr = np.full(n, np.nan)
    for i in range(n - HORIZON_BARS):
        fwd_close_arr[i] = close[i + HORIZON_BARS]
    out["forward_close"] = fwd_close_arr
    out["remaining_signed_move_pct"] = (out["forward_close"] / out["close"] - 1) * 100

    # Continuation only when intraday move strong enough
    mask = out["intraday_signed_move_pct"].abs() >= 0.3
    cont_vals = pd.array([pd.NA] * len(out), dtype="Int8")
    same_sign = (
        np.sign(out["remaining_signed_move_pct"].fillna(0))
        == np.sign(out["intraday_signed_move_pct"].fillna(0))
    ) & mask
    cont_vals[mask & same_sign] = 1
    cont_vals[mask & ~same_sign] = 0
    out["y_continuation"] = cont_vals

    # Drop helpers
    out = out.drop(columns=["day", "day_open", "forward_close"])

    # Split flag
    out["split"] = "unused"
    out.loc[(out.index >= TRAIN_START) & (out.index <= TRAIN_END), "split"] = "train"
    out.loc[(out.index >= HOLDOUT_START) & (out.index <= HOLDOUT_END), "split"] = "holdout"

    elapsed = time.time() - t0
    print(f"Targets built in {elapsed:.1f}s")
    return out


def main() -> None:
    df = load_1h()
    targets = build_targets(df)

    # Sanity check: positive class rates per target × split
    print("\n=== Positive class rates ===")
    print("split × target → positive %")
    for split in ["train", "holdout"]:
        sub = targets[targets["split"] == split]
        print(f"\n[{split}] N={len(sub):,}")
        for col in sub.columns:
            if not col.startswith("y_"):
                continue
            valid = sub[col].dropna()
            pos_pct = valid.mean() * 100 if len(valid) > 0 else 0
            print(f"  {col:25} pos={pos_pct:6.2f}%  (N_valid={len(valid):,})")

    # Range quantile distribution
    print("\n=== Range distribution (24h forward, training set) ===")
    train_sub = targets[targets["split"] == "train"]
    for col in ["range_up_pct_24h", "range_down_pct_24h"]:
        v = train_sub[col].dropna()
        print(f"  {col}:")
        print(f"    mean={v.mean():.2f}%  median={v.median():.2f}%")
        print(f"    p10={v.quantile(0.1):.2f}%  p50={v.quantile(0.5):.2f}%  p90={v.quantile(0.9):.2f}%  p99={v.quantile(0.99):.2f}%")

    # Save
    DATA_DIR.mkdir(exist_ok=True)
    targets.to_parquet(OUT_PATH)
    print(f"\n→ Saved: {OUT_PATH}  ({len(targets):,} rows, {len(targets.columns)} cols)")


if __name__ == "__main__":
    main()
