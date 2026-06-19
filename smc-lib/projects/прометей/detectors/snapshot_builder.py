"""Прометей snapshot builder.

Для каждого cutoff `t0` (1 snapshot/day @ 15:00 МСК или 4h cadence 6/day)
выдаёт JSON со всеми active SMC instances + state.

Canon (rules.md + zone_of_interest.md):
  - Rule 14: TF anchor = 0 UTC (Binance/TV), W = пн 03:00 МСК
  - Rule 15: cutoff = t0 - tf_ms для HTF; live indicators per TF
  - Rule 2: apply_mitigation() для всех zone elements
  - Rule 1: Mitigation Block требует закрепления (4 свечи)

Anti-lookahead guardrails (per known-pitfalls):
  - Cutoff = t0 - tf_ms (НЕ t0) — HTF lookup на последний ЗАКРЫТЫЙ HTF bar
  - 1m CSV → HTF через compose with origin=0 UTC (для non-W) / Monday для W / epoch для 2D/3D
  - Year coverage + gap detection ДО любой агрегации
  - Confirm_time = open_time + tf_ms (не open_time)

Output format (snapshot JSON):
  {
    "t0": <unix_seconds>,
    "t0_msk": "YYYY-MM-DD HH:MM",
    "symbol": "BTCUSDT",
    "active_zones": [
      {
        "element": "ob",
        "tf": "1h",
        "direction": "long" | "short",
        "zone": [lo, hi],
        "born_ts": <unix_seconds>,
        "age_bars": int,
        "mit_count": int,
        "is_consumed": bool,
        "active_zone_after_wickfill": [lo, hi],
      }, ...
    ],
    "fractals": {
      "1h": {"unswept_FH": [...], "unswept_FL": [...]},
      ...
    },
    "structural": {
      "1h": {"choch_state": "+1"|"-1"|"0", "last_event": "BOS"|"CHoCH"|null, ...},
      ...
    },
    "mb_active": [...],          # Mitigation Block instances (Rule 1 confirmed)
    "breaker_active": [...],     # Breaker Block instances
    "inducement_active": [...],  # ARMED/TRIGGERED inducements
  }
"""
from __future__ import annotations

import csv
import json
import pathlib
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional

import pandas as pd

# Add smc-lib to path
SMC_LIB = pathlib.Path.home() / "smc-lib"
sys.path.insert(0, str(SMC_LIB))

from candle import Candle
from elements.ob.code import detect_ob, is_full_break
from elements.fvg.code import detect_fvg
from elements.block_orders.code import detect_block_orders
from elements.rdrb.code import detect_rdrb
from elements.i_rdrb.code import detect_i_rdrb
from elements.i_fvg.code import detect_i_fvg
from elements.marubozu.code import detect_marubozu
from elements.ob_liq.code import detect_ob_liq
from elements.breaker_block.code import detect_breaker
from elements.mitigation_block.code import detect_mitigation_block
from elements.choch_bos.code import scan_market_structure
from elements.fractal.code import detect_fractal
from patterns.inducement.code import (
    detect_bullish_inducement,
    detect_bearish_inducement,
)
from elements._mitigation import (
    apply_wick_fill_mitigation,
    apply_first_touch_mitigation,
    apply_sweep_mitigation,
)


# ─── Configuration ────────────────────────────────────────
CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
SNAPSHOTS_DIR = SMC_LIB / "projects/прометей/detectors/snapshots"
SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)

MS = 60_000
MSK = timezone(timedelta(hours=3))
UTC = timezone.utc

# TF panel (Прометей spec §2 Group A)
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

# Rule 14: anchor = 0 UTC для всех не-W TF
ANCHOR_MS = 0


# ─── 1m data loading + canonical TF aggregation ────────────

def load_1m_csv(csv_path: pathlib.Path = CSV_PATH) -> list[tuple[int, float, float, float, float]]:
    """Загружает 1m CSV → list[(ts_ms, o, h, l, c)]."""
    print(f"Loading {csv_path}...", file=sys.stderr)
    rows = []
    with csv_path.open() as f:
        rd = csv.reader(f)
        next(rd)
        for r in rd:
            t = datetime.fromisoformat(r[0]).replace(tzinfo=UTC)
            ts_ms = int(t.timestamp() * 1000)
            rows.append((ts_ms, float(r[1]), float(r[2]), float(r[3]), float(r[4])))
    print(f"  loaded {len(rows):,} 1m bars", file=sys.stderr)
    return rows


