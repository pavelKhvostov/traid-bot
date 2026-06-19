"""Volume family features per req #9.

Per-TF:
  - vol_T              raw volume of the bar at born_ms
  - vol_z30, vol_z90   z-score vs rolling N bars
  - vol_spike_2sig     bool z > 2
  - vol_pct_change_1   (vol - prev_vol) / prev_vol
  - cvd_sum_50         cumulative sign(close-open)*volume last 50 bars
  - cvd_pct_bull_30    % bull-volume bars in last 30
  - vol_div_30         price up but vol down (divergence) bool
  - vwap_dist_pct      distance (%) from N-bar VWAP

Cross-TF aggregates:
  - vol_spike_count    how many TFs show vol_spike at born
"""
from __future__ import annotations
import numpy as np


VOL_TFS = ["15m", "1h", "2h", "4h", "12h", "1d"]


def build_volume_features_for_asset(bars: dict[str, np.ndarray],
                                      born_ms_array: np.ndarray) -> dict[str, np.ndarray]:
    n_events = len(born_ms_array)
    out = {}

    for tf in VOL_TFS:
        if tf not in bars:
            continue
        bar_arr = bars[tf]
        ts_arr = bar_arr[:, 0].astype(np.int64)
        opens = bar_arr[:, 1]
        closes = bar_arr[:, 4]
        volumes = bar_arr[:, 5]
        idx_at_event = np.searchsorted(ts_arr, born_ms_array, side="right") - 1
        valid = idx_at_event >= 0

        # vol_T (raw)
        vol_T = np.full(n_events, np.nan)
        vol_T[valid] = volumes[idx_at_event[valid]]
        out[f"vol_{tf}_T"] = vol_T

        # vol_pct_change_1: vs previous bar
        vol_pct_1 = np.full(n_events, np.nan)
        m1 = valid & (idx_at_event >= 1)
        prev_vol = volumes[idx_at_event[m1] - 1]
        cur_vol = volumes[idx_at_event[m1]]
        with np.errstate(divide="ignore", invalid="ignore"):
            vol_pct_1[m1] = np.where(prev_vol > 1e-9,
                                       (cur_vol - prev_vol) / prev_vol, np.nan)
        out[f"vol_{tf}_pct_change_1"] = vol_pct_1

        # vol_z30, vol_z90 — rolling z-score
        for win, label in ((30, "z30"), (90, "z90")):
            zarr = np.full(n_events, np.nan)
            for i, idx in enumerate(idx_at_event):
                if idx < win:
                    continue
                window = volumes[idx-win:idx]
                if len(window) < 5:
                    continue
                m = window.mean()
                s = window.std()
                if s > 1e-9:
                    zarr[i] = (volumes[idx] - m) / s
            out[f"vol_{tf}_{label}"] = zarr

        # vol_spike_2sig: bool z > 2 (от vol_z30)
        zkey = f"vol_{tf}_z30"
        if zkey in out:
            zar = out[zkey]
            spike = np.full(n_events, np.nan)
            mask = ~np.isnan(zar)
            spike[mask] = (zar[mask] > 2).astype(np.float64)
            out[f"vol_{tf}_spike_2sig"] = spike

        # CVD: cumulative sign(close-open) * volume over last N bars
        for N, label in ((50, "cvd_sum_50"),):
            cvd_arr = np.full(n_events, np.nan)
            for i, idx in enumerate(idx_at_event):
                if idx < N:
                    continue
                sub_open = opens[idx-N:idx]
                sub_close = closes[idx-N:idx]
                sub_vol = volumes[idx-N:idx]
                sign = np.sign(sub_close - sub_open)
                cvd_arr[i] = float((sign * sub_vol).sum())
            out[f"vol_{tf}_{label}"] = cvd_arr

        # cvd_pct_bull_30: % bull bars among last 30
        pct_bull_30 = np.full(n_events, np.nan)
        for i, idx in enumerate(idx_at_event):
            if idx < 30:
                continue
            sub_open = opens[idx-30:idx]
            sub_close = closes[idx-30:idx]
            bull_count = int((sub_close > sub_open).sum())
            pct_bull_30[i] = bull_count / 30
        out[f"vol_{tf}_pct_bull_30"] = pct_bull_30

        # Volume divergence: price up but vol down over last 10 bars
        vol_div = np.full(n_events, np.nan)
        for i, idx in enumerate(idx_at_event):
            if idx < 10:
                continue
            price_chg = closes[idx] - closes[idx-10]
            vol_chg = volumes[idx-5:idx].sum() - volumes[idx-10:idx-5].sum()
            if price_chg > 0 and vol_chg < 0:
                vol_div[i] = 1.0
            else:
                vol_div[i] = 0.0
        out[f"vol_{tf}_divergence_10"] = vol_div

        # VWAP rolling 50 bars
        vwap_dist = np.full(n_events, np.nan)
        for i, idx in enumerate(idx_at_event):
            if idx < 50:
                continue
            sub_close = closes[idx-50:idx+1]
            sub_vol = volumes[idx-50:idx+1]
            if sub_vol.sum() > 1e-9:
                vwap = (sub_close * sub_vol).sum() / sub_vol.sum()
                if vwap > 1e-9:
                    vwap_dist[i] = (closes[idx] - vwap) / vwap * 100
        out[f"vol_{tf}_vwap_dist_pct"] = vwap_dist

    # Cross-TF aggregate: vol_spike count across TFs
    spike_total = np.zeros(n_events)
    valid_cnt = np.zeros(n_events, dtype=np.int32)
    for tf in VOL_TFS:
        key = f"vol_{tf}_spike_2sig"
        if key in out:
            arr = out[key]
            v = ~np.isnan(arr)
            spike_total[v] += arr[v]
            valid_cnt[v] += 1
    out["vol_spike_count_cross_tf"] = np.where(valid_cnt > 0, spike_total, np.nan)

    return out
