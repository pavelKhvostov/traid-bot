"""
Сравнение двух 12h свечей: какие зоны взаимодействовали с каждой, side-by-side.

Тренировка модели — ОДИН раз (на данных ДО ранней свечи).
Использует **zone-only** модель (без candle context tautology) для чистой интерпретации.

Usage:
    python3 -m force_model_v2.compare --t1 2026-03-04T00:00:00 --t2 2026-03-04T12:00:00
"""
from __future__ import annotations

import argparse
import os
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=FutureWarning)

SMC_LIB = Path(os.environ.get("SMCLIB_ROOT", str(Path.home() / "smc-lib")))
sys.path.insert(0, str(SMC_LIB / "prediction-algo"))

from data import load_btc_1m  # noqa: E402
from zones import precompute_zone_events, snapshot_from_events  # noqa: E402

from force_model_v2.dataset import (  # noqa: E402
    build_datasets, expand_to_cell_wise,
    SMC_TFS, TARGET_ELEMENTS,
)
from force_model_v2.train import train_all  # noqa: E402
from force_model_v2 import features as F  # noqa: E402


def _zone_interacts(zone, candle_high: float, candle_low: float) -> bool:
    if zone.type == "fractal":
        level = zone.level
        if zone.direction == "high":
            return candle_high > level
        return candle_low < level
    return candle_high >= zone.lo and candle_low <= zone.hi


def _zone_key(z) -> tuple:
    """Уникальный ключ зоны для cross-candle matching."""
    return (z.type, z.tf, z.direction, z.born_ts)


