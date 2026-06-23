"""event_detector_v11 — fix Ошибки #19 (invalid active_zone в simplified path).

v10 имел баг: на LTF (15m/30m) simplified path emit'ил fill_partial с invalid
active_zone (a_lo > a_hi) когда фитиль перепрыгивал через границу зоны:
  LONG: low ≤ z_lo → fill_lvl < z_lo → active_hi < z_lo = active_lo (invalid)
  SHORT: high ≥ z_hi → fill_lvl > z_hi → active_lo > z_hi = active_hi (invalid)

172,918 events (42.9%) в v10 имели invalid bounds. Snapshot v5 → 22% zones
имели corrupted last_active.

v11 fix: _wick_fill_simplified возвращает None для fill если fill_idx ≥ retire_idx
(fill coincides with retire или после). Только retire emit'ится. Active валидный.

Pipeline иначе идентичен v10.

Pipeline: 1m CSV → 8 TFs aggregate → (TF × element) parallel scan
       → ob_vc cross-TF (sequential) → renumber zone_ids globally → events parquet (zstd).

Performance:
  - Vectorized numpy mitigation (wick_fill / first_touch / sweep) — ~100× vs Python loop
  - Pre-built lows/highs numpy arrays per (TF × element) unit
  - 1m CSV: sort + dedupe by ts (fix rogue bar Jan 1 2020 в idx 1045899)

TF-aware канон adaptations (LTF где ML использует только counts/density):
  - 15m/30m: simplified wick_fill — born + fill@50% + retire
  - 15m/30m: skip mitigation_block (forward scan слишком тяжёл)
  - 15m/30m/1h/2h: i_fvg search cap — B в пределах 50 баров от A.c3
  - block_orders: max_len 10 (canon 20) — теряем редкие длинные блоки за ~4×

HTF (4h+): полный канон без adaptations.
"""
from __future__ import annotations
import sys
import csv
import time
import pathlib
import argparse
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from joblib import Parallel, delayed

SMC_LIB = pathlib.Path.home() / "smc-lib"
sys.path.insert(0, str(SMC_LIB))

from candle import Candle
from elements.ob.code import detect_ob
from elements.fvg.code import detect_fvg
from elements.rb.code import detect_rb
from elements.marubozu.code import detect_marubozu
from elements.block_orders.code import detect_block_orders
from elements.rdrb.code import detect_rdrb
from elements.i_rdrb.code import detect_i_rdrb
from elements.i_fvg.code import detect_i_fvg
from elements.ob_liq.code import detect_ob_liq
from elements.fractal.code import detect_fractal
from elements.breaker_block.code import detect_breaker
from elements.mitigation_block.code import detect_mitigation_block


# ─── Paths & schema ───────────────────────────────────────

CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
OUT_PATH = SMC_LIB / "projects/живой-рынок/data/events_v12_2020-01-01_2026-06-15.parquet"

UTC = timezone.utc
TF_MS = {
    "15m": 15 * 60 * 1000, "30m": 30 * 60 * 1000, "1h": 60 * 60 * 1000,
    "2h": 2 * 60 * 60 * 1000, "4h": 4 * 60 * 60 * 1000, "6h": 6 * 60 * 60 * 1000,
    "12h": 12 * 60 * 60 * 1000, "1D": 24 * 60 * 60 * 1000,
}
# Canon 2026-06-22 final: LIQ=fractal only; INE=fvg/i_fvg/marubozu; BLOCK=всё institutional
ROLE = {
    "fractal": "LIQ",
    "fvg": "INE", "i_fvg": "INE", "marubozu": "INE",
    "ob": "BLOCK", "rb": "BLOCK", "ob_liq": "BLOCK", "ob_vc": "BLOCK",
    "rdrb": "BLOCK", "i_rdrb": "BLOCK", "block_orders": "BLOCK",
    "breaker_block": "BLOCK", "mitigation_block": "BLOCK",
}
OB_VC_HTF_TO_LTF = {
    "1h": ("15m", "30m"), "2h": ("15m", "30m"),
    "4h": ("1h", "2h"), "6h": ("1h", "2h"),
    "12h": ("4h", "6h"), "1D": ("4h", "6h"),
}


