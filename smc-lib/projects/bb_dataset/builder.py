"""bb_dataset builder для bounce-or-break classifier (#3 roadmap).

Первая версия — minimum viable:
  Filter:    type=="ob_vc" AND tf in ("1h", "2h")
  Event:     первое касание зоны на 1m в окне [born_ts, born_ts + 72h]
  Label:     геометрически по границе зоны
             LONG bounce  = min(low[t..t+W]) > lo
             SHORT bounce = max(high[t..t+W]) < hi
             W = 2 × HTF_bars (1h→2h, 2h→4h)
  Features:  Group A (zone properties) + Group B (penetration) — ~12 фичей
             Расширение до 70 фичей — после smoke-теста

Output:     bb_obvc_1h2h.parquet
            columns: zone_id, tf, direction, lo, hi, level, width, born_ts, touch_ts,
                     [features A+B], label

Usage:
    python builder.py [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--out PATH] [--limit N]

См. ~/smc-lib/projects/bounce-or-break.md для полной спецификации.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

SMC_LIB = Path.home() / "smc-lib"
sys.path.insert(0, str(SMC_LIB))
sys.path.insert(0, str(SMC_LIB / "prediction-algo"))

from data import load_btc_1m  # noqa: E402
from resample import resample_many  # noqa: E402
from zones import _scan_ob_vc_cross_tf  # noqa: E402

TFS_NEEDED = ("15m", "20m", "1h", "2h")   # 1h/2h HTFs + 15m/20m LTFs для canon ob_vc
TFS_TARGET = ("1h", "2h")
TOUCH_WINDOW_H = 72                       # окно поиска первого касания после born_ts


def collect_unique_obvc_zones(df_1m: pd.DataFrame, resampled: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Скан ob_vc на 1h и 2h. Возвращает per-TF уникальные зоны."""
    out_rows = []
    events_per_htf = _scan_ob_vc_cross_tf(resampled, df_1m)
    for htf, events in events_per_htf.items():
        if htf not in TFS_TARGET:
            continue
        df_htf = resampled[htf]
        for ev in events:
            born_ts = df_htf.index[ev["born_idx"]]
            out_rows.append({
                "tf": htf,
                "direction": ev["direction"],
                "lo": ev["lo"],
                "hi": ev["hi"],
                "level": (ev["lo"] + ev["hi"]) / 2,
                "width": ev["hi"] - ev["lo"],
                "born_ts": born_ts,
                "n_fvg_components": ev.get("n_fvg_components", 1),
            })
    df = pd.DataFrame(out_rows)
    if df.empty:
        return df
    # Канонический dedup (одинаковая зона может быть детектирована дважды на cross-TF)
    df["zone_id"] = (
        df["tf"].astype(str) + "|" +
        df["direction"].astype(str) + "|" +
        df["born_ts"].astype(str) + "|" +
        df["lo"].round(2).astype(str) + "|" +
        df["hi"].round(2).astype(str)
    )
    df = df.drop_duplicates(subset="zone_id").reset_index(drop=True)
    return df


def detect_first_touch(zone: pd.Series, df_1m: pd.DataFrame, window_h: int = TOUCH_WINDOW_H) -> pd.Timestamp | None:
    """Первое касание зоны на 1m в окне [born_ts, born_ts + window_h]."""
    born = zone["born_ts"]
    end = born + pd.Timedelta(hours=window_h)
    # Окно поиска НАЧИНАЕТСЯ строго после born (born = candle close time, цена уже там)
    slice_1m = df_1m.loc[born:end]
    if slice_1m.empty:
        return None
    if str(zone["direction"]).lower() == "long":
        # зона ниже цены — касание = low <= hi
        mask = slice_1m["low"] <= zone["hi"]
    else:
        # зона выше цены — касание = high >= lo
        mask = slice_1m["high"] >= zone["lo"]
    hits = slice_1m.index[mask]
    return hits[0] if len(hits) > 0 else None


