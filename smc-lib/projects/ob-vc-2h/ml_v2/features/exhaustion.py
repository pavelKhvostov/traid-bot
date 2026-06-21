"""Trend exhaustion features per req #14.

Per TF:
  - momentum_decay        current body / avg body of last 5 (>1=acceleration, <1=decay)
  - diminishing_pushes    are consecutive bull/bear pushes getting smaller?
  - new_extreme_vol_div   new HH but volume lower than prior HH (or new LL)
  - bars_in_uptrend       count of bull bars in last 20
  - bars_in_downtrend
  - slope_diminishing     slope_5 < slope_20 (loss of momentum)
"""
from __future__ import annotations
import numpy as np


EXHAUST_TFS = ["2h", "4h", "6h", "12h", "1d"]


def build_exhaustion_features_for_asset(bars: dict[str, np.ndarray],
                                          born_ms_array: np.ndarray) -> dict[str, np.ndarray]:
    n_events = len(born_ms_array)
    out = {}

    for tf in EXHAUST_TFS:
        if tf not in bars: continue
        bar_arr = bars[tf]
        ts_arr = bar_arr[:, 0].astype(np.int64)
        opens = bar_arr[:, 1]
        highs = bar_arr[:, 2]
        lows = bar_arr[:, 3]
        closes = bar_arr[:, 4]
        volumes = bar_arr[:, 5]
        idx_at_event = np.searchsorted(ts_arr, born_ms_array, side="right") - 1

        momentum_decay = np.full(n_events, np.nan)
        diminishing_pushes = np.full(n_events, np.nan)
        new_hh_vol_div = np.full(n_events, np.nan)
        new_ll_vol_div = np.full(n_events, np.nan)
        bars_up = np.full(n_events, np.nan)
        bars_dn = np.full(n_events, np.nan)
        slope_dim = np.full(n_events, np.nan)

        for i, idx in enumerate(idx_at_event):
            if idx < 20: continue

            # momentum decay
            sub_body = np.abs(closes[idx-5:idx+1] - opens[idx-5:idx+1])
            cur_b = sub_body[-1]
            avg_prev_b = sub_body[:-1].mean()
            if avg_prev_b > 1e-9:
                momentum_decay[i] = cur_b / avg_prev_b

            # diminishing pushes — measure last 3 consecutive same-direction bodies
            # If 3 bull bars in a row: check if each subsequent body smaller than previous
            last3_bull = (closes[idx-2:idx+1] > opens[idx-2:idx+1]).all()
            last3_bear = (closes[idx-2:idx+1] < opens[idx-2:idx+1]).all()
            if last3_bull or last3_bear:
                b = np.abs(closes[idx-2:idx+1] - opens[idx-2:idx+1])
                if b[0] > b[1] > b[2]:
                    diminishing_pushes[i] = 1.0  # confirmed diminishing
                elif b[0] < b[1] < b[2]:
                    diminishing_pushes[i] = -1.0  # accelerating
                else:
                    diminishing_pushes[i] = 0.0

            # new HH vol divergence: cur high > max(last 10 highs prior), but vol < median
            if idx >= 11:
                prior_highs = highs[idx-10:idx]
                if highs[idx] > prior_highs.max():
                    median_vol = np.median(volumes[idx-10:idx])
                    if volumes[idx] < median_vol:
                        new_hh_vol_div[i] = 1.0
                    else:
                        new_hh_vol_div[i] = 0.0
                else:
                    new_hh_vol_div[i] = 0.0

            # new LL vol divergence
            if idx >= 11:
                prior_lows = lows[idx-10:idx]
                if lows[idx] < prior_lows.min():
                    median_vol = np.median(volumes[idx-10:idx])
                    if volumes[idx] < median_vol:
                        new_ll_vol_div[i] = 1.0
                    else:
                        new_ll_vol_div[i] = 0.0
                else:
                    new_ll_vol_div[i] = 0.0

            # bars_up / bars_dn last 20
            sub_bull = (closes[idx-19:idx+1] > opens[idx-19:idx+1])
            bars_up[i] = int(sub_bull.sum())
            bars_dn[i] = 20 - bars_up[i]

            # slope diminishing
            sub_close = closes[idx-20:idx+1]
            if sub_close[-1] > 1e-9 and sub_close[-6] > 1e-9:
                slope5 = (sub_close[-1] - sub_close[-6]) / sub_close[-6]
                slope20 = (sub_close[-1] - sub_close[0]) / sub_close[0]
                slope_dim[i] = slope5 - slope20  # negative = slowing

        prefix = f"exh_{tf}"
        out[f"{prefix}_momentum_decay"] = momentum_decay
        out[f"{prefix}_diminishing_pushes"] = diminishing_pushes
        out[f"{prefix}_new_hh_vol_div"] = new_hh_vol_div
        out[f"{prefix}_new_ll_vol_div"] = new_ll_vol_div
        out[f"{prefix}_bars_up_20"] = bars_up
        out[f"{prefix}_bars_dn_20"] = bars_dn
        out[f"{prefix}_slope_diminishing"] = slope_dim

    return out