# ─── Tuning ───────────────────────────────────────────────

LTF_SIMPLIFIED_TFS = {"15m", "30m"}
IFVG_BETWEEN_LIMIT_TFS = {"15m", "30m", "1h", "2h"}
IFVG_BETWEEN_MAX_BARS = 50
BO_MAX_WINDOW = 10
SKIP_HEAVY = {("15m", "mitigation_block"), ("30m", "mitigation_block")}


# ─── Event factory ────────────────────────────────────────

def make_event(ts, elem, tf, direction, action, zone_lo, zone_hi,
               active_lo=None, active_hi=None, source_idx=0, zone_id=0):
    if active_lo is None: active_lo = zone_lo
    if active_hi is None: active_hi = zone_hi
    return {
        "ts": int(ts), "element_type": elem, "tf": tf, "direction": direction,
        "action": action, "level": float((zone_lo + zone_hi) / 2),
        "zone_lo": float(zone_lo), "zone_hi": float(zone_hi),
        "active_zone_lo": float(active_lo), "active_zone_hi": float(active_hi),
        "role": ROLE[elem], "source_idx": int(source_idx),
        "zone_id": int(zone_id),
    }


# ─── Vectorized mitigation primitives ─────────────────────

def _wick_fill_full(z_lo, z_hi, direction, lows, highs, start):
    """Full canon wick_fill: cum_min/max scan."""
    if direction == "long":
        sub = lows[start:]
        if len(sub) == 0: return [], [], None
        cum = np.minimum.accumulate(sub)
        consumed = np.flatnonzero(cum <= z_lo)
        end = int(consumed[0]) if len(consumed) > 0 else len(cum)
        prev = np.concatenate(([z_hi + 1.0], cum[:-1]))
        shrink_mask = (cum < prev) & (cum <= z_hi)
        shrink_local = np.flatnonzero(shrink_mask[:end])
        return (
            (start + shrink_local).tolist(),
            cum[shrink_local].tolist(),
            (start + end) if end < len(cum) else None,
        )
    sub = highs[start:]
    if len(sub) == 0: return [], [], None
    cum = np.maximum.accumulate(sub)
    consumed = np.flatnonzero(cum >= z_hi)
    end = int(consumed[0]) if len(consumed) > 0 else len(cum)
    prev = np.concatenate(([z_lo - 1.0], cum[:-1]))
    shrink_mask = (cum > prev) & (cum >= z_lo)
    shrink_local = np.flatnonzero(shrink_mask[:end])
    return (
        (start + shrink_local).tolist(),
        cum[shrink_local].tolist(),
        (start + end) if end < len(cum) else None,
    )


def _wick_fill_simplified(z_lo, z_hi, direction, lows, highs, start):
    """LTF simplified: born + fill@50% + retire (at most 1 fill_partial).

    Fix Ошибки #19: skip fill_partial если fill_idx ≥ retire_idx (фитиль пробил
    через границу — не emit'ить bogus fill_partial с invalid active bounds).
    """
    mid = (z_lo + z_hi) / 2.0
    if direction == "long":
        sub = lows[start:]
        fill_hits = np.flatnonzero(sub <= mid) if len(sub) else np.array([], dtype=np.int64)
        retire_hits = np.flatnonzero(sub <= z_lo) if len(sub) else np.array([], dtype=np.int64)
    else:
        sub = highs[start:]
        fill_hits = np.flatnonzero(sub >= mid) if len(sub) else np.array([], dtype=np.int64)
        retire_hits = np.flatnonzero(sub >= z_hi) if len(sub) else np.array([], dtype=np.int64)
    retire_idx = (start + int(retire_hits[0])) if len(retire_hits) > 0 else None
    # Только fills СТРОГО до retire (иначе bogus active с invalid bounds)
    if retire_idx is not None:
        fill_hits = fill_hits[(start + fill_hits) < retire_idx]
    fill_idx = (start + int(fill_hits[0])) if len(fill_hits) > 0 else None
    fill_lvl = float(sub[fill_hits[0]]) if len(fill_hits) > 0 else None
    return fill_idx, fill_lvl, retire_idx


