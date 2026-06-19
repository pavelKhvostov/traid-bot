"""Этап 1 — Comprehensive event detector для проекта «Живой рынок».

Сканирует ВСЕ 14 элементов на ВСЕХ 8 канонических TF, выдаёт chronological log
events: births + key actions (sweep, fill_partial, fill_full, break).

Канон: per Правило 2 (mitigation models), Правило 14 (TF anchor = 0 UTC),
Правило 8 (роли LIQ/INE/BLOCK/STRUCT).

Output: events.parquet с колонками:
  ts (int, ms UTC), element_type, tf, direction, action,
  level (float), magnitude_pct (float), role,
  source_idx (int — индекс bar где event случился)

Usage:
    python3 event_detector.py [--start 2020-01-01] [--end 2026-06-15]
"""
from __future__ import annotations

import sys
import csv
import time
import bisect
import pathlib
import argparse
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass

import pandas as pd

SMC_LIB = pathlib.Path.home() / "smc-lib"
sys.path.insert(0, str(SMC_LIB))

from candle import Candle
from elements.ob.code import detect_ob, is_full_break
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
from elements.choch_bos.code import scan_market_structure
from elements._mitigation import (
    apply_wick_fill_mitigation,
    apply_first_touch_mitigation,
    apply_sweep_mitigation,
)

# Configuration
CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
OUT_DIR = SMC_LIB / "projects/живой-рынок/data"
OUT_DIR.mkdir(parents=True, exist_ok=True)

MS = 60_000
ANCHOR_MS = 0  # Rule 14: 0 UTC anchor для non-W
UTC = timezone.utc

TF_MS = {
    "15m": 15 * MS,
    "30m": 30 * MS,
    "1h": 60 * MS,
    "2h": 120 * MS,
    "4h": 240 * MS,
    "6h": 360 * MS,
    "12h": 720 * MS,
    "1D": 1440 * MS,
}

# Per element-type role assignment (Правило 8)
ELEMENT_ROLE = {
    "fractal": "LIQ",
    "rb": "LIQ",
    "ob_liq_liq": "LIQ",        # liq_zone маркер
    "marubozu_open": "LIQ",
    "fvg": "INE",
    "i_fvg": "INE",
    "marubozu_body": "INE",
    "ob": "BLOCK",
    "rdrb": "BLOCK",
    "i_rdrb": "BLOCK",
    "block_orders": "BLOCK",
    "ob_liq": "BLOCK",
    "ob_vc": "BLOCK",
    "breaker_block": "BLOCK",
    "mitigation_block": "BLOCK",
    "choch_bos": "STRUCT",
}


def load_1m_csv():
    """Load 1m CSV → list of (ts_ms, o, h, l, c)."""
    print(f"Loading {CSV_PATH}...", file=sys.stderr, flush=True)
    rows = []
    with CSV_PATH.open() as f:
        rd = csv.reader(f)
        next(rd)
        for r in rd:
            t = datetime.fromisoformat(r[0]).replace(tzinfo=UTC)
            ts_ms = int(t.timestamp() * 1000)
            rows.append((ts_ms, float(r[1]), float(r[2]), float(r[3]), float(r[4])))
    print(f"  loaded {len(rows):,} 1m bars", file=sys.stderr, flush=True)
    return rows


def aggregate_to_tf(bars_1m, tf_ms, anchor_ms=ANCHOR_MS):
    """Aggregate 1m → HTF bars [(ts, o, h, l, c)] with anchor."""
    out = []
    cur_bucket = None
    o = h = l = c = 0.0
    for ts, oo, hh, ll, cc in bars_1m:
        bucket = ts - ((ts - anchor_ms) % tf_ms)
        if bucket != cur_bucket:
            if cur_bucket is not None:
                out.append((cur_bucket, o, h, l, c))
            cur_bucket = bucket
            o, h, l, c = oo, hh, ll, cc
        else:
            h = max(h, hh)
            l = min(l, ll)
            c = cc
    if cur_bucket is not None:
        out.append((cur_bucket, o, h, l, c))
    return out


def to_candles(tf_bars):
    """Convert aggregated bars to Candle objects."""
    return [Candle(open=b[1], high=b[2], low=b[3], close=b[4]) for b in tf_bars]


def filter_range(bars, start_ts, end_ts):
    """Slice bars to time range."""
    return [b for b in bars if start_ts <= b[0] <= end_ts]


