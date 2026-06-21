"""Tension/release features per req #16 — compression chains, BB squeeze, range decay.

Per TF:
  - atr_compression_chain    consecutive bars ATR declining (req #11 already has but here we add chain)
  - range_decay_5            slope of 5-bar range linregress (negative = compressing)
  - range_decay_10
  - narrow_range_bars        consecutive bars with range < 0.5 * avg_range_30
  - bb_squeeze_chain         consecutive bars BB width < 0.5 * 30-avg
  - silence_score            combo: low ATR + low vol + flat HMA — stored tension
  - expansion_signal         opposite of silence — ready to release
"""
from __future__ import annotations
import numpy as np

from .volatility import compute_atr_series


TENS_TFS = ["2h", "4h", "6h", "12h", "1d"]


def build_tension_features_for_asset(bars: dict[str, np.ndarray],
                                       born_ms_array: np.ndarray) -> dict[str, np.ndarray]:
    n_events = len(born_ms_array)
    out = {}

    for tf in TENS_TFS:
        if tf not in bars: continue
        bar_arr = bars[tf]
        ts_arr = bar_arr[:, 0].astype(np.int64)
        opens = bar_arr[:, 1]
        highs = bar_arr[:, 2]
        lows = bar_arr[:, 3]
        closes = bar_arr[:, 4]
        volumes = bar_arr[:, 5]
        idx_at_event = np.searchsorted(ts_arr, born_ms_array, side="right") - 1

        atr_arr = compute_atr_series(highs, lows, closes, 14)
        ranges = highs - lows

        atr_compression = np.full(n_events, np.nan)
        range_decay_5 = np.full(n_events, np.nan)
        range_decay_10 = np.full(n_events, np.nan)
        narrow_range_bars = np.full(n_events, np.nan)
        bb_sqz_chain = np.full(n_events, np.nan)
        silence_score = np.full(n_events, np.nan)
        expansion_signal = np.full(n_events, np.nan)

        for i, idx in enumerate(idx_at_event):
            if idx < 30: continue

            # ATR compression chain
            chain = 0
            for k in range(idx, max(0, idx - 30), -1):
                if k == 0: break
                if not np.isnan(atr_arr[k]) and not np.isnan(atr_arr[k-1]):
                    if atr_arr[k] < atr_arr[k-1]:
                        chain += 1
                    else:
                        break
                else:
                    break
            atr_compression[i] = chain

            # range_decay slope (linregress)
            sub_r5 = ranges[idx-4:idx+1]
            x5 = np.arange(5, dtype=np.float64)
            slope5, _ = np.polyfit(x5, sub_r5, 1)
            range_decay_5[i] = float(slope5)
            sub_r10 = ranges[idx-9:idx+1]
            x10 = np.arange(10, dtype=np.float64)
            slope10, _ = np.polyfit(x10, sub_r10, 1)
            range_decay_10[i] = float(slope10)

            # narrow range bars chain
            avg_r30 = ranges[idx-30:idx].mean()
            nrb = 0
            for k in range(idx, max(0, idx-30), -1):
                if ranges[k] < 0.5 * avg_r30:
                    nrb += 1
                else:
                    break
            narrow_range_bars[i] = nrb

            # BB squeeze chain
            chain_bb = 0
            for k in range(idx, max(20, idx-30), -1):
                sub = closes[k-19:k+1]
                if len(sub) < 20: break
                s = np.std(sub)
                bb_w = 4 * s / max(closes[k], 1e-9) * 100
                if k > 50:
                    widths = []
                    for kk in range(k-30, k):
                        ssub = closes[kk-19:kk+1]
                        if len(ssub) >= 20:
                            ws = np.std(ssub)
                            widths.append(4 * ws / max(closes[kk], 1e-9) * 100)
                    if widths and bb_w < 0.5 * np.mean(widths):
                        chain_bb += 1
                    else:
                        break
                else:
                    break
            bb_sqz_chain[i] = chain_bb

            # silence score: low ATR z + low recent volume z + small range
            cur_atr = atr_arr[idx]
            if not np.isnan(cur_atr) and idx >= 60:
                atr_win = atr_arr[idx-60:idx]
                m, s = np.nanmean(atr_win), np.nanstd(atr_win)
                atr_z = (cur_atr - m) / s if s > 1e-9 else 0
                vol_win = volumes[idx-30:idx]
                vm, vs = vol_win.mean(), vol_win.std()
                vol_z = (volumes[idx] - vm) / vs if vs > 1e-9 else 0
                range_win = ranges[idx-30:idx]
                rm, rs = range_win.mean(), range_win.std()
                range_z = (ranges[idx] - rm) / rs if rs > 1e-9 else 0
                # All three < 0 = silence (low)
                silence_score[i] = -(atr_z + vol_z + range_z) / 3
                # Expansion = opposite
                expansion_signal[i] = (atr_z + vol_z + range_z) / 3

        prefix = f"tens_{tf}"
        out[f"{prefix}_atr_compression_chain"] = atr_compression
        out[f"{prefix}_range_decay_5"] = range_decay_5
        out[f"{prefix}_range_decay_10"] = range_decay_10
        out[f"{prefix}_narrow_range_bars"] = narrow_range_bars
        out[f"{prefix}_bb_squeeze_chain"] = bb_sqz_chain
        out[f"{prefix}_silence_score"] = silence_score
        out[f"{prefix}_expansion_signal"] = expansion_signal

    return out
