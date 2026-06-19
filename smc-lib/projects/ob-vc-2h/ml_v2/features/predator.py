"""Predator/prey features per req #15 — stop hunts, false breakouts, springs, liquidity grabs.

Per TF:
  - sweep_high_recent     was prior high cleared then price closed below it (last 5 bars)
  - sweep_low_recent      mirror for low
  - false_break_up_rec    close back below broken level (last 5 bars)
  - false_break_dn_rec
  - spring_pattern        fake breakdown + quick recovery (Wyckoff Spring; long-side)
  - upthrust_pattern      fake breakout + quick rejection (Wyckoff Upthrust; short-side)
  - equal_highs_cluster   ≥3 highs within 0.2% range in last 20 bars
  - equal_lows_cluster
  - max_wick_recent_5     max(upper_wick or lower_wick) / range in last 5 bars (capitulation)
"""
from __future__ import annotations
import numpy as np


PRED_TFS = ["2h", "4h", "6h", "12h", "1d"]


def build_predator_features_for_asset(bars: dict[str, np.ndarray],
                                        born_ms_array: np.ndarray) -> dict[str, np.ndarray]:
    n_events = len(born_ms_array)
    out = {}

    for tf in PRED_TFS:
        if tf not in bars: continue
        bar_arr = bars[tf]
        ts_arr = bar_arr[:, 0].astype(np.int64)
        opens = bar_arr[:, 1]
        highs = bar_arr[:, 2]
        lows = bar_arr[:, 3]
        closes = bar_arr[:, 4]
        idx_at_event = np.searchsorted(ts_arr, born_ms_array, side="right") - 1

        sweep_h = np.full(n_events, np.nan)
        sweep_l = np.full(n_events, np.nan)
        fbreak_up = np.full(n_events, np.nan)
        fbreak_dn = np.full(n_events, np.nan)
        spring = np.full(n_events, np.nan)
        upthrust = np.full(n_events, np.nan)
        eq_h_cluster = np.full(n_events, np.nan)
        eq_l_cluster = np.full(n_events, np.nan)
        max_wick_recent = np.full(n_events, np.nan)

        for i, idx in enumerate(idx_at_event):
            if idx < 20: continue

            # sweep_high_recent: in last 5 bars, any bar's high > max(prior 10 highs) AND closed below that level
            recent_range_high = highs[idx-15:idx-5].max() if idx >= 15 else np.nan
            sweep_h_flag = 0.0
            for k in range(idx-4, idx+1):
                if highs[k] > recent_range_high and closes[k] < recent_range_high:
                    sweep_h_flag = 1.0
                    break
            sweep_h[i] = sweep_h_flag

            recent_range_low = lows[idx-15:idx-5].min() if idx >= 15 else np.nan
            sweep_l_flag = 0.0
            for k in range(idx-4, idx+1):
                if lows[k] < recent_range_low and closes[k] > recent_range_low:
                    sweep_l_flag = 1.0
                    break
            sweep_l[i] = sweep_l_flag

            # false break up: any of last 5 closed above prior high but next close back below
            fbr_up = 0.0
            for k in range(idx-4, idx):
                prior_h = highs[max(0,k-10):k].max() if k > 0 else np.nan
                if not np.isnan(prior_h) and closes[k] > prior_h and closes[k+1] < prior_h:
                    fbr_up = 1.0
                    break
            fbreak_up[i] = fbr_up
            fbr_dn = 0.0
            for k in range(idx-4, idx):
                prior_l = lows[max(0,k-10):k].min() if k > 0 else np.nan
                if not np.isnan(prior_l) and closes[k] < prior_l and closes[k+1] > prior_l:
                    fbr_dn = 1.0
                    break
            fbreak_dn[i] = fbr_dn

            # spring: low breaks support, but close back above support, within last 3 bars
            sp_flag = 0.0
            support_l = lows[idx-15:idx-3].min() if idx >= 15 else np.nan
            for k in range(idx-2, idx+1):
                if lows[k] < support_l and closes[k] > support_l:
                    sp_flag = 1.0
                    break
            spring[i] = sp_flag

            # upthrust: high breaks resistance, close back below
            ut_flag = 0.0
            resist_h = highs[idx-15:idx-3].max() if idx >= 15 else np.nan
            for k in range(idx-2, idx+1):
                if highs[k] > resist_h and closes[k] < resist_h:
                    ut_flag = 1.0
                    break
            upthrust[i] = ut_flag

            # equal highs cluster: ≥3 highs in last 20 within 0.2% range
            sub_highs = highs[idx-19:idx+1]
            cluster_h = 0
            for hh in sub_highs:
                close_to = ((sub_highs - hh) / hh).abs() if hasattr(sub_highs - hh, "abs") else np.abs((sub_highs - hh) / hh)
                cluster_h = max(cluster_h, int((close_to < 0.002).sum()))
            eq_h_cluster[i] = 1.0 if cluster_h >= 3 else 0.0

            sub_lows = lows[idx-19:idx+1]
            cluster_l = 0
            for ll in sub_lows:
                close_to = np.abs((sub_lows - ll) / ll)
                cluster_l = max(cluster_l, int((close_to < 0.002).sum()))
            eq_l_cluster[i] = 1.0 if cluster_l >= 3 else 0.0

            # max wick recent: max wick size / range in last 5 bars
            max_w = 0.0
            for k in range(idx-4, idx+1):
                rng = highs[k] - lows[k]
                if rng > 1e-9:
                    upper = highs[k] - max(opens[k], closes[k])
                    lower = min(opens[k], closes[k]) - lows[k]
                    wick_ratio = max(upper, lower) / rng
                    if wick_ratio > max_w:
                        max_w = wick_ratio
            max_wick_recent[i] = max_w

        prefix = f"pred_{tf}"
        out[f"{prefix}_sweep_high_recent"] = sweep_h
        out[f"{prefix}_sweep_low_recent"] = sweep_l
        out[f"{prefix}_fbreak_up_recent"] = fbreak_up
        out[f"{prefix}_fbreak_dn_recent"] = fbreak_dn
        out[f"{prefix}_spring_pattern"] = spring
        out[f"{prefix}_upthrust_pattern"] = upthrust
        out[f"{prefix}_equal_highs_cluster"] = eq_h_cluster
        out[f"{prefix}_equal_lows_cluster"] = eq_l_cluster
        out[f"{prefix}_max_wick_recent_5"] = max_wick_recent

    return out