def score_candle(
    target_ts: pd.Timestamp,
    results: dict,
    events_by_tf_type,
    resampled,
    helpers,
    df_1m_full,
    zone_only: bool,
) -> tuple[pd.DataFrame, dict]:
    """Снимок + scoring всех взаимодействующих зон. Returns (df_zones, candle_info)."""
    from force_model_v2.dataset import _extract_zone_features

    zones_snapshot = snapshot_from_events(events_by_tf_type, resampled, df_1m_full, target_ts)
    zones_snapshot = [z for z in zones_snapshot if z.type in TARGET_ELEMENTS]

    df_12h = resampled["12h"]
    if target_ts not in df_12h.index:
        return pd.DataFrame(), {}
    candle = df_12h.loc[target_ts]
    candle_high = float(candle["high"])
    candle_low = float(candle["low"])
    candle_open = float(candle["open"])
    candle_close = float(candle["close"])

    atr_12h = helpers["12h"]["atr"]
    prior_trend_12h = F.compute_prior_trend_slope(df_12h, F.PRIOR_TREND_BARS)
    atr12 = float(atr_12h.loc[target_ts]) if target_ts in atr_12h.index else 0.0
    ptrend = float(prior_trend_12h.loc[target_ts]) if target_ts in prior_trend_12h.index else 0.0

    body = abs(candle_close - candle_open)
    rng = candle_high - candle_low
    candle_ctx = {
        "candle_body_atr": body / atr12 if atr12 > 0 else 0.0,
        "candle_range_atr": rng / atr12 if atr12 > 0 else 0.0,
        "candle_direction": int(candle_close > candle_open),
        "prior_n_bars_trend": ptrend if np.isfinite(ptrend) else 0.0,
        "is_bull": candle_close > candle_open,
    }

    rows = []
    for z in zones_snapshot:
        if not _zone_interacts(z, candle_high, candle_low):
            continue
        feats = _extract_zone_features(z, target_ts, resampled, helpers, events_by_tf_type, candle_ctx)
        if feats is None:
            continue
        feats["tf"] = z.tf
        feats["target"] = 0
        feats["candle_open_ts"] = target_ts
        elem = z.type
        model_res = results.get(elem)
        if model_res is None or "model" not in model_res or model_res["model"] is None:
            continue
        df_row = pd.DataFrame([feats])
        expanded = expand_to_cell_wise(df_row, model_res["feature_cols"], tfs=SMC_TFS)
        X = expanded[model_res["cell_cols"]].to_numpy()
        proba = float(model_res["model"].predict_proba(X)[0, 1])
        logit = float(model_res["model"].decision_function(X)[0])
        rows.append({
            "zone_key": _zone_key(z),
            "type": z.type, "tf": z.tf, "direction": z.direction, "side": z.side,
            "lo": z.lo, "hi": z.hi, "level": z.level,
            "born_ts": z.born_ts, "age_bars": z.age_bars,
            "distance_pct": z.distance_pct,
            "p_pivot": proba, "logit": logit,
        })

    df = pd.DataFrame(rows)
    return df, {
        "candle_open_ts": target_ts,
        "open": candle_open, "high": candle_high, "low": candle_low, "close": candle_close,
        "range_pct": (candle_high - candle_low) / candle_open * 100,
        "direction": "bull" if candle_close > candle_open else "bear",
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--t1", required=True, help="первая 12h candle open UTC")
    p.add_argument("--t2", required=True, help="вторая 12h candle open UTC")
    p.add_argument("--train-start", default="2025-01-01")
    p.add_argument("--train-end", default=None, help="default: t1 - 1d")
    p.add_argument("--C", type=float, default=1.0)
    p.add_argument("--zone-only", action="store_true", default=True, help="Используем zone-only модель (default True)")
    p.add_argument("--full", action="store_true", help="Override: использовать full модель")
    args = p.parse_args()

    if args.full:
        args.zone_only = False

    t1 = pd.Timestamp(args.t1, tz="UTC")
    t2 = pd.Timestamp(args.t2, tz="UTC")
    train_end = pd.Timestamp(args.train_end, tz="UTC") if args.train_end else (min(t1, t2) - pd.Timedelta(days=1))

    print(f"t1 = {t1} UTC = {t1.tz_convert('Europe/Moscow')} MSK")
    print(f"t2 = {t2} UTC = {t2.tz_convert('Europe/Moscow')} MSK")
    print(f"train: {args.train_start}..{train_end}")
    print(f"mode: {'zone_only' if args.zone_only else 'full'}")

    print("\n[1/3] Train model...")
    df_1m_train = load_btc_1m(start=args.train_start, end=train_end)
    datasets, _ = build_datasets(df_1m_train)
    results = train_all(datasets, C=args.C, test_split_ts=None, zone_only=args.zone_only)

    print("\n[2/3] Precompute zones to t2 + 12h...")
    df_1m_full = load_btc_1m(start=args.train_start, end=max(t1, t2) + pd.Timedelta(hours=12))
    types_to_scan = list(TARGET_ELEMENTS) + ["ob_vc"]
    events_by_tf_type, resampled = precompute_zone_events(df_1m_full, tfs=SMC_TFS, types=types_to_scan)
    helpers = {tf: {"atr": F.compute_atr(df, F.ATR_PERIOD),
                    "hma_slope": F.compute_hma_slope(df, F.HMA_PERIOD)}
               for tf, df in resampled.items()}

    print("\n[3/3] Score candles...")
    df1, ci1 = score_candle(t1, results, events_by_tf_type, resampled, helpers, df_1m_full, args.zone_only)
    df2, ci2 = score_candle(t2, results, events_by_tf_type, resampled, helpers, df_1m_full, args.zone_only)

    print(f"\n=== Candle 1: {ci1['candle_open_ts']} = {ci1['candle_open_ts'].tz_convert('Europe/Moscow')} MSK ===")
    print(f"  O={ci1['open']:.2f} H={ci1['high']:.2f} L={ci1['low']:.2f} C={ci1['close']:.2f}  range={ci1['range_pct']:.2f}% [{ci1['direction']}]")
    print(f"  interacting zones: {len(df1)}")
    print(f"  SUM p_pivot = {df1['p_pivot'].sum():.4f}  MEAN={df1['p_pivot'].mean():.4f}")
    print(f"  by side: above={int((df1['side']=='above').sum())} below={int((df1['side']=='below').sum())} inside={int((df1['side']=='inside').sum())}")

    print(f"\n=== Candle 2: {ci2['candle_open_ts']} = {ci2['candle_open_ts'].tz_convert('Europe/Moscow')} MSK ===")
    print(f"  O={ci2['open']:.2f} H={ci2['high']:.2f} L={ci2['low']:.2f} C={ci2['close']:.2f}  range={ci2['range_pct']:.2f}% [{ci2['direction']}]")
    print(f"  interacting zones: {len(df2)}")
    print(f"  SUM p_pivot = {df2['p_pivot'].sum():.4f}  MEAN={df2['p_pivot'].mean():.4f}")
    print(f"  by side: above={int((df2['side']=='above').sum())} below={int((df2['side']=='below').sum())} inside={int((df2['side']=='inside').sum())}")

    # Intersection / unique
    keys1 = set(df1["zone_key"].tolist()) if not df1.empty else set()
    keys2 = set(df2["zone_key"].tolist()) if not df2.empty else set()
    common = keys1 & keys2
    only1 = keys1 - keys2
    only2 = keys2 - keys1

    print(f"\n=== Overlap ===")
    print(f"  common zones: {len(common)}")
    print(f"  only in candle 1: {len(only1)}")
    print(f"  only in candle 2: {len(only2)}")

    print("\n=== Element/TF breakdown ===")
    def _crosstab(df, label):
        if df.empty:
            print(f"  [{label}] empty")
            return
        ct = df.pivot_table(index="type", columns="tf", values="p_pivot", aggfunc="size", fill_value=0)
        # Сортируем колонки по TF order
        cols_present = [tf for tf in SMC_TFS if tf in ct.columns]
        ct = ct[cols_present]
        print(f"\n  [{label}] counts (type × TF):")
        print(ct.to_string())
        print(f"\n  [{label}] sum p_pivot per (type × TF):")
        ct2 = df.pivot_table(index="type", columns="tf", values="p_pivot", aggfunc="sum", fill_value=0)
        ct2 = ct2[cols_present]
        print(ct2.round(3).to_string())

    _crosstab(df1, f"Candle 1 ({ci1['candle_open_ts'].tz_convert('Europe/Moscow').strftime('%H:%M MSK')})")
    _crosstab(df2, f"Candle 2 ({ci2['candle_open_ts'].tz_convert('Europe/Moscow').strftime('%H:%M MSK')})")

    out_dir = Path.home() / "Desktop"
    f1 = out_dir / f"force_score_{t1.strftime('%Y%m%d_%H%M')}.csv"
    f2 = out_dir / f"force_score_{t2.strftime('%Y%m%d_%H%M')}.csv"
    df1.sort_values("p_pivot", ascending=False).to_csv(f1, index=False)
    df2.sort_values("p_pivot", ascending=False).to_csv(f2, index=False)
    print(f"\nFull per-zone CSVs:\n  {f1}\n  {f2}")


if __name__ == "__main__":
    main()
