"""Pulse / rhythm features per req #13.

Per TF:
  - bar_size_slope_5     linregress slope on last 5 |body| sizes (acceleration)
  - range_accel          current range vs avg of last 5 ranges
  - efficiency_ratio_20  net price move / sum of bar movements (chop indicator)
  - pulse_amplitude_20   max-min of close over 20 bars (oscillation amplitude)
  - vol_pulse_pattern    alternating high-low volume (oscillation)
  - inter_bar_acceleration  body[i]/body[i-1] avg over 5 bars
"""
from __future__ import annotations
import numpy as np


RHYTHM_TFS = ["2h", "4h", "6h", "12h", "1d"]


def build_rhythm_features_for_asset(bars: dict[str, np.ndarray],
                                      born_ms_array: np.ndarray) -> dict[str, np.ndarray]:
    n_events = len(born_ms_array)
    out = {}

    for tf in RHYTHM_TFS:
        if tf not in bars: continue
        bar_arr = bars[tf]
        ts_arr = bar_arr[:, 0].astype(np.int64)
        opens = bar_arr[:, 1]
        highs = bar_arr[:, 2]
        lows = bar_arr[:, 3]
        closes = bar_arr[:, 4]
        volumes = bar_arr[:, 5]
        idx_at_event = np.searchsorted(ts_arr, born_ms_array, side="right") - 1

        bar_size_slope = np.full(n_events, np.nan)
        range_accel = np.full(n_events, np.nan)
        efficiency = np.full(n_events, np.nan)
        pulse_amp = np.full(n_events, np.nan)
        vol_pulse = np.full(n_events, np.nan)
        inter_bar_accel = np.full(n_events, np.nan)

        for i, idx in enumerate(idx_at_event):
            if idx < 20:
                continue
            # bar_size slope on last 5 |body|
            sub_body = np.abs(closes[idx-4:idx+1] - opens[idx-4:idx+1])
            x = np.arange(5, dtype=np.float64)
            if sub_body.std() > 1e-9:
                slope, _ = np.polyfit(x, sub_body, 1)
                bar_size_slope[i] = float(slope)

            # range_accel: current range vs avg of last 5
            ranges = highs[idx-4:idx+1] - lows[idx-4:idx+1]
            cur_r = ranges[-1]
            avg_r = ranges[:-1].mean()
            if avg_r > 1e-9:
                range_accel[i] = cur_r / avg_r

            # efficiency ratio 20: |close[end] - close[start]| / Σ|close[i] - close[i-1]|
            sub_close = closes[idx-19:idx+1]
            denom = np.sum(np.abs(np.diff(sub_close)))
            if denom > 1e-9:
                efficiency[i] = abs(sub_close[-1] - sub_close[0]) / denom

            # pulse amplitude: (max - min) of close over 20 bars / current close
            sub_close20 = closes[idx-19:idx+1]
            if closes[idx] > 1e-9:
                pulse_amp[i] = (sub_close20.max() - sub_close20.min()) / closes[idx] * 100

            # vol pulse: count alternating high-low pairs
            sub_vol = volumes[idx-9:idx+1]
            alts = 0
            for k in range(1, len(sub_vol) - 1):
                if (sub_vol[k] > sub_vol[k-1] and sub_vol[k] > sub_vol[k+1]) or \
                   (sub_vol[k] < sub_vol[k-1] and sub_vol[k] < sub_vol[k+1]):
                    alts += 1
            vol_pulse[i] = alts / max(1, len(sub_vol) - 2)

            # inter_bar accel: mean(body[k] / body[k-1])
            sub_body6 = np.abs(closes[idx-5:idx+1] - opens[idx-5:idx+1])
            ratios = []
            for k in range(1, len(sub_body6)):
                if sub_body6[k-1] > 1e-9:
                    ratios.append(sub_body6[k] / sub_body6[k-1])
            if ratios:
                inter_bar_accel[i] = float(np.mean(ratios))

        prefix = f"rhy_{tf}"
        out[f"{prefix}_bar_size_slope_5"] = bar_size_slope
        out[f"{prefix}_range_accel"] = range_accel
        out[f"{prefix}_efficiency_20"] = efficiency
        out[f"{prefix}_pulse_amp_20"] = pulse_amp
        out[f"{prefix}_vol_pulse_pattern"] = vol_pulse
        out[f"{prefix}_inter_bar_accel"] = inter_bar_accel

    return out
