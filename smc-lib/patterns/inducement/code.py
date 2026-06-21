"""Inducement — composite ZoI после CHoCH. Спецификация: definition.md.

Canon 2026-06-14: Inducement = structural закономерность из 8 шагов, не fixed-candle pattern.

ZoI = (OB unmitigated) ∪ (FVG residual after partial fill) — композитная зона интереса
в premium-half (Bearish) или discount-half (Bullish).

8 шагов (на примере Bearish setup):
  1. SHORT OB на топе bull-импульса
  2. Bearish FVG (aligned), внутри/около OB
  3. Bearish CHoCH — close < lower_fractal (slом uptrend, gate-условие)
  4. Fractal Low подтверждает bearish-направление после CHoCH
  5. Корректирующий bounce частично заполняет FVG (residual ≠ ∅)
  6. Fractal High = IDM-маркер (mini-LH ниже LH до CHoCH)
  7. Fractal Low — новый LL (BOS continuation, zone ARMED)
  8. Возврат + sweep IDM + касание composite zone → TRIGGERED (SHORT entry)

Bullish setup — зеркально (LONG OB → Bullish FVG → Bullish CHoCH → ... → LONG entry).

Anti-lookahead guardrails:
  - Все детекторы получают closed bars only (caller-responsible)
  - Fractal confirmation_time = center.open_time + (N+1)*tf_ms (не center.open_time)
  - State machine progressing strictly left-to-right через candles
  - Composite zone armed только ПОСЛЕ confirmed BOS-fractal (step 7), не раньше
"""
from __future__ import annotations

import sys
import pathlib
from dataclasses import dataclass, field
from typing import Literal, Optional

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from candle import Candle
from elements.ob.code import OB, detect_ob, is_full_break
from elements.fvg.code import FVG, detect_fvg


Direction = Literal["bullish", "bearish"]
Interval = tuple[float, float]

# State machine states (string literals для serialization)
STATE_PENDING = "pending"           # OB + FVG найдены, ждём CHoCH
STATE_GATED = "gated"               # CHoCH подтверждён + post-CHoCH fractal
STATE_BOUNCING = "bouncing"         # корректирующий bounce, ждём IDM-фрактал
STATE_ARMED = "armed"               # BOS continuation подтверждён, zone валидна
STATE_TRIGGERED = "triggered"       # sweep IDM + касание composite zone
STATE_INVALIDATED = "invalidated"   # любое условие нарушено
InducementState = Literal[
    "pending", "gated", "bouncing", "armed", "triggered", "invalidated",
]


@dataclass(frozen=True)
class Inducement:
    """Inducement instance c canonical 8-step state machine.

    Возвращается из детектора со state = ARMED или TRIGGERED (рабочие состояния).
    Если state = INVALIDATED — кандидат не дозрел, отбрасывается caller'ом.
    """
    direction: Direction
    state: InducementState

    # Step 1: OB
    ob: OB
    i_ob: int                    # индекс cur свечи OB в candles

    # Step 2: FVG (aligned)
    fvg: FVG
    i_fvg_c3: int                # индекс c3 свечи FVG

    # Step 3: CHoCH (gate)
    i_choch: int                 # бар где зафиксирован close-cross
    choch_level: float           # уровень фрактала, который был cross'нут

    # Step 4: post-CHoCH fractal (подтверждение направления)
    i_post_choch_fractal: int    # bearish setup → fractal_low; bullish → fractal_high

    # Step 5: partial FVG fill (residual)
    fvg_residual: Interval       # остаточная часть FVG после bounce wick-fill

    # Step 6: IDM marker (mini-LH/HL)
    i_idm: int
    idm_level: float             # bearish setup → fractal.high; bullish → fractal.low

    # Step 7: BOS continuation fractal
    i_bos: int

    # Composite zone (ZoI) = OB.zone ∪ fvg_residual (объединение перекрывающихся/смежных)
    composite_zone: Interval

    # Step 8: triggered (если sweep + touch произошёл)
    i_sweep: Optional[int] = None      # бар где sweep IDM произошёл
    i_zone_touch: Optional[int] = None # бар касания composite zone


def _is_fractal_low(candles: list[Candle], i: int, n: int = 2) -> bool:
    if i < n or i + n >= len(candles):
        return False
    pivot = candles[i].low
    for k in range(-n, n + 1):
        if k == 0:
            continue
        if candles[i + k].low <= pivot:
            return False
    return True


def _is_fractal_high(candles: list[Candle], i: int, n: int = 2) -> bool:
    if i < n or i + n >= len(candles):
        return False
    pivot = candles[i].high
    for k in range(-n, n + 1):
        if k == 0:
            continue
        if candles[i + k].high >= pivot:
            return False
    return True