def compute_label(zone: pd.Series, touch_ts: pd.Timestamp, df_1m: pd.DataFrame) -> int:
    """Bounce (0) или break (1) — close-based по канону SMC.

    «100% fill зоны» = CLOSE за противоположной границей.
    Wick fill / retest НЕ считается break (это нормальное retest-поведение зоны).

    Окно W = 2 × HTF_bars:
        1h zone → 2h window after touch
        2h zone → 4h window after touch
    """
    tf_hours = {"1h": 1, "2h": 2}[zone["tf"]]
    W = 2 * tf_hours
    end = touch_ts + pd.Timedelta(hours=W)
    slice_1m = df_1m.loc[touch_ts:end]
    if slice_1m.empty:
        return -1  # invalid (no data after touch)
    if str(zone["direction"]).lower() == "long":
        return 1 if (slice_1m["close"].min() <= zone["lo"]) else 0
    else:
        return 1 if (slice_1m["close"].max() >= zone["hi"]) else 0


def compute_features_AB(zone: pd.Series, touch_ts: pd.Timestamp, df_1m: pd.DataFrame) -> dict:
    """Минимальные features: Group A (zone properties) + Group B (penetration).

    Group A — статика зоны:
      tf, direction, width_pct, age_bars (от born до touch в часах HTF), level, mit_model (всегда wick-fill для ob_vc)
    Group B — динамика касания:
      touch_price (low для LONG / high для SHORT), penetration_pct, close_inside,
      first_bar_wick_to_body, n_touches_prior (в this version = 0; inherited zones — todo)
    """
    tf_hours = {"1h": 1, "2h": 2}[zone["tf"]]
    age_bars = (touch_ts - zone["born_ts"]).total_seconds() / 3600 / tf_hours

    touch_bar = df_1m.loc[touch_ts]
    if str(zone["direction"]).lower() == "long":
        touch_price = float(touch_bar["low"])
        penetration_pct = max(0.0, zone["hi"] - touch_price) / zone["width"] * 100
        close_inside = int(touch_bar["close"] <= zone["hi"] and touch_bar["close"] >= zone["lo"])
    else:
        touch_price = float(touch_bar["high"])
        penetration_pct = max(0.0, touch_price - zone["lo"]) / zone["width"] * 100
        close_inside = int(touch_bar["close"] >= zone["lo"] and touch_bar["close"] <= zone["hi"])

    body = abs(touch_bar["close"] - touch_bar["open"])
    if str(zone["direction"]).lower() == "long":
        wick = max(0.0, min(touch_bar["open"], touch_bar["close"]) - touch_bar["low"])
    else:
        wick = max(0.0, touch_bar["high"] - max(touch_bar["open"], touch_bar["close"]))
    wick_to_body = wick / body if body > 0 else 0.0

    return {
        # A — zone properties
        "tf": zone["tf"],
        "tf_hours": tf_hours,
        "direction": zone["direction"],
        "width_pct": zone["width"] / zone["level"] * 100,
        "age_bars": age_bars,
        "n_fvg_components": int(zone.get("n_fvg_components", 1)),
        "mit_model": "wick-fill",  # const для ob_vc
        # B — penetration on first touch
        "touch_price": touch_price,
        "penetration_pct": penetration_pct,
        "close_inside": close_inside,
        "first_bar_wick_to_body": wick_to_body,
        "n_touches_prior": 0,  # TODO: реализовать через inherited zones
    }