# ─── Emit helpers ─────────────────────────────────────────

def emit_wick_fill(elem, tf, ts_list, idx_born, zone, direction,
                    lows, highs, zone_id, born_action="born"):
    """born + fill_partial(s) + retire. Все events с одинаковым zone_id."""
    events = []
    z_lo, z_hi = zone
    events.append(make_event(ts_list[idx_born] + TF_MS[tf], elem, tf, direction,
                              born_action, z_lo, z_hi, source_idx=idx_born,
                              zone_id=zone_id))
    start = idx_born + 1

    if tf in LTF_SIMPLIFIED_TFS:
        fill_idx, fill_lvl, retire_idx = _wick_fill_simplified(
            z_lo, z_hi, direction, lows, highs, start
        )
        if fill_idx is not None:
            a_lo, a_hi = (z_lo, fill_lvl) if direction == "long" else (fill_lvl, z_hi)
            events.append(make_event(ts_list[fill_idx] + TF_MS[tf], elem, tf,
                                      direction, "fill_partial", z_lo, z_hi,
                                      a_lo, a_hi, source_idx=fill_idx, zone_id=zone_id))
        if retire_idx is not None:
            a_lo, a_hi = (z_lo, z_lo) if direction == "long" else (z_hi, z_hi)
            events.append(make_event(ts_list[retire_idx] + TF_MS[tf], elem, tf,
                                      direction, "retire", z_lo, z_hi,
                                      a_lo, a_hi, source_idx=retire_idx, zone_id=zone_id))
        return events

    shrink_idxs, shrink_lvls, retire_idx = _wick_fill_full(
        z_lo, z_hi, direction, lows, highs, start
    )
    for idx, lvl in zip(shrink_idxs, shrink_lvls):
        a_lo, a_hi = (z_lo, lvl) if direction == "long" else (lvl, z_hi)
        events.append(make_event(ts_list[idx] + TF_MS[tf], elem, tf, direction,
                                  "fill_partial", z_lo, z_hi, a_lo, a_hi,
                                  source_idx=idx, zone_id=zone_id))
    if retire_idx is not None:
        a_lo, a_hi = (z_lo, z_lo) if direction == "long" else (z_hi, z_hi)
        events.append(make_event(ts_list[retire_idx] + TF_MS[tf], elem, tf,
                                  direction, "retire", z_lo, z_hi, a_lo, a_hi,
                                  source_idx=retire_idx, zone_id=zone_id))
    return events


def emit_first_touch(elem, tf, ts_list, idx_born, zone, direction,
                      lows, highs, fraction, zone_id):
    """born + retire при первом касании consume_level."""
    events = []
    z_lo, z_hi = zone
    events.append(make_event(ts_list[idx_born] + TF_MS[tf], elem, tf, direction,
                              "born", z_lo, z_hi, source_idx=idx_born, zone_id=zone_id))
    start = idx_born + 1
    if direction == "long":
        level = z_lo + (z_hi - z_lo) * fraction
        hits = np.flatnonzero(lows[start:] <= level)
    else:
        level = z_hi - (z_hi - z_lo) * fraction
        hits = np.flatnonzero(highs[start:] >= level)
    if len(hits) > 0:
        abs_idx = start + int(hits[0])
        events.append(make_event(ts_list[abs_idx] + TF_MS[tf], elem, tf, direction,
                                  "retire", z_lo, z_hi, source_idx=abs_idx, zone_id=zone_id))
    return events