def _bearish_fvg_residual_after_touch(
    fvg: FVG, candles: list[Candle], i_start: int, i_end: int
) -> Optional[Interval]:
    """Bearish FVG = [c3.high, c1.low] = resistance сверху.

    Wick-fill model: касание снизу wick'ом, high ≥ zone_lo (=c3.high).
    После касания zone сжимается до [high_touch, c1.low].
    Возврат: residual или None если consumed (high ≥ zone_hi).
    """
    zone_lo, zone_hi = fvg.zone
    max_high_in_window = max(candles[j].high for j in range(i_start, i_end + 1))
    if max_high_in_window < zone_lo:
        return zone_lo, zone_hi  # no touch — full residual
    if max_high_in_window >= zone_hi:
        return None  # consumed
    return max_high_in_window, zone_hi


def _bullish_fvg_residual_after_touch(
    fvg: FVG, candles: list[Candle], i_start: int, i_end: int
) -> Optional[Interval]:
    """Bullish FVG = [c1.high, c3.low] = support снизу.

    Wick-fill: касание сверху wick'ом, low ≤ zone_hi (=c3.low).
    После касания zone сжимается до [c1.high, low_touch].
    """
    zone_lo, zone_hi = fvg.zone
    min_low_in_window = min(candles[j].low for j in range(i_start, i_end + 1))
    if min_low_in_window > zone_hi:
        return zone_lo, zone_hi
    if min_low_in_window <= zone_lo:
        return None
    return zone_lo, min_low_in_window


def _merge_zones(z1: Interval, z2: Interval) -> Interval:
    """Объединение перекрывающихся/смежных интервалов в один."""
    return (min(z1[0], z2[0]), max(z1[1], z2[1]))


def detect_bearish_inducement(
    candles: list[Candle],
    max_bars_choch_to_idm: int = 30,
    max_bars_idm_to_bos: int = 30,
    max_bars_to_return: int = 50,
) -> Optional[Inducement]:
    """Scan candles for FIRST Bearish Inducement (SHORT setup).

    Steps 1-7 → state = ARMED. Step 8 (return + sweep + touch) → state = TRIGGERED.
    """
    n = len(candles)

    # Step 1: scan for SHORT OB
    for i_ob in range(1, n - 10):
        ob = detect_ob(candles[i_ob - 1], candles[i_ob])
        if ob is None or ob.direction != "short":
            continue

        # Step 2: Bearish FVG aligned, начинающаяся после OB.cur (closed)
        # FVG в окне [i_ob + 1 .. i_ob + max_bars_choch_to_idm]
        for i_fvg_c1 in range(i_ob + 1, min(i_ob + 1 + max_bars_choch_to_idm, n - 2)):
            fvg = detect_fvg(
                candles[i_fvg_c1], candles[i_fvg_c1 + 1], candles[i_fvg_c1 + 2]
            )
            if fvg is None or fvg.direction != "short":
                continue
            i_fvg_c3 = i_fvg_c1 + 2

            # Step 3: Bearish CHoCH после FVG.c3
            # CHoCH bearish = close < last_fractal_low.value
            # Сканируем для confirmed fractal_low и close-cross
            i_choch_search_start = i_fvg_c3 + 1
            i_choch = _find_bearish_choch_after(
                candles, i_choch_search_start, max_bars_choch_to_idm
            )
            if i_choch is None:
                continue
            # Уровень CHoCH = центральный low фрактала, который был cross'нут
            choch_fractal_idx = _find_last_fractal_low_before(candles, i_choch)
            if choch_fractal_idx is None:
                continue
            choch_level = candles[choch_fractal_idx].low

            # Step 4: post-CHoCH fractal_low (подтверждение нового bearish)
            i_post_choch_fractal = _find_first_fractal_low_after(
                candles, i_choch, max_bars_idm_to_bos
            )
            if i_post_choch_fractal is None:
                continue

            # Step 5: partial FVG fill — корректирующий bounce между #4 и потенциальным #6
            # Минимум что нужно: max(high) в окне [i_post_choch_fractal, i_idm_search_start]
            # частично, но не полностью заполняет FVG.
            i_idm_search_start = i_post_choch_fractal + 1

            # Step 6: IDM = fractal_high (mini-LH) на топе bounce
            for i_idm in range(
                i_idm_search_start,
                min(i_idm_search_start + max_bars_idm_to_bos, n - 2),
            ):
                if not _is_fractal_high(candles, i_idm):
                    continue
                idm_level = candles[i_idm].high
                # NB: IDM = mini-LH в bear environment после CHoCH.
                # Структурно гарантировано что bounce-high < pre-CHoCH high (downtrend).

                # Step 5 check: partial fill FVG в окне [i_post_choch_fractal, i_idm]
                residual = _bearish_fvg_residual_after_touch(
                    fvg, candles, i_post_choch_fractal, i_idm
                )
                if residual is None:
                    # FVG полностью consumed → setup invalid
                    continue

                # Step 7: BOS continuation = новый fractal_low НИЖЕ i_post_choch_fractal
                ll_level_to_break = candles[i_post_choch_fractal].low
                i_bos = _find_first_fractal_low_below_after(
                    candles, i_idm, ll_level_to_break, max_bars_idm_to_bos
                )
                if i_bos is None:
                    continue

                # ✅ ARMED: steps 1-7 complete
                composite = _merge_zones(ob.zone, residual)

                # Step 8: return up + sweep IDM + touch composite zone
                i_sweep, i_zone_touch = _check_step_8_bearish(
                    candles, i_bos, idm_level, composite, max_bars_to_return
                )

                state: InducementState = (
                    STATE_TRIGGERED if (i_sweep is not None and i_zone_touch is not None)
                    else STATE_ARMED
                )

                return Inducement(
                    direction="bearish",
                    state=state,
                    ob=ob,
                    i_ob=i_ob,
                    fvg=fvg,
                    i_fvg_c3=i_fvg_c3,
                    i_choch=i_choch,
                    choch_level=choch_level,
                    i_post_choch_fractal=i_post_choch_fractal,
                    fvg_residual=residual,
                    i_idm=i_idm,
                    idm_level=idm_level,
                    i_bos=i_bos,
                    composite_zone=composite,
                    i_sweep=i_sweep,
                    i_zone_touch=i_zone_touch,
                )
    return None