def aggregate_to_tf(
    bars_1m: list[tuple[int, float, float, float, float]],
    tf_ms: int,
    anchor_ms: int = ANCHOR_MS,
) -> list[tuple[int, float, float, float, float]]:
    """Aggregate 1m → HTF using anchor.

    Per Rule 14: anchor = 0 UTC для всех не-W TF.
    Bar boundary: ts - ((ts - anchor) % tf_ms).
    """
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


def sanity_check_data(bars_1m: list[tuple[int, float, float, float, float]]) -> None:
    """Year coverage check + gap detection (per pitfall «Год отсутствует»).

    Raises AssertionError если есть критичные gaps или missing years.
    """
    if not bars_1m:
        raise ValueError("No 1m bars loaded")

    ts_arr = [b[0] for b in bars_1m]
    years = set()
    for ts in ts_arr:
        years.add(datetime.fromtimestamp(ts / 1000, tz=UTC).year)
    first_year = min(years)
    last_year = max(years)
    expected = set(range(first_year, last_year + 1))
    missing = expected - years
    if missing:
        raise AssertionError(
            f"Missing years in 1m data: {sorted(missing)} "
            f"(expected {first_year}-{last_year})"
        )

    # Gap detection (1m bars must be <= 2 hours apart)
    max_gap_ms = 0
    for i in range(1, len(ts_arr)):
        gap = ts_arr[i] - ts_arr[i - 1]
        if gap > max_gap_ms:
            max_gap_ms = gap
    if max_gap_ms > 2 * 3600 * 1000:
        gap_hours = max_gap_ms / 3600 / 1000
        print(
            f"  ⚠ Largest 1m gap: {gap_hours:.1f}h "
            f"(may indicate missing data)",
            file=sys.stderr,
        )


# ─── Cutoff helpers (anti-lookahead) ──────────────────────

def cutoff_idx_for_tf(
    tf_bars: list[tuple[int, float, float, float, float]],
    t0_ms: int,
    tf_ms: int,
) -> int:
    """Index последнего ЗАКРЫТОГО HTF bara at cutoff t0.

    Closure: bar closed if (bar.open_time + tf_ms) <= t0.
    Per Rule 15: cutoff = t0 - tf_ms.
    """
    cutoff = t0_ms - tf_ms
    # Find largest idx where bar.open_time <= cutoff
    last_closed = -1
    for i, b in enumerate(tf_bars):
        if b[0] <= cutoff:
            last_closed = i
        else:
            break
    return last_closed


def bars_up_to_cutoff(
    tf_bars: list[tuple[int, float, float, float, float]],
    t0_ms: int,
    tf_ms: int,
) -> list[Candle]:
    """Возвращает Candle list только из ЗАКРЫТЫХ bars на момент t0."""
    last_idx = cutoff_idx_for_tf(tf_bars, t0_ms, tf_ms)
    if last_idx < 0:
        return []
    return [
        Candle(open=b[1], high=b[2], low=b[3], close=b[4])
        for b in tf_bars[: last_idx + 1]
    ]


def bars_with_ts_up_to_cutoff(
    tf_bars: list[tuple[int, float, float, float, float]],
    t0_ms: int,
    tf_ms: int,
    max_bars_back: int | None = None,
) -> tuple[list[Candle], list[int]]:
    """Возвращает (Candles, open_ts_ms) только для закрытых bars.

    max_bars_back: если задано, ограничивает результат последними K барами
    (для скорости детекции на низких TFs). Структурно очень старые zones
    обычно уже отработаны (consumed/invalidated), поэтому cap безопасен.
    """
    last_idx = cutoff_idx_for_tf(tf_bars, t0_ms, tf_ms)
    if last_idx < 0:
        return [], []
    start = 0
    if max_bars_back is not None and last_idx + 1 > max_bars_back:
        start = last_idx + 1 - max_bars_back
    candles = [
        Candle(open=b[1], high=b[2], low=b[3], close=b[4])
        for b in tf_bars[start: last_idx + 1]
    ]
    ts_list = [b[0] for b in tf_bars[start: last_idx + 1]]
    return candles, ts_list