# ─── Per-element event extractors (births + key actions) ──────────────────

def events_fractal(candles, ts_list, tf_label, n=2):
    """Fractal births + sweeps."""
    out = []
    total = len(candles)
    for center_idx in range(n, total - n):
        window = candles[center_idx - n: center_idx + n + 1]
        fr = detect_fractal(window, n=n)
        if fr is None:
            continue
        confirm_idx = center_idx + n  # confirmation at last bar of window
        zone_lo = zone_hi = fr.level  # точечный level (sweep element)
        out.append({
            "ts": ts_list[confirm_idx] + TF_MS[tf_label],
            "element_type": "fractal",
            "tf": tf_label,
            "direction": fr.direction,
            "action": "born",
            "level": fr.level,
            "zone_lo": zone_lo,
            "zone_hi": zone_hi,
            "magnitude_pct": 0.0,
            "role": "LIQ",
            "source_idx": center_idx,
        })
        # Sweep tracking on subsequent bars
        subsequent = candles[confirm_idx + 1:]
        sw = apply_sweep_mitigation(
            level=fr.level,
            direction=fr.direction,
            subsequent_bars=subsequent,
            start_idx=confirm_idx + 1,
        )
        if sw["swept"]:
            out.append({
                "ts": ts_list[sw["swept_at_bar"]] + TF_MS[tf_label],
                "element_type": "fractal",
                "tf": tf_label,
                "direction": fr.direction,
                "action": "sweep",
                "level": fr.level,
                "zone_lo": zone_lo,
                "zone_hi": zone_hi,
                "magnitude_pct": sw["magnitude_pct"],
                "role": "LIQ",
                "source_idx": sw["swept_at_bar"],
            })
    return out


def events_ob(candles, ts_list, tf_label):
    """OB births + wick-fill tracking. Canon 2026-06-14: zone = drop/rally area."""
    out = []
    n = len(candles)
    for i in range(1, n - 1):
        ob = detect_ob(candles[i - 1], candles[i])
        if ob is None:
            continue
        born_ts = ts_list[i] + TF_MS[tf_label]
        zone_lo, zone_hi = ob.zone
        center = (zone_lo + zone_hi) / 2
        out.append({
            "ts": born_ts,
            "element_type": "ob",
            "tf": tf_label,
            "direction": ob.direction,
            "action": "born",
            "level": center,
            "zone_lo": zone_lo,
            "zone_hi": zone_hi,
            "magnitude_pct": 0.0,
            "role": "BLOCK",
            "source_idx": i,
        })
        state = apply_wick_fill_mitigation(
            initial_zone=ob.zone,
            direction=ob.direction,
            subsequent_bars=candles[i + 1:],
            start_idx=i + 1,
        )
        if state.n_real_mitigations > 0 and state.mit_history:
            first_mit_idx, _ = state.mit_history[0]
            out.append({
                "ts": ts_list[first_mit_idx] + TF_MS[tf_label],
                "element_type": "ob",
                "tf": tf_label,
                "direction": ob.direction,
                "action": "fill_partial",
                "level": center,
                "zone_lo": zone_lo,
                "zone_hi": zone_hi,
                "magnitude_pct": (zone_hi - zone_lo) / center * 100,
                "role": "BLOCK",
                "source_idx": first_mit_idx,
            })
        if state.is_consumed:
            out.append({
                "ts": ts_list[state.consumed_at_bar] + TF_MS[tf_label],
                "element_type": "ob",
                "tf": tf_label,
                "direction": ob.direction,
                "action": "fill_full",
                "level": center,
                "zone_lo": zone_lo,
                "zone_hi": zone_hi,
                "magnitude_pct": 0.0,
                "role": "BLOCK",
                "source_idx": state.consumed_at_bar,
            })
    return out