def detect_bullish_inducement(
    candles: list[Candle],
    max_bars_choch_to_idm: int = 30,
    max_bars_idm_to_bos: int = 30,
    max_bars_to_return: int = 50,
) -> Optional[Inducement]:
    """Mirror — Bullish Inducement (LONG setup)."""
    n = len(candles)

    for i_ob in range(1, n - 10):
        ob = detect_ob(candles[i_ob - 1], candles[i_ob])
        if ob is None or ob.direction != "long":
            continue

        for i_fvg_c1 in range(i_ob + 1, min(i_ob + 1 + max_bars_choch_to_idm, n - 2)):
            fvg = detect_fvg(
                candles[i_fvg_c1], candles[i_fvg_c1 + 1], candles[i_fvg_c1 + 2]
            )
            if fvg is None or fvg.direction != "long":
                continue
            i_fvg_c3 = i_fvg_c1 + 2

            i_choch_search_start = i_fvg_c3 + 1
            i_choch = _find_bullish_choch_after(
                candles, i_choch_search_start, max_bars_choch_to_idm
            )
            if i_choch is None:
                continue
            choch_fractal_idx = _find_last_fractal_high_before(candles, i_choch)
            if choch_fractal_idx is None:
                continue
            choch_level = candles[choch_fractal_idx].high

            i_post_choch_fractal = _find_first_fractal_high_after(
                candles, i_choch, max_bars_idm_to_bos
            )
            if i_post_choch_fractal is None:
                continue

            i_idm_search_start = i_post_choch_fractal + 1

            for i_idm in range(
                i_idm_search_start,
                min(i_idm_search_start + max_bars_idm_to_bos, n - 2),
            ):
                if not _is_fractal_low(candles, i_idm):
                    continue
                idm_level = candles[i_idm].low
                # NB: IDM = mini-HL в bull environment после CHoCH.

                residual = _bullish_fvg_residual_after_touch(
                    fvg, candles, i_post_choch_fractal, i_idm
                )
                if residual is None:
                    continue

                hh_level_to_break = candles[i_post_choch_fractal].high
                i_bos = _find_first_fractal_high_above_after(
                    candles, i_idm, hh_level_to_break, max_bars_idm_to_bos
                )
                if i_bos is None:
                    continue

                composite = _merge_zones(ob.zone, residual)

                i_sweep, i_zone_touch = _check_step_8_bullish(
                    candles, i_bos, idm_level, composite, max_bars_to_return
                )

                state = (
                    STATE_TRIGGERED if (i_sweep is not None and i_zone_touch is not None)
                    else STATE_ARMED
                )

                return Inducement(
                    direction="bullish",
                    state=state,
                    ob=ob,
                    i_ob=i_ob,
                    fvg=fvg,
                    i_fvg_c3=i_fvg_c3,
                    i_choch=i_choch,
                    choch_level=choch_level,
                    i_post_choch_fractal=i_post_choch_fractal,
                    fvg_residual=residual,
                    i_idm=i_idm,
                    idm_level=idm_level,
                    i_bos=i_bos,
                    composite_zone=composite,
                    i_sweep=i_sweep,
                    i_zone_touch=i_zone_touch,
                )
    return None