def emit_sweep(elem, tf, ts_list, idx_born, level, direction,
                lows, highs, sweep_dir, zone_id):
    """born + retire при первом sweep'е point level'а."""
    events = [make_event(ts_list[idx_born] + TF_MS[tf], elem, tf, direction,
                          "born", level, level, source_idx=idx_born, zone_id=zone_id)]
    start = idx_born + 1
    sub = lows[start:] if sweep_dir == "low" else highs[start:]
    hits = np.flatnonzero(sub <= level) if sweep_dir == "low" else np.flatnonzero(sub >= level)
    if len(hits) > 0:
        abs_idx = start + int(hits[0])
        events.append(make_event(ts_list[abs_idx] + TF_MS[tf], elem, tf, direction,
                                  "retire", level, level, source_idx=abs_idx, zone_id=zone_id))
    return events


# ─── Per-element scanners ─────────────────────────────────

def scan_ob(candles, ts_list, tf, lows, highs):
    events = []; zid = 0
    for i in range(1, len(candles) - 1):
        ob = detect_ob(candles[i - 1], candles[i])
        if ob is None: continue
        zid += 1
        events.extend(emit_wick_fill("ob", tf, ts_list, i, ob.zone, ob.direction,
                                      lows, highs, zone_id=zid))
    return events


def scan_fvg(candles, ts_list, tf, lows, highs):
    events = []; zid = 0
    for i in range(len(candles) - 2):
        fv = detect_fvg(candles[i], candles[i + 1], candles[i + 2])
        if fv is None: continue
        zid += 1
        events.extend(emit_wick_fill("fvg", tf, ts_list, i + 2, fv.zone, fv.direction,
                                      lows, highs, zone_id=zid))
    return events


def scan_rb(candles, ts_list, tf, lows, highs):
    """RB canon: BOTTOM (long support) / TOP (short resist); first_touch fraction=0.5."""
    events = []; zid = 0
    for i, c in enumerate(candles):
        rb = detect_rb(c)
        if rb is None: continue
        zid += 1
        z_lo, z_hi = rb.zone
        events.append(make_event(ts_list[i] + TF_MS[tf], "rb", tf, rb.direction,
                                  "born", z_lo, z_hi, source_idx=i, zone_id=zid))
        start = i + 1
        if rb.direction == "bottom":
            level = z_lo + (z_hi - z_lo) * 0.5
            hits = np.flatnonzero(lows[start:] <= level)
        else:
            level = z_hi - (z_hi - z_lo) * 0.5
            hits = np.flatnonzero(highs[start:] >= level)
        if len(hits) > 0:
            abs_idx = start + int(hits[0])
            events.append(make_event(ts_list[abs_idx] + TF_MS[tf], "rb", tf,
                                      rb.direction, "retire", z_lo, z_hi,
                                      source_idx=abs_idx, zone_id=zid))
    return events


def scan_marubozu(candles, ts_list, tf, lows, highs):
    events = []; zid = 0
    for i, c in enumerate(candles):
        m = detect_marubozu(c)
        if m is None: continue
        zid += 1
        sweep_dir = "low" if m.direction == "long" else "high"
        events.extend(emit_sweep("marubozu", tf, ts_list, i, m.candle.open,
                                  m.direction, lows, highs, sweep_dir, zone_id=zid))
    return events


def scan_fractal(candles, ts_list, tf, lows, highs, n=2):
    events = []; zid = 0
    for center in range(n, len(candles) - n):
        window = candles[center - n: center + n + 1]
        fr = detect_fractal(window, n=n)
        if fr is None: continue
        zid += 1
        confirm = center + n
        sweep_dir = "low" if fr.direction == "low" else "high"
        events.extend(emit_sweep("fractal", tf, ts_list, confirm, fr.level,
                                  fr.direction, lows, highs, sweep_dir, zone_id=zid))
    return events


