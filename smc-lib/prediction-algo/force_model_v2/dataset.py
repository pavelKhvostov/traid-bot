"""
Build per-element datasets для force-model v2.

Output: dict[element_type → pd.DataFrame], где каждая строка — одна (12h candle, active zone)
пара со всеми feature-полями + target.

Encoding для cell-wise interaction (9 features × 9 TFs = 81 columns на zone-row):
  каждая base feature раскрывается в 9 TF-specific колонок (one-hot по TF зоны).
  В строке value ставится только в TF[zone.tf], остальные 8 = 0.
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

from force_model_v2 import features as F  # noqa: E402
from force_model_v2.labeling import label_williams_12h  # noqa: E402


SMC_TFS = ("1h", "2h", "4h", "6h", "12h", "1d", "2d", "3d")  # 8h убран 2026-06-03
TARGET_ELEMENTS = ("FVG", "fractal", "OB", "block_orders", "RDRB")

# Feature lists per element type. Порядок ВАЖЕН — он определяет column-mapping.
FEATURES = {
    "FVG": [
        "age_bucket", "first_touch", "fill_state", "size_bucket",
        "direction_match", "htf_trend_match",
        "candle_body_atr", "candle_range_atr", "candle_direction",
    ],
    "fractal": [
        "age_bucket", "failed_attempts", "wick_size_atr",
        "direction_match", "htf_trend_match",
        "candle_body_atr", "candle_range_atr", "candle_direction",
        "prior_n_bars_trend",
    ],
    "OB": [
        "age_bucket", "has_vc", "size_bucket",
        "direction_match", "htf_trend_match",
        "candle_body_atr", "candle_range_atr", "candle_direction",
        "prior_n_bars_trend",
    ],
    "block_orders": [
        "age_bucket", "size_bucket",
        "direction_match", "htf_trend_match",
        "candle_body_atr", "candle_range_atr", "candle_direction",
        "prior_n_bars_trend",
    ],
    "RDRB": [
        "age_bucket", "size_bucket",
        "direction_match", "htf_trend_match",
        "candle_body_atr", "candle_range_atr", "candle_direction",
        "prior_n_bars_trend",
    ],
}


def _event_lookup(events: list[dict]) -> dict[tuple, dict]:
    """Build (born_ts, type, direction) → event dict для быстрого lookup из ActiveZone."""
    return {(ev["born_ts"], ev["type"], ev["direction"]): ev for ev in events}


def _build_per_tf_helpers(resampled: dict[str, pd.DataFrame]) -> dict[str, dict]:
    """Pre-compute ATR / HMA-slope per TF. Returns {tf: {"atr": Series, "hma_slope": Series}}."""
    out = {}
    for tf, df_tf in resampled.items():
        atr = F.compute_atr(df_tf, F.ATR_PERIOD)
        hma_slope = F.compute_hma_slope(df_tf, F.HMA_PERIOD)
        out[tf] = {"atr": atr, "hma_slope": hma_slope}
    return out


def _candle_context(row_12h: pd.Series, atr_12h: float, prior_trend: float) -> dict:
    """Context features про саму 12h свечу (общие для всех её zone-rows)."""
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
        "prior_n_bars_trend": float(prior_trend) if prior_trend == prior_trend else 0.0,  # NaN-safe
        "is_bull": c > o,
    }


def _extract_zone_features(
    zone: ActiveZone,
    cut_off_ts: pd.Timestamp,
    resampled: dict[str, pd.DataFrame],
    helpers: dict[str, dict],
    events_by_tf_type: dict[tuple, list[dict]],
    candle_ctx: dict,
) -> dict | None:
    """Извлечь feature dict для одной зоны под element_type или None если zone не нужен."""
    if zone.type not in TARGET_ELEMENTS:
        return None
    df_tf = resampled[zone.tf]
    atr_series = helpers[zone.tf]["atr"]
    hma_slope_series = helpers[zone.tf]["hma_slope"]
    # ATR / HMA slope в момент cut_off_ts (последнее значение ≤ cut_off на TF)
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
    }

    if zone.type == "FVG":
        base["age_bucket"] = F.encode_age_fvg(zone.age_bars)
        base["size_bucket"] = F.encode_size(width, atr_val)
        # Lookup original width via event
        ev = events_by_tf_type.get((zone.tf, "FVG"), [])
        lookup = _event_lookup(ev)
        key = (zone.born_ts, "FVG", zone.direction)
        orig = lookup.get(key)
        if orig is None:
            return None
        original_width = orig["hi"] - orig["lo"]
        base["first_touch"] = F.fvg_first_touch(zone, df_tf, cut_off_ts, original_width)
        base["fill_state"] = F.fvg_fill_state(zone, df_tf, cut_off_ts)
        return base

    if zone.type == "fractal":
        base["age_bucket"] = F.encode_age_other(zone.age_bars)
        base["failed_attempts"] = F.fractal_failed_attempts(zone, df_tf, cut_off_ts)
        # wick_size_atr: wick на born candle / ATR в момент born
        ev = events_by_tf_type.get((zone.tf, "fractal"), [])
        lookup = _event_lookup(ev)
        key = (zone.born_ts, "fractal", zone.direction)
        orig = lookup.get(key)
        if orig is None:
            return None
        center_idx = orig.get("center_idx", orig["born_idx"] - 2)  # fractal center = born_idx - n
        if center_idx < F.ATR_PERIOD:
            return None
        # ATR at center bar
        atr_at_birth = float(atr_series.iloc[center_idx]) if pd.notna(atr_series.iloc[center_idx]) else 0.0
        wick_atr = F.fractal_wick_size_at_birth(df_tf, center_idx, atr_at_birth)
        base["wick_size_atr"] = int(wick_atr >= F.WICK_ATR_RATIO)
        return base

    if zone.type == "OB":
        base["age_bucket"] = F.encode_age_other(zone.age_bars)
        base["size_bucket"] = F.encode_size(width, atr_val)
        # has_vc: есть ли ob_vc event с тем же (tf, born_ts)
        ob_vc_events = events_by_tf_type.get((zone.tf, "ob_vc"), [])
        has_vc = any(ev["born_ts"] == zone.born_ts and ev["direction"] == zone.direction for ev in ob_vc_events)
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
    Главная функция: построить 5 per-element DataFrames + labeled 12h DataFrame.

    Returns:
      datasets — dict[element_type → DataFrame] с колонками:
        - tf (zone TF)
        - все base features (см. FEATURES[element_type])
        - target (1 = candle 12h is Williams pivot, 0 = no)
        - candle_open_ts (для walk-forward split)
      labels_12h — DataFrame с pivot-labels для каждой 12h свечи
    """
    print(f"[1/5] Resample 1m → {len(tfs)} TFs + precompute zone events...")
    types_to_scan = list(TARGET_ELEMENTS) + ["ob_vc"]  # ob_vc для has_vc feature
    events_by_tf_type, resampled = precompute_zone_events(df_1m, tfs=tfs, types=types_to_scan)

    print(f"[2/5] Compute per-TF helpers (ATR{F.ATR_PERIOD}, HMA{F.HMA_PERIOD})...")
    helpers = _build_per_tf_helpers(resampled)

    print("[3/5] Build 12h Williams labels...")
    df_12h = resampled["12h"]
    labels_12h = label_williams_12h(df_12h, n=2)
    atr_12h = helpers["12h"]["atr"]
    prior_trend_12h = F.compute_prior_trend_slope(df_12h, F.PRIOR_TREND_BARS)

    print("[4/5] Iterate 12h candles, snapshot zones, extract features...")
    rows_by_element: dict[str, list[dict]] = {e: [] for e in TARGET_ELEMENTS}
    confirmable_mask = labels_12h["confirm_ts"].notna()
    n_candles = int(confirmable_mask.sum())
    print(f"    candles to process: {n_candles}")

    for k, (open_ts, row) in enumerate(labels_12h.loc[confirmable_mask].iterrows()):
        if k % 100 == 0 and k > 0:
            print(f"    {k}/{n_candles} ...")
        # cut_off_ts = open_ts свечи (до её движения). Снапшот зон ДО формирования свечи.
        # Но context features (body/range/direction) считаем ПОСЛЕ её закрытия — это retrospective,
        # leak в pivot label НЕТ (label requires +n*12h confirmation).
        zones_snapshot = snapshot_from_events(events_by_tf_type, resampled, df_1m, open_ts)
        if not zones_snapshot:
            continue
        # ATR / prior_trend на 12h в момент открытия свечи
        atr12 = float(atr_12h.loc[open_ts]) if open_ts in atr_12h.index and pd.notna(atr_12h.loc[open_ts]) else 0.0
        ptrend = float(prior_trend_12h.loc[open_ts]) if open_ts in prior_trend_12h.index else 0.0
        if atr12 <= 0 or not np.isfinite(ptrend):
            continue
        candle_ctx = _candle_context(row, atr12, ptrend)
        target = int(bool(row["is_pivot"]))

        for zone in zones_snapshot:
            if zone.type not in TARGET_ELEMENTS:
                continue
            feats = _extract_zone_features(zone, open_ts, resampled, helpers, events_by_tf_type, candle_ctx)
            if feats is None:
                continue
            feats["tf"] = zone.tf
            feats["target"] = target
            feats["candle_open_ts"] = open_ts
            rows_by_element[zone.type].append(feats)

    print("[5/5] Pack to DataFrames...")
    datasets = {}
    for elem, rows in rows_by_element.items():
        if not rows:
            datasets[elem] = pd.DataFrame()
            continue
        df = pd.DataFrame(rows)
        # Reorder columns: tf, features..., target, candle_open_ts
        feat_cols = FEATURES[elem]
        cols = ["tf"] + feat_cols + ["target", "candle_open_ts"]
        # Some features (e.g. fractal-specific) may be missing for other rows — defensive
        for c in cols:
            if c not in df.columns:
                df[c] = 0
        datasets[elem] = df[cols]

    return datasets, labels_12h


def expand_to_cell_wise(df: pd.DataFrame, feat_cols: list[str], tfs: tuple = SMC_TFS) -> pd.DataFrame:
    """
    Expand zone-row → cell-wise representation (9 features × 9 TFs = 81 columns).

    Каждая колонка `{feature}__{tf}` содержит значение feature если zone.tf == tf, иначе 0.
    """
    if df.empty:
        return df
    n = len(df)
    cells = {}
    for tf in tfs:
        mask = (df["tf"] == tf).to_numpy()
        for feat in feat_cols:
            col_name = f"{feat}__{tf}"
            vals = df[feat].to_numpy(dtype=float)
            cells[col_name] = np.where(mask, vals, 0.0)
    expanded = pd.DataFrame(cells, index=df.index)
    # carry forward target + candle_open_ts для downstream
    expanded["target"] = df["target"].to_numpy()
    expanded["candle_open_ts"] = df["candle_open_ts"].to_numpy()
    return expanded
