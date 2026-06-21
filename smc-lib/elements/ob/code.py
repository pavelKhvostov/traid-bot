"""OB (Order Block). Спецификация: definition.md.

Канонический 2-свечный паттерн. Зона интереса по vault canon.
"""
from __future__ import annotations

import sys
import pathlib
from dataclasses import dataclass
from typing import Literal

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from candle import Candle


Direction = Literal["long", "short"]
Interval = tuple[float, float]


@dataclass(frozen=True)
class OB:
    direction: Direction
    prev: Candle
    cur: Candle
    zone: Interval            # ZoI OB = drop/rally area, всегда: [min(prev.low, cur.low), prev.open] LONG / [prev.open, max(prev.high, cur.high)] SHORT


def is_full_break(ob: "OB") -> bool:
    """Проткнул ли cur prev целиком — триггер для отдельного элемента Breaker Block.

    LONG: cur.close > prev.high; SHORT: cur.close < prev.low.
    Сам OB.zone от этого не зависит. См. elements/breaker_block/.
    """
    if ob.direction == "long":
        return ob.cur.close > ob.prev.high
    return ob.cur.close < ob.prev.low


def detect_ob(prev: Candle, cur: Candle) -> OB | None:
    """Возвращает OB или None.

    LONG: prev bear, cur bull, cur.close > prev.open. ZoI = drop area = [min(prev.low, cur.low), prev.open].
    SHORT: prev bull, cur bear, cur.close < prev.open. ZoI = rally area = [prev.open, max(prev.high, cur.high)].

    Breaker block — самостоятельный элемент со своей ZoI (canon 2026-06-14), см. elements/breaker_block/.
    """
    if prev.is_bear and cur.is_bull and cur.close > prev.open:
        drop_low = min(prev.low, cur.low)
        return OB("long", prev, cur, (drop_low, prev.open))
    if prev.is_bull and cur.is_bear and cur.close < prev.open:
        rally_high = max(prev.high, cur.high)
        return OB("short", prev, cur, (prev.open, rally_high))
    return None