def scan_block_orders(candles, ts_list, tf, lows, highs):
    """block_orders: preceding + N₁ initial + N₂ counter, окно 3..BO_MAX_WINDOW."""
    events = []; zid = 0
    n = len(candles)
    for i in range(n - 2):
        for window in range(3, min(BO_MAX_WINDOW + 1, n - i)):
            bo = detect_block_orders(candles[i: i + window])
            if bo is None: continue
            zid += 1
            block_end = i + window - 1
            events.extend(emit_wick_fill("block_orders", tf, ts_list, block_end,
                                          bo.zone, bo.direction, lows, highs, zone_id=zid))
            break
    return events


def scan_rdrb(candles, ts_list, tf, lows, highs):
    events = []; zid = 0
    for i in range(len(candles) - 2):
        r = detect_rdrb(candles[i], candles[i + 1], candles[i + 2])
        if r is None: continue
        zid += 1
        events.extend(emit_wick_fill("rdrb", tf, ts_list, i + 2, r.poi, r.direction,
                                      lows, highs, zone_id=zid))
    return events


def scan_i_rdrb(candles, ts_list, tf, lows, highs):
    events = []; zid = 0
    for i in range(len(candles) - 3):
        ir = detect_i_rdrb(candles[i], candles[i + 1], candles[i + 2], candles[i + 3])
        if ir is None: continue
        zid += 1
        events.extend(emit_wick_fill("i_rdrb", tf, ts_list, i + 3, ir.poi, ir.direction,
                                      lows, highs, zone_id=zid))
    return events


def scan_i_fvg(candles, ts_list, tf, lows, highs):
    """i-FVG canon v2: pair (A, B) opposite direction; ZoI = overlap(shrunk_A, B.zone).
    Canon stop: A dead когда wick касается far border. На LTF дополнительный cap
    IFVG_BETWEEN_MAX_BARS bars между A.c3 и B.c1.
    """
    events = []; zid = 0
    n = len(candles)
    between_cap = IFVG_BETWEEN_MAX_BARS if tf in IFVG_BETWEEN_LIMIT_TFS else None

    fvgs = []
    for i in range(n - 2):
        fv = detect_fvg(candles[i], candles[i + 1], candles[i + 2])
        if fv is None: continue
        fvgs.append((i, i + 1, i + 2, fv))

    for ai, (a1, a2, a3, A) in enumerate(fvgs):
        if A.direction == "long":
            mask = lows[a3 + 1:] <= A.zone[0]
        else:
            mask = highs[a3 + 1:] >= A.zone[1]
        hits = np.flatnonzero(mask)
        a_dead_at = (a3 + 1 + int(hits[0])) if len(hits) > 0 else n
        if between_cap is not None:
            a_dead_at = min(a_dead_at, a3 + between_cap + 1)

        for (b1, b2, b3, B) in fvgs[ai + 1:]:
            if b1 > a_dead_at: break
            if B.direction == A.direction: continue
            if b1 <= a3: continue
            between = tuple(candles[a3 + 1: b1])
            ifvg = detect_i_fvg(
                candles[a1], candles[a2], candles[a3], between,
                candles[b1], candles[b2], candles[b3],
            )
            if ifvg is None: continue
            zid += 1
            events.extend(emit_wick_fill("i_fvg", tf, ts_list, b3, ifvg.overlap,
                                          ifvg.direction, lows, highs, zone_id=zid))
    return events


def scan_ob_liq(candles, ts_list, tf, lows, highs):
    """ob_liq canon: ZoI = LIQ marker (narrow); first_touch fraction=1.0 (rigid outer edge)."""
    events = []; zid = 0
    for i in range(1, len(candles)):
        ol = detect_ob_liq(candles[i - 1], candles[i])
        if ol is None: continue
        zid += 1
        events.extend(emit_first_touch("ob_liq", tf, ts_list, i, ol.zone, ol.direction,
                                        lows, highs, fraction=1.0, zone_id=zid))
    return events


