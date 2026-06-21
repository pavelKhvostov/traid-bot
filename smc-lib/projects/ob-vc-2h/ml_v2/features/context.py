"""Prior context features per req #8.

For each event, look at zones of interest formed BEFORE born_ms and check
their state (mitigated / active).

For v2 Phase 3 we focus on FVG mitigation (per [[feedback-untraded-area-is-magnet]]):
  - Count of FVGs same-direction below entry (LONG) / above (SHORT) at born_ms
  - Count of unfilled FVGs nearby (within 5% of entry)
  - Recency of last FVG mitigation event
  - Active FVG cluster density (within ATR-scaled window)

Additional zones (OB, RDRB POI, marubozu, ob_liq) — deferred to Phase 3b
or later iteration.
"""
from __future__ import annotations
import numpy as np

from ._common import TF_SPECS


# TFs on which to detect FVGs for context features
FVG_TFS = ["15m", "1h", "2h", "4h", "6h", "12h", "1d"]


def detect_fvgs(bars: np.ndarray) -> list[dict]:
    """Detect FVGs on a bar array. Returns list of dicts.

    FVG canon (3-bar pattern):
      LONG  FVG: c3.low > c1.high → zone = [c1.high, c3.low]
      SHORT FVG: c3.high < c1.low → zone = [c3.high, c1.low]
    """
    fvgs = []
    n = len(bars)
    if n < 3:
        return fvgs
    for i in range(n - 2):
        c1_h = bars[i, 2]; c1_l = bars[i, 3]
        c3_h = bars[i+2, 2]; c3_l = bars[i+2, 3]
        c3_open_time = bars[i+2, 0]

        # LONG FVG
        if c3_l > c1_h:
            fvgs.append({
                "direction": "long",
                "zone_lo": c1_h, "zone_hi": c3_l,
                "born_ms": int(c3_open_time),
                "c1_idx": i, "c3_idx": i + 2,
            })
        # SHORT FVG
        elif c3_h < c1_l:
            fvgs.append({
                "direction": "short",
                "zone_lo": c3_h, "zone_hi": c1_l,
                "born_ms": int(c3_open_time),
                "c1_idx": i, "c3_idx": i + 2,
            })
    return fvgs


def fvg_mitigation_state(fvg: dict, bars_after: np.ndarray) -> dict:
    """Track wick-fill mitigation for a single FVG.

    Returns dict with last_mitigation_ms (or None) and final state (consumed bool).
    """
    zone_lo = fvg["zone_lo"]
    zone_hi = fvg["zone_hi"]
    dir_ = fvg["direction"]
    last_mit_ms = None
    consumed = False
    for j in range(len(bars_after)):
        ts = bars_after[j, 0]
        h = bars_after[j, 2]
        l = bars_after[j, 3]
        if dir_ == "long":
            # LONG zone is support; touched when low <= zone_hi
            if l <= zone_hi:
                last_mit_ms = int(ts)
                if l <= zone_lo:
                    consumed = True
                    break
        else:
            # SHORT zone is resistance; touched when high >= zone_lo
            if h >= zone_lo:
                last_mit_ms = int(ts)
                if h >= zone_hi:
                    consumed = True
                    break
    return {"last_mit_ms": last_mit_ms, "consumed": consumed}


def build_context_features_for_asset(bars: dict[str, np.ndarray],
                                       born_ms_array: np.ndarray,
                                       directions: np.ndarray,
                                       entries: np.ndarray) -> dict[str, np.ndarray]:
    """For each event, FVG context features."""
    n_events = len(born_ms_array)
    out = {}

    # Pre-compute all FVGs per TF and their mitigation states
    fvgs_per_tf = {}      # tf -> list[fvg dicts]
    for tf in FVG_TFS:
        if tf not in bars:
            continue
        all_fvgs = detect_fvgs(bars[tf])
        fvgs_per_tf[tf] = all_fvgs

    # For each event we want:
    #   - active FVG count same-dir below (for long) / above (for short) within 5% of entry
    #   - active FVG count opposite-dir
    #   - recency of last FVG mitigation (any direction)
    #   - active FVG cluster density (count within 5% of entry)

    for tf in FVG_TFS:
        if tf not in bars:
            continue
        bar_arr = bars[tf]
        ts_arr = bar_arr[:, 0].astype(np.int64)
        all_fvgs = fvgs_per_tf[tf]

        # Per-FVG: compute consumed_ms and last_mit_ms by walking forward
        fvg_consumed_ms = [None] * len(all_fvgs)
        for k, fvg in enumerate(all_fvgs):
            c3_idx = fvg["c3_idx"]
            bars_after = bar_arr[c3_idx + 1:]
            ms = fvg_mitigation_state(fvg, bars_after)
            if ms["consumed"]:
                fvg_consumed_ms[k] = ms["last_mit_ms"]

        # ms->fvg lookup
        fvg_born_arr = np.array([f["born_ms"] for f in all_fvgs], dtype=np.int64)

        # For each event
        active_same_below_above = np.full(n_events, np.nan)
        active_opp_below_above = np.full(n_events, np.nan)
        active_within_5pct = np.full(n_events, np.nan)
        last_mit_recency_hours = np.full(n_events, np.nan)

        for i, (b, dir_, ent) in enumerate(zip(born_ms_array, directions, entries)):
            if np.isnan(ent):
                continue
            # All FVGs that were born before b
            mask_born = fvg_born_arr < b
            if not mask_born.any():
                active_same_below_above[i] = 0
                active_opp_below_above[i] = 0
                active_within_5pct[i] = 0
                continue

            count_same_below_above = 0
            count_opp_below_above = 0
            count_within_5pct = 0
            most_recent_mit = -1

            window_low = ent * 0.95
            window_high = ent * 1.05

            for k, fvg in enumerate(all_fvgs):
                if not mask_born[k]:
                    continue
                # Active = not consumed yet at time b
                consumed_ms = fvg_consumed_ms[k]
                is_active = (consumed_ms is None) or (consumed_ms > b)
                fvg_dir = fvg["direction"]

                if is_active:
                    # Within ±5% of entry?
                    if window_low <= fvg["zone_hi"] and fvg["zone_lo"] <= window_high:
                        count_within_5pct += 1
                    if dir_ == "long":
                        # Same-dir is long; we want long FVGs below entry
                        if fvg_dir == "long" and fvg["zone_hi"] < ent:
                            count_same_below_above += 1
                        elif fvg_dir == "short" and fvg["zone_lo"] > ent:
                            count_opp_below_above += 1
                    else:  # short
                        if fvg_dir == "short" and fvg["zone_lo"] > ent:
                            count_same_below_above += 1
                        elif fvg_dir == "long" and fvg["zone_hi"] < ent:
                            count_opp_below_above += 1
                else:
                    # Was mitigated before b → track recency
                    if consumed_ms is not None and consumed_ms <= b:
                        if consumed_ms > most_recent_mit:
                            most_recent_mit = consumed_ms

            active_same_below_above[i] = count_same_below_above
            active_opp_below_above[i] = count_opp_below_above
            active_within_5pct[i] = count_within_5pct
            if most_recent_mit > 0:
                last_mit_recency_hours[i] = (b - most_recent_mit) / 3_600_000

        prefix = f"ctx_{tf}"
        out[f"{prefix}_fvg_active_same_dir_count"] = active_same_below_above
        out[f"{prefix}_fvg_active_opp_dir_count"] = active_opp_below_above
        out[f"{prefix}_fvg_active_5pct_count"] = active_within_5pct
        out[f"{prefix}_fvg_last_mit_recency_h"] = last_mit_recency_hours

    return out
