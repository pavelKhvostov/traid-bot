"""Прометей Phase 2 — feature extractor.

Per snapshot JSON → fixed-vector feature dict (~2000 features) ready for ML.

Groups (per spec.md §2):
  A — SMC element panel: per (element_type × TF) zone state
  B — Williams fractals: per TF unswept/swept stats
  C — Confluence: cross-element aggregates at price
  D — Structural: CHoCH/BOS state + flip-zones (breaker/MB/inducement)
"""
from __future__ import annotations

from typing import Any

# 14 zone-element types (matches snapshot detector output)
ZONE_ELEMENTS = (
    "ob", "fvg", "marubozu", "block_orders", "rdrb", "i_rdrb",
    "ob_liq", "i_fvg",
    # flip-zones tracked separately in snapshot but included as zones in Group A:
    # "breaker_block", "mitigation_block" — handled via dedicated Group A subsection
)

TF_LIST = ("15m", "30m", "1h", "2h", "4h", "6h", "12h", "1D")

# TF weights for confluence (per spec §2 Group C: W > D > 12h > 4h > ...).
# We don't have W here, start from 1D.
TF_WEIGHT = {
    "1D": 8,
    "12h": 6,
    "6h": 4,
    "4h": 3,
    "2h": 2,
    "1h": 1.5,
    "30m": 1,
    "15m": 0.5,
}


def _is_long(z: dict) -> bool:
    """Determine if zone is LONG (support below price) or SHORT (resistance above).

    For OB/RDRB/etc. 'long' = LONG support; 'short' = SHORT resistance.
    For breakers (role inverted) we use 'flipped_direction'.
    For MB also flipped_direction.
    """
    flip = z.get("flipped_direction")
    if flip is not None:
        return flip == "long"
    return z.get("direction") == "long"


def _zone_center(z: dict) -> float:
    """Midpoint of active_zone (preferred) or zone."""
    z_int = z.get("active_zone") or z.get("zone")
    if z_int is None:
        return 0.0
    return (z_int[0] + z_int[1]) / 2.0


def _zone_distance_pct(z: dict, price: float) -> float:
    """Signed distance: + if zone above price, - if below."""
    if price <= 0:
        return 0.0
    return (_zone_center(z) - price) / price * 100


# ─── Group A: SMC element panel (per element × TF) ──────────────────────────

def features_group_a(snap: dict, price: float) -> dict[str, float]:
    """Per (element_type, TF) zone state. ~14 features × 8 elements × 8 TFs = 896."""
    out: dict[str, float] = {}

    # Partition active_zones by (element, tf, side)
    by_key: dict[tuple[str, str, str], list[dict]] = {}
    for z in snap["active_zones"]:
        side = "long" if _is_long(z) else "short"
        key = (z["element"], z["tf"], side)
        by_key.setdefault(key, []).append(z)

    for elem in ZONE_ELEMENTS:
        for tf in TF_LIST:
            for side in ("long", "short"):
                zones = by_key.get((elem, tf, side), [])
                prefix = f"a_{elem}_{tf}_{side}"
                out[f"{prefix}_n"] = float(len(zones))
                if not zones:
                    out[f"{prefix}_nearest_dist_pct"] = 0.0
                    out[f"{prefix}_nearest_age"] = 0.0
                    out[f"{prefix}_nearest_mit"] = 0.0
                    out[f"{prefix}_min_age"] = 0.0
                    out[f"{prefix}_max_age"] = 0.0
                    continue
                # Distance-ranked: nearest by abs(distance)
                dists = [(z, _zone_distance_pct(z, price)) for z in zones]
                dists.sort(key=lambda zd: abs(zd[1]))
                nearest, nd = dists[0]
                out[f"{prefix}_nearest_dist_pct"] = nd
                out[f"{prefix}_nearest_age"] = float(nearest.get("age_bars", 0))
                out[f"{prefix}_nearest_mit"] = float(nearest.get("mit_count", 0))
                ages = [z.get("age_bars", 0) for z in zones]
                out[f"{prefix}_min_age"] = float(min(ages))
                out[f"{prefix}_max_age"] = float(max(ages))
    return out


# ─── Group A-extra: flip-zones (breakers + mitigation_blocks) per TF ────────

def features_group_a_flip(snap: dict, price: float) -> dict[str, float]:
    """Breakers and mitigation_blocks per TF × flipped_side."""
    out: dict[str, float] = {}
    for name, key in (("breaker", "breakers"), ("mb", "mitigation_blocks")):
        bucket: dict[tuple[str, str], list[dict]] = {}
        for z in snap.get(key, []):
            side = z.get("flipped_direction", "long")
            bucket.setdefault((z["tf"], side), []).append(z)
        for tf in TF_LIST:
            for side in ("long", "short"):
                zones = bucket.get((tf, side), [])
                prefix = f"flip_{name}_{tf}_{side}"
                out[f"{prefix}_n"] = float(len(zones))
                if not zones:
                    out[f"{prefix}_nearest_dist_pct"] = 0.0
                    out[f"{prefix}_nearest_age"] = 0.0
                    out[f"{prefix}_nearest_mit"] = 0.0
                    continue
                dists = [(z, _zone_distance_pct(z, price)) for z in zones]
                dists.sort(key=lambda zd: abs(zd[1]))
                nearest, nd = dists[0]
                out[f"{prefix}_nearest_dist_pct"] = nd
                out[f"{prefix}_nearest_age"] = float(nearest.get("armed_age_bars", nearest.get("age_bars", 0)))
                out[f"{prefix}_nearest_mit"] = float(nearest.get("mit_count", 0))
    return out


