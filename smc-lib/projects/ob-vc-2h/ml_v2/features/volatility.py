"""Volatility regime features per req #11.

Per TF:
  - atr_14                       current ATR(14)
  - atr_z30, atr_z90             z-score vs rolling window
  - atr_percentile_100           ATR percentile in last 100 bars
  - atr_compression_bars         consecutive bars ATR declining
  - atr_expansion_bars           consecutive bars ATR rising
  - realized_vol_30              std(returns) last 30 bars
  - vol_of_vol_30                std(ATR) last 30 bars
  - bb_width_pct                 Bollinger width as % of close
  - bb_squeeze                   bool: BB width < 0.5 * 30-bar avg
"""
from __future__ import annotations
import numpy as np


VOL_TFS = ["1h", "2h", "4h", "6h", "12h", "1d", "3d"]


def compute_atr_series(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
                        period: int = 14) -> np.ndarray:
    """ATR Wilder series."""
    n = len(closes)
    tr = np.empty(n)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        tr[i] = max(highs[i] - lows[i],
                     abs(highs[i] - closes[i-1]),
                     abs(lows[i] - closes[i-1]))
    atr = np.full(n, np.nan)
    if n < period: return atr
    atr[period-1] = tr[:period].mean()
    for i in range(period, n):
        atr[i] = (atr[i-1] * (period-1) + tr[i]) / period
    return atr


def build_volatility_features_for_asset(bars: dict[str, np.ndarray],
                                          born_ms_array: np.ndarray) -> dict[str, np.ndarray]:
    n_events = len(born_ms_array)
    out = {}

    for tf in VOL_TFS:
        if tf not in bars: continue
        bar_arr = bars[tf]
        ts_arr = bar_arr[:, 0].astype(np.int64)
        opens = bar_arr[:, 1]
        highs = bar_arr[:, 2]
        lows = bar_arr[:, 3]
        closes = bar_arr[:, 4]

        atr_arr = compute_atr_series(highs, lows, closes, 14)
        idx_at_event = np.searchsorted(ts_arr, born_ms_array, side="right") - 1

        # Outputs
        atr_14 = np.full(n_events, np.nan)
        atr_z30 = np.full(n_events, np.nan)
        atr_z90 = np.full(n_events, np.nan)
        atr_pct_100 = np.full(n_events, np.nan)
        atr_compress = np.full(n_events, np.nan)
        atr_expand = np.full(n_events, np.nan)
        rv_30 = np.full(n_events, np.nan)
        vov_30 = np.full(n_events, np.nan)
        bb_width = np.full(n_events, np.nan)
        bb_squeeze = np.full(n_events, np.nan)

        for i, idx in enumerate(idx_at_event):
            if idx < 14:
                continue
            cur_atr = atr_arr[idx]
            atr_14[i] = cur_atr
            if np.isnan(cur_atr):
                continue

            # z-score
            if idx >= 30:
                win = atr_arr[idx-30:idx]
                m, s = np.nanmean(win), np.nanstd(win)
                if s > 1e-9:
                    atr_z30[i] = (cur_atr - m) / s
            if idx >= 90:
                win = atr_arr[idx-90:idx]
                m, s = np.nanmean(win), np.nanstd(win)
                if s > 1e-9:
                    atr_z90[i] = (cur_atr - m) / s

            # percentile in last 100
            if idx >= 100:
                win = atr_arr[idx-100:idx]
                win_valid = win[~np.isnan(win)]
                if len(win_valid) > 5:
                    atr_pct_100[i] = (win_valid < cur_atr).sum() / len(win_valid)

            # compression/expansion bars
            comp_len = 0
            for k in range(idx, max(0, idx-30), -1):
                if k == 0: break
                if not np.isnan(atr_arr[k]) and not np.isnan(atr_arr[k-1]):
                    if atr_arr[k] < atr_arr[k-1]:
                        comp_len += 1
                    else:
                        break
                else:
                    break
            atr_compress[i] = comp_len

            exp_len = 0
            for k in range(idx, max(0, idx-30), -1):
                if k == 0: break
                if not np.isnan(atr_arr[k]) and not np.isnan(atr_arr[k-1]):
                    if atr_arr[k] > atr_arr[k-1]:
                        exp_len += 1
                    else:
                        break
                else:
                    break
            atr_expand[i] = exp_len

            # realized vol (std of log returns last 30)
            if idx >= 30:
                sub = closes[idx-30:idx+1]
                rets = np.diff(np.log(sub + 1e-12))
                rv_30[i] = float(np.std(rets) * 100)
                # vol-of-vol
                vov_30[i] = float(np.nanstd(atr_arr[idx-30:idx+1]))

            # BB width 20 + squeeze
            if idx >= 20:
                sub = closes[idx-19:idx+1]
                m, s = np.mean(sub), np.std(sub)
                if closes[idx] > 1e-9:
                    bb_width[i] = (4 * s) / closes[idx] * 100  # ± 2σ band
                # squeeze vs 30-bar avg BB width
                if idx >= 50:
                    widths = []
                    for k in range(idx-30, idx):
                        ssub = closes[k-19:k+1]
                        if len(ssub) >= 20:
                            ws = np.std(ssub)
                            widths.append(4 * ws / max(closes[k], 1e-9) * 100)
                    if widths:
                        avg_w = np.mean(widths)
                        bb_squeeze[i] = 1.0 if bb_width[i] < 0.5 * avg_w else 0.0

        prefix = f"vol_{tf}"
        out[f"{prefix}_atr_14"] = atr_14
        out[f"{prefix}_atr_z30"] = atr_z30
        out[f"{prefix}_atr_z90"] = atr_z90
        out[f"{prefix}_atr_pct_100"] = atr_pct_100
        out[f"{prefix}_compression_bars"] = atr_compress
        out[f"{prefix}_expansion_bars"] = atr_expand
        out[f"{prefix}_realized_vol_30"] = rv_30
        out[f"{prefix}_vov_30"] = vov_30
        out[f"{prefix}_bb_width_pct"] = bb_width
        out[f"{prefix}_bb_squeeze"] = bb_squeeze

    return out