# Per-TF detection lookback cap (Phase 1 baseline).
# Structural rationale: zones живут редко дольше ~3000 bars без consumption.
# HTFs (12h, 1D) keep full history — там zones rare и structurally important.
MAX_BARS_BACK = {
    "15m": 3000,   # ≈ 31 day
    "30m": 3000,   # ≈ 62 days
    "1h": 3000,    # ≈ 4 months
    "2h": 3000,    # ≈ 8 months
    "4h": 5000,    # ≈ 27 months
    "6h": 5000,    # ≈ 41 months
    "12h": None,   # full history
    "1D": None,    # full history
}


# ─── Per-TF detection ────────────────────────────────────

def detect_active_obs_on_tf(
    candles: list[Candle],
    ts_list: list[int],
    tf_label: str,
) -> list[dict]:
    """Detect all OB pairs, apply wick-fill mitigation, return active instances.

    «Active» = not is_consumed AND not is_invalidated_by_close.
    """
    out = []
    n = len(candles)
    for i in range(1, n - 1):
        ob = detect_ob(candles[i - 1], candles[i])
        if ob is None:
            continue
        # Subsequent bars (closed) for mitigation tracking
        subsequent = candles[i + 1:]
        state = apply_wick_fill_mitigation(
            initial_zone=ob.zone,
            direction=ob.direction,
            subsequent_bars=subsequent,
            start_idx=i + 1,
        )
        if state.is_consumed or state.is_invalidated_by_close:
            continue
        out.append({
            "element": "ob",
            "tf": tf_label,
            "direction": ob.direction,
            "zone": list(ob.zone),
            "active_zone": list(state.active_zone),
            "born_ts": ts_list[i],
            "age_bars": n - 1 - i,
            "mit_count": state.n_real_mitigations,
            "is_full_break": is_full_break(ob),
        })
    return out


def detect_active_fvgs_on_tf(
    candles: list[Candle],
    ts_list: list[int],
    tf_label: str,
) -> list[dict]:
    out = []
    n = len(candles)
    for i in range(n - 2):
        fvg = detect_fvg(candles[i], candles[i + 1], candles[i + 2])
        if fvg is None:
            continue
        subsequent = candles[i + 3:]
        state = apply_wick_fill_mitigation(
            initial_zone=fvg.zone,
            direction=fvg.direction,
            subsequent_bars=subsequent,
            start_idx=i + 3,
        )
        if state.is_consumed or state.is_invalidated_by_close:
            continue
        out.append({
            "element": "fvg",
            "tf": tf_label,
            "direction": fvg.direction,
            "zone": list(fvg.zone),
            "active_zone": list(state.active_zone),
            "born_ts": ts_list[i + 2],
            "age_bars": n - 1 - (i + 2),
            "mit_count": state.n_real_mitigations,
        })
    return out


def detect_active_marubozu_on_tf(
    candles: list[Candle],
    ts_list: list[int],
    tf_label: str,
) -> list[dict]:
    """Marubozu: 1 свеча, sweep open level (Rule 2 model 3).

    Per memory feedback-marubozu-canon-pine-wicked: open на экстремуме.
    Active = open level не swept (касанием wick'a другой стороны).
    """
    out = []
    n = len(candles)
    for i in range(n):
        m = detect_marubozu(candles[i])
        if m is None:
            continue
        # Sweep tracking: bull marubozu (open == low) consumed when low ≤ open;
        # bear marubozu (open == high) consumed when high ≥ open.
        open_level = m.candle.open
        subsequent = candles[i + 1:]
        if m.direction == "long":  # bull marubozu, open == low
            sweep_dir = "low"  # FL-like: swept when low < open
        else:
            sweep_dir = "high"
        sweep_result = apply_sweep_mitigation(
            level=open_level,
            direction=sweep_dir,
            subsequent_bars=subsequent,
            start_idx=i + 1,
        )
        if sweep_result["swept"]:
            continue  # open level swept — marubozu отработан
        out.append({
            "element": "marubozu",
            "tf": tf_label,
            "direction": m.direction,
            "zone": list(m.zone),
            "open_level": open_level,
            "born_ts": ts_list[i],
            "age_bars": n - 1 - i,
        })
    return out


