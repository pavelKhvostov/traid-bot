"""
Score единичной 12h свечи: тренируем модель на данных ДО target, затем считаем суммарную
силу всех зон, с которыми свеча взаимодействовала в период [open, close].

Usage:
    python3 -m force_model_v2.score --target 2026-03-04T12:00:00 [--train-end 2026-02-28]
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
    SMC_TFS, TARGET_ELEMENTS, FEATURES,
)
from force_model_v2.train import train_all  # noqa: E402
from force_model_v2 import features as F  # noqa: E402


def _zone_interacts_with_candle(zone, candle_high: float, candle_low: float) -> bool:
    """True если свеча своим [low, high] зацепила зону."""
    if zone.type == "fractal":
        level = zone.level
        if zone.direction == "high":
            return candle_high > level  # sweep FH
        else:
            return candle_low < level  # sweep FL
    # interval zone
    return candle_high >= zone.lo and candle_low <= zone.hi


def score_zone(zone, model_result: dict, candle_ctx: dict, atr_val: float, hma_slope: float,
               events_by_tf_type: dict, df_tf, cut_off_ts: pd.Timestamp) -> dict | None:
    """Извлечь features → expand → predict_proba и logit для одной зоны."""
    from force_model_v2.dataset import _extract_zone_features  # local to avoid cycle
    feats = _extract_zone_features(zone, cut_off_ts,
                                    {zone.tf: df_tf}, {zone.tf: {"atr": pd.Series(), "hma_slope": pd.Series()}},
                                    events_by_tf_type, candle_ctx)
    if feats is None:
        return None
    feats["tf"] = zone.tf
    feats["target"] = 0  # dummy
    feats["candle_open_ts"] = cut_off_ts
    df_row = pd.DataFrame([feats])
    feat_cols = model_result["feature_cols"]
    expanded = expand_to_cell_wise(df_row, feat_cols, tfs=SMC_TFS)
    cell_cols = model_result["cell_cols"]
    X = expanded[cell_cols].to_numpy()
    model = model_result["model"]
    proba = float(model.predict_proba(X)[0, 1])
    logit = float(model.decision_function(X)[0])
    return {
        "tf": zone.tf,
        "type": zone.type,
        "direction": zone.direction,
        "side": zone.side,
        "lo": zone.lo,
        "hi": zone.hi,
        "level": zone.level,
        "age_bars": zone.age_bars,
        "distance_pct": zone.distance_pct,
        "p_pivot": proba,
        "logit": logit,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True, help="UTC timestamp of 12h candle open (YYYY-MM-DDTHH:MM:SS)")
    parser.add_argument("--train-start", default="2025-01-01")
    parser.add_argument("--train-end", default=None, help="Default: target_ts - 1 day")
    parser.add_argument("--C", type=float, default=1.0)
    args = parser.parse_args()

    target_ts = pd.Timestamp(args.target, tz="UTC")
    train_end = pd.Timestamp(args.train_end, tz="UTC") if args.train_end else target_ts - pd.Timedelta(days=1)

    print(f"Target candle open: {target_ts} UTC = {target_ts.tz_convert('Europe/Moscow')} MSK")
    print(f"Train range: {args.train_start} .. {train_end}")

    print("\n[1/4] Load 1m data (train) + train 5 models...")
    df_1m_train = load_btc_1m(start=args.train_start, end=train_end)
    datasets, _ = build_datasets(df_1m_train)
    results = train_all(datasets, C=args.C, test_split_ts=None, zone_only=False)

    print("\n[2/4] Load full data + scan zones at target...")
    # Нужно загрузить до target + 12h чтобы взять данные свечи
    df_1m_full = load_btc_1m(start=args.train_start, end=target_ts + pd.Timedelta(hours=12))
    types_to_scan = list(TARGET_ELEMENTS) + ["ob_vc"]
    events_by_tf_type, resampled = precompute_zone_events(df_1m_full, tfs=SMC_TFS, types=types_to_scan)
    helpers = {tf: {"atr": F.compute_atr(df, F.ATR_PERIOD),
                    "hma_slope": F.compute_hma_slope(df, F.HMA_PERIOD)}
               for tf, df in resampled.items()}

    # Snapshot активных зон в момент target open
    zones_snapshot = snapshot_from_events(events_by_tf_type, resampled, df_1m_full, target_ts)
    zones_snapshot = [z for z in zones_snapshot if z.type in TARGET_ELEMENTS]
    print(f"    active zones at target open: {len(zones_snapshot)}")

    # Свеча: [target_ts, target_ts + 12h]
    df_12h = resampled["12h"]
    if target_ts not in df_12h.index:
        print(f"!!! target_ts {target_ts} not in 12h index!")
        return
    candle = df_12h.loc[target_ts]
    candle_high = float(candle["high"])
    candle_low = float(candle["low"])
    candle_open = float(candle["open"])
    candle_close = float(candle["close"])
    print(f"    candle: open={candle_open:.2f}  high={candle_high:.2f}  low={candle_low:.2f}  close={candle_close:.2f}")

    print("\n[3/4] Filter zones interacting with candle, compute features + score...")
    atr_12h = helpers["12h"]["atr"]
    prior_trend_12h = F.compute_prior_trend_slope(df_12h, F.PRIOR_TREND_BARS)
    atr12 = float(atr_12h.loc[target_ts])
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
    from force_model_v2.dataset import _extract_zone_features
    for z in zones_snapshot:
        if not _zone_interacts_with_candle(z, candle_high, candle_low):
            continue
        feats = _extract_zone_features(z, target_ts, resampled, helpers, events_by_tf_type, candle_ctx)
        if feats is None:
            continue
        feats["tf"] = z.tf
        feats["target"] = 0
        feats["candle_open_ts"] = target_ts
        elem = z.type
        if elem not in results or "model" not in results[elem] or results[elem]["model"] is None:
            continue
        model_res = results[elem]
        df_row = pd.DataFrame([feats])
        expanded = expand_to_cell_wise(df_row, model_res["feature_cols"], tfs=SMC_TFS)
        X = expanded[model_res["cell_cols"]].to_numpy()
        proba = float(model_res["model"].predict_proba(X)[0, 1])
        logit = float(model_res["model"].decision_function(X)[0])
        rows.append({
            "type": z.type, "tf": z.tf, "direction": z.direction, "side": z.side,
            "lo": z.lo, "hi": z.hi, "level": z.level,
            "age_bars": z.age_bars, "distance_pct": z.distance_pct,
            "p_pivot": proba, "logit": logit,
        })

    df_scored = pd.DataFrame(rows)
    print(f"    interacting zones: {len(df_scored)}")

    if df_scored.empty:
        print("\n!!! No interacting zones found.")
        return

    print("\n[4/4] Aggregation:")
    print(f"\n  SUM logit = {df_scored['logit'].sum():+.4f}")
    print(f"  SUM p_pivot = {df_scored['p_pivot'].sum():.4f}")
    print(f"  MEAN p_pivot = {df_scored['p_pivot'].mean():.4f}")
    print(f"  count = {len(df_scored)}")

    print(f"\n  by element:")
    by_elem = df_scored.groupby("type").agg(n=("p_pivot", "size"),
                                              sum_p=("p_pivot", "sum"),
                                              sum_logit=("logit", "sum"))
    print(by_elem.round(4).to_string())

    print(f"\n  by side (above/below/inside):")
    by_side = df_scored.groupby("side").agg(n=("p_pivot", "size"),
                                             sum_p=("p_pivot", "sum"),
                                             sum_logit=("logit", "sum"))
    print(by_side.round(4).to_string())

    print(f"\n  by TF:")
    by_tf = df_scored.groupby("tf").agg(n=("p_pivot", "size"),
                                          sum_p=("p_pivot", "sum"),
                                          sum_logit=("logit", "sum"))
    print(by_tf.round(4).to_string())

    out = Path.home() / "Desktop" / f"force_score_{target_ts.strftime('%Y%m%d_%H%M')}.csv"
    df_scored.sort_values("p_pivot", ascending=False).to_csv(out, index=False)
    print(f"\nFull per-zone scores → {out}")


if __name__ == "__main__":
    main()
