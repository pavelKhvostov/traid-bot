"""FVG scan + event timeline для B1Cx scripts.

FVG (Fair Value Gap) детектируется на 5 TFs (12h/D/2D/3D/W).
Для каждого FVG строится event timeline на 12h:
    list of (bar_idx, penetration_%, close_inside_bool, close_outside_far_bool)

Strict causality: events с bar_idx ≥ ready_ms (FVG complete).
"""
from __future__ import annotations
import numpy as np
import sys, pathlib
sys.path.insert(0, str(pathlib.Path.home() / "smc-lib"))
from candle import Candle
from elements.fvg.code import detect_fvg
from _lib import load_htf_bars, TF_HTF, MS_M


def scan_fvgs(tfs=("12h", "D", "2D", "3D", "W")) -> list[dict]:
    """Detect all FVGs across given TFs. Returns list of dicts."""
    all_fvg = []
    for tf in tfs:
        bars = load_htf_bars(tf)
        cans = [Candle(open=b[1], high=b[2], low=b[3], close=b[4], open_time=b[0]) for b in bars]
        tfms = TF_HTF[tf]
        for i in range(len(cans) - 2):
            fv = detect_fvg(cans[i], cans[i+1], cans[i+2])
            if fv is None: continue
            all_fvg.append({
                "tf": tf,
                "direction": fv.direction,
                "zlo": fv.zone[0],
                "zhi": fv.zone[1],
                "c3_ms": cans[i+2].open_time,
                "ready_ms": cans[i+2].open_time + tfms,
            })
    return all_fvg


def build_events(all_fvg: list[dict], bars12: dict):
    """Mutate each FVG dict to add 'events' list and 'broken_at' index.

    events: [(k, pen%, close_inside, close_outside_far), ...] на 12h grid.
    """
    t12, h12, l12, c12 = bars12["t"], bars12["h"], bars12["l"], bars12["c"]
    n12 = bars12["n"]
    for z in all_fvg:
        sp = int(np.searchsorted(t12, z["ready_ms"], side="left"))
        z["events"] = []
        z["broken_at"] = None
        if sp >= n12: continue
        zlo, zhi = z["zlo"], z["zhi"]
        w = zhi - zlo
        if w <= 0: continue
        for k in range(sp, n12):
            if z["direction"] == "short":
                hh, cc = h12[k], c12[k]
                if hh < zlo: continue
                pen = min((hh - zlo) / w * 100, 999)
                ci = (zlo <= cc <= zhi)
                co_far = (cc < zlo)
                co_thru = (cc > zhi)
            else:
                ll, cc = l12[k], c12[k]
                if ll > zhi: continue
                pen = min((zhi - ll) / w * 100, 999)
                ci = (zlo <= cc <= zhi)
                co_far = (cc > zhi)
                co_thru = (cc < zlo)
            z["events"].append((k, pen, ci, co_far))
            if z["broken_at"] is None and co_thru:
                z["broken_at"] = k


def filt(z: dict, k: int, ftype: str, bars12: dict, atr12: np.ndarray) -> bool:
    """Apply zone filter (WIDE/AGE50/HTF/combinations). Causal at bar k."""
    t12 = bars12["t"]
    if ftype == "ANY":   return True
    age = (t12[k] - z["c3_ms"]) // (12 * 60 * MS_M)
    width = z["zhi"] - z["zlo"]
    a = atr12[k] if atr12[k] > 0 else 1.0
    is_htf = z["tf"] in ("D", "2D", "3D", "W")
    if ftype == "WIDE":       return width / a >= 0.7
    if ftype == "AGE50":      return age >= 50
    if ftype == "AGE50_WIDE": return age >= 50 and width / a >= 0.7
    if ftype == "HTF_WIDE":   return is_htf and width / a >= 0.7
    return False


def fires_strict_sweep(all_fvg: list[dict], bars12: dict, atr12: np.ndarray,
                       pen_min: float, filt_type: str) -> set:
    """Generic strict-sweep filter: pen ≥ pen_min ∧ close OUTSIDE far ∧ zone-filter.

    Returns set of (bar_idx, zone_direction).
    """
    fires = set()
    for z in all_fvg:
        for k, pen, ci, co_far in z["events"]:
            if pen < pen_min: continue
            if not co_far: continue
            if not filt(z, k, filt_type, bars12, atr12): continue
            fires.add((k, z["direction"]))
            break
    return fires