def scan_breaker_block(candles, ts_list, tf, lows, highs):
    """breaker_block canon v4: ARMED на close-cross в окне bar 3-6 после OB."""
    events = []; zid = 0
    n = len(candles)
    for i in range(1, n - 1):
        ob = detect_ob(candles[i - 1], candles[i])
        if ob is None: continue
        br = detect_breaker(ob, candles[i + 1:])
        if br is None: continue
        armed_abs = i + 1 + br.activated_at_idx
        if armed_abs >= len(ts_list): continue
        zid += 1
        z_lo, z_hi = br.initial_zone
        events.append(make_event(ts_list[armed_abs] + TF_MS[tf], "breaker_block", tf,
                                  br.direction, "armed", z_lo, z_hi,
                                  source_idx=armed_abs, zone_id=zid))
        if br.consumed_at_idx is not None:
            consumed_abs = i + 1 + br.consumed_at_idx
            if consumed_abs < len(ts_list):
                events.append(make_event(ts_list[consumed_abs] + TF_MS[tf], "breaker_block",
                                          tf, br.direction, "retire", z_lo, z_hi,
                                          source_idx=consumed_abs, zone_id=zid))
    return events


def scan_mitigation_block(candles, ts_list, tf, lows, highs):
    """mitigation_block canon: OB fully broken + Правило 1 → ARMED; wick_fill mit."""
    events = []; zid = 0
    n = len(candles)
    for i in range(1, n - 4):
        ob = detect_ob(candles[i - 1], candles[i])
        if ob is None: continue
        mb = detect_mitigation_block(ob, candles[i + 1:])
        if mb is None: continue
        armed_abs = i + 1 + mb.armed_at_idx
        if armed_abs >= len(ts_list): continue
        zid += 1
        events.extend(emit_wick_fill("mitigation_block", tf, ts_list, armed_abs,
                                      mb.zone, mb.direction, lows, highs,
                                      zone_id=zid, born_action="armed"))
    return events


SCANNERS = [
    ("ob", scan_ob),
    ("fvg", scan_fvg),
    ("rb", scan_rb),
    ("marubozu", scan_marubozu),
    ("block_orders", scan_block_orders),
    ("rdrb", scan_rdrb),
    ("i_rdrb", scan_i_rdrb),
    ("i_fvg", scan_i_fvg),
    ("ob_liq", scan_ob_liq),
    ("fractal", scan_fractal),
    ("breaker_block", scan_breaker_block),
    ("mitigation_block", scan_mitigation_block),
]


# ─── ob_vc cross-TF (HTF OB ⨯ LTF FVG) ────────────────────