def events_fvg(candles, ts_list, tf_label):
    """FVG births + wick-fill tracking."""
    out = []
    n = len(candles)
    for i in range(n - 2):
        fvg = detect_fvg(candles[i], candles[i + 1], candles[i + 2])
        if fvg is None:
            continue
        born_idx = i + 2
        born_ts = ts_list[born_idx] + TF_MS[tf_label]
        zone_lo, zone_hi = fvg.zone
        center = (zone_lo + zone_hi) / 2
        out.append({
            "ts": born_ts, "element_type": "fvg", "tf": tf_label,
            "direction": fvg.direction, "action": "born", "level": center,
            "zone_lo": zone_lo, "zone_hi": zone_hi,
            "magnitude_pct": 0.0, "role": "INE", "source_idx": born_idx,
        })
        state = apply_wick_fill_mitigation(
            initial_zone=fvg.zone, direction=fvg.direction,
            subsequent_bars=candles[born_idx + 1:], start_idx=born_idx + 1,
        )
        if state.is_consumed:
            out.append({
                "ts": ts_list[state.consumed_at_bar] + TF_MS[tf_label],
                "element_type": "fvg", "tf": tf_label,
                "direction": fvg.direction, "action": "fill_full", "level": center,
                "zone_lo": zone_lo, "zone_hi": zone_hi,
                "magnitude_pct": 0.0, "role": "INE",
                "source_idx": state.consumed_at_bar,
            })
    return out


def events_choch_bos(candles, ts_list, tf_label):
    """CHoCH/BOS structural events."""
    out = []
    try:
        events_list = scan_market_structure(candles)
    except Exception:
        return []
    for ev in events_list:
        idx = ev.break_idx
        lvl = ev.fractal_level  # canon: MarketStructureEvent.fractal_level
        out.append({
            "ts": ts_list[idx] + TF_MS[tf_label],
            "element_type": "choch_bos", "tf": tf_label,
            "direction": ev.side, "action": ev.type.lower(),  # "bos" or "choch"
            "level": lvl, "zone_lo": lvl, "zone_hi": lvl,    # event = line, не зона
            "magnitude_pct": 0.0, "role": "STRUCT", "source_idx": idx,
        })
    return out


def events_marubozu(candles, ts_list, tf_label):
    """Marubozu births + open-level sweep (canon: open = магнит уровень)."""
    out = []
    for i, c in enumerate(candles):
        m = detect_marubozu(c)
        if m is None:
            continue
        born_ts = ts_list[i] + TF_MS[tf_label]
        lvl = m.candle.open
        out.append({
            "ts": born_ts, "element_type": "marubozu", "tf": tf_label,
            "direction": m.direction, "action": "born",
            "level": lvl, "zone_lo": lvl, "zone_hi": lvl,
            "magnitude_pct": 0.0, "role": "LIQ", "source_idx": i,
        })
        sweep_dir = "low" if m.direction == "long" else "high"
        sw = apply_sweep_mitigation(level=lvl, direction=sweep_dir,
                                     subsequent_bars=candles[i + 1:], start_idx=i + 1)
        if sw["swept"]:
            out.append({
                "ts": ts_list[sw["swept_at_bar"]] + TF_MS[tf_label],
                "element_type": "marubozu", "tf": tf_label,
                "direction": m.direction, "action": "sweep",
                "level": lvl, "zone_lo": lvl, "zone_hi": lvl,
                "magnitude_pct": sw["magnitude_pct"], "role": "LIQ",
                "source_idx": sw["swept_at_bar"],
            })
    return out


def events_rdrb(candles, ts_list, tf_label):
    """RDRB births + wick-fill on POI."""
    out = []
    n = len(candles)
    for i in range(n - 2):
        r = detect_rdrb(candles[i], candles[i + 1], candles[i + 2])
        if r is None:
            continue
        born_idx = i + 2
        born_ts = ts_list[born_idx] + TF_MS[tf_label]
        zone_lo, zone_hi = r.poi
        center = (zone_lo + zone_hi) / 2
        out.append({
            "ts": born_ts, "element_type": "rdrb", "tf": tf_label,
            "direction": r.direction, "action": "born", "level": center,
            "zone_lo": zone_lo, "zone_hi": zone_hi,
            "magnitude_pct": 0.0, "role": "BLOCK", "source_idx": born_idx,
        })
        state = apply_wick_fill_mitigation(
            initial_zone=r.poi, direction=r.direction,
            subsequent_bars=candles[born_idx + 1:], start_idx=born_idx + 1,
        )
        if state.n_real_mitigations > 0 and state.mit_history:
            first_idx, _ = state.mit_history[0]
            out.append({
                "ts": ts_list[first_idx] + TF_MS[tf_label],
                "element_type": "rdrb", "tf": tf_label,
                "direction": r.direction, "action": "fill_partial", "level": center,
                "zone_lo": zone_lo, "zone_hi": zone_hi,
                "magnitude_pct": 0.0, "role": "BLOCK", "source_idx": first_idx,
            })
        if state.is_consumed:
            out.append({
                "ts": ts_list[state.consumed_at_bar] + TF_MS[tf_label],
                "element_type": "rdrb", "tf": tf_label,
                "direction": r.direction, "action": "fill_full", "level": center,
                "zone_lo": zone_lo, "zone_hi": zone_hi,
                "magnitude_pct": 0.0, "role": "BLOCK",
                "source_idx": state.consumed_at_bar,
            })
    return out


