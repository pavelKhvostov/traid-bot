"""Marubozu — свеча без фитиля со стороны open. Спецификация: definition.md.

Canon: Pine WICK.ED.
  LONG:  open == low  AND  close > open
  SHORT: open == high AND  close < open

Зона интереса = тело свечи.
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
class Marubozu:
    direction: Direction
    candle: Candle
    zone: Interval     # тело свечи: [body_bottom, body_top]


def detect_marubozu(c: Candle) -> Marubozu | None:
    """Возвращает Marubozu или None.

    LONG: open == low AND close > open (нет нижнего фитиля, bull).
    SHORT: open == high AND close < open (нет верхнего фитиля, bear).
    Doji и нулевой диапазон исключены автоматически (close > open / close < open).
    """
    if c.open == c.low and c.close > c.open:
        return Marubozu("long", c, (c.open, c.close))
    if c.open == c.high and c.close < c.open:
        return Marubozu("short", c, (c.close, c.open))
    return None
