"""i-FVG (Inverse FVG). Спецификация: definition.md.

Composite: FVG-A + FVG-B противоположного направления. B первой касается A
(untouched A между A.c3 и B.c1). Зоны должны пересекаться. После события
роль зоны A инвертирует. Направление i-FVG = направление B.
"""
from __future__ import annotations

import sys
import pathlib
from dataclasses import dataclass
from typing import Literal

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from candle import Candle, intervals_overlap
from elements.fvg.code import FVG, detect_fvg


Direction = Literal["long", "short"]
Interval = tuple[float, float]


@dataclass(frozen=True)
class IFVG:
    direction: Direction         # = b.direction
    a: FVG                       # исходная FVG (роль инвертирует)
    b: FVG                       # обратная FVG (the i-FVG)
    between: tuple[Candle, ...]  # untouched-свечи между A.c3 и B.c1
    overlap: Interval            # пересечение A.zone и B.zone — зона интереса


def _candle_touches(candle: Candle, zone: Interval) -> bool:
    """Wick свечи входит в зону (строгое пересечение интервалов)."""
    return intervals_overlap((candle.low, candle.high), zone)


def detect_i_fvg(
    a_c1: Candle, a_c2: Candle, a_c3: Candle,
    between: tuple[Candle, ...] | list[Candle],
    b_c1: Candle, b_c2: Candle, b_c3: Candle,
) -> IFVG | None:
    """Возвращает IFVG или None.

    Условия:
    1. FVG-A валидна на (a_c1, a_c2, a_c3).
    2. FVG-B валидна на (b_c1, b_c2, b_c3), B.direction != A.direction.
    3. Ни одна свеча в `between` не касается A.zone (A осталась untouched).
    4. Хотя бы одна из (b_c1, b_c2, b_c3) касается A.zone (first touch внутри B).
    5. A.zone и B.zone имеют общий ценовой диапазон (intervals_overlap).
    """
    a = detect_fvg(a_c1, a_c2, a_c3)
    if a is None:
        return None
    b = detect_fvg(b_c1, b_c2, b_c3)
    if b is None or b.direction == a.direction:
        return None

    if any(_candle_touches(c, a.zone) for c in between):
        return None

    if not any(_candle_touches(c, a.zone) for c in (b_c1, b_c2, b_c3)):
        return None

    if not intervals_overlap(a.zone, b.zone):
        return None

    overlap: Interval = (max(a.zone[0], b.zone[0]), min(a.zone[1], b.zone[1]))
    return IFVG(b.direction, a, b, tuple(between), overlap)