def events_i_rdrb(candles, ts_list, tf_label):
    """i-RDRB births + wick-fill on POI (4 свечи)."""
    out = []
    n = len(candles)
    for i in range(n - 3):
        ir = detect_i_rdrb(candles[i], candles[i + 1], candles[i + 2], candles[i + 3])
        if ir is None:
            continue
        born_idx = i + 3
        born_ts = ts_list[born_idx] + TF_MS[tf_label]
        zone_lo, zone_hi = ir.poi
        center = (zone_lo + zone_hi) / 2
        out.append({
            "ts": born_ts, "element_type": "i_rdrb", "tf": tf_label,
            "direction": ir.direction, "action": "born", "level": center,
            "zone_lo": zone_lo, "zone_hi": zone_hi,
            "magnitude_pct": 0.0, "role": "BLOCK", "source_idx": born_idx,
        })
        state = apply_wick_fill_mitigation(
            initial_zone=ir.poi, direction=ir.direction,
            subsequent_bars=candles[born_idx + 1:], start_idx=born_idx + 1,
        )
        if state.is_consumed:
            out.append({
                "ts": ts_list[state.consumed_at_bar] + TF_MS[tf_label],
                "element_type": "i_rdrb", "tf": tf_label,
                "direction": ir.direction, "action": "fill_full", "level": center,
                "zone_lo": zone_lo, "zone_hi": zone_hi,
                "magnitude_pct": 0.0, "role": "BLOCK",
                "source_idx": state.consumed_at_bar,
            })
    return out


def events_block_orders(candles, ts_list, tf_label, max_len=20):
    """Block orders births + wick-fill (canon 2026-06-15: zone = drop/rally only)."""
    out = []
    n = len(candles)
    for i in range(n - 2):
        for window in range(3, min(max_len + 1, n - i)):
            slice_ = candles[i: i + window]
            bo = detect_block_orders(slice_)
            if bo is None:
                continue
            block_end_idx = i + window - 1
            born_ts = ts_list[block_end_idx] + TF_MS[tf_label]
            zone_lo, zone_hi = bo.zone
            center = (zone_lo + zone_hi) / 2
            out.append({
                "ts": born_ts, "element_type": "block_orders", "tf": tf_label,
                "direction": bo.direction, "action": "born", "level": center,
                "zone_lo": zone_lo, "zone_hi": zone_hi,
                "magnitude_pct": 0.0, "role": "BLOCK", "source_idx": block_end_idx,
            })
            state = apply_wick_fill_mitigation(
                initial_zone=bo.zone, direction=bo.direction,
                subsequent_bars=candles[block_end_idx + 1:], start_idx=block_end_idx + 1,
            )
            if state.is_consumed:
                out.append({
                    "ts": ts_list[state.consumed_at_bar] + TF_MS[tf_label],
                    "element_type": "block_orders", "tf": tf_label,
                    "direction": bo.direction, "action": "fill_full", "level": center,
                    "zone_lo": zone_lo, "zone_hi": zone_hi,
                    "magnitude_pct": 0.0, "role": "BLOCK",
                    "source_idx": state.consumed_at_bar,
                })
            break  # one block per start
    return out


def events_ob_liq(candles, ts_list, tf_label):
    """ob_liq births + liq_zone first-touch.

    Main zone (canon-OB) — для входа.
    liq_zone (узкий маркер ликвидности) — для retire через first-touch (zone boundary, fraction=1.0).
    """
    out = []
    n = len(candles)
    for i in range(1, n):
        ol = detect_ob_liq(candles[i - 1], candles[i])
        if ol is None:
            continue
        born_ts = ts_list[i] + TF_MS[tf_label]
        zone_lo, zone_hi = ol.zone
        center = (zone_lo + zone_hi) / 2
        out.append({
            "ts": born_ts, "element_type": "ob_liq", "tf": tf_label,
            "direction": ol.direction, "action": "born", "level": center,
            "zone_lo": zone_lo, "zone_hi": zone_hi,
            "magnitude_pct": 0.0, "role": "BLOCK", "source_idx": i,
        })
        liq_lo, liq_hi = ol.liq_zone
        liq_center = (liq_lo + liq_hi) / 2
        liq_state = apply_first_touch_mitigation(
            initial_zone=ol.liq_zone, direction=ol.direction,
            subsequent_bars=candles[i + 1:], start_idx=i + 1,
        )
        if liq_state.is_consumed:
            out.append({
                "ts": ts_list[liq_state.consumed_at_bar] + TF_MS[tf_label],
                "element_type": "ob_liq", "tf": tf_label,
                "direction": ol.direction, "action": "liq_first_touch",
                "level": liq_center,
                "zone_lo": liq_lo, "zone_hi": liq_hi,
                "magnitude_pct": 0.0, "role": "LIQ",
                "source_idx": liq_state.consumed_at_bar,
            })
    return out


