"""i-FVG (Inverse FVG). Спецификация: definition.md.

Canon v2 (2026-06-15) — FINAL:
  Composite: FVG-A + FVG-B противоположного направления. Между A.c3 и B.c1
  свечи могут касаться A.zone wick'ами — A.zone шринкается через wick-fill
  mitigation (Правило 2 Модель 1). Если A не consumed до B.c1, имеем
  shrunk_A. i-FVG ZoI = overlap(shrunk_A, B.zone). Direction = B.direction.

Старый канон (v1) с условием «A untouched between» — DEPRECATED. Slishком
строг, отсекает большинство реальных i-FVG (включая user-A $67,516-$67,732
2026-06-03 BTC 12h, который v1 не находил).
"""
from __future__ import annotations

import sys
import pathlib
from dataclasses import dataclass
from typing import Literal

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from candle import Candle, intervals_overlap
from elements.fvg.code import FVG, detect_fvg
from elements._mitigation import apply_wick_fill_mitigation


Direction = Literal["long", "short"]
Interval = tuple[float, float]


@dataclass(frozen=True)
class IFVG:
    direction: Direction         # = b.direction
    a: FVG                       # исходная FVG (роль инвертирует)
    b: FVG                       # обратная FVG (the i-FVG)
    between: tuple[Candle, ...]  # свечи между A.c3 и B.c1 (могут шринкать A.zone)
    a_shrunk: Interval           # A.zone после wick-fill через between bars (canon v2)
    overlap: Interval            # пересечение shrunk_A и B.zone — зона интереса


def _candle_touches(candle: Candle, zone: Interval) -> bool:
    """Wick свечи входит в зону (строгое пересечение интервалов)."""
    return intervals_overlap((candle.low, candle.high), zone)


def detect_i_fvg(
    a_c1: Candle, a_c2: Candle, a_c3: Candle,
    between: tuple[Candle, ...] | list[Candle],
    b_c1: Candle, b_c2: Candle, b_c3: Candle,
) -> IFVG | None:
    """Возвращает IFVG или None.

    Канон v2 (2026-06-15):
    1. FVG-A валидна на (a_c1, a_c2, a_c3).
    2. FVG-B валидна на (b_c1, b_c2, b_c3), B.direction != A.direction.
    3. Применяем wick-fill mitigation A.zone через свечи `between` (направление
       = A.direction). Если A полностью consumed — return None.
    4. shrunk_A = state.active_zone после mitigation.
    5. Хотя бы одна из (b_c1, b_c2, b_c3) касается shrunk_A wick'ом
       (inversion trigger).
    6. shrunk_A ∩ B.zone имеет положительную ширину.
    7. overlap = max(shrunk_A.lo, B.zone.lo), min(shrunk_A.hi, B.zone.hi).
    """
    a = detect_fvg(a_c1, a_c2, a_c3)
    if a is None:
        return None
    b = detect_fvg(b_c1, b_c2, b_c3)
    if b is None or b.direction == a.direction:
        return None

    # Шринкаем A.zone через between bars
    state = apply_wick_fill_mitigation(
        initial_zone=a.zone,
        direction=a.direction,
        subsequent_bars=list(between),
    )
    if state.is_consumed:
        return None    # A полностью съедена до B-формирования
    a_shrunk: Interval = state.active_zone

    # B должна задеть shrunk A (inversion trigger)
    if not any(_candle_touches(c, a_shrunk) for c in (b_c1, b_c2, b_c3)):
        return None

    # Overlap shrunk_A ∩ B.zone
    if not intervals_overlap(a_shrunk, b.zone):
        return None

    overlap: Interval = (max(a_shrunk[0], b.zone[0]),
                          min(a_shrunk[1], b.zone[1]))
    return IFVG(
        direction=b.direction,
        a=a, b=b,
        between=tuple(between),
        a_shrunk=a_shrunk,
        overlap=overlap,
    )