def scan_ob_vc_cross_tf(tf_bars_all):
    """ob_vc canon: per HTF OB scan matching LTF FVGs в окне [prev_open, cur_close+2×HTF]."""
    candles_by_tf = {tf: to_candles(bars) for tf, bars in tf_bars_all.items()}
    ts_by_tf = {tf: [b[0] for b in bars] for tf, bars in tf_bars_all.items()}
    lows_by_tf = {tf: np.array([c.low for c in cans], dtype=np.float64)
                   for tf, cans in candles_by_tf.items()}
    highs_by_tf = {tf: np.array([c.high for c in cans], dtype=np.float64)
                    for tf, cans in candles_by_tf.items()}

    fvgs_by_tf = {}
    needed_ltfs = {ltf for ltfs in OB_VC_HTF_TO_LTF.values() for ltf in ltfs}
    for ltf in needed_ltfs:
        if ltf not in candles_by_tf: continue
        cans, ts_list = candles_by_tf[ltf], ts_by_tf[ltf]
        ltf_long, ltf_short = [], []
        for i in range(len(cans) - 2):
            fv = detect_fvg(cans[i], cans[i + 1], cans[i + 2])
            if fv is None: continue
            entry = {"c1_open_ms": ts_list[i],
                     "c3_close_ms": ts_list[i + 2] + TF_MS[ltf],
                     "zone": fv.zone}
            (ltf_long if fv.direction == "long" else ltf_short).append(entry)
        fvgs_by_tf[(ltf, "long")] = sorted(ltf_long, key=lambda x: x["c1_open_ms"])
        fvgs_by_tf[(ltf, "short")] = sorted(ltf_short, key=lambda x: x["c1_open_ms"])

    events = []; zid = 0
    for htf, ltf_pair in OB_VC_HTF_TO_LTF.items():
        if htf not in candles_by_tf: continue
        htf_cans, htf_ts = candles_by_tf[htf], ts_by_tf[htf]
        htf_ms = TF_MS[htf]
        lows, highs = lows_by_tf[htf], highs_by_tf[htf]
        for i in range(1, len(htf_cans)):
            ob = detect_ob(htf_cans[i - 1], htf_cans[i])
            if ob is None: continue
            cur_open_ms = htf_ts[i]; cur_close_ms = cur_open_ms + htf_ms
            prev_open_ms = cur_open_ms - htf_ms
            if ob.direction == "long":
                drop_area = (min(ob.prev.low, ob.cur.low), ob.prev.open)
            else:
                drop_area = (ob.prev.open, max(ob.prev.high, ob.cur.high))

            matched = []
            for ltf in ltf_pair:
                for fvg in fvgs_by_tf.get((ltf, ob.direction), []):
                    if fvg["c1_open_ms"] < prev_open_ms: continue
                    if fvg["c1_open_ms"] > cur_close_ms + htf_ms * 2: break
                    if max(fvg["zone"][0], drop_area[0]) > min(fvg["zone"][1], drop_area[1]):
                        continue
                    matched.append(fvg)
            if not matched: continue

            for fvg in matched:
                zid += 1
                z_lo, z_hi = fvg["zone"]
                born_ts = max(cur_close_ms, fvg["c3_close_ms"])
                events.append(make_event(born_ts, "ob_vc", htf, ob.direction,
                                          "born", z_lo, z_hi, source_idx=i, zone_id=zid))
                shrink_idxs, shrink_lvls, retire_idx = _wick_fill_full(
                    z_lo, z_hi, ob.direction, lows, highs, i + 1
                )
                for idx, lvl in zip(shrink_idxs, shrink_lvls):
                    a_lo, a_hi = (z_lo, lvl) if ob.direction == "long" else (lvl, z_hi)
                    events.append(make_event(htf_ts[idx] + htf_ms, "ob_vc", htf,
                                              ob.direction, "fill_partial",
                                              z_lo, z_hi, a_lo, a_hi,
                                              source_idx=idx, zone_id=zid))
                if retire_idx is not None:
                    a_lo, a_hi = (z_lo, z_lo) if ob.direction == "long" else (z_hi, z_hi)
                    events.append(make_event(htf_ts[retire_idx] + htf_ms, "ob_vc", htf,
                                              ob.direction, "retire", z_lo, z_hi,
                                              a_lo, a_hi, source_idx=retire_idx, zone_id=zid))
    return events


# ─── Data loading & aggregation ───────────────────────────

