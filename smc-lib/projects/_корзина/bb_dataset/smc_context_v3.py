"""SMC-контекст feature extractor для bb-model Phase 2.

~110 фичей в 11 группах для каждого ob_vc(1h+2h) сигнала:

  I.    Containing zones (где «лежит» ob_vc) — 22
  II.   Surrounding density per class — 32
  III.  Path features (как цена пришла к рождению) — 12
  IV.   ob_vc properties — 10
  V.    SMC sweep markers at birth — 6
  VI.   Liquidity (BSL/SSL) — 7
  VII.  Mitigation history & flow — 6
  VIII. Position in HTF range — 5
  IX.   Confluence / alignment — 5
  X.    Temporal — 4
  XI.   Sweep magnitude — 3

Input:
  - events_by_tf_type, resampled (precomputed via precompute_zone_events)
  - df_1m (1m OHLCV)
  - signal_time + ob_zone + direction + tf (per event)

Output:
  - dict {feature_name: value} per event
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

SMC_LIB = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SMC_LIB / "prediction-algo"))

from zones import ActiveZone, snapshot_from_events  # noqa: E402

# 9 ТФ для context snapshot
SMC_TFS = ("1h", "2h", "4h", "6h", "8h", "12h", "1d", "2d", "3d")

# Tier grouping для агрегации
LTF_TIER = ("1h", "2h")
MTF_TIER = ("4h", "6h", "8h")
HTF_TIER = ("12h", "1d")
MACRO_TIER = ("2d", "3d")

# Classes per memory: liquidity / inefficiency / блок
CLASS_MAP = {
    "fractal": "liquidity",
    "ob_liq": "liquidity",
    "FVG": "inefficiency",
    "iFVG": "inefficiency",
    "RDRB": "inefficiency",
    "iRDRB": "inefficiency",
    "marubozu": "inefficiency",
    "OB": "block",
    "ob_vc": "block",
    "block_orders": "block",
}
CLASSES = ("liquidity", "inefficiency", "block")


def _zones_above_below(zones: list[ActiveZone], ob_lo: float, ob_hi: float, price_now: float
                       ) -> tuple[list[ActiveZone], list[ActiveZone], list[ActiveZone]]:
    """Разделение зон на above/below/containing относительно ob_vc."""
    above, below, containing = [], [], []
    for z in zones:
        if z.lo <= ob_lo and z.hi >= ob_hi:
            containing.append(z)
        elif z.lo > ob_hi:
            above.append(z)
        elif z.hi < ob_lo:
            below.append(z)
        else:
            # partial overlap — counts as containing (loose)
            containing.append(z)
    return above, below, containing


# ───────────────────────── I. Containing zones (22) ─────────────────────────

def group_I_containing(zones: list[ActiveZone], ob_lo: float, ob_hi: float,
                        ob_direction: str) -> dict:
    """Where ob_vc lies inside other zones."""
    feats = {}
    _, _, containing = _zones_above_below(zones, ob_lo, ob_hi, (ob_lo + ob_hi) / 2)
    # Per-tier containers count
    for tier_name, tier_tfs in [("LTF", LTF_TIER), ("MTF", MTF_TIER),
                                  ("HTF", HTF_TIER), ("MACRO", MACRO_TIER)]:
        sub = [z for z in containing if z.tf in tier_tfs]
        feats[f"I_n_containing_{tier_name}"] = len(sub)
        feats[f"I_n_containing_{tier_name}_same_dir"] = sum(
            1 for z in sub if z.direction.lower() == ob_direction.lower()
        )
    # Best (largest/oldest) containing
    if containing:
        oldest = max(containing, key=lambda z: z.age_bars)
        widest = max(containing, key=lambda z: z.hi - z.lo)
        feats["I_containing_max_age_bars"] = oldest.age_bars
        feats["I_containing_max_width_pct"] = (widest.hi - widest.lo) / ((widest.hi + widest.lo) / 2) * 100
        feats["I_containing_oldest_tf_LTF"] = int(oldest.tf in LTF_TIER)
        feats["I_containing_oldest_tf_MTF"] = int(oldest.tf in MTF_TIER)
        feats["I_containing_oldest_tf_HTF"] = int(oldest.tf in HTF_TIER)
        feats["I_containing_oldest_tf_MACRO"] = int(oldest.tf in MACRO_TIER)
        feats["I_containing_oldest_class_liquidity"] = int(CLASS_MAP.get(oldest.type) == "liquidity")
        feats["I_containing_oldest_class_inefficiency"] = int(CLASS_MAP.get(oldest.type) == "inefficiency")
        feats["I_containing_oldest_class_block"] = int(CLASS_MAP.get(oldest.type) == "block")
        # ob_vc position inside oldest container (0=at lower edge, 1=at upper)
        zone_height = oldest.hi - oldest.lo
        if zone_height > 0:
            pos = ((ob_lo + ob_hi) / 2 - oldest.lo) / zone_height
            feats["I_ob_vc_position_in_container"] = float(np.clip(pos, 0, 1))
        else:
            feats["I_ob_vc_position_in_container"] = 0.5
    else:
        feats["I_containing_max_age_bars"] = 0
        feats["I_containing_max_width_pct"] = 0.0
        feats["I_containing_oldest_tf_LTF"] = 0
        feats["I_containing_oldest_tf_MTF"] = 0
        feats["I_containing_oldest_tf_HTF"] = 0
        feats["I_containing_oldest_tf_MACRO"] = 0
        feats["I_containing_oldest_class_liquidity"] = 0
        feats["I_containing_oldest_class_inefficiency"] = 0
        feats["I_containing_oldest_class_block"] = 0
        feats["I_ob_vc_position_in_container"] = -1.0  # sentinel for no container
    return feats


# ───────────────── II. Surrounding density per class (32) ─────────────────

def group_II_surrounding_density(zones: list[ActiveZone], ob_lo: float, ob_hi: float,
                                  price_now: float) -> dict:
    """Density of zones above/below ob_vc per class × per tier."""
    feats = {}
    above, below, _ = _zones_above_below(zones, ob_lo, ob_hi, price_now)

    for cls in CLASSES:
        for tier_name, tier_tfs in [("LTF", LTF_TIER), ("MTF", MTF_TIER),
                                      ("HTF", HTF_TIER), ("MACRO", MACRO_TIER)]:
            above_sub = [z for z in above if CLASS_MAP.get(z.type) == cls and z.tf in tier_tfs]
            below_sub = [z for z in below if CLASS_MAP.get(z.type) == cls and z.tf in tier_tfs]
            feats[f"II_n_above_{cls}_{tier_name}"] = len(above_sub)
            feats[f"II_n_below_{cls}_{tier_name}"] = len(below_sub)
        # Nearest above/below distance (any tier)
        cls_above = [z for z in above if CLASS_MAP.get(z.type) == cls]
        cls_below = [z for z in below if CLASS_MAP.get(z.type) == cls]
        if cls_above:
            nearest = min(cls_above, key=lambda z: z.lo - ob_hi)
            feats[f"II_dist_nearest_above_{cls}_pct"] = (nearest.lo - ob_hi) / max(price_now, 1) * 100
        else:
            feats[f"II_dist_nearest_above_{cls}_pct"] = 99.0
        if cls_below:
            nearest = min(cls_below, key=lambda z: ob_lo - z.hi)
            feats[f"II_dist_nearest_below_{cls}_pct"] = (ob_lo - nearest.hi) / max(price_now, 1) * 100
        else:
            feats[f"II_dist_nearest_below_{cls}_pct"] = 99.0
    return feats


# ───────────────── III. Path features (12) ─────────────────

def group_III_path(zones: list[ActiveZone], df_1m: pd.DataFrame,
                    ob_born_ts: pd.Timestamp, signal_time: pd.Timestamp,
                    price_now: float, ob_direction: str) -> dict:
    """How price arrived at ob_vc birth — recent SMC events."""
    feats = {}
    window_start = signal_time - pd.Timedelta(hours=24)
    window_end = signal_time
    df_window = df_1m.loc[window_start:window_end]
    if df_window.empty:
        # Default 0
        return {
            "III_n_HTF_zones_consumed_same_24h": 0,
            "III_n_HTF_zones_consumed_opp_24h": 0,
            "III_n_LTF_zones_consumed_24h": 0,
            "III_time_since_extremum_h": 0.0,
            "III_path_pct_move": 0.0,
            "III_n_FVG_in_path_LTF": 0,
            "III_n_FVG_in_path_HTF": 0,
            "III_path_fractals_count": 0,
            "III_untraded_inventory_between_pct": 0.0,
            "III_hours_since_birth_to_signal": 0.0,
            "III_path_volatility_norm": 0.0,
            "III_path_directness": 0.0,
        }
    # Time from ob_vc birth to signal_time
    feats["III_hours_since_birth_to_signal"] = (signal_time - ob_born_ts).total_seconds() / 3600

    # Extremum in 24h pre-signal
    last_high_idx = df_window["high"].idxmax()
    last_low_idx = df_window["low"].idxmin()
    extremum_ts = max(last_high_idx, last_low_idx)
    feats["III_time_since_extremum_h"] = (signal_time - extremum_ts).total_seconds() / 3600

    # Path move pct
    feats["III_path_pct_move"] = (price_now - df_window["close"].iloc[0]) / max(df_window["close"].iloc[0], 1) * 100

    # Path volatility (high-low range / mean close)
    rng = df_window["high"].max() - df_window["low"].min()
    feats["III_path_volatility_norm"] = rng / max(df_window["close"].mean(), 1) * 100

    # Path directness: ratio of net move vs cumulative move
    closes = df_window["close"]
    net = abs(closes.iloc[-1] - closes.iloc[0])
    cum = closes.diff().abs().sum()
    feats["III_path_directness"] = float(net / max(cum, 1e-9))

    # Zones consumed in 24h (rough approximation via mitigation_model + age check is heavy;
    # use snapshot at signal_time and approximate via age_bars vs window)
    # Same-direction inventory consumed: zones with born_ts before window but consumed_during
    # (proxy: count zones that have mitigation_model in {wick-fill, sweep} and age_bars > window in HTF terms)
    # Simplification: use n active zones same-dir vs opposite that are CLOSE to price (likely recently touched)
    same_dir_close = sum(
        1 for z in zones if z.direction.lower() == ob_direction.lower()
        and z.tf in HTF_TIER + MTF_TIER and abs(z.distance_pct) < 2.0
    )
    opp_dir_close = sum(
        1 for z in zones if z.direction.lower() != ob_direction.lower()
        and z.tf in HTF_TIER + MTF_TIER and abs(z.distance_pct) < 2.0
    )
    feats["III_n_HTF_zones_consumed_same_24h"] = same_dir_close
    feats["III_n_HTF_zones_consumed_opp_24h"] = opp_dir_close
    feats["III_n_LTF_zones_consumed_24h"] = sum(
        1 for z in zones if z.tf in LTF_TIER and abs(z.distance_pct) < 1.0
    )

    # FVG count by tier in path
    feats["III_n_FVG_in_path_LTF"] = sum(
        1 for z in zones if z.type == "FVG" and z.tf in LTF_TIER and abs(z.distance_pct) < 3.0
    )
    feats["III_n_FVG_in_path_HTF"] = sum(
        1 for z in zones if z.type == "FVG" and z.tf in HTF_TIER and abs(z.distance_pct) < 3.0
    )

    # Fractals in path
    feats["III_path_fractals_count"] = sum(
        1 for z in zones if z.type == "fractal" and abs(z.distance_pct) < 3.0
    )

    # Untraded inventory between ob_vc and price (FVG + iFVG widths sum)
    untraded = sum(
        (z.hi - z.lo) / max(price_now, 1) * 100
        for z in zones if z.type in ("FVG", "iFVG", "marubozu")
        and abs(z.distance_pct) < 2.0 and z.direction.lower() == ob_direction.lower()
    )
    feats["III_untraded_inventory_between_pct"] = float(untraded)
    return feats


# ───────────────── IV. ob_vc properties (10) ─────────────────

def group_IV_self(ob_event: dict, df_1m: pd.DataFrame, signal_time: pd.Timestamp,
                   price_now: float) -> dict:
    """Properties of the ob_vc itself."""
    feats = {}
    ob_lo, ob_hi = ob_event["ob_htf_zone"]
    feats["IV_tf_hours"] = {"1h": 1.0, "2h": 2.0}[ob_event["ob_htf_tf"]]
    feats["IV_direction_long"] = int(ob_event["direction"].lower() == "long")
    feats["IV_width_pct"] = (ob_hi - ob_lo) / max((ob_lo + ob_hi) / 2, 1) * 100
    feats["IV_n_fvg_components"] = ob_event.get("n_fvg_components", 1)
    feats["IV_fvg_tf_15m"] = int(ob_event.get("fvg_tf") == "15m")
    feats["IV_ob_age_to_signal_h"] = (signal_time - ob_event["ob_cur_time"]).total_seconds() / 3600
    # Distance ob_vc to current price
    if ob_event["direction"].lower() == "long":
        feats["IV_dist_to_zone_pct"] = (price_now - ob_hi) / max(price_now, 1) * 100
        feats["IV_zone_below_price"] = 1
    else:
        feats["IV_dist_to_zone_pct"] = (ob_lo - price_now) / max(price_now, 1) * 100
        feats["IV_zone_below_price"] = 0
    feats["IV_zone_mid_pct"] = ((ob_lo + ob_hi) / 2 - price_now) / max(price_now, 1) * 100
    feats["IV_signal_price"] = price_now  # context
    return feats


# ───────────────── V. SMC sweep markers at birth (6) ─────────────────

def group_V_sweep_birth(df_1m: pd.DataFrame, ob_born_ts: pd.Timestamp,
                         resampled: dict) -> dict:
    """Sweep markers around ob_vc birth."""
    feats = {}
    born_minus_24h = ob_born_ts - pd.Timedelta(hours=24)
    pre_window = df_1m.loc[born_minus_24h:ob_born_ts]
    if pre_window.empty:
        return {
            "V_pre_birth_range_pct": 0.0,
            "V_pre_birth_consec_same_color": 0,
            "V_pre_birth_marubozu_count": 0,
            "V_HTF_high_swept_24h_before": 0,
            "V_HTF_low_swept_24h_before": 0,
            "V_birth_bar_body_pct": 0.0,
        }
    feats["V_pre_birth_range_pct"] = (pre_window["high"].max() - pre_window["low"].min()) / max(pre_window["close"].mean(), 1) * 100

    # Consecutive same-color bars before birth (in 1h resampled)
    df_1h = resampled.get("1h")
    if df_1h is not None and not df_1h.empty:
        pre_1h = df_1h.loc[born_minus_24h:ob_born_ts]
        if len(pre_1h) > 0:
            colors = (pre_1h["close"] > pre_1h["open"]).astype(int)
            # Last consecutive same-color streak
            last = colors.iloc[-1] if len(colors) else 0
            streak = 0
            for v in colors.iloc[::-1]:
                if v == last:
                    streak += 1
                else:
                    break
            feats["V_pre_birth_consec_same_color"] = streak
        else:
            feats["V_pre_birth_consec_same_color"] = 0
    else:
        feats["V_pre_birth_consec_same_color"] = 0

    # Marubozu count in pre window (1h candles with body > 0.95 of range)
    if df_1h is not None and not df_1h.empty:
        pre_1h = df_1h.loc[born_minus_24h:ob_born_ts]
        if len(pre_1h) > 0:
            body = (pre_1h["close"] - pre_1h["open"]).abs()
            rng = pre_1h["high"] - pre_1h["low"]
            maru = (body / rng.replace(0, np.nan)) > 0.95
            feats["V_pre_birth_marubozu_count"] = int(maru.sum())
        else:
            feats["V_pre_birth_marubozu_count"] = 0
    else:
        feats["V_pre_birth_marubozu_count"] = 0

    # HTF high/low swept (12h high/low broken)
    df_12h = resampled.get("12h")
    if df_12h is not None and not df_12h.empty:
        pre_12h = df_12h.loc[born_minus_24h:ob_born_ts]
        if len(pre_12h) > 0:
            high_swept = int((pre_window["high"] > pre_12h["high"].iloc[0]).any())
            low_swept = int((pre_window["low"] < pre_12h["low"].iloc[0]).any())
            feats["V_HTF_high_swept_24h_before"] = high_swept
            feats["V_HTF_low_swept_24h_before"] = low_swept
        else:
            feats["V_HTF_high_swept_24h_before"] = 0
            feats["V_HTF_low_swept_24h_before"] = 0
    else:
        feats["V_HTF_high_swept_24h_before"] = 0
        feats["V_HTF_low_swept_24h_before"] = 0

    # Birth bar body pct (from 1h)
    if df_1h is not None and not df_1h.empty:
        # Find the 1h bar containing ob_born_ts
        idx = df_1h.index.searchsorted(ob_born_ts, side="right") - 1
        if 0 <= idx < len(df_1h):
            bar = df_1h.iloc[idx]
            rng = bar["high"] - bar["low"]
            if rng > 0:
                feats["V_birth_bar_body_pct"] = abs(bar["close"] - bar["open"]) / rng * 100
            else:
                feats["V_birth_bar_body_pct"] = 0.0
        else:
            feats["V_birth_bar_body_pct"] = 0.0
    else:
        feats["V_birth_bar_body_pct"] = 0.0
    return feats


# ───────────────── VI. Liquidity BSL/SSL (7) ─────────────────

def group_VI_liquidity(zones: list[ActiveZone], price_now: float, ob_direction: str,
                        signal_time: pd.Timestamp, df_1m: pd.DataFrame) -> dict:
    """BSL/SSL liquidity context — unswept fractals."""
    feats = {}
    # All fractals on HTF tiers
    htf_fractals = [z for z in zones if z.type == "fractal" and z.tf in HTF_TIER + MACRO_TIER]
    # BSL = high fractal above price (FH not swept), SSL = low fractal below
    bsl_above = [z for z in htf_fractals if z.direction.lower() == "short" and z.level and z.level > price_now]
    ssl_below = [z for z in htf_fractals if z.direction.lower() == "long" and z.level and z.level < price_now]

    if bsl_above:
        nearest = min(bsl_above, key=lambda z: z.level - price_now)
        feats["VI_nearest_unswept_BSL_above_pct"] = (nearest.level - price_now) / max(price_now, 1) * 100
    else:
        feats["VI_nearest_unswept_BSL_above_pct"] = 99.0
    if ssl_below:
        nearest = min(ssl_below, key=lambda z: price_now - z.level)
        feats["VI_nearest_unswept_SSL_below_pct"] = (price_now - nearest.level) / max(price_now, 1) * 100
    else:
        feats["VI_nearest_unswept_SSL_below_pct"] = 99.0

    feats["VI_n_unswept_HTF_BSL_within_2pct"] = sum(
        1 for z in bsl_above if (z.level - price_now) / max(price_now, 1) * 100 < 2.0
    )
    feats["VI_n_unswept_HTF_SSL_within_2pct"] = sum(
        1 for z in ssl_below if (price_now - z.level) / max(price_now, 1) * 100 < 2.0
    )

    # Last sweep events approx: nearest fractal that's CONSUMED (mitigation_model='sweep')
    swept_fractals = [z for z in htf_fractals if z.mitigation_model == "sweep"]
    if swept_fractals:
        # Use age_bars as proxy for hours since sweep
        # age_bars × tf_hours
        feats["VI_last_HTF_BSL_swept_h_ago"] = min(
            (z.age_bars * {"12h": 12, "1d": 24, "2d": 48, "3d": 72}.get(z.tf, 12)
             for z in swept_fractals if z.direction.lower() == "short"),
            default=999.0,
        )
        feats["VI_last_HTF_SSL_swept_h_ago"] = min(
            (z.age_bars * {"12h": 12, "1d": 24, "2d": 48, "3d": 72}.get(z.tf, 12)
             for z in swept_fractals if z.direction.lower() == "long"),
            default=999.0,
        )
    else:
        feats["VI_last_HTF_BSL_swept_h_ago"] = 999.0
        feats["VI_last_HTF_SSL_swept_h_ago"] = 999.0

    # BSL/SSL imbalance — signed count
    feats["VI_bsl_ssl_imbalance"] = len(bsl_above) - len(ssl_below)
    return feats


# ───────────────── VII. Mitigation history & flow (6) ─────────────────

def group_VII_mitigation_history(zones: list[ActiveZone], ob_direction: str) -> dict:
    """Recent mitigation flow in active zones."""
    feats = {}
    # Approximation: use mitigation_model + age_bars
    # Zones with mitigation in recent past (age_bars small, mitigation done)
    recent_zones = [z for z in zones if z.age_bars > 0 and z.mitigation_model in ("wick-fill", "sweep", "first-touch")]
    feats["VII_n_zones_partially_mitigated_24h"] = sum(1 for z in recent_zones if z.mitigation_model == "wick-fill")
    feats["VII_n_zones_fully_consumed_24h"] = 0  # consumed zones removed from snapshot, proxy=0
    feats["VII_n_zones_consumed_same_dir_24h"] = sum(
        1 for z in recent_zones if z.direction.lower() == ob_direction.lower()
    )
    feats["VII_n_zones_consumed_opp_dir_24h"] = sum(
        1 for z in recent_zones if z.direction.lower() != ob_direction.lower()
    )
    # Class balance — ratio
    cls_counts = {"liquidity": 0, "inefficiency": 0, "block": 0}
    for z in recent_zones:
        cls = CLASS_MAP.get(z.type)
        if cls:
            cls_counts[cls] += 1
    total = sum(cls_counts.values()) or 1
    feats["VII_mitigation_class_liquidity_pct"] = cls_counts["liquidity"] / total * 100
    feats["VII_time_since_last_consumed_h"] = min(
        (z.age_bars * 4 for z in recent_zones), default=999.0  # rough hours
    )
    return feats


# ───────────────── VIII. Position in HTF range (5) ─────────────────

def group_VIII_position_in_range(df_1m: pd.DataFrame, signal_time: pd.Timestamp,
                                   price_now: float, zones: list[ActiveZone]) -> dict:
    """Where in HTF range is current price."""
    feats = {}
    win_24h = df_1m.loc[signal_time - pd.Timedelta(hours=24):signal_time]
    if not win_24h.empty:
        rng = win_24h["high"].max() - win_24h["low"].min()
        if rng > 0:
            feats["VIII_price_position_in_24h_range_pct"] = (price_now - win_24h["low"].min()) / rng * 100
        else:
            feats["VIII_price_position_in_24h_range_pct"] = 50.0
    else:
        feats["VIII_price_position_in_24h_range_pct"] = 50.0

    win_7d = df_1m.loc[signal_time - pd.Timedelta(days=7):signal_time]
    if not win_7d.empty:
        rng = win_7d["high"].max() - win_7d["low"].min()
        if rng > 0:
            feats["VIII_price_position_in_7d_range_pct"] = (price_now - win_7d["low"].min()) / rng * 100
        else:
            feats["VIII_price_position_in_7d_range_pct"] = 50.0
    else:
        feats["VIII_price_position_in_7d_range_pct"] = 50.0

    # Distance from HTF HH/LL — use largest fractal of correct direction
    htf_fractals = [z for z in zones if z.type == "fractal" and z.tf in HTF_TIER + MACRO_TIER]
    hh_fractals = [z for z in htf_fractals if z.direction.lower() == "short"]
    ll_fractals = [z for z in htf_fractals if z.direction.lower() == "long"]
    if hh_fractals:
        hh_max = max((z.level for z in hh_fractals if z.level), default=price_now)
        feats["VIII_dist_from_HTF_HH_pct"] = (hh_max - price_now) / max(price_now, 1) * 100
    else:
        feats["VIII_dist_from_HTF_HH_pct"] = 0.0
    if ll_fractals:
        ll_min = min((z.level for z in ll_fractals if z.level), default=price_now)
        feats["VIII_dist_from_HTF_LL_pct"] = (price_now - ll_min) / max(price_now, 1) * 100
    else:
        feats["VIII_dist_from_HTF_LL_pct"] = 0.0
    # Containing zone position handled in Group I (I_ob_vc_position_in_container)
    # Add a 7d-position-from-mid as bonus
    if not win_7d.empty:
        mid = (win_7d["high"].max() + win_7d["low"].min()) / 2
        feats["VIII_dist_from_7d_mid_pct"] = (price_now - mid) / max(price_now, 1) * 100
    else:
        feats["VIII_dist_from_7d_mid_pct"] = 0.0
    return feats


# ───────────────── IX. Confluence / alignment (5) ─────────────────

def group_IX_confluence(zones: list[ActiveZone], ob_lo: float, ob_hi: float,
                         ob_direction: str, price_now: float) -> dict:
    """Confluence with overlapping zones at ob_vc level."""
    feats = {}
    # Zones overlapping ob_vc level
    overlapping = [
        z for z in zones if z.tf not in ("1h", "2h") and
        not (z.hi < ob_lo or z.lo > ob_hi)
    ]
    feats["IX_n_overlapping_zones_at_level"] = len(overlapping)
    feats["IX_max_overlap_count"] = len(overlapping)  # per ob_vc, total
    # Aligned with HTF fractal direction
    htf_fractals = [z for z in zones if z.type == "fractal" and z.tf in HTF_TIER]
    recent_aligned = sum(
        1 for z in htf_fractals if z.direction.lower() == ob_direction.lower() and z.age_bars < 24
    )
    feats["IX_ob_vc_aligned_with_HTF_fractal"] = int(recent_aligned > 0)
    # Failed sweep proxy: recent fractal of same direction with mit_model='sweep' nearby
    failed = sum(
        1 for z in htf_fractals if z.mitigation_model == "sweep" and
        z.direction.lower() == ob_direction.lower() and
        abs((z.level or price_now) - price_now) / max(price_now, 1) * 100 < 1.0
    )
    feats["IX_ob_vc_at_failed_sweep"] = int(failed > 0)
    # Confluence score
    feats["IX_confluence_score"] = sum(
        1 if z.direction.lower() == ob_direction.lower() else -0.5
        for z in overlapping
    )
    return feats


# ───────────────── X. Temporal (4) ─────────────────

def group_X_temporal(signal_time: pd.Timestamp) -> dict:
    """Time-of-day / session features."""
    h = signal_time.hour
    dow = signal_time.dayofweek
    # EU/US overlap: 13-16 UTC
    is_eu_us = int(13 <= h <= 16)
    # Hours to next major session open (Asian=00, EU=07, US=13 UTC)
    sessions = [0, 7, 13]
    hours_to_next = min((s - h) % 24 for s in sessions)
    return {
        "X_hour_of_day_utc": h,
        "X_day_of_week": dow,
        "X_is_eu_us_overlap": is_eu_us,
        "X_hours_to_next_session": hours_to_next,
    }


# ───────────────── XI. Sweep magnitude (3) ─────────────────

def group_XI_sweep_magnitude(zones: list[ActiveZone], price_now: float,
                              ob_direction: str) -> dict:
    """Recent sweep magnitudes."""
    feats = {}
    # Use swept fractals' relative magnitude as proxy
    htf_fractals = [z for z in zones if z.type == "fractal" and z.tf in HTF_TIER + MACRO_TIER]
    swept_short = [z for z in htf_fractals if z.mitigation_model == "sweep" and z.direction.lower() == "short"]
    swept_long = [z for z in htf_fractals if z.mitigation_model == "sweep" and z.direction.lower() == "long"]
    if swept_short:
        # Sweep magnitude = penetration beyond level (proxy via |distance_pct| of newest)
        newest = min(swept_short, key=lambda z: z.age_bars)
        feats["XI_last_HTF_BSL_sweep_magnitude_pct"] = abs(newest.distance_pct)
    else:
        feats["XI_last_HTF_BSL_sweep_magnitude_pct"] = 0.0
    if swept_long:
        newest = min(swept_long, key=lambda z: z.age_bars)
        feats["XI_last_HTF_SSL_sweep_magnitude_pct"] = abs(newest.distance_pct)
    else:
        feats["XI_last_HTF_SSL_sweep_magnitude_pct"] = 0.0
    # Failed sweeps 24h: count of sweep-model fractals with low age (≈ recent)
    failed_24h = sum(1 for z in htf_fractals if z.mitigation_model == "sweep" and z.age_bars < 2)
    feats["XI_n_failed_sweeps_24h"] = failed_24h
    return feats


# ────────────────── Trigger Zone Identification (Phase 3) ──────────────────

HTF_TIER_V3 = ("4h", "6h", "8h", "12h", "1d", "2d", "3d")
TF_MINUTES = {"1h": 60, "2h": 120, "4h": 240, "6h": 360, "8h": 480,
              "12h": 720, "1d": 1440, "2d": 2880, "3d": 4320}


def identify_trigger_zone(zones: list[ActiveZone], ob_lo: float, ob_hi: float,
                            ob_direction: str, ob_born_ts: pd.Timestamp,
                            df_1m: pd.DataFrame) -> dict | None:
    """
    Найти trigger HTF-зону. Logic:
      1. Containing HTF same-direction candidates (HTF = >=4h)
      2. Score by "most recently touched border" в окне [born-24h, born]
      3. Fallback: oldest same-direction containing HTF
    """
    dir_l = ob_direction.lower()
    candidates = [z for z in zones if z.tf in HTF_TIER_V3
                   and z.direction.lower() == dir_l
                   and z.lo <= ob_lo and z.hi >= ob_hi]
    if not candidates:
        return None

    # 1m window [born-24h, born]
    win_start = ob_born_ts - pd.Timedelta(hours=24)
    win = df_1m.loc[win_start:ob_born_ts]
    if win.empty:
        # Fallback: oldest by age
        trigger = max(candidates, key=lambda z: z.age_bars)
        return _trigger_pack(trigger, ob_born_ts, None, df_1m)

    lows = win["low"].to_numpy()
    highs = win["high"].to_numpy()
    ts = win.index.to_numpy()

    scored = []
    for z in candidates:
        if dir_l == "long":
            # LONG zone: relevant border is hi (price comes down to it from above)
            mask = lows <= z.hi
        else:
            mask = highs >= z.lo
        idxs = np.where(mask)[0]
        if len(idxs):
            last_touch_ts = pd.Timestamp(ts[idxs[-1]])
            recency_h = (ob_born_ts - last_touch_ts).total_seconds() / 3600.0
        else:
            last_touch_ts = None
            recency_h = 999.0
        scored.append((z, last_touch_ts, recency_h))

    # Smallest recency wins; tie-break by largest width
    scored.sort(key=lambda x: (x[2], -(x[0].hi - x[0].lo)))
    trigger, last_touch_ts, recency_h = scored[0]
    return _trigger_pack(trigger, ob_born_ts, last_touch_ts, df_1m, recency_h)


def _trigger_pack(z: ActiveZone, ob_born_ts: pd.Timestamp,
                   last_touch_ts: pd.Timestamp | None,
                   df_1m: pd.DataFrame,
                   recency_h: float | None = None) -> dict:
    out = {
        "zone": z,
        "tf": z.tf,
        "type": z.type,
        "direction": z.direction,
        "lo": z.lo,
        "hi": z.hi,
        "width": z.hi - z.lo,
        "age_bars": z.age_bars,
        "mitigation_model": z.mitigation_model,
        "born_ts": z.born_ts,
    }
    tf_min = TF_MINUTES.get(z.tf, 60)
    out["age_h"] = z.age_bars * tf_min / 60.0
    if recency_h is None and last_touch_ts is not None:
        recency_h = (ob_born_ts - last_touch_ts).total_seconds() / 3600.0
    out["touch_recency_h"] = recency_h if recency_h is not None else 999.0
    out["last_touch_ts"] = last_touch_ts
    return out


# ───────────────── Trigger zone features (15) ─────────────────

def group_trigger(trigger: dict | None, ob_lo: float, ob_hi: float, price_now: float,
                   zones: list[ActiveZone]) -> dict:
    if trigger is None:
        return {
            "t_found": 0,
            "t_type_OB": 0, "t_type_FVG": 0, "t_type_RDRB": 0, "t_type_iFVG": 0,
            "t_type_marubozu": 0, "t_type_block_orders": 0, "t_type_other": 1,
            "t_class_block": 0, "t_class_inefficiency": 0, "t_class_liquidity": 0,
            "t_tf_minutes": 0, "t_width_pct": 0.0, "t_age_h": 0.0,
            "t_distance_pct": 99.0, "t_mitigation_wickfill": 0, "t_mitigation_sweep": 0,
            "t_touch_recency_h": 999.0, "t_was_swept_at_birth": 0,
            "t_anchor_strength_score": 0.0,
        }
    z = trigger["zone"]
    feats = {"t_found": 1}
    # One-hot type (top types only)
    for t in ("OB", "FVG", "RDRB", "iFVG", "marubozu", "block_orders"):
        feats[f"t_type_{t}"] = int(z.type == t)
    feats["t_type_other"] = int(z.type not in ("OB", "FVG", "RDRB", "iFVG", "marubozu", "block_orders"))
    # Class one-hot
    cls = CLASS_MAP.get(z.type, "block")
    for c in CLASSES:
        feats[f"t_class_{c}"] = int(cls == c)
    feats["t_tf_minutes"] = TF_MINUTES.get(z.tf, 0)
    width = z.hi - z.lo
    feats["t_width_pct"] = width / max((z.lo + z.hi) / 2, 1) * 100
    feats["t_age_h"] = trigger["age_h"]
    # Distance ob_vc center to trigger center
    feats["t_distance_pct"] = abs((z.lo + z.hi) / 2 - (ob_lo + ob_hi) / 2) / max(price_now, 1) * 100
    feats["t_mitigation_wickfill"] = int(z.mitigation_model == "wick-fill")
    feats["t_mitigation_sweep"] = int(z.mitigation_model == "sweep")
    feats["t_touch_recency_h"] = trigger["touch_recency_h"]
    feats["t_was_swept_at_birth"] = 0  # placeholder (would need extra HTF state)
    # Anchor strength score
    n_overlapping = sum(1 for o in zones if o.lo <= z.hi and o.hi >= z.lo)
    feats["t_anchor_strength_score"] = (
        feats["t_width_pct"] * np.log1p(trigger["age_h"]) * n_overlapping / 10.0
    )
    return feats


# ───────────────── XII. Recently swept liquidity (8) ─────────────────

def group_XII_recently_swept(zones: list[ActiveZone], df_1m: pd.DataFrame,
                                signal_time: pd.Timestamp, price_now: float,
                                ob_direction: str) -> dict:
    htf_fractals = [z for z in zones if z.type == "fractal" and z.tf in HTF_TIER_V3]
    swept = [z for z in htf_fractals if z.mitigation_model == "sweep"]

    # 24h proxy via age_bars × tf_minutes
    def age_h(z):
        return z.age_bars * TF_MINUTES.get(z.tf, 60) / 60.0

    swept_24h = [z for z in swept if age_h(z) <= 24]
    swept_7d = [z for z in swept if age_h(z) <= 168]

    feats = {}
    feats["XII_n_HTF_fractal_swept_24h"] = len(swept_24h)
    feats["XII_n_HTF_fractal_swept_7d"] = len(swept_7d)
    # Multi-TF stack at same level (≤0.1% spread)
    if swept_24h:
        levels = sorted([z.level for z in swept_24h if z.level])
        max_stack = 1
        for lvl in levels:
            stack = sum(1 for l in levels if abs(l - lvl) / max(price_now, 1) * 100 < 0.1)
            max_stack = max(max_stack, stack)
        feats["XII_n_multi_TF_swept_at_same_level"] = max_stack
        # last sweep magnitude (use distance_pct as proxy)
        newest = min(swept_24h, key=lambda z: z.age_bars)
        feats["XII_last_sweep_magnitude_pct"] = abs(newest.distance_pct)
        feats["XII_time_since_last_HTF_sweep_h"] = age_h(newest)
    else:
        feats["XII_n_multi_TF_swept_at_same_level"] = 0
        feats["XII_last_sweep_magnitude_pct"] = 0.0
        feats["XII_time_since_last_HTF_sweep_h"] = 999.0

    # BSL vs SSL bias
    n_bsl = sum(1 for z in swept_24h if z.direction.lower() == "short")  # high fractal
    n_ssl = sum(1 for z in swept_24h if z.direction.lower() == "long")
    feats["XII_BSL_vs_SSL_sweep_imbalance_24h"] = n_bsl - n_ssl

    if swept_7d:
        feats["XII_max_sweep_magnitude_7d_pct"] = max(abs(z.distance_pct) for z in swept_7d)
    else:
        feats["XII_max_sweep_magnitude_7d_pct"] = 0.0

    # Failed sweeps (sweep but distance_pct small = couldn't pierce far)
    feats["XII_n_failed_sweeps_24h"] = sum(1 for z in swept_24h if abs(z.distance_pct) < 0.5)
    # Consecutive cascade — sweep events stacked in time
    if len(swept_24h) >= 2:
        ages_h = sorted([age_h(z) for z in swept_24h])
        gaps = [ages_h[i+1] - ages_h[i] for i in range(len(ages_h) - 1)]
        n_cascade = sum(1 for g in gaps if g < 4.0)  # within 4h of each other
        feats["XII_n_consecutive_sweeps_cascade_24h"] = n_cascade
    else:
        feats["XII_n_consecutive_sweeps_cascade_24h"] = 0

    return feats


# ───────────────── XIII. Cascade / drawdown pressure (6) ─────────────────

def group_XIII_cascade_pressure(df_1m: pd.DataFrame, signal_time: pd.Timestamp,
                                   price_now: float) -> dict:
    feats = {}
    win_7d = df_1m.loc[signal_time - pd.Timedelta(days=7):signal_time]
    if win_7d.empty:
        return {
            "XIII_drawdown_from_HH_7d_pct": 0.0,
            "XIII_drawup_from_LL_7d_pct": 0.0,
            "XIII_days_since_HH_7d": 0.0,
            "XIII_max_daily_drop_7d_pct": 0.0,
            "XIII_velocity_pct_per_day_24h": 0.0,
            "XIII_n_consecutive_red_days": 0,
        }
    hh = win_7d["high"].max()
    hh_ts = win_7d["high"].idxmax()
    ll = win_7d["low"].min()
    feats["XIII_drawdown_from_HH_7d_pct"] = (hh - price_now) / max(hh, 1) * 100
    feats["XIII_drawup_from_LL_7d_pct"] = (price_now - ll) / max(ll, 1) * 100
    feats["XIII_days_since_HH_7d"] = (signal_time - hh_ts).total_seconds() / 86400.0

    # Max daily drop
    daily = win_7d.resample("1D")[["high", "low", "open", "close"]].agg(
        {"high": "max", "low": "min", "open": "first", "close": "last"})
    if not daily.empty:
        drops = (daily["close"] / daily["open"] - 1).fillna(0) * 100
        feats["XIII_max_daily_drop_7d_pct"] = abs(drops.min()) if not drops.empty else 0.0
        # Consecutive red days
        reds = (drops < 0).astype(int)
        if not reds.empty and reds.iloc[-1] == 1:
            streak = 0
            for v in reds.iloc[::-1]:
                if v == 1: streak += 1
                else: break
            feats["XIII_n_consecutive_red_days"] = streak
        else:
            feats["XIII_n_consecutive_red_days"] = 0
    else:
        feats["XIII_max_daily_drop_7d_pct"] = 0.0
        feats["XIII_n_consecutive_red_days"] = 0

    # 24h velocity
    win_24h = df_1m.loc[signal_time - pd.Timedelta(hours=24):signal_time]
    if not win_24h.empty:
        chg_pct = (win_24h["close"].iloc[-1] / win_24h["close"].iloc[0] - 1) * 100
        feats["XIII_velocity_pct_per_day_24h"] = chg_pct
    else:
        feats["XIII_velocity_pct_per_day_24h"] = 0.0

    return feats


# ───────────────── XIV. Wick-reclaim signature (5) ─────────────────

def group_XIV_wick_reclaim(df_1m: pd.DataFrame, resampled: dict,
                             signal_time: pd.Timestamp, ob_lo: float, ob_hi: float,
                             ob_direction: str, price_now: float) -> dict:
    feats = {}
    df_1h = resampled.get("1h")
    if df_1h is None or df_1h.empty:
        return {"XIV_reversal_wick_to_body_ratio": 0.0,
                 "XIV_reversal_close_back_pct": 0.0,
                 "XIV_bars_from_extreme_to_reclaim": 0,
                 "XIV_volume_z_at_reversal_bar": 0.0,
                 "XIV_range_expansion_ratio_at_reversal": 1.0}

    # 6 1h-bars preceding signal
    pre_1h = df_1h.loc[df_1h.index < signal_time].tail(6)
    if pre_1h.empty:
        return {"XIV_reversal_wick_to_body_ratio": 0.0,
                 "XIV_reversal_close_back_pct": 0.0,
                 "XIV_bars_from_extreme_to_reclaim": 0,
                 "XIV_volume_z_at_reversal_bar": 0.0,
                 "XIV_range_expansion_ratio_at_reversal": 1.0}

    # Find biggest wick (against direction = reversal)
    if ob_direction.lower() == "long":
        # Look for biggest lower wick = sweep down then reclaim
        lower_wicks = pre_1h.apply(
            lambda r: max(0, min(r["open"], r["close"]) - r["low"]) / max(r["high"] - r["low"], 1), axis=1)
        idx_max = lower_wicks.idxmax()
        bar = pre_1h.loc[idx_max]
        body = abs(bar["close"] - bar["open"])
        wick = max(0, min(bar["open"], bar["close"]) - bar["low"])
        feats["XIV_reversal_wick_to_body_ratio"] = wick / max(body, 1)
        # Close above ob_hi means reclaim
        feats["XIV_reversal_close_back_pct"] = max(0, bar["close"] - ob_hi) / max(price_now, 1) * 100
    else:
        upper_wicks = pre_1h.apply(
            lambda r: max(0, r["high"] - max(r["open"], r["close"])) / max(r["high"] - r["low"], 1), axis=1)
        idx_max = upper_wicks.idxmax()
        bar = pre_1h.loc[idx_max]
        body = abs(bar["close"] - bar["open"])
        wick = max(0, bar["high"] - max(bar["open"], bar["close"]))
        feats["XIV_reversal_wick_to_body_ratio"] = wick / max(body, 1)
        feats["XIV_reversal_close_back_pct"] = max(0, ob_lo - bar["close"]) / max(price_now, 1) * 100

    # bars from extreme to reclaim
    feats["XIV_bars_from_extreme_to_reclaim"] = int((signal_time - idx_max).total_seconds() / 3600)

    # Volume z-score (vs preceding 60 1h bars)
    win = df_1h.loc[df_1h.index < signal_time].tail(60)
    if "volume" in df_1h.columns and len(win) > 5 and win["volume"].std() > 0:
        feats["XIV_volume_z_at_reversal_bar"] = (bar["volume"] - win["volume"].mean()) / win["volume"].std()
    else:
        feats["XIV_volume_z_at_reversal_bar"] = 0.0

    # Range expansion
    bar_range = bar["high"] - bar["low"]
    if len(win) > 5:
        avg_range = (win["high"] - win["low"]).mean()
        feats["XIV_range_expansion_ratio_at_reversal"] = bar_range / max(avg_range, 1)
    else:
        feats["XIV_range_expansion_ratio_at_reversal"] = 1.0

    return feats


# ───────────────── XV. Multi-TF level confluence (4) ─────────────────

def group_XV_multi_tf_stack(zones: list[ActiveZone], ob_lo: float, ob_hi: float,
                              price_now: float) -> dict:
    feats = {}
    radius_pct = 0.2  # 0.2% radius around ob_vc center
    center = (ob_lo + ob_hi) / 2
    radius_abs = center * radius_pct / 100
    nearby = [z for z in zones
              if (abs((z.lo + z.hi) / 2 - center) <= radius_abs
                  or (z.lo <= ob_hi and z.hi >= ob_lo))]
    distinct_tfs = set(z.tf for z in nearby)
    distinct_types = set(z.type for z in nearby)
    distinct_classes = set(CLASS_MAP.get(z.type) for z in nearby if CLASS_MAP.get(z.type))

    feats["XV_n_TFs_with_zone_at_same_level"] = len(distinct_tfs)
    feats["XV_n_zone_types_at_same_level"] = len(distinct_types)
    feats["XV_cross_class_confluence_score"] = float(len(distinct_classes))
    widths_sum = sum((z.hi - z.lo) for z in nearby)
    feats["XV_total_overlap_widths_at_level_pct"] = widths_sum / max(price_now, 1) * 100
    return feats


# ───────────────── XVI. Inefficiency strength (5) ─────────────────

def group_XVI_inefficiency_strength(zones: list[ActiveZone], price_now: float,
                                       ob_direction: str) -> dict:
    feats = {}
    nearby = [z for z in zones if abs(z.distance_pct) < 2.0 and
              z.tf in HTF_TIER_V3 and z.direction.lower() == ob_direction.lower()]
    htf_fvgs = [z for z in nearby if z.type == "FVG"]
    htf_ifvgs = [z for z in nearby if z.type == "iFVG"]

    if htf_fvgs:
        widths = [(z.hi - z.lo) / max(price_now, 1) * 100 for z in htf_fvgs]
        feats["XVI_largest_HTF_FVG_width_within_2pct_pct"] = max(widths)
        feats["XVI_FVG_age_oldest_HTF_h"] = max(
            z.age_bars * TF_MINUTES.get(z.tf, 60) / 60.0 for z in htf_fvgs)
    else:
        feats["XVI_largest_HTF_FVG_width_within_2pct_pct"] = 0.0
        feats["XVI_FVG_age_oldest_HTF_h"] = 0.0

    feats["XVI_n_iFVG_within_2pct"] = len(htf_ifvgs)

    inv_types = ("FVG", "iFVG", "marubozu")
    feats["XVI_total_untraded_inventory_HTF_pct"] = sum(
        (z.hi - z.lo) / max(price_now, 1) * 100
        for z in nearby if z.type in inv_types)

    # Round number distance — nearest 100$ tick
    round_dist = (price_now % 100)
    if round_dist > 50:
        round_dist = 100 - round_dist
    feats["XVI_inefficiency_at_round_number_dist_pct"] = round_dist / max(price_now, 1) * 100
    return feats


# ───────────────── XVII. Run room for trade (5) ─────────────────

def group_XVII_run_room(zones: list[ActiveZone], ob_lo: float, ob_hi: float,
                          price_now: float, ob_direction: str,
                          df_1m: pd.DataFrame, signal_time: pd.Timestamp) -> dict:
    feats = {}
    # Opposing direction HTF zones beyond ob_vc (target direction)
    opp = "short" if ob_direction.lower() == "long" else "long"
    opp_htf = [z for z in zones if z.direction.lower() == opp and z.tf in HTF_TIER_V3]
    if ob_direction.lower() == "long":
        # Target is up — find opposing zones above ob_hi
        above = [z for z in opp_htf if z.lo > ob_hi]
        if above:
            nearest = min(above, key=lambda z: z.lo - ob_hi)
            feats["XVII_dist_to_nearest_opposing_HTF_zone_pct"] = (nearest.lo - ob_hi) / max(price_now, 1) * 100
        else:
            feats["XVII_dist_to_nearest_opposing_HTF_zone_pct"] = 10.0
    else:
        below = [z for z in opp_htf if z.hi < ob_lo]
        if below:
            nearest = min(below, key=lambda z: ob_lo - z.hi)
            feats["XVII_dist_to_nearest_opposing_HTF_zone_pct"] = (ob_lo - nearest.hi) / max(price_now, 1) * 100
        else:
            feats["XVII_dist_to_nearest_opposing_HTF_zone_pct"] = 10.0

    # HTF HH/LL distances (7d)
    win_7d = df_1m.loc[signal_time - pd.Timedelta(days=7):signal_time]
    if not win_7d.empty:
        feats["XVII_dist_to_HTF_HH_pct"] = (win_7d["high"].max() - price_now) / max(price_now, 1) * 100
        feats["XVII_dist_to_HTF_LL_pct"] = (price_now - win_7d["low"].min()) / max(price_now, 1) * 100
    else:
        feats["XVII_dist_to_HTF_HH_pct"] = 0.0
        feats["XVII_dist_to_HTF_LL_pct"] = 0.0

    # Clear path / inventory obstacle
    obstacles = [z for z in zones if z.tf in HTF_TIER_V3 and abs(z.distance_pct) < 5]
    obstacle_widths = sum((z.hi - z.lo) for z in obstacles)
    feats["XVII_clear_path_pct"] = obstacle_widths / max(price_now, 1) * 100
    inv = [z for z in zones if z.type in ("FVG", "iFVG") and abs(z.distance_pct) < 3
           and z.direction.lower() == ob_direction.lower()]
    feats["XVII_imbalance_size_to_clear_pct"] = sum((z.hi - z.lo) for z in inv) / max(price_now, 1) * 100
    return feats


# ───────────────── XVIII. Pristine / fresh OB context (4) ─────────────────

def group_XVIII_pristine_ob(trigger: dict | None, df_1m: pd.DataFrame,
                              resampled: dict) -> dict:
    feats = {}
    if trigger is None or trigger["type"] != "OB":
        return {"XVIII_trigger_OB_birth_with_marubozu": 0,
                 "XVIII_trigger_OB_n_prior_touches": 0,
                 "XVIII_trigger_OB_body_to_range_at_birth": 0.0,
                 "XVIII_trigger_HTF_displacement_pct_at_birth": 0.0}

    born = trigger["born_ts"]
    tf = trigger["tf"]
    df_tf = resampled.get(tf)
    if df_tf is None or df_tf.empty:
        return {"XVIII_trigger_OB_birth_with_marubozu": 0,
                 "XVIII_trigger_OB_n_prior_touches": 0,
                 "XVIII_trigger_OB_body_to_range_at_birth": 0.0,
                 "XVIII_trigger_HTF_displacement_pct_at_birth": 0.0}

    idx = df_tf.index.searchsorted(born, side="right") - 1
    if 0 <= idx < len(df_tf):
        bar = df_tf.iloc[idx]
        body = abs(bar["close"] - bar["open"])
        rng = bar["high"] - bar["low"]
        b2r = body / max(rng, 1)
        feats["XVIII_trigger_OB_body_to_range_at_birth"] = b2r
        feats["XVIII_trigger_OB_birth_with_marubozu"] = int(b2r > 0.85)
        # Displacement: next bar's body
        if idx + 1 < len(df_tf):
            nb = df_tf.iloc[idx + 1]
            displ = abs(nb["close"] - nb["open"]) / max(bar["close"], 1) * 100
            feats["XVIII_trigger_HTF_displacement_pct_at_birth"] = displ
        else:
            feats["XVIII_trigger_HTF_displacement_pct_at_birth"] = 0.0
    else:
        feats["XVIII_trigger_OB_body_to_range_at_birth"] = 0.0
        feats["XVIII_trigger_OB_birth_with_marubozu"] = 0
        feats["XVIII_trigger_HTF_displacement_pct_at_birth"] = 0.0

    # Prior touches: count 1m bars where price entered trigger zone since born
    z = trigger["zone"]
    post = df_1m.loc[born:]
    if not post.empty:
        if trigger["direction"] == "long":
            touches = (post["low"] <= z.hi) & (post["low"] >= z.lo)
        else:
            touches = (post["high"] >= z.lo) & (post["high"] <= z.hi)
        # Count distinct touch episodes (consecutive True = 1 touch)
        ep = touches.astype(int)
        n_eps = ((ep == 1) & (ep.shift(1, fill_value=0) == 0)).sum()
        feats["XVIII_trigger_OB_n_prior_touches"] = int(n_eps)
    else:
        feats["XVIII_trigger_OB_n_prior_touches"] = 0

    return feats


# ───────────────────────── Combined extractor V3 ─────────────────────────

def extract_features(ob_event: dict, events_by_tf_type: dict,
                      resampled: dict, df_1m: pd.DataFrame) -> dict:
    """Все ~128 фичей для одного ob_vc-события (Phase 3).

    Включает: I-XI baseline + Trigger zone + XII-XVIII новые группы.
    """
    signal_time = ob_event["signal_time"]
    ob_lo, ob_hi = ob_event["ob_htf_zone"]
    direction = ob_event["direction"]

    zones = snapshot_from_events(events_by_tf_type, resampled, df_1m, signal_time)
    df_pre = df_1m.loc[df_1m.index < signal_time]
    if df_pre.empty:
        return {}
    price_now = float(df_pre["close"].iloc[-1])

    # Identify trigger zone (Phase 3 core)
    trigger = identify_trigger_zone(zones, ob_lo, ob_hi, direction,
                                       ob_event["ob_cur_time"], df_1m)

    feats = {}
    # Phase 2 baseline (kept)
    feats.update(group_I_containing(zones, ob_lo, ob_hi, direction))
    feats.update(group_II_surrounding_density(zones, ob_lo, ob_hi, price_now))
    feats.update(group_III_path(zones, df_1m, ob_event["ob_cur_time"], signal_time,
                                 price_now, direction))
    feats.update(group_IV_self(ob_event, df_1m, signal_time, price_now))
    feats.update(group_V_sweep_birth(df_1m, ob_event["ob_cur_time"], resampled))
    feats.update(group_VI_liquidity(zones, price_now, direction, signal_time, df_1m))
    feats.update(group_VIII_position_in_range(df_1m, signal_time, price_now, zones))
    feats.update(group_IX_confluence(zones, ob_lo, ob_hi, direction, price_now))
    feats.update(group_X_temporal(signal_time))
    feats.update(group_XI_sweep_magnitude(zones, price_now, direction))
    # Phase 3 NEW
    feats.update(group_trigger(trigger, ob_lo, ob_hi, price_now, zones))
    feats.update(group_XII_recently_swept(zones, df_1m, signal_time, price_now, direction))
    feats.update(group_XIII_cascade_pressure(df_1m, signal_time, price_now))
    feats.update(group_XIV_wick_reclaim(df_1m, resampled, signal_time, ob_lo, ob_hi,
                                          direction, price_now))
    feats.update(group_XV_multi_tf_stack(zones, ob_lo, ob_hi, price_now))
    feats.update(group_XVI_inefficiency_strength(zones, price_now, direction))
    feats.update(group_XVII_run_room(zones, ob_lo, ob_hi, price_now, direction,
                                       df_1m, signal_time))
    feats.update(group_XVIII_pristine_ob(trigger, df_1m, resampled))
    return feats