def events_breaker_block(candles, ts_list, tf_label):
    """Breaker block births + wick-fill retire (canon v4 2026-06-15).

    v4: ARM при close>prev.high (LONG OB) / close<prev.low (SHORT OB)
    в окне bar 3-6 = post_bars[0..3]. Wick-fill mit с свечи ПОСЛЕ activator.
    """
    out = []
    n = len(candles)
    for i in range(1, n - 1):
        ob = detect_ob(candles[i - 1], candles[i])
        if ob is None:
            continue
        br = detect_breaker(ob, candles[i + 1:])
        if br is None:
            continue
        armed_abs_idx = i + 1 + br.activated_at_idx
        if armed_abs_idx >= len(ts_list):
            continue
        zone_lo, zone_hi = br.initial_zone
        center = (zone_lo + zone_hi) / 2
        out.append({
            "ts": ts_list[armed_abs_idx] + TF_MS[tf_label],
            "element_type": "breaker_block", "tf": tf_label,
            "direction": br.direction, "action": "armed", "level": center,
            "zone_lo": zone_lo, "zone_hi": zone_hi,
            "magnitude_pct": 0.0, "role": "BLOCK", "source_idx": armed_abs_idx,
        })
        if br.consumed_at_idx is not None:
            consumed_abs_idx = i + 1 + br.consumed_at_idx
            if consumed_abs_idx < len(ts_list):
                out.append({
                    "ts": ts_list[consumed_abs_idx] + TF_MS[tf_label],
                    "element_type": "breaker_block", "tf": tf_label,
                    "direction": br.direction, "action": "fill_full", "level": center,
                    "zone_lo": zone_lo, "zone_hi": zone_hi,
                    "magnitude_pct": 0.0, "role": "BLOCK",
                    "source_idx": consumed_abs_idx,
                })
    return out


def events_mitigation_block(candles, ts_list, tf_label):
    """Mitigation block births + wick-fill retire (flipped role)."""
    out = []
    n = len(candles)
    for i in range(1, n - 4):
        ob = detect_ob(candles[i - 1], candles[i])
        if ob is None:
            continue
        mb = detect_mitigation_block(ob, candles[i + 1:])
        if mb is None:
            continue
        armed_abs_idx = i + 1 + mb.armed_at_idx
        if armed_abs_idx >= len(ts_list):
            continue
        zone_lo, zone_hi = mb.zone
        center = (zone_lo + zone_hi) / 2
        out.append({
            "ts": ts_list[armed_abs_idx] + TF_MS[tf_label],
            "element_type": "mitigation_block", "tf": tf_label,
            "direction": mb.direction, "action": "armed", "level": center,
            "zone_lo": zone_lo, "zone_hi": zone_hi,
            "magnitude_pct": 0.0, "role": "BLOCK", "source_idx": armed_abs_idx,
        })
        flipped_dir = "short" if mb.direction == "bearish" else "long"
        state = apply_wick_fill_mitigation(
            initial_zone=mb.zone, direction=flipped_dir,
            subsequent_bars=candles[armed_abs_idx + 1:], start_idx=armed_abs_idx + 1,
        )
        if state.is_consumed:
            out.append({
                "ts": ts_list[state.consumed_at_bar] + TF_MS[tf_label],
                "element_type": "mitigation_block", "tf": tf_label,
                "direction": mb.direction, "action": "fill_full", "level": center,
                "zone_lo": zone_lo, "zone_hi": zone_hi,
                "magnitude_pct": 0.0, "role": "BLOCK",
                "source_idx": state.consumed_at_bar,
            })
    return out


