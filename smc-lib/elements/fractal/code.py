"""Fractal (Williams). Спецификация: definition.md.

Canon: 5-bar Williams BW с N=2. Параметр N настраиваемый.
FH: center.high строго > всех 2N соседей.
FL: center.low строго < всех 2N соседей.
Зона интереса = уровень (одна цена), не интервал.
"""
from __future__ import annotations

import sys
import pathlib
from dataclasses import dataclass
from typing import Literal

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from candle import Candle


Direction = Literal["high", "low"]


@dataclass(frozen=True)
class Fractal:
    direction: Direction       # "high" = FH, "low" = FL
    n: int                     # параметр Williams (= radius окна; всего 2N+1 свечей)
    center: Candle             # pivot candle
    level: float               # = center.high (FH) или center.low (FL); ТОЧКА, не интервал


def detect_fractal(candles: list[Candle] | tuple[Candle, ...], n: int = 2) -> Fractal | None:
    """Williams fractal detector. Центр на индексе n.

    Args:
        candles: ровно 2N+1 свечей (N=2 → 5 свечей).
        n: радиус окна (canon=2). Допускается n ≥ 1.

    Returns:
        Fractal если центральная свеча строго максимальна по high (FH) ИЛИ
        строго минимальна по low (FL).
        None если: неверная длина, ничья (==), оба условия одновременно.
    """
    if n < 1 or len(candles) != 2 * n + 1:
        return None

    center = candles[n]
    others = tuple(candles[:n]) + tuple(candles[n + 1:])

    is_fh = all(center.high > c.high for c in others)
    is_fl = all(center.low < c.low for c in others)

    if is_fh and not is_fl:
        return Fractal("high", n, center, center.high)
    if is_fl and not is_fh:
        return Fractal("low", n, center, center.low)
    return None
