"""
Training dataset builder: пройти по cut-offs → snapshot + labels → flat records.

Phase 1 — простой brute-force: каждый cut-off независимо. Оптимизация
(precompute zone events + mitigation timelines) откладывается до этапа когда
brute-force окажется узким местом для walk-forward валидации.

CLI:
    python dataset.py --start 2024-01-01 --end 2024-02-01 \
        --step-hours 12 --tfs 1h,4h,12h,1d --out /tmp/dataset.parquet
"""
from __future__ import annotations

import argparse
import time
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from data import load_btc_1m
from labels import ZoneLabel, label_zones
from zones import ALL_TYPES, ActiveZone, precompute_zone_events, snapshot_from_events


def _zone_label_to_record(cut_off_ts: pd.Timestamp, lbl: ZoneLabel) -> dict:
    z = lbl.zone
    width = z.hi - z.lo
    return {
        "cut_off_ts": cut_off_ts,
        # zone identity
        "tf": z.tf,
        "type": z.type,
        "direction": z.direction,
        # zone geometry
        "lo": z.lo,
        "hi": z.hi,
        "level": z.level if z.level is not None else float("nan"),
        "width": width,
        # context
        "side": z.side,
        "distance_pct": z.distance_pct,
        "age_bars": z.age_bars,
        "mitigation_model": z.mitigation_model,
        "born_ts": z.born_ts,
        # labels
        "hit_12h": lbl.hit_12h,
        "hit_D": lbl.hit_D,
        "time_to_hit_minutes": lbl.time_to_hit_minutes if lbl.time_to_hit_minutes is not None else -1,
        "first_hit_horizon": lbl.first_hit_horizon if lbl.first_hit_horizon else "none",
        "first_hit_above": lbl.first_hit_above,
        "first_hit_below": lbl.first_hit_below,
    }


def gen_cut_offs(start: pd.Timestamp, end: pd.Timestamp, step_hours: int) -> list[pd.Timestamp]:
    """Сгенерировать cut-offs от start до end с шагом step_hours.
    Cut-offs выравниваются на UTC midnight (00:00) — затем шаг."""
    # Округляем start до ближайшего верхнего step_hours-выровненного часа от UTC midnight
    base = start.normalize()  # 00:00 UTC того же дня
    cut = base
    while cut < start:
        cut += pd.Timedelta(hours=step_hours)
    out = []
    while cut <= end:
        out.append(cut)
        cut += pd.Timedelta(hours=step_hours)
    return out


def build_dataset(
    df_1m: pd.DataFrame,
    cut_offs: list[pd.Timestamp],
    tfs: tuple[str, ...] = ("1h", "4h", "12h", "1d"),
    types: tuple[str, ...] = ALL_TYPES,
    verbose: bool = True,
) -> pd.DataFrame:
    """
    Прогнать все cut-offs и собрать общий DataFrame с записями (zone × label) на каждый cut-off.
    Использует precompute_zone_events для амортизации сканирования.
    """
    records: list[dict] = []
    t_start = time.time()
    print("  Precomputing zone events...")
    events, resampled = precompute_zone_events(df_1m, tfs=tfs, types=types)
    n_events = sum(len(v) for v in events.values())
    print(f"  {n_events} zone events precomputed in {time.time()-t_start:.1f}s")

    t_loop = time.time()
    for i, cut in enumerate(cut_offs):
        zones = snapshot_from_events(events, resampled, df_1m, cut)
        labels = label_zones(zones, df_1m, cut)
        for lbl in labels:
            records.append(_zone_label_to_record(cut, lbl))
        if verbose and (i + 1) % 200 == 0:
            elapsed = time.time() - t_loop
            rate = (i + 1) / elapsed
            remaining = (len(cut_offs) - i - 1) / rate
            print(f"  [{i+1}/{len(cut_offs)}] {elapsed:.1f}s elapsed, ~{remaining:.0f}s remaining, {len(records)} records")

    return pd.DataFrame(records)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--start", required=True, help="UTC date start, e.g. 2024-01-01")
    p.add_argument("--end", required=True, help="UTC date end, e.g. 2024-02-01")
    p.add_argument("--step-hours", type=int, default=12)
    p.add_argument("--tfs", default="1h,4h,12h,1d")
    p.add_argument("--types", default=",".join(ALL_TYPES))
    p.add_argument("--out", required=True, help="Output path (.csv или .parquet)")
    args = p.parse_args()

    start = pd.Timestamp(args.start, tz="UTC")
    end = pd.Timestamp(args.end, tz="UTC")
    tfs = tuple(args.tfs.split(","))
    types = tuple(args.types.split(","))

    # Загружаем 1m с lookback (нужен запас для зон старше cut-off) + lookahead на 1d для labels
    load_start = start - pd.Timedelta(days=90)   # 90d lookback
    load_end = end + pd.Timedelta(days=2)
    print(f"Load 1m from {load_start.date()} to {load_end.date()} ...")
    df = load_btc_1m(start=load_start, end=load_end)
    print(f"  loaded {len(df)} rows")

    cut_offs = gen_cut_offs(start, end, args.step_hours)
    print(f"Cut-offs: {len(cut_offs)} (step {args.step_hours}h)")

    ds = build_dataset(df, cut_offs, tfs=tfs, types=types)
    print(f"Dataset built: {len(ds)} records, {ds.shape[1]} columns")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.suffix == ".parquet":
        ds.to_parquet(out_path, index=False)
    else:
        ds.to_csv(out_path, index=False)
    print(f"Saved: {out_path}")

    # Quick summary
    n_hit12 = ds["hit_12h"].sum()
    n_hitD = ds["hit_D"].sum()
    print(f"Hit rate: 12h={n_hit12}/{len(ds)} ({100*n_hit12/len(ds):.1f}%), "
          f"D={n_hitD}/{len(ds)} ({100*n_hitD/len(ds):.1f}%)")


if __name__ == "__main__":
    main()