def events_rb(candles, ts_list, tf_label):
    """RB births + first-touch retire по entry-level 0.5 (canon 2026-06-15).

    Canon: mitigation срабатывает когда wick доходит до середины wick'a (entry-level),
    а не до внешнего края зоны. Это согласовано с торговой моделью RB
    (entry = mid wick из definition.md).
    """
    out = []
    for i, c in enumerate(candles):
        r = detect_rb(c)
        if r is None:
            continue
        born_ts = ts_list[i] + TF_MS[tf_label]
        zone_lo, zone_hi = r.zone
        center = (zone_lo + zone_hi) / 2   # = entry-level = consume trigger
        out.append({
            "ts": born_ts, "element_type": "rb", "tf": tf_label,
            "direction": r.direction,  # bottom/top
            "action": "born", "level": center,
            "zone_lo": zone_lo, "zone_hi": zone_hi,
            "magnitude_pct": 0.0, "role": "LIQ", "source_idx": i,
        })
        # First-touch retire по entry-level 0.5 (canon 2026-06-15)
        for j in range(i + 1, len(candles)):
            cj = candles[j]
            consumed = False
            if r.direction == "bottom":
                if cj.low <= center:
                    consumed = True
            else:
                if cj.high >= center:
                    consumed = True
            if consumed:
                out.append({
                    "ts": ts_list[j] + TF_MS[tf_label],
                    "element_type": "rb", "tf": tf_label,
                    "direction": r.direction, "action": "first_touch", "level": center,
                    "zone_lo": r.zone[0], "zone_hi": r.zone[1],
                    "magnitude_pct": 0.0, "role": "LIQ", "source_idx": j,
                })
                break
    return out


def events_i_fvg(candles, ts_list, tf_label, max_b_lookahead=300):
    """i-FVG births (canon v2 2026-06-15 — shrunk_A ∩ B.zone).

    max_b_lookahead=300 канонически: real BTC 12h кейс (user-A 2026-06-03)
    имел 113 свечей between A.c3 и B.c1. 100 (старый default) был слишком
    жёсток. detect_i_fvg сам шринкает A через between (canon v2).
    """
    out = []
    n = len(candles)
    fvgs = []
    for i in range(n - 2):
        fv = detect_fvg(candles[i], candles[i + 1], candles[i + 2])
        if fv is None:
            continue
        fvgs.append((i, i + 1, i + 2, fv))
    for ai, (a1, a2, a3, A) in enumerate(fvgs):
        for B_idx, (b1, b2, b3, B) in enumerate(fvgs[ai + 1:], start=ai + 1):
            if B.direction == A.direction:
                continue
            if b1 <= a3:
                continue
            if b1 - a3 > max_b_lookahead:
                break
            between = tuple(candles[a3 + 1: b1])
            ifvg = detect_i_fvg(
                candles[a1], candles[a2], candles[a3],
                between,
                candles[b1], candles[b2], candles[b3],
            )
            if ifvg is None:
                continue
            zone_lo, zone_hi = ifvg.overlap
            center = (zone_lo + zone_hi) / 2
            out.append({
                "ts": ts_list[b3] + TF_MS[tf_label],
                "element_type": "i_fvg", "tf": tf_label,
                "direction": ifvg.direction, "action": "born", "level": center,
                "zone_lo": zone_lo, "zone_hi": zone_hi,
                "magnitude_pct": 0.0, "role": "INE", "source_idx": b3,
            })
            state = apply_wick_fill_mitigation(
                initial_zone=ifvg.overlap, direction=ifvg.direction,
                subsequent_bars=candles[b3 + 1:], start_idx=b3 + 1,
            )
            if state.is_consumed:
                out.append({
                    "ts": ts_list[state.consumed_at_bar] + TF_MS[tf_label],
                    "element_type": "i_fvg", "tf": tf_label,
                    "direction": ifvg.direction, "action": "fill_full", "level": center,
                    "zone_lo": zone_lo, "zone_hi": zone_hi,
                    "magnitude_pct": 0.0, "role": "INE",
                    "source_idx": state.consumed_at_bar,
                })
    return out