def detect_active_block_orders_on_tf(
    candles: list[Candle],
    ts_list: list[int],
    tf_label: str,
) -> list[dict]:
    """Block orders: composite N+M. Scan starting positions, slice до max разумной длины."""
    out = []
    n = len(candles)
    MAX_BLOCK_LEN = 20  # preceding + initial + counter, разумный potolok
    for i in range(n - 2):
        # Try slices starting at i with growing length
        for window in range(3, min(MAX_BLOCK_LEN + 1, n - i)):
            slice_ = candles[i: i + window]
            bo = detect_block_orders(slice_)
            if bo is None:
                continue
            # Found block at i. Skip overlapping starts in further iterations.
            block_end_idx = i + window - 1  # последний bar block (counter cross)
            subsequent = candles[block_end_idx + 1:]
            state = apply_wick_fill_mitigation(
                initial_zone=bo.zone,
                direction=bo.direction,
                subsequent_bars=subsequent,
                start_idx=block_end_idx + 1,
            )
            if state.is_consumed or state.is_invalidated_by_close:
                break  # next i
            out.append({
                "element": "block_orders",
                "tf": tf_label,
                "direction": bo.direction,
                "zone": list(bo.zone),
                "active_zone": list(state.active_zone),
                "n_initial": bo.n_initial,
                "n_counter": bo.n_counter,
                "born_ts": ts_list[block_end_idx],
                "age_bars": n - 1 - block_end_idx,
                "mit_count": state.n_real_mitigations,
            })
            break  # found block at this start, move to next i
    return out


def detect_active_rdrb_on_tf(
    candles: list[Candle],
    ts_list: list[int],
    tf_label: str,
) -> list[dict]:
    """RDRB: 3-candle, ZoI = POI (block ∪ liq)."""
    out = []
    n = len(candles)
    for i in range(n - 2):
        r = detect_rdrb(candles[i], candles[i + 1], candles[i + 2])
        if r is None:
            continue
        subsequent = candles[i + 3:]
        state = apply_wick_fill_mitigation(
            initial_zone=r.poi,
            direction=r.direction,
            subsequent_bars=subsequent,
            start_idx=i + 3,
        )
        if state.is_consumed or state.is_invalidated_by_close:
            continue
        out.append({
            "element": "rdrb",
            "tf": tf_label,
            "direction": r.direction,
            "variant": r.variant,
            "zone": list(r.poi),       # POI (= ZoI)
            "block_zone": list(r.block),
            "active_zone": list(state.active_zone),
            "born_ts": ts_list[i + 2],
            "age_bars": n - 1 - (i + 2),
            "mit_count": state.n_real_mitigations,
        })
    return out


def detect_active_i_rdrb_on_tf(
    candles: list[Candle],
    ts_list: list[int],
    tf_label: str,
) -> list[dict]:
    """i-RDRB: 4-candle composite, ZoI = POI (block ∪ inverted liq)."""
    out = []
    n = len(candles)
    for i in range(n - 3):
        ir = detect_i_rdrb(candles[i], candles[i + 1], candles[i + 2], candles[i + 3])
        if ir is None:
            continue
        subsequent = candles[i + 4:]
        state = apply_wick_fill_mitigation(
            initial_zone=ir.poi,
            direction=ir.direction,
            subsequent_bars=subsequent,
            start_idx=i + 4,
        )
        if state.is_consumed or state.is_invalidated_by_close:
            continue
        out.append({
            "element": "i_rdrb",
            "tf": tf_label,
            "direction": ir.direction,
            "variant": ir.variant,
            "zone": list(ir.poi),
            "block_zone": list(ir.block),
            "active_zone": list(state.active_zone),
            "born_ts": ts_list[i + 3],
            "age_bars": n - 1 - (i + 3),
            "mit_count": state.n_real_mitigations,
        })
    return out


def detect_active_ob_liq_on_tf(
    candles: list[Candle],
    ts_list: list[int],
    tf_label: str,
) -> list[dict]:
    """ob_liq: OB + 2-условный liq marker (canon 2026-05-27 без Williams).

    Main zone (canon-OB) — wick-fill. liq_zone marker — first-touch.
    Active if liq_zone NOT first-touched (canon priority).
    """
    out = []
    n = len(candles)
    for i in range(1, n):
        ol = detect_ob_liq(candles[i - 1], candles[i])
        if ol is None:
            continue
        subsequent = candles[i + 1:]
        # liq_zone first-touch tracking
        liq_state = apply_first_touch_mitigation(
            initial_zone=ol.liq_zone,
            direction=ol.direction,
            subsequent_bars=subsequent,
            start_idx=i + 1,
        )
        # Main zone wick-fill tracking
        main_state = apply_wick_fill_mitigation(
            initial_zone=ol.zone,
            direction=ol.direction,
            subsequent_bars=subsequent,
            start_idx=i + 1,
        )
        if liq_state.is_consumed or main_state.is_consumed or main_state.is_invalidated_by_close:
            continue
        out.append({
            "element": "ob_liq",
            "tf": tf_label,
            "direction": ol.direction,
            "zone": list(ol.zone),
            "liq_zone": list(ol.liq_zone),
            "active_zone": list(main_state.active_zone),
            "born_ts": ts_list[i],
            "age_bars": n - 1 - i,
            "mit_count": main_state.n_real_mitigations,
        })
    return out


