"""Candle structure features per TF — body, wicks, marubozu, relative size.

ВСЕ значения вычисляются HONEST на LAST CLOSED bar at entry_ms (для каждого TF
отдельный closed_idx). Для текущего in-progress бара — НЕ берём (это уже captured
в wait-window).

Per TF (11 TFs), per derivative:
  body_pct                — |close-open| / range  (0-1)
  upper_wick_pct          — (high - max(open,close)) / range
  lower_wick_pct          — (min(open,close) - low) / range
  is_bull                 — close > open (binary)
  is_marubozu             — body_pct >= 0.95 (binary)
  range_norm_atr20        — range / ATR(20) on this TF
  body_vs_prev3_avg       — |close-open| / mean(|close-open|) for last 3 bars
"""
from __future__ import annotations
import numpy as np

from ._common import TF_SPECS


def build_candle_features(bars: dict[str, np.ndarray],
                            entry_ms_array: np.ndarray) -> dict[str, np.ndarray]:
    """For each event, compute candle features at LAST CLOSED bar of each TF."""
    n_events = len(entry_ms_array)
    out: dict[str, np.ndarray] = {}
    valid_event = entry_ms_array > 0

    for tf, bar_arr in bars.items():
        tf_ms = TF_SPECS[tf]
        ts_arr = bar_arr[:, 0].astype(np.int64)
        opens = bar_arr[:, 1]; highs = bar_arr[:, 2]
        lows = bar_arr[:, 3]; closes = bar_arr[:, 4]

        # Honest closed_idx: open + tf_ms <= entry_ms
        closed_idx = np.full(n_events, -1, dtype=np.int64)
        if valid_event.any():
            cutoff = entry_ms_array[valid_event] - tf_ms
            closed_idx[valid_event] = np.searchsorted(ts_arr, cutoff, side="right") - 1
        valid = (closed_idx >= 0) & valid_event

        # Slice values
        v_open = np.full(n_events, np.nan)
        v_high = np.full(n_events, np.nan)
        v_low = np.full(n_events, np.nan)
        v_close = np.full(n_events, np.nan)
        v_open[valid] = opens[closed_idx[valid]]
        v_high[valid] = highs[closed_idx[valid]]
        v_low[valid] = lows[closed_idx[valid]]
        v_close[valid] = closes[closed_idx[valid]]

        rng = v_high - v_low
        body = np.abs(v_close - v_open)
        with np.errstate(divide="ignore", invalid="ignore"):
            body_pct = np.where(rng > 1e-9, body / rng, 0.0)
            upper_wick = v_high - np.maximum(v_open, v_close)
            upper_wick_pct = np.where(rng > 1e-9, upper_wick / rng, 0.0)
            lower_wick = np.minimum(v_open, v_close) - v_low
            lower_wick_pct = np.where(rng > 1e-9, lower_wick / rng, 0.0)
            is_bull = (v_close > v_open).astype(np.float64)
            is_bull[~valid] = np.nan
            is_marubozu = (body_pct >= 0.95).astype(np.float64)
            is_marubozu[~valid] = np.nan

        # ATR-normalized range (ATR-20 on this TF)
        atr_period = 20
        range_norm_atr = np.full(n_events, np.nan)
        if len(closes) >= atr_period + 1:
            # True range per bar
            tr = np.maximum.reduce([
                highs[1:] - lows[1:],
                np.abs(highs[1:] - closes[:-1]),
                np.abs(lows[1:] - closes[:-1]),
            ])
            atr = np.convolve(tr, np.ones(atr_period) / atr_period, mode="full")[:len(tr)]
            atr_padded = np.concatenate([[np.nan] * (atr_period), atr[atr_period - 1:]])
            # atr_padded[i] corresponds to atr for bar i (using bars 0..i)
            for i in np.where(valid)[0]:
                ci = closed_idx[i]
                if ci < atr_period: continue
                atr_v = atr_padded[ci] if ci < len(atr_padded) else np.nan
                if not np.isnan(atr_v) and atr_v > 1e-9:
                    range_norm_atr[i] = rng[i] / atr_v

        # Body vs 3-bar avg
        body_vs_prev3 = np.full(n_events, np.nan)
        if len(closes) >= 4:
            for i in np.where(valid)[0]:
                ci = closed_idx[i]
                if ci < 3: continue
                prev3_bodies = np.abs(closes[ci-3:ci] - opens[ci-3:ci])
                avg = prev3_bodies.mean()
                if avg > 1e-9:
                    body_vs_prev3[i] = body[i] / avg

        prefix = f"candle_{tf}"
        out[f"{prefix}_body_pct"] = body_pct
        out[f"{prefix}_upper_wick_pct"] = upper_wick_pct
        out[f"{prefix}_lower_wick_pct"] = lower_wick_pct
        out[f"{prefix}_is_bull"] = is_bull
        out[f"{prefix}_is_marubozu"] = is_marubozu
        out[f"{prefix}_range_norm_atr"] = range_norm_atr
        out[f"{prefix}_body_vs_prev3"] = body_vs_prev3

    return out