# ─── Group B: Williams fractals per TF ──────────────────────────────────────

def features_group_b(snap: dict, price: float) -> dict[str, float]:
    """Per TF: unswept FH/FL distance + age, swept counts."""
    out: dict[str, float] = {}
    for tf in TF_LIST:
        frs = snap["fractals"].get(tf, [])
        for side, dir_key in (("fh", "high"), ("fl", "low")):
            relevant = [f for f in frs if f["direction"] == dir_key]
            unswept = [f for f in relevant if not f["swept"]]
            swept = [f for f in relevant if f["swept"]]
            prefix = f"b_{tf}_{side}"
            out[f"{prefix}_n_unswept"] = float(len(unswept))
            out[f"{prefix}_n_swept"] = float(len(swept))
            # Nearest unswept (by abs distance to price)
            if unswept and price > 0:
                dists = [(f, (f["level"] - price) / price * 100) for f in unswept]
                dists.sort(key=lambda fd: abs(fd[1]))
                nearest, nd = dists[0]
                out[f"{prefix}_nearest_unswept_dist_pct"] = nd
                out[f"{prefix}_nearest_unswept_age"] = float(nearest.get("age_bars", 0))
            else:
                out[f"{prefix}_nearest_unswept_dist_pct"] = 0.0
                out[f"{prefix}_nearest_unswept_age"] = 0.0
            # Recent sweep (any swept in last 100 bars on this TF)
            recent_sweeps = [
                f for f in swept
                if f.get("swept_at_bar") is not None
                and (f.get("born_idx", 0) and (f["swept_at_bar"] - f["born_idx"] >= 0))
            ]
            out[f"{prefix}_n_recent_swept"] = float(len(recent_sweeps))
    return out


# ─── Group C: cross-element confluence ──────────────────────────────────────

def features_group_c(snap: dict, price: float) -> dict[str, float]:
    """Cross-element aggregates: overlap-at-price, n_within_pct, weighted score."""
    out: dict[str, float] = {}
    all_zones = list(snap["active_zones"]) + list(snap.get("breakers", [])) + list(snap.get("mitigation_blocks", []))
    if price <= 0:
        return {
            "c_n_zones_at_price": 0.0,
            "c_n_long_within_1pct": 0.0, "c_n_short_within_1pct": 0.0,
            "c_n_long_within_2pct": 0.0, "c_n_short_within_2pct": 0.0,
            "c_n_long_within_5pct": 0.0, "c_n_short_within_5pct": 0.0,
            "c_weighted_long_score": 0.0, "c_weighted_short_score": 0.0,
            "c_inside_long": 0.0, "c_inside_short": 0.0,
            "c_inside_breaker_above": 0.0, "c_inside_breaker_below": 0.0,
        }
    n_at_price = 0
    n_long_1, n_short_1 = 0, 0
    n_long_2, n_short_2 = 0, 0
    n_long_5, n_short_5 = 0, 0
    w_long_score = 0.0
    w_short_score = 0.0
    inside_long = 0
    inside_short = 0
    inside_breaker_above = 0
    inside_breaker_below = 0
    for z in all_zones:
        is_long = _is_long(z)
        zint = z.get("active_zone") or z.get("zone")
        if zint is None:
            continue
        zlo, zhi = zint
        # Inside?
        inside = zlo <= price <= zhi
        if inside:
            n_at_price += 1
            if z.get("flipped_direction"):
                if is_long:  # support below — was SHORT OB pierced, now LONG flip
                    inside_breaker_below += 1
                else:
                    inside_breaker_above += 1
            else:
                if is_long:
                    inside_long += 1
                else:
                    inside_short += 1

        dist_pct = abs(_zone_distance_pct(z, price))
        tf = z.get("tf", "1h")
        w = TF_WEIGHT.get(tf, 1.0)
        if is_long:
            w_long_score += w / (1 + dist_pct)
            if dist_pct <= 1: n_long_1 += 1
            if dist_pct <= 2: n_long_2 += 1
            if dist_pct <= 5: n_long_5 += 1
        else:
            w_short_score += w / (1 + dist_pct)
            if dist_pct <= 1: n_short_1 += 1
            if dist_pct <= 2: n_short_2 += 1
            if dist_pct <= 5: n_short_5 += 1

    out.update({
        "c_n_zones_at_price": float(n_at_price),
        "c_n_long_within_1pct": float(n_long_1),
        "c_n_short_within_1pct": float(n_short_1),
        "c_n_long_within_2pct": float(n_long_2),
        "c_n_short_within_2pct": float(n_short_2),
        "c_n_long_within_5pct": float(n_long_5),
        "c_n_short_within_5pct": float(n_short_5),
        "c_weighted_long_score": w_long_score,
        "c_weighted_short_score": w_short_score,
        "c_inside_long": float(inside_long),
        "c_inside_short": float(inside_short),
        "c_inside_breaker_above": float(inside_breaker_above),
        "c_inside_breaker_below": float(inside_breaker_below),
    })
    return out