def detect_active_i_fvg_on_tf(
    candles: list[Candle],
    ts_list: list[int],
    tf_label: str,
    max_b_lookahead_bars: int = 300,
) -> list[dict]:
    """i-FVG: composite двух FVG противоположного направления (canon v2 2026-06-15).

    canon v2: detect_i_fvg сам шринкает A.zone через between bars wick-fill'ом.
    ZoI = overlap(shrunk_A, B.zone). Если A consumed между — i-FVG не формируется.

    max_b_lookahead_bars=300 канонически (real BTC 12h кейс имел 113 between).
    Старый default 100 отсекал валидные i-FVG.
    """
    out = []
    n = len(candles)

    # Step 1: collect all FVGs with their (c1, c2, c3) indices
    fvgs = []
    for i in range(n - 2):
        fvg = detect_fvg(candles[i], candles[i + 1], candles[i + 2])
        if fvg is None:
            continue
        fvgs.append((i, i + 1, i + 2, fvg))

    # Step 2: for each ordered pair (A before B), check i_fvg
    for ai, (a1, a2, a3, A) in enumerate(fvgs):
        for B_idx, (b1, b2, b3, B) in enumerate(fvgs[ai + 1:], start=ai + 1):
            if B.direction == A.direction:
                continue
            if b1 <= a3:
                # B must start AFTER A.c3 closes
                continue
            if b1 - a3 > max_b_lookahead_bars:
                # Too far ahead — skip remaining (fvgs sorted by b1 ascending)
                break
            between = tuple(candles[a3 + 1: b1])
            ifvg = detect_i_fvg(
                candles[a1], candles[a2], candles[a3],
                between,
                candles[b1], candles[b2], candles[b3],
            )
            if ifvg is None:
                continue
            # Mitigation on overlap (wick-fill, direction = ifvg.direction)
            subsequent = candles[b3 + 1:]
            state = apply_wick_fill_mitigation(
                initial_zone=ifvg.overlap,
                direction=ifvg.direction,
                subsequent_bars=subsequent,
                start_idx=b3 + 1,
            )
            if state.is_consumed or state.is_invalidated_by_close:
                continue
            out.append({
                "element": "i_fvg",
                "tf": tf_label,
                "direction": ifvg.direction,
                "zone": list(ifvg.overlap),      # ZoI = overlap
                "a_zone": list(ifvg.a.zone),
                "b_zone": list(ifvg.b.zone),
                "active_zone": list(state.active_zone),
                "born_ts": ts_list[b3],
                "age_bars": n - 1 - b3,
                "mit_count": state.n_real_mitigations,
            })
    return out


def detect_active_breaker_blocks_on_tf(
    candles: list[Candle],
    ts_list: list[int],
    tf_label: str,
) -> list[dict]:
    """Breaker blocks per TF (canon v4 2026-06-15).

    v4: ARM при close-cross в окне bar 3-6 (post_bars[0..3]). detect_breaker
    сам трекает wick-fill mit от bar ПОСЛЕ activator (built-in).
    Активен если br.consumed_at_idx is None.
    """
    out = []
    n = len(candles)
    for i in range(1, n - 1):
        ob = detect_ob(candles[i - 1], candles[i])
        if ob is None:
            continue
        post = candles[i + 1:]
        br = detect_breaker(ob, post)
        if br is None:
            continue
        # v4 canon: detect_breaker уже трекает consume. Активен если consumed_at_idx is None.
        if br.consumed_at_idx is not None:
            continue
        # activated_at_idx — local в post; absolute = i + 1 + local
        armed_abs_idx = i + 1 + br.activated_at_idx
        out.append({
            "element": "breaker_block",
            "tf": tf_label,
            "direction": br.direction,        # 'bullish' / 'bearish'
            "zone": list(br.initial_zone),    # zone на момент активации
            "active_zone": list(br.current_zone),  # zone после shrink (canon v4)
            "ob_zone": list(br.ob.zone),
            "activated_at_idx": armed_abs_idx,
            "born_ts": ts_list[armed_abs_idx] if armed_abs_idx < len(ts_list) else ts_list[i],
            "armed_age_bars": n - 1 - armed_abs_idx,
            "shrink_count": br.shrink_count,
        })
    return out