# Combined scanner per TF — 13 элементов single-TF (ob_vc отдельно как cross-TF)
def scan_tf(tf_label, candles, ts_list):
    """Run all 13 single-TF element detectors on one TF.

    ob_vc — cross-TF элемент, обрабатывается отдельно в events_ob_vc_cross_tf.
    """
    events = []
    events.extend(events_fractal(candles, ts_list, tf_label))
    events.extend(events_ob(candles, ts_list, tf_label))
    events.extend(events_fvg(candles, ts_list, tf_label))
    events.extend(events_marubozu(candles, ts_list, tf_label))
    events.extend(events_rdrb(candles, ts_list, tf_label))
    events.extend(events_i_rdrb(candles, ts_list, tf_label))
    events.extend(events_block_orders(candles, ts_list, tf_label))
    events.extend(events_ob_liq(candles, ts_list, tf_label))
    events.extend(events_breaker_block(candles, ts_list, tf_label))
    events.extend(events_mitigation_block(candles, ts_list, tf_label))
    events.extend(events_i_fvg(candles, ts_list, tf_label))
    events.extend(events_rb(candles, ts_list, tf_label))
    events.extend(events_choch_bos(candles, ts_list, tf_label))
    return events


# ─── ob_vc cross-TF detector ────────────────────────────────
OB_VC_HTF_TO_LTF = {
    "1h": ("15m", "30m"),
    "2h": ("15m", "30m"),
    "4h": ("1h", "2h"),
    "6h": ("1h", "2h"),
    "12h": ("4h", "6h"),
    "1D": ("4h", "6h"),
}


def events_ob_vc_cross_tf(tf_bars_all):
    """Cross-TF ob_vc detection (canon #1-#8 без #9 1m-check).

    Для каждой HTF OB-пары: ищем LTF FVG того же направления внутри drop/rally area.
    Если найден → ob_vc emit с born_ts = max(cur_close, fvg_c3_close).
    Wick-fill tracking → fill_full retire.
    """
    out = []
    # Pre-compute candles + ts per TF
    candles_by_tf = {tf: to_candles(bars) for tf, bars in tf_bars_all.items()}
    ts_by_tf = {tf: [b[0] for b in bars] for tf, bars in tf_bars_all.items()}

    # Pre-compute FVGs per LTF
    fvgs_by_tf = {}
    for ltf in set(sum([list(v) for v in OB_VC_HTF_TO_LTF.values()], [])):
        if ltf not in candles_by_tf:
            continue
        cans = candles_by_tf[ltf]
        ts_list = ts_by_tf[ltf]
        ltf_fvgs_long = []
        ltf_fvgs_short = []
        for i in range(len(cans) - 2):
            fv = detect_fvg(cans[i], cans[i + 1], cans[i + 2])
            if fv is None:
                continue
            entry = {
                "c1_open_ms": ts_list[i],
                "c3_open_ms": ts_list[i + 2],
                "c3_close_ms": ts_list[i + 2] + TF_MS[ltf],
                "zone": fv.zone,
            }
            if fv.direction == "long":
                ltf_fvgs_long.append(entry)
            else:
                ltf_fvgs_short.append(entry)
        fvgs_by_tf[(ltf, "long")] = sorted(ltf_fvgs_long, key=lambda x: x["c1_open_ms"])
        fvgs_by_tf[(ltf, "short")] = sorted(ltf_fvgs_short, key=lambda x: x["c1_open_ms"])

    for htf, ltf_list in OB_VC_HTF_TO_LTF.items():
        if htf not in candles_by_tf:
            continue
        htf_cans = candles_by_tf[htf]
        htf_ts = ts_by_tf[htf]
        htf_ms = TF_MS[htf]
        for i in range(1, len(htf_cans)):
            ob = detect_ob(htf_cans[i - 1], htf_cans[i])
            if ob is None:
                continue
            cur_open_ms = htf_ts[i]
            cur_close_ms = cur_open_ms + htf_ms
            prev_open_ms = cur_open_ms - htf_ms

            # Drop area (LONG) / rally area (SHORT)
            if ob.direction == "long":
                drop_lo = min(ob.prev.low, ob.cur.low)
                drop_hi = ob.prev.open
                drop_area = (drop_lo, drop_hi)
            else:
                rally_lo = ob.prev.open
                rally_hi = max(ob.prev.high, ob.cur.high)
                drop_area = (rally_lo, rally_hi)

            # Find any LTF FVG same direction within drop area + OB pair window
            found = False
            earliest_fvg_close = None
            for ltf in ltf_list:
                fvgs = fvgs_by_tf.get((ltf, ob.direction), [])
                for fvg in fvgs:
                    # Window: c1.open ≥ prev.open, c3.close ≤ cur.close + reasonable lookahead
                    if fvg["c1_open_ms"] < prev_open_ms:
                        continue
                    if fvg["c1_open_ms"] > cur_close_ms + htf_ms * 2:
                        break  # sorted ascending
                    # Overlap with drop area
                    if max(fvg["zone"][0], drop_area[0]) > min(fvg["zone"][1], drop_area[1]):
                        continue
                    found = True
                    if earliest_fvg_close is None or fvg["c3_close_ms"] < earliest_fvg_close:
                        earliest_fvg_close = fvg["c3_close_ms"]
                    break
                if found:
                    break

            if not found:
                continue

            born_ts = max(cur_close_ms, earliest_fvg_close)
            zone_lo, zone_hi = ob.zone
            center = (zone_lo + zone_hi) / 2
            out.append({
                "ts": born_ts, "element_type": "ob_vc", "tf": htf,
                "direction": ob.direction, "action": "born", "level": center,
                "zone_lo": zone_lo, "zone_hi": zone_hi,
                "magnitude_pct": 0.0, "role": "BLOCK", "source_idx": i,
            })
            state = apply_wick_fill_mitigation(
                initial_zone=ob.zone, direction=ob.direction,
                subsequent_bars=htf_cans[i + 1:], start_idx=i + 1,
            )
            if state.is_consumed:
                out.append({
                    "ts": htf_ts[state.consumed_at_bar] + htf_ms,
                    "element_type": "ob_vc", "tf": htf,
                    "direction": ob.direction, "action": "fill_full", "level": center,
                    "zone_lo": zone_lo, "zone_hi": zone_hi,
                    "magnitude_pct": 0.0, "role": "BLOCK",
                    "source_idx": state.consumed_at_bar,
                })
    return out


