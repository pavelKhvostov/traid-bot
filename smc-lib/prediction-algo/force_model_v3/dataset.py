"""
Build per-element directional datasets для force-model v3.

Каждая строка = (12h candle, region direction, zone в region).
Target:
  short-side rows (zone in SHORT region) → target = is_FH
  long-side rows  (zone in LONG region)  → target = is_FL

Feature blocks per row:
  - per-element features (age, first_touch, etc — depends on element type)
  - cross-element features (direction_match, htf_trend_match, size_bucket)
  - candle context (body_atr, range_atr, direction, prior_n_bars_trend)
  - liquidity count в region (НОВОЕ в v3)

8 TFs: 1h, 2h, 4h, 6h, 12h, 1d, 2d, 3d (8h убран).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

SMC_LIB = Path(os.environ.get("SMCLIB_ROOT", str(Path.home() / "smc-lib")))
sys.path.insert(0, str(SMC_LIB / "prediction-algo"))

from zones import ActiveZone, precompute_zone_events, snapshot_from_events  # noqa: E402

from force_model_v3 import features as F  # noqa: E402
from force_model_v3.labeling import label_williams_12h  # noqa: E402
from force_model_v3.regions import compute_regions, CandleRegions  # noqa: E402


SMC_TFS = ("1h", "2h", "4h", "6h", "12h", "1d", "2d", "3d")  # 8 TFs
TARGET_ELEMENTS = ("FVG", "fractal", "OB", "block_orders", "RDRB")

FEATURES = {
    "FVG": [
        "age_bucket", "first_touch", "fill_state", "size_bucket",
        "direction_match", "htf_trend_match",
        "candle_body_atr", "candle_range_atr", "candle_direction",
        "liq_count_region",
    ],
    "fractal": [
        "age_bucket", "failed_attempts", "wick_size_atr",
        "direction_match", "htf_trend_match",
        "candle_body_atr", "candle_range_atr", "candle_direction",
        "prior_n_bars_trend",
        "liq_count_region",
    ],
    "OB": [
        "age_bucket", "has_vc", "size_bucket",
        "direction_match", "htf_trend_match",
        "candle_body_atr", "candle_range_atr", "candle_direction",
        "prior_n_bars_trend",
        "liq_count_region",
    ],
    "block_orders": [
        "age_bucket", "size_bucket",
        "direction_match", "htf_trend_match",
        "candle_body_atr", "candle_range_atr", "candle_direction",
        "prior_n_bars_trend",
        "liq_count_region",
    ],
    "RDRB": [
        "age_bucket", "size_bucket",
        "direction_match", "htf_trend_match",
        "candle_body_atr", "candle_range_atr", "candle_direction",
        "prior_n_bars_trend",
        "liq_count_region",
    ],
}


def _build_helpers(resampled: dict[str, pd.DataFrame]) -> dict[str, dict]:
    return {tf: {
        "atr": F.compute_atr(df, F.ATR_PERIOD),
        "hma_slope": F.compute_hma_slope(df, F.HMA_PERIOD),
    } for tf, df in resampled.items()}


def _candle_context(row_12h: pd.Series, atr_12h: float, prior_trend: float) -> dict:
    o = float(row_12h["open"])
    h = float(row_12h["high"])
    l = float(row_12h["low"])
    c = float(row_12h["close"])
    body = abs(c - o)
    rng = h - l
    return {
        "candle_body_atr": body / atr_12h if atr_12h > 0 else 0.0,
        "candle_range_atr": rng / atr_12h if atr_12h > 0 else 0.0,
        "candle_direction": int(c > o),
        "prior_n_bars_trend": float(prior_trend) if prior_trend == prior_trend else 0.0,
        "is_bull": c > o,
    }


def _zone_in_short_region(z: ActiveZone, regs: CandleRegions) -> bool:
    if not regs.has_short:
        return False
    if z.direction not in ("short", "high", "top"):
        return False
    if z.type == "fractal":
        return regs.short_lo <= z.level <= regs.short_hi
    return z.hi >= regs.short_lo and z.lo <= regs.short_hi


def _zone_in_long_region(z: ActiveZone, regs: CandleRegions) -> bool:
    if not regs.has_long:
        return False
    if z.direction not in ("long", "bottom", "low"):
        return False
    if z.type == "fractal":
        return regs.long_lo <= z.level <= regs.long_hi
    return z.hi >= regs.long_lo and z.lo <= regs.long_hi


def _extract_zone_features(
    zone: ActiveZone,
    cut_off_ts: pd.Timestamp,
    resampled: dict,
    helpers: dict,
    events_by_tf_type: dict,
    candle_ctx: dict,
    liq_count: int,
) -> dict | None:
    if zone.type not in TARGET_ELEMENTS:
        return None
    df_tf = resampled[zone.tf]
    atr_series = helpers[zone.tf]["atr"]
    hma_slope_series = helpers[zone.tf]["hma_slope"]
    mask = df_tf.index <= cut_off_ts
    if not mask.any():
        return None
    last_idx = df_tf.index[mask][-1]
    atr_val = float(atr_series.loc[last_idx]) if pd.notna(atr_series.loc[last_idx]) else 0.0
    hma_slope = float(hma_slope_series.loc[last_idx])

    width = zone.hi - zone.lo if zone.lo is not None else 0.0
    direction_match = F.encode_direction_match(zone, candle_ctx["is_bull"])
    htf_trend_match = F.encode_htf_trend_match(zone, hma_slope)

    base = {
        "direction_match": direction_match,
        "htf_trend_match": htf_trend_match,
        "candle_body_atr": candle_ctx["candle_body_atr"],
        "candle_range_atr": candle_ctx["candle_range_atr"],
        "candle_direction": candle_ctx["candle_direction"],
        "prior_n_bars_trend": candle_ctx["prior_n_bars_trend"],
        "liq_count_region": float(liq_count),
    }

    if zone.type == "FVG":
        base["age_bucket"] = F.encode_age_fvg(zone.age_bars)
        base["size_bucket"] = F.encode_size(width, atr_val)
        ev = events_by_tf_type.get((zone.tf, "FVG"), [])
        lookup = {(e["born_ts"], e["type"], e["direction"]): e for e in ev}
        orig = lookup.get((zone.born_ts, "FVG", zone.direction))
        if orig is None:
            return None
        original_width = orig["hi"] - orig["lo"]
        base["first_touch"] = F.fvg_first_touch(zone, df_tf, cut_off_ts, original_width)
        base["fill_state"] = F.fvg_fill_state(zone, df_tf, cut_off_ts)
        return base

    if zone.type == "fractal":
        base["age_bucket"] = F.encode_age_other(zone.age_bars)
        base["failed_attempts"] = F.fractal_failed_attempts(zone, df_tf, cut_off_ts)
        ev = events_by_tf_type.get((zone.tf, "fractal"), [])
        lookup = {(e["born_ts"], e["type"], e["direction"]): e for e in ev}
        orig = lookup.get((zone.born_ts, "fractal", zone.direction))
        if orig is None:
            return None
        center_idx = orig.get("center_idx", orig["born_idx"] - 2)
        if center_idx < F.ATR_PERIOD:
            return None
        atr_at_birth = float(atr_series.iloc[center_idx]) if pd.notna(atr_series.iloc[center_idx]) else 0.0
        wick_atr = F.fractal_wick_size_at_birth(df_tf, center_idx, atr_at_birth)
        base["wick_size_atr"] = int(wick_atr >= F.WICK_ATR_RATIO)
        return base

    if zone.type == "OB":
        base["age_bucket"] = F.encode_age_other(zone.age_bars)
        base["size_bucket"] = F.encode_size(width, atr_val)
        obvc_events = events_by_tf_type.get((zone.tf, "ob_vc"), [])
        has_vc = any(e["born_ts"] == zone.born_ts and e["direction"] == zone.direction for e in obvc_events)
        base["has_vc"] = int(has_vc)
        return base

    if zone.type in ("block_orders", "RDRB"):
        base["age_bucket"] = F.encode_age_other(zone.age_bars)
        base["size_bucket"] = F.encode_size(width, atr_val)
        return base

    return None


def build_datasets(
    df_1m: pd.DataFrame,
    tfs: tuple = SMC_TFS,
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    """
    Returns:
      datasets — dict[element_type → DataFrame] columns:
        tf, side ("short"|"long"), features..., target, candle_open_ts
      labels_12h — DataFrame с pivot-labels per 12h candle (is_fh, is_fl, confirm_ts)
    """
    print(f"[1/5] Resample 1m → {len(tfs)} TFs + precompute zone events...")
    # Need full ALL_TYPES scan to include ob_vc for has_vc feature
    types_to_scan = list(TARGET_ELEMENTS) + ["ob_vc"]
    # Use все tfs PLUS 8h subset if needed for ob_vc cross-TF logic.
    # But 8h not in our SMC_TFS for v3. ob_vc cross-TF может требовать другие LTFs автоматически — это OK.
    events_by_tf_type, resampled = precompute_zone_events(df_1m, tfs=tfs, types=types_to_scan)

    print(f"[2/5] Compute per-TF helpers...")
    helpers = _build_helpers(resampled)

    print("[3/5] Build 12h Williams (FH/FL) labels...")
    df_12h = resampled["12h"]
    labels_12h = label_williams_12h(df_12h, n=2)
    atr_12h = helpers["12h"]["atr"]
    prior_trend_12h = F.compute_prior_trend_slope(df_12h, F.PRIOR_TREND_BARS)

    print("[4/5] Iterate 12h candles → regions → directional rows...")
    rows_by_element = {e: [] for e in TARGET_ELEMENTS}
    confirmable = labels_12h["confirm_ts"].notna()
    n_candles = int(confirmable.sum())
    print(f"    candles to process: {n_candles}")

    for k, (open_ts, row) in enumerate(labels_12h.loc[confirmable].iterrows()):
        if k % 100 == 0 and k > 0:
            print(f"    {k}/{n_candles} ...")
        regs = compute_regions(df_12h, open_ts)
        if regs is None:
            continue
        if not regs.has_short and not regs.has_long:
            continue  # candle didn't extend beyond prior swing — skip

        atr12 = float(atr_12h.loc[open_ts]) if open_ts in atr_12h.index and pd.notna(atr_12h.loc[open_ts]) else 0.0
        ptrend = float(prior_trend_12h.loc[open_ts]) if open_ts in prior_trend_12h.index else 0.0
        if atr12 <= 0 or not np.isfinite(ptrend):
            continue
        candle_ctx = _candle_context(row, atr12, ptrend)

        zones_snapshot = snapshot_from_events(events_by_tf_type, resampled, df_1m, open_ts)
        zones_snapshot = [z for z in zones_snapshot if z.type in TARGET_ELEMENTS]

        # Compute liquidity counts per region (constant for all zone-rows of same candle/region)
        liq_short = 0
        liq_long = 0
        if regs.has_short:
            liq_short = F.liquidity_count_in_region_short(resampled, open_ts, regs.short_lo, regs.short_hi)
        if regs.has_long:
            liq_long = F.liquidity_count_in_region_long(resampled, open_ts, regs.long_lo, regs.long_hi)

        is_fh = int(bool(row["is_fh"]))
        is_fl = int(bool(row["is_fl"]))

        for z in zones_snapshot:
            # SHORT-side zones go into SHORT-region dataset
            if regs.has_short and _zone_in_short_region(z, regs):
                feats = _extract_zone_features(z, open_ts, resampled, helpers, events_by_tf_type, candle_ctx, liq_short)
                if feats is None:
                    continue
                feats["tf"] = z.tf
                feats["side"] = "short"
                feats["target"] = is_fh  # SHORT region → predict FH
                feats["candle_open_ts"] = open_ts
                rows_by_element[z.type].append(feats)
            # LONG-side zones go into LONG-region dataset
            if regs.has_long and _zone_in_long_region(z, regs):
                feats = _extract_zone_features(z, open_ts, resampled, helpers, events_by_tf_type, candle_ctx, liq_long)
                if feats is None:
                    continue
                feats["tf"] = z.tf
                feats["side"] = "long"
                feats["target"] = is_fl
                feats["candle_open_ts"] = open_ts
                rows_by_element[z.type].append(feats)

    print("[5/5] Pack to DataFrames...")
    datasets = {}
    for elem, rows in rows_by_element.items():
        if not rows:
            datasets[elem] = pd.DataFrame()
            continue
        df = pd.DataFrame(rows)
        feat_cols = FEATURES[elem]
        cols = ["tf", "side"] + feat_cols + ["target", "candle_open_ts"]
        for c in cols:
            if c not in df.columns:
                df[c] = 0
        datasets[elem] = df[cols]
    return datasets, labels_12h


def expand_to_cell_wise(df: pd.DataFrame, feat_cols: list[str], tfs: tuple = SMC_TFS) -> pd.DataFrame:
    """Per-feature × per-TF one-hot expansion. Returns N rows × (len(feat_cols)*len(tfs)) columns."""
    if df.empty:
        return df
    cells = {}
    for tf in tfs:
        mask = (df["tf"] == tf).to_numpy()
        for feat in feat_cols:
            col_name = f"{feat}__{tf}"
            vals = df[feat].to_numpy(dtype=float)
            cells[col_name] = np.where(mask, vals, 0.0)
    out = pd.DataFrame(cells, index=df.index)
    out["target"] = df["target"].to_numpy()
    out["candle_open_ts"] = df["candle_open_ts"].to_numpy()
    out["side"] = df["side"].to_numpy()
    return out