def detect_active_mitigation_blocks_on_tf(
    candles: list[Candle],
    ts_list: list[int],
    tf_label: str,
) -> list[dict]:
    """Mitigation blocks per TF: armed (Rule 1 closure done) but not yet consumed."""
    out = []
    n = len(candles)
    for i in range(1, n - 4):
        ob = detect_ob(candles[i - 1], candles[i])
        if ob is None:
            continue
        post = candles[i + 1:]
        mb = detect_mitigation_block(ob, post)
        if mb is None:
            continue
        # MB armed at mb.armed_at_idx (relative to post). Flipped role direction:
        # bearish MB = LONG OB пробит вниз → flipped = SHORT setup
        # bullish MB = SHORT OB пробит вверх → flipped = LONG setup
        flipped_dir = "short" if mb.direction == "bearish" else "long"
        after_armed = post[mb.armed_at_idx + 1:]
        state = apply_wick_fill_mitigation(
            initial_zone=mb.zone,
            direction=flipped_dir,
            subsequent_bars=after_armed,
            start_idx=i + 1 + mb.armed_at_idx + 1,
        )
        if state.is_consumed:
            continue
        armed_idx_abs = i + 1 + mb.armed_at_idx
        out.append({
            "element": "mitigation_block",
            "tf": tf_label,
            "direction": mb.direction,
            "flipped_direction": flipped_dir,
            "zone": list(mb.zone),
            "active_zone": list(state.active_zone),
            "broken_level": mb.broken_level,
            "born_ts": ts_list[armed_idx_abs] if armed_idx_abs < len(ts_list) else ts_list[i],
            "armed_age_bars": n - 1 - armed_idx_abs,
            "mit_count": state.n_real_mitigations,
        })
    return out


def detect_active_inducements_on_tf(
    candles: list[Candle],
    ts_list: list[int],
    tf_label: str,
    max_lookback_bars: int = 200,
) -> list[dict]:
    """Inducement instances per TF.

    Phase 1 baseline: вызываем detect_bullish/bearish_inducement один раз на хвосте
    последних max_lookback_bars свечей. Возвращаем (если есть) текущий armed/triggered
    instance.

    NB: detect_*_inducement сейчас возвращает Optional[Inducement] — first match scenario.
    Для full enumeration по истории нужен отдельный scan_inducements (TODO Phase 2).
    """
    out = []
    if len(candles) < 30:
        return out
    tail = candles[-max_lookback_bars:] if len(candles) > max_lookback_bars else candles
    offset = len(candles) - len(tail)
    for fn, direction in (
        (detect_bullish_inducement, "bullish"),
        (detect_bearish_inducement, "bearish"),
    ):
        try:
            ind = fn(tail)
        except Exception:
            ind = None
        if ind is None:
            continue
        out.append({
            "element": "inducement",
            "tf": tf_label,
            "direction": direction,
            "state": ind.state,
            "ob_zone": list(ind.ob.zone),
            "fvg_zone": list(ind.fvg.zone),
            "composite_zone": list(ind.composite_zone),
            "choch_level": ind.choch_level,
            "idm_level": ind.idm_level,
            "born_ts": ts_list[offset + ind.i_bos] if (offset + ind.i_bos) < len(ts_list) else ts_list[-1],
            "i_sweep": ind.i_sweep,
            "i_zone_touch": ind.i_zone_touch,
        })
    return out