def main(start_date: str, end_date: str):
    bars_1m = load_1m_csv()
    start_ts = int(datetime.fromisoformat(start_date).replace(tzinfo=UTC).timestamp() * 1000)
    end_ts = int(datetime.fromisoformat(end_date).replace(tzinfo=UTC).timestamp() * 1000)

    # Aggregate ONCE per TF
    print(f"Aggregating 8 TFs...", file=sys.stderr, flush=True)
    tf_bars = {}
    for tf, ms in TF_MS.items():
        agg = aggregate_to_tf(bars_1m, ms)
        agg = filter_range(agg, start_ts, end_ts)
        tf_bars[tf] = agg
        print(f"  {tf}: {len(agg):,} bars", file=sys.stderr, flush=True)

    # Scan per TF
    all_events = []
    for tf in TF_MS.keys():
        t_start = time.time()
        candles = to_candles(tf_bars[tf])
        ts_list = [b[0] for b in tf_bars[tf]]
        events = scan_tf(tf, candles, ts_list)
        all_events.extend(events)
        print(f"  [{tf}] {len(events):,} events in {time.time() - t_start:.1f}s",
              file=sys.stderr, flush=True)

    # Cross-TF ob_vc scan
    t_start = time.time()
    print(f"  [ob_vc cross-TF] scanning...", file=sys.stderr, flush=True)
    ob_vc_events = events_ob_vc_cross_tf(tf_bars)
    all_events.extend(ob_vc_events)
    print(f"  [ob_vc cross-TF] {len(ob_vc_events):,} events in {time.time() - t_start:.1f}s",
          file=sys.stderr, flush=True)

    # Sort chronologically
    all_events.sort(key=lambda e: e["ts"])

    # Convert to DataFrame
    df = pd.DataFrame(all_events)
    print(f"\nTotal events: {len(df):,}", file=sys.stderr, flush=True)
    print(f"By element_type:", file=sys.stderr, flush=True)
    print(df["element_type"].value_counts().to_string(), file=sys.stderr, flush=True)
    print(f"\nBy tf:", file=sys.stderr, flush=True)
    print(df["tf"].value_counts().to_string(), file=sys.stderr, flush=True)
    print(f"\nBy action:", file=sys.stderr, flush=True)
    print(df["action"].value_counts().to_string(), file=sys.stderr, flush=True)

    # Save
    out_path = OUT_DIR / f"events_{start_date}_{end_date}.parquet"
    df.to_parquet(out_path, index=False)
    print(f"\nSaved: {out_path} ({out_path.stat().st_size / 1024 / 1024:.1f} MB)",
          file=sys.stderr, flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2020-01-01")
    ap.add_argument("--end", default="2026-06-15")
    args = ap.parse_args()
    main(args.start, args.end)