# ─── Group D: structural state + inducements ────────────────────────────────

def features_group_d(snap: dict, price: float) -> dict[str, float]:
    """CHoCH/BOS state per TF + inducement counts + flip-zone armed counts."""
    out: dict[str, float] = {}
    for tf in TF_LIST:
        st = snap["structural"].get(tf)
        prefix = f"d_{tf}"
        if st is None:
            out[f"{prefix}_choch_state"] = 0.0
            out[f"{prefix}_last_event_is_choch"] = 0.0
            out[f"{prefix}_last_event_bullish"] = 0.0
            out[f"{prefix}_bars_since"] = 0.0
            out[f"{prefix}_n_choch_24"] = 0.0
            out[f"{prefix}_n_bos_24"] = 0.0
        else:
            out[f"{prefix}_choch_state"] = float(st.get("choch_state", 0))
            out[f"{prefix}_last_event_is_choch"] = 1.0 if st.get("last_event_type") == "CHoCH" else 0.0
            out[f"{prefix}_last_event_bullish"] = 1.0 if st.get("last_event_side") == "bullish" else 0.0
            out[f"{prefix}_bars_since"] = float(st.get("bars_since_last", 0))
            out[f"{prefix}_n_choch_24"] = float(st.get("n_choch_24bars", 0))
            out[f"{prefix}_n_bos_24"] = float(st.get("n_bos_24bars", 0))
    # Inducement counts (across all TFs)
    inds = snap.get("inducements", [])
    out["d_n_inducement_total"] = float(len(inds))
    by_state: dict[str, int] = {}
    by_side: dict[str, int] = {"bullish": 0, "bearish": 0}
    for ind in inds:
        by_state[ind.get("state", "pending")] = by_state.get(ind.get("state", "pending"), 0) + 1
        by_side[ind.get("direction", "bullish")] = by_side.get(ind.get("direction", "bullish"), 0) + 1
    for s in ("pending", "gated", "bouncing", "armed", "triggered", "invalidated"):
        out[f"d_n_inducement_state_{s}"] = float(by_state.get(s, 0))
    out["d_n_inducement_bull"] = float(by_side["bullish"])
    out["d_n_inducement_bear"] = float(by_side["bearish"])
    # Breaker armed counts per direction
    breakers = snap.get("breakers", [])
    mbs = snap.get("mitigation_blocks", [])
    out["d_n_breakers_total"] = float(len(breakers))
    out["d_n_breakers_long_flip"] = float(sum(1 for b in breakers if b.get("flipped_direction") == "long"))
    out["d_n_breakers_short_flip"] = float(sum(1 for b in breakers if b.get("flipped_direction") == "short"))
    out["d_n_mb_total"] = float(len(mbs))
    out["d_n_mb_long_flip"] = float(sum(1 for m in mbs if m.get("flipped_direction") == "long"))
    out["d_n_mb_short_flip"] = float(sum(1 for m in mbs if m.get("flipped_direction") == "short"))
    return out


# ─── Top-level ──────────────────────────────────────────────────────────────

def extract_features(snap: dict) -> dict[str, float]:
    """Flatten snapshot → fixed feature dict.

    Returns dict with keys: 't0', 't0_iso_msk', 'current_price', + ~2000 numeric features.
    """
    price = float(snap.get("current_price") or 0.0)
    out: dict[str, Any] = {
        "t0": snap["t0"],
        "t0_iso_msk": snap["t0_iso_msk"],
        "current_price": price,
    }
    out.update(features_group_a(snap, price))
    out.update(features_group_a_flip(snap, price))
    out.update(features_group_b(snap, price))
    out.update(features_group_c(snap, price))
    out.update(features_group_d(snap, price))
    return out


def feature_columns() -> list[str]:
    """Return canonical feature column order (for empty-snapshot fallback)."""
    fake_snap = {
        "t0": 0, "t0_iso_msk": "", "symbol": "", "current_price": 0,
        "active_zones": [], "fractals": {tf: [] for tf in TF_LIST},
        "structural": {}, "breakers": [], "mitigation_blocks": [], "inducements": [],
    }
    feats = extract_features(fake_snap)
    return list(feats.keys())