def load_1m():
    """Load 1m CSV, sort by ts, dedupe — fix rogue bar."""
    print(f"Loading 1m from {CSV_PATH.name}...", file=sys.stderr, flush=True)
    bars = []
    with CSV_PATH.open() as f:
        rd = csv.reader(f); next(rd)
        for r in rd:
            t = datetime.fromisoformat(r[0]).replace(tzinfo=UTC)
            ts = int(t.timestamp() * 1000)
            bars.append((ts, float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
    bars.sort(key=lambda b: b[0])
    seen = set(); clean = []
    for b in bars:
        if b[0] in seen: continue
        seen.add(b[0]); clean.append(b)
    if len(clean) != len(bars):
        print(f"  deduped: {len(bars):,} → {len(clean):,}", file=sys.stderr, flush=True)
    return clean


def aggregate(bars_1m, tf_ms):
    out = []
    cur_bucket = None; o = h = l = c = None; v = 0
    for ts, bo, bh, bl, bc, bv in bars_1m:
        bucket = ts - (ts % tf_ms)
        if cur_bucket is None:
            cur_bucket = bucket; o, h, l, c, v = bo, bh, bl, bc, bv
            continue
        if bucket != cur_bucket:
            out.append((cur_bucket, o, h, l, c, v))
            cur_bucket = bucket; o, h, l, c, v = bo, bh, bl, bc, bv
        else:
            h = max(h, bh); l = min(l, bl); c = bc; v += bv
    if cur_bucket is not None:
        out.append((cur_bucket, o, h, l, c, v))
    return out


def to_candles(bars):
    return [Candle(open=b[1], high=b[2], low=b[3], close=b[4]) for b in bars]


def filter_range(bars, start_ts, end_ts):
    return [b for b in bars if start_ts <= b[0] <= end_ts]


# ─── Parallel orchestration ───────────────────────────────

def scan_one_unit(args):
    tf, bars, elem, scanner = args
    candles = to_candles(bars)
    ts_list = [b[0] for b in bars]
    lows = np.array([c.low for c in candles], dtype=np.float64)
    highs = np.array([c.high for c in candles], dtype=np.float64)
    return scanner(candles, ts_list, tf, lows, highs)


def main(start, end, n_workers=14):
    bars_1m = load_1m()
    start_ts = int(datetime.fromisoformat(start).replace(tzinfo=UTC).timestamp() * 1000)
    end_ts = int(datetime.fromisoformat(end).replace(tzinfo=UTC).timestamp() * 1000)

    print("Aggregating 8 TFs...", file=sys.stderr, flush=True)
    tf_bars = {}
    for tf, ms in TF_MS.items():
        agg = filter_range(aggregate(bars_1m, ms), start_ts, end_ts)
        tf_bars[tf] = agg
        print(f"  {tf}: {len(agg):,}", file=sys.stderr, flush=True)
    del bars_1m

    work_units = [(tf, bars, elem, scanner)
                  for tf, bars in tf_bars.items()
                  for elem, scanner in SCANNERS
                  if (tf, elem) not in SKIP_HEAVY]
    print(f"\nParallel scan: {len(work_units)} units on {n_workers} workers...",
          file=sys.stderr, flush=True)
    t0 = time.time()
    per_unit = Parallel(n_jobs=n_workers, backend="loky", verbose=5)(
        delayed(scan_one_unit)(u) for u in work_units
    )
    # Globally unique zone_ids: renumber local 1..N с накопительным offset
    zid_offset = 0
    for sub in per_unit:
        if not sub: continue
        local_max = max(e["zone_id"] for e in sub)
        for e in sub:
            if e["zone_id"] > 0:
                e["zone_id"] += zid_offset
        zid_offset += local_max
    all_events = [e for sub in per_unit for e in sub]
    print(f"Per-unit done in {time.time() - t0:.0f}s, {len(all_events):,} events",
          file=sys.stderr, flush=True)

    t1 = time.time()
    ob_vc_events = scan_ob_vc_cross_tf(tf_bars)
    if ob_vc_events:
        local_max = max(e["zone_id"] for e in ob_vc_events)
        for e in ob_vc_events:
            if e["zone_id"] > 0:
                e["zone_id"] += zid_offset
        zid_offset += local_max
    all_events.extend(ob_vc_events)
    print(f"ob_vc cross-TF: {len(ob_vc_events):,} events in {time.time() - t1:.0f}s",
          file=sys.stderr, flush=True)

    df = pd.DataFrame(all_events).sort_values("ts").reset_index(drop=True)
    df.to_parquet(OUT_PATH, index=False, compression="zstd", compression_level=9)
    print(f"\nSaved {len(df):,} events → {OUT_PATH}", file=sys.stderr)
    print("By element × action:", file=sys.stderr)
    print(pd.crosstab(df["element_type"], df["action"]), file=sys.stderr)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2020-01-01")
    ap.add_argument("--end", default="2026-06-15")
    ap.add_argument("--workers", type=int, default=14)
    a = ap.parse_args()
    main(a.start, a.end, a.workers)
