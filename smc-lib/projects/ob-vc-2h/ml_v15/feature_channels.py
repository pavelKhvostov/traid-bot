"""Build per-channel features for all ob_vc events.

Channels:
  - Funding rate (per asset)
  - OI (per asset)
  - DVOL (per asset)
  - Cross-asset: ETHBTC, DXY, US10Y, SPX, GOLD (shared across BTC/ETH events)
  - Macro events: hours_to_next/hours_since for FOMC/CPI/NFP

Output: pd.DataFrame, one row per event, N feature columns.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

from data_loaders import (
    load_funding, load_oi, load_dvol, load_cross, load_macro, CROSS_NAMES
)
from quasi_seq import quasi_seq_features


def build_channel_features(events: pd.DataFrame) -> pd.DataFrame:
    """events must have columns: asset, born_ms.

    Returns: pd.DataFrame indexed same as events, with feature columns added.
    """
    born_ms = events["born_ms"].to_numpy(dtype=np.int64)
    feat = {}

    # ─── Per-asset channels (funding, OI, DVOL) ─────
    for asset in ("BTC", "ETH"):
        mask = (events["asset"].values == asset)
        if mask.sum() == 0:
            continue
        born_subset = born_ms[mask]

        # Funding
        f = load_funding(asset)
        if not f.empty:
            ff = quasi_seq_features(
                f, "funding_time_ms", ["funding_rate"], born_subset,
                channel_prefix=f"fund_{asset.lower()}")
            for k, v in ff.items():
                full = np.full(len(events), np.nan)
                full[mask] = v
                feat[k] = full

        # OI
        oi = load_oi(asset)
        if not oi.empty:
            ff = quasi_seq_features(
                oi, "ts_ms", ["open_interest_coin"], born_subset,
                channel_prefix=f"oi_{asset.lower()}")
            for k, v in ff.items():
                full = np.full(len(events), np.nan)
                full[mask] = v
                feat[k] = full

        # DVOL (1h ohlc — use close only for simplicity)
        d = load_dvol(asset)
        if not d.empty:
            ff = quasi_seq_features(
                d, "ts_ms", ["close"], born_subset,
                channel_prefix=f"dvol_{asset.lower()}")
            for k, v in ff.items():
                full = np.full(len(events), np.nan)
                full[mask] = v
                feat[k] = full

    # ─── Cross-asset (shared across all events) ─────
    for name in CROSS_NAMES:
        c = load_cross(name)
        if c.empty:
            continue
        ff = quasi_seq_features(
            c, "ts_ms", ["close"], born_ms,
            channel_prefix=f"cross_{name.lower()}")
        feat.update(ff)

    # ─── Macro events ───────────────────────────────
    macro_feats = build_macro_features(born_ms)
    feat.update(macro_feats)

    df_feat = pd.DataFrame(feat, index=events.index)
    return df_feat


def build_macro_features(born_ms_array: np.ndarray) -> dict[str, np.ndarray]:
    """For each event, compute hours_to_next_{type} and hours_since_last_{type}."""
    m = load_macro()
    out = {}
    if m.empty:
        return out

    event_ms = m["event_ms"].to_numpy()
    event_types = m["event_type"].to_numpy()

    HOUR_MS = 3_600_000

    for evt_type in ("FOMC", "CPI", "NFP"):
        mask = event_types == evt_type
        if mask.sum() == 0:
            continue
        ts_evt = event_ms[mask]
        # hours_to_next: smallest ts_evt > born
        to_next = np.full(len(born_ms_array), np.nan)
        since_last = np.full(len(born_ms_array), np.nan)
        for i, b in enumerate(born_ms_array):
            nxt_idx = np.searchsorted(ts_evt, b, side="right")
            if nxt_idx < len(ts_evt):
                to_next[i] = (ts_evt[nxt_idx] - b) / HOUR_MS
            if nxt_idx > 0:
                since_last[i] = (b - ts_evt[nxt_idx - 1]) / HOUR_MS
        out[f"macro_hours_to_next_{evt_type.lower()}"] = to_next
        out[f"macro_hours_since_last_{evt_type.lower()}"] = since_last

    # within ±48h of any event = boolean
    any_evt = np.full(len(born_ms_array), 0, dtype=np.int8)
    for i, b in enumerate(born_ms_array):
        # check any event within ±48h
        win_lo = b - 48 * HOUR_MS
        win_hi = b + 48 * HOUR_MS
        lo_idx = np.searchsorted(event_ms, win_lo, side="left")
        hi_idx = np.searchsorted(event_ms, win_hi, side="right")
        if hi_idx > lo_idx:
            any_evt[i] = 1
    out["macro_in_event_window_48h"] = any_evt.astype(np.float64)

    return out