def build_dataset(
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
    out_path: Path | None = None,
    limit: int | None = None,
    verbose: bool = True,
) -> pd.DataFrame:
    t0 = time.time()
    if verbose:
        print(f"[bb] loading 1m BTC...")
    df_1m = load_btc_1m()
    if start is not None:
        df_1m = df_1m.loc[start:]
    if end is not None:
        df_1m = df_1m.loc[:end]
    if verbose:
        print(f"  {len(df_1m):,} 1m bars: {df_1m.index[0]} -> {df_1m.index[-1]}")

    if verbose:
        print(f"[bb] resampling to {TFS_NEEDED}...")
    cut_off = df_1m.index[-1] + pd.Timedelta(minutes=1)
    resampled = resample_many(df_1m, TFS_NEEDED, cut_off)
    for tf, d in resampled.items():
        if verbose: print(f"  {tf}: {len(d):,}")

    if verbose:
        print(f"[bb] scanning ob_vc events on {TFS_TARGET}...")
    t1 = time.time()
    zones = collect_unique_obvc_zones(df_1m, resampled)
    if verbose:
        print(f"  found {len(zones):,} unique ob_vc zones in {time.time()-t1:.1f}s")
        print(f"  by tf: {zones.groupby('tf').size().to_dict()}")
        print(f"  by direction: {zones.groupby('direction').size().to_dict()}")

    if limit is not None:
        zones = zones.head(limit)
        if verbose: print(f"  limited to first {limit} zones for smoke-test")

    out_rows = []
    n_no_touch = 0
    n_invalid_label = 0
    t1 = time.time()
    for i, (_, zone) in enumerate(zones.iterrows()):
        if verbose and i > 0 and i % 1000 == 0:
            elapsed = time.time() - t1
            eta = elapsed / i * (len(zones) - i)
            print(f"  [{i}/{len(zones)}] elapsed {elapsed:.0f}s, ETA {eta:.0f}s, no_touch={n_no_touch}")
        touch = detect_first_touch(zone, df_1m)
        if touch is None:
            n_no_touch += 1
            continue
        label = compute_label(zone, touch, df_1m)
        if label < 0:
            n_invalid_label += 1
            continue
        feats = compute_features_AB(zone, touch, df_1m)
        out_rows.append({
            "zone_id": zone["zone_id"],
            "born_ts": zone["born_ts"],
            "touch_ts": touch,
            "lo": zone["lo"],
            "hi": zone["hi"],
            "level": zone["level"],
            "width": zone["width"],
            **feats,
            "label": label,
        })

    df_out = pd.DataFrame(out_rows)
    if verbose:
        print(f"\n[bb] final dataset: {len(df_out):,} rows")
        print(f"  no_touch (dropped): {n_no_touch} ({n_no_touch / max(len(zones),1) * 100:.1f}%)")
        print(f"  invalid_label (dropped): {n_invalid_label}")
        if len(df_out) > 0:
            print(f"  label distribution: bounce={int((df_out['label']==0).sum())}, "
                  f"break={int((df_out['label']==1).sum())} "
                  f"(P(bounce) = {(df_out['label']==0).mean():.3f})")
            print(f"  by tf+direction:")
            print(df_out.groupby(['tf','direction'])['label'].agg(['size','mean']).to_string())

    if out_path is not None:
        df_out.to_parquet(out_path, engine="pyarrow", compression="zstd", index=False)
        if verbose: print(f"\n[bb] saved to {out_path}")

    if verbose:
        print(f"\n[bb] TOTAL TIME: {(time.time()-t0)/60:.1f} min")
    return df_out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=str, default=None, help="start date YYYY-MM-DD (inclusive)")
    ap.add_argument("--end", type=str, default=None, help="end date YYYY-MM-DD (inclusive)")
    ap.add_argument("--out", type=Path, default=Path.home() / "Desktop" / "bb_obvc_1h2h.parquet")
    ap.add_argument("--limit", type=int, default=None, help="limit to first N zones (smoke test)")
    args = ap.parse_args()

    start = pd.Timestamp(args.start, tz="UTC") if args.start else None
    end = pd.Timestamp(args.end, tz="UTC") if args.end else None

    build_dataset(start=start, end=end, out_path=args.out, limit=args.limit)


if __name__ == "__main__":
    main()
