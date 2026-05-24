"""Базовая геометрия свечи. Используется всеми элементами библиотеки.

Соглашения:
- body_top = max(open, close), body_bottom = min(open, close)
- upper_wick = [body_top, high], lower_wick = [low, body_bottom]
- bull: close > open; bear: close < open; doji: close == open
- Время — UTC (миллисекунды от эпохи). Отображение в UTC+3 — задача визуализации.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class Candle:
    open: float
    high: float
    low: float
    close: float
    open_time: int | None = None  # ms since epoch, UTC

    @property
    def body_top(self) -> float:
        return max(self.open, self.close)

    @property
    def body_bottom(self) -> float:
        return min(self.open, self.close)

    @property
    def body_size(self) -> float:
        return self.body_top - self.body_bottom

    @property
    def upper_wick_size(self) -> float:
        return self.high - self.body_top

    @property
    def lower_wick_size(self) -> float:
        return self.body_bottom - self.low

    @property
    def is_bull(self) -> bool:
        return self.close > self.open

    @property
    def is_bear(self) -> bool:
        return self.close < self.open

    @property
    def is_doji(self) -> bool:
        return self.close == self.open


def intervals_overlap(a: tuple[float, float], b: tuple[float, float]) -> bool:
    """Строгое пересечение замкнутых интервалов: длина пересечения > 0."""
    return max(a[0], b[0]) < min(a[1], b[1])