def detect_fractals_on_tf(
    candles: list[Candle],
    ts_list: list[int],
    tf_label: str,
    n: int = 2,
    max_age_bars: int = 500,
) -> list[dict]:
    """Williams BW fractals per TF + sweep status (canon: TF-relative wick).

    Per memory feedback-fractal-liquidity-strength-and-sweep:
      сила = TF × age × cluster; sweep TF-relative.

    Phase 1 baseline: return ALL fractals within max_age (active OR swept).
    Swept fractals — это структурный signal (liquidity sweep event), не выбрасываем.
    """
    out = []
    total = len(candles)
    # Iterate over all possible centers (need n bars on each side)
    for center_idx in range(n, total - n):
        window = candles[center_idx - n: center_idx + n + 1]
        fr = detect_fractal(window, n=n)
        if fr is None:
            continue

        age = total - 1 - center_idx
        if age > max_age_bars:
            continue

        subsequent = candles[center_idx + n + 1:]  # bars AFTER fractal confirmed
        sweep = apply_sweep_mitigation(
            level=fr.level,
            direction=fr.direction,
            subsequent_bars=subsequent,
            start_idx=center_idx + n + 1,
        )
        out.append({
            "tf": tf_label,
            "direction": fr.direction,
            "level": fr.level,
            "n": n,
            "born_ts": ts_list[center_idx],
            "born_idx": center_idx,
            "age_bars": age,
            "swept": sweep["swept"],
            "swept_at_bar": sweep["swept_at_bar"],
            "magnitude_pct": sweep["magnitude_pct"],
        })
    return out


def detect_choch_bos_on_tf(
    candles: list[Candle],
    ts_list: list[int],
    tf_label: str,
) -> dict:
    """Return structural state per TF (choch_bos state machine `os`)."""
    events = scan_market_structure(candles, length=5)
    if not events:
        return {
            "tf": tf_label,
            "choch_state": 0,
            "last_event_type": None,
            "last_event_side": None,
            "last_event_idx": None,
            "bars_since_last": None,
            "n_choch_24bars": 0,
            "n_bos_24bars": 0,
        }
    last = events[-1]
    state_map = {"bullish": 1, "bearish": -1}
    n_total = len(candles)
    bars_since = n_total - 1 - last.break_idx
    # Counts in last 24 bars
    threshold_idx = max(0, n_total - 24)
    n_choch = sum(1 for e in events if e.break_idx >= threshold_idx and e.type == "CHoCH")
    n_bos = sum(1 for e in events if e.break_idx >= threshold_idx and e.type == "BOS")
    return {
        "tf": tf_label,
        "choch_state": state_map.get(last.side, 0),
        "last_event_type": last.type,
        "last_event_side": last.side,
        "last_event_idx": last.break_idx,
        "bars_since_last": bars_since,
        "n_choch_24bars": n_choch,
        "n_bos_24bars": n_bos,
    }


# ─── Top-level builder ────────────────────────────────────

def build_snapshot(
    bars_1m: list[tuple[int, float, float, float, float]],
    t0_ms: int,
    symbol: str = "BTCUSDT",
    tf_panel: tuple[str, ...] = ("15m", "1h", "4h", "12h", "1D"),
    bars_1m_ts: list[int] | None = None,
) -> dict:
    """Build snapshot dict for cutoff t0."""
    t0_iso_msk = datetime.fromtimestamp(t0_ms / 1000, tz=MSK).strftime("%Y-%m-%d %H:%M MSK")
    # current_price = close of last 1m bar that closed STRICTLY before t0.
    # bars_1m entries (ts, o, h, l, c) where ts = bar OPEN time.
    # bar at ts closes at ts + 60_000. closed-before-t0 → ts + 60_000 <= t0.
    cur_price = None
    if bars_1m:
        import bisect
        ts_arr = bars_1m_ts if bars_1m_ts is not None else [b[0] for b in bars_1m]
        idx = bisect.bisect_right(ts_arr, t0_ms - 60_000) - 1
        if idx >= 0:
            cur_price = bars_1m[idx][4]  # close
    snapshot = {
        "t0": t0_ms // 1000,
        "t0_iso_msk": t0_iso_msk,
        "symbol": symbol,
        "current_price": cur_price,
        "active_zones": [],
        "fractals": {},
        "structural": {},
        "breakers": [],
        "mitigation_blocks": [],
        "inducements": [],
    }

    import time
    for tf_label in tf_panel:
        tf_ms = TF_MS[tf_label]
        tf_bars = aggregate_to_tf(bars_1m, tf_ms, anchor_ms=ANCHOR_MS)
        candles, ts_list = bars_with_ts_up_to_cutoff(
            tf_bars, t0_ms, tf_ms, max_bars_back=MAX_BARS_BACK.get(tf_label),
        )
        if len(candles) < 5:
            continue  # need min bars for detection
        t_start = time.time()
        print(f"  [{tf_label}] {len(candles)} closed bars...", file=sys.stderr, flush=True)

        snapshot["active_zones"].extend(
            detect_active_obs_on_tf(candles, ts_list, tf_label)
        )
        snapshot["active_zones"].extend(
            detect_active_fvgs_on_tf(candles, ts_list, tf_label)
        )
        snapshot["active_zones"].extend(
            detect_active_marubozu_on_tf(candles, ts_list, tf_label)
        )
        snapshot["active_zones"].extend(
            detect_active_block_orders_on_tf(candles, ts_list, tf_label)
        )
        snapshot["active_zones"].extend(
            detect_active_rdrb_on_tf(candles, ts_list, tf_label)
        )
        snapshot["active_zones"].extend(
            detect_active_i_rdrb_on_tf(candles, ts_list, tf_label)
        )
        snapshot["active_zones"].extend(
            detect_active_ob_liq_on_tf(candles, ts_list, tf_label)
        )
        # i-FVG: O(N²) на FVGs, может быть тяжёлой для высоких TFs с many bars.
        # Для Phase 1 baseline — включаем; profile в Phase 2 если станет узким местом.
        snapshot["active_zones"].extend(
            detect_active_i_fvg_on_tf(candles, ts_list, tf_label)
        )
        snapshot["fractals"][tf_label] = detect_fractals_on_tf(
            candles, ts_list, tf_label
        )
        snapshot["structural"][tf_label] = detect_choch_bos_on_tf(
            candles, ts_list, tf_label
        )
        snapshot["breakers"].extend(
            detect_active_breaker_blocks_on_tf(candles, ts_list, tf_label)
        )
        snapshot["mitigation_blocks"].extend(
            detect_active_mitigation_blocks_on_tf(candles, ts_list, tf_label)
        )
        snapshot["inducements"].extend(
            detect_active_inducements_on_tf(candles, ts_list, tf_label)
        )
        print(
            f"  [{tf_label}] done in {time.time() - t_start:.1f}s",
            file=sys.stderr,
            flush=True,
        )

    return snapshot