# ─────────────────────────────────────────────────────────────────────
# Helpers — поиск фракталов и CHoCH
# ─────────────────────────────────────────────────────────────────────

def _find_last_fractal_low_before(candles: list[Candle], i_limit: int) -> Optional[int]:
    """Последний confirmed fractal_low в окне [0, i_limit-1]."""
    for i in range(i_limit - 1, 1, -1):
        if _is_fractal_low(candles, i):
            return i
    return None


def _find_last_fractal_high_before(candles: list[Candle], i_limit: int) -> Optional[int]:
    for i in range(i_limit - 1, 1, -1):
        if _is_fractal_high(candles, i):
            return i
    return None


def _find_first_fractal_low_after(
    candles: list[Candle], i_from: int, max_bars: int
) -> Optional[int]:
    for i in range(i_from + 1, min(i_from + 1 + max_bars, len(candles) - 2)):
        if _is_fractal_low(candles, i):
            return i
    return None


def _find_first_fractal_high_after(
    candles: list[Candle], i_from: int, max_bars: int
) -> Optional[int]:
    for i in range(i_from + 1, min(i_from + 1 + max_bars, len(candles) - 2)):
        if _is_fractal_high(candles, i):
            return i
    return None


def _find_first_fractal_low_below_after(
    candles: list[Candle], i_from: int, level: float, max_bars: int
) -> Optional[int]:
    """Первый confirmed fractal_low ПОСЛЕ i_from, чей low < level."""
    for i in range(i_from + 1, min(i_from + 1 + max_bars, len(candles) - 2)):
        if _is_fractal_low(candles, i) and candles[i].low < level:
            return i
    return None


def _find_first_fractal_high_above_after(
    candles: list[Candle], i_from: int, level: float, max_bars: int
) -> Optional[int]:
    for i in range(i_from + 1, min(i_from + 1 + max_bars, len(candles) - 2)):
        if _is_fractal_high(candles, i) and candles[i].high > level:
            return i
    return None


def _find_bearish_choch_after(
    candles: list[Candle], i_from: int, max_bars: int
) -> Optional[int]:
    """Bearish CHoCH = close < последний fractal_low.value.

    Возвращает индекс свечи где зафиксирован close-cross.
    """
    fractal_low_idx = _find_last_fractal_low_before(candles, i_from)
    if fractal_low_idx is None:
        return None
    level = candles[fractal_low_idx].low
    for i in range(i_from, min(i_from + max_bars, len(candles))):
        if candles[i].close < level:
            return i
    return None


def _find_bullish_choch_after(
    candles: list[Candle], i_from: int, max_bars: int
) -> Optional[int]:
    fractal_high_idx = _find_last_fractal_high_before(candles, i_from)
    if fractal_high_idx is None:
        return None
    level = candles[fractal_high_idx].high
    for i in range(i_from, min(i_from + max_bars, len(candles))):
        if candles[i].close > level:
            return i
    return None


def _check_step_8_bearish(
    candles: list[Candle],
    i_from: int,
    idm_level: float,
    composite: Interval,
    max_bars: int,
) -> tuple[Optional[int], Optional[int]]:
    """Bearish step 8: return up → sweep IDM (high > idm_level) → touch composite zone.

    Returns (i_sweep, i_zone_touch). Если последовательность не выполнена → (None, None).
    """
    zone_lo, zone_hi = composite
    i_sweep: Optional[int] = None
    for j in range(i_from + 1, min(i_from + 1 + max_bars, len(candles))):
        bar = candles[j]
        if i_sweep is None and bar.high > idm_level:
            i_sweep = j
            continue
        if i_sweep is not None and bar.high >= zone_lo and bar.low <= zone_hi:
            return i_sweep, j
    return i_sweep, None


def _check_step_8_bullish(
    candles: list[Candle],
    i_from: int,
    idm_level: float,
    composite: Interval,
    max_bars: int,
) -> tuple[Optional[int], Optional[int]]:
    zone_lo, zone_hi = composite
    i_sweep: Optional[int] = None
    for j in range(i_from + 1, min(i_from + 1 + max_bars, len(candles))):
        bar = candles[j]
        if i_sweep is None and bar.low < idm_level:
            i_sweep = j
            continue
        if i_sweep is not None and bar.low <= zone_hi and bar.high >= zone_lo:
            return i_sweep, j
    return i_sweep, None
