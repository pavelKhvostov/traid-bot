"""Candle morphology features per req #5.

For each event, take cur + prev + n1 + n2 candles on multiple TFs.
For each candle:
  - range (high - low)
  - body |close - open|
  - upper_wick (high - max(open, close))
  - lower_wick (min(open, close) - low)
  - body_pct (body / range)
  - upper_wick_pct (upper_wick / range)
  - lower_wick_pct (lower_wick / range)
  - upper_to_body (upper_wick / body)
  - lower_to_body (lower_wick / body)
  - upper_to_lower (upper_wick / lower_wick)
  - is_bull (close > open)

Aggregates per TF (last 5 bars):
  - consecutive_bull_count
  - consecutive_bear_count
  - bull_bars_5 (count)
  - avg_body_5 (% of avg range)
  - body_range_ratio_avg_5
"""
from __future__ import annotations
import numpy as np


# Apply morphology on these TFs (subset for ML signal density)
MORPH_TFS = ["2h", "4h", "6h", "12h", "1d", "3d"]
CANDLE_OFFSETS = {"cur": 0, "prev": 1, "n1": 2, "n2": 3}


def _safe_div(num, den, default=np.nan):
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(np.abs(den) > 1e-12, num / den, default)


def build_candle_features_for_asset(bars: dict[str, np.ndarray],
                                      born_ms_array: np.ndarray) -> dict[str, np.ndarray]:
    n_events = len(born_ms_array)
    out = {}

    for tf in MORPH_TFS:
        if tf not in bars:
            continue
        bar_arr = bars[tf]
        ts_arr = bar_arr[:, 0].astype(np.int64)
        idx_at_event = np.searchsorted(ts_arr, born_ms_array, side="right") - 1

        # For each offset: compute morphology of that candle
        for label, offset in CANDLE_OFFSETS.items():
            idx = idx_at_event - offset
            valid = (idx >= 0) & (idx < len(bar_arr))

            opens = np.full(n_events, np.nan)
            highs = np.full(n_events, np.nan)
            lows  = np.full(n_events, np.nan)
            closes = np.full(n_events, np.nan)
            opens[valid] = bar_arr[idx[valid], 1]
            highs[valid] = bar_arr[idx[valid], 2]
            lows[valid] = bar_arr[idx[valid], 3]
            closes[valid] = bar_arr[idx[valid], 4]

            range_ = highs - lows
            body = np.abs(closes - opens)
            upper = highs - np.maximum(opens, closes)
            lower = np.minimum(opens, closes) - lows

            prefix = f"c_{tf}_{label}"
            out[f"{prefix}_range"] = range_
            out[f"{prefix}_body"] = body
            out[f"{prefix}_upper_wick"] = upper
            out[f"{prefix}_lower_wick"] = lower
            out[f"{prefix}_body_pct"] = _safe_div(body, range_)
            out[f"{prefix}_upper_pct"] = _safe_div(upper, range_)
            out[f"{prefix}_lower_pct"] = _safe_div(lower, range_)
            out[f"{prefix}_upper_to_body"] = _safe_div(upper, body)
            out[f"{prefix}_lower_to_body"] = _safe_div(lower, body)
            out[f"{prefix}_upper_to_lower"] = _safe_div(upper, lower)
            out[f"{prefix}_is_bull"] = (closes > opens).astype(np.float64)
            out[f"{prefix}_is_bull"][~valid] = np.nan

        # Aggregates per TF: stats over last 5 bars before event
        consec_bull = np.full(n_events, np.nan)
        consec_bear = np.full(n_events, np.nan)
        bull5 = np.full(n_events, np.nan)
        avg_body_pct_5 = np.full(n_events, np.nan)

        for i, idx in enumerate(idx_at_event):
            if idx < 4:
                continue
            window = bar_arr[idx-4:idx+1]  # last 5 bars including cur
            is_bull_seq = (window[:, 4] > window[:, 1]).astype(int)
            bull5[i] = int(is_bull_seq.sum())

            # consecutive bull/bear ending at current bar
            cnt_bull = 0
            for k in range(len(is_bull_seq) - 1, -1, -1):
                if is_bull_seq[k] == 1: cnt_bull += 1
                else: break
            cnt_bear = 0
            for k in range(len(is_bull_seq) - 1, -1, -1):
                if is_bull_seq[k] == 0: cnt_bear += 1
                else: break
            consec_bull[i] = cnt_bull
            consec_bear[i] = cnt_bear

            ranges = window[:, 2] - window[:, 3]
            bodies = np.abs(window[:, 4] - window[:, 1])
            if (ranges > 1e-9).all():
                avg_body_pct_5[i] = (bodies / ranges).mean()

        out[f"c_{tf}_consec_bull_5"] = consec_bull
        out[f"c_{tf}_consec_bear_5"] = consec_bear
        out[f"c_{tf}_bull_count_5"] = bull5
        out[f"c_{tf}_avg_body_pct_5"] = avg_body_pct_5

    return out