def save_snapshot(snapshot: dict, out_dir: pathlib.Path = SNAPSHOTS_DIR) -> pathlib.Path:
    """Save snapshot JSON. Filename = t0_iso_msk."""
    fname = snapshot["t0_iso_msk"].replace(" ", "_").replace(":", "-") + ".json"
    out_path = out_dir / fname
    out_path.write_text(json.dumps(snapshot, indent=2))
    return out_path


# ─── CLI / smoke test ─────────────────────────────────────

def main(
    t0_iso_msk: str = "2026-06-14 15:00",
    tf_panel: tuple[str, ...] = ("15m", "1h", "4h", "12h", "1D"),
):
    """Build single snapshot at t0.

    Usage:
        python3 snapshot_builder.py [t0_iso_msk] [tfs]
        tfs: comma-separated, e.g. "4h,12h,1D" (default: 15m,1h,4h,12h,1D)
    """
    bars_1m = load_1m_csv()
    sanity_check_data(bars_1m)

    naive = datetime.strptime(t0_iso_msk, "%Y-%m-%d %H:%M")
    t0_dt = naive.replace(tzinfo=MSK)
    t0_ms = int(t0_dt.timestamp() * 1000)

    print(
        f"Building snapshot for t0 = {t0_dt.isoformat()} (= {t0_ms} ms)\n"
        f"TFs: {tf_panel}",
        file=sys.stderr,
    )
    snapshot = build_snapshot(bars_1m, t0_ms, tf_panel=tf_panel)
    out_path = save_snapshot(snapshot)
    import collections
    by_elem = collections.Counter(z["element"] for z in snapshot["active_zones"])
    by_tf = collections.Counter(z["tf"] for z in snapshot["active_zones"])
    print(
        f"Saved: {out_path}\n"
        f"  active_zones: {len(snapshot['active_zones'])}\n"
        f"    by element: {dict(by_elem)}\n"
        f"    by tf:      {dict(by_tf)}\n"
        f"  fractals: {sum(len(v) for v in snapshot['fractals'].values())}\n"
        f"  structural TFs: {len(snapshot['structural'])}\n"
        f"  breakers: {len(snapshot['breakers'])}\n"
        f"  mitigation_blocks: {len(snapshot['mitigation_blocks'])}\n"
        f"  inducements: {len(snapshot['inducements'])}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "2026-06-14 15:00"
    tfs_arg = sys.argv[2] if len(sys.argv) > 2 else None
    tf_panel = tuple(tfs_arg.split(",")) if tfs_arg else ("15m", "1h", "4h", "12h", "1D")
    main(arg, tf_panel)
