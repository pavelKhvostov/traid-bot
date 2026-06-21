"""CHoCH / BOS — Market Structure (Fractal). Спецификация: definition.md.

LuxAlgo Pine v5 canon (CC BY-NC-SA). Два разных элемента (CHoCH, BOS) c общей
state machine `os`. На выходе — единый поток MarketStructureEvent с полем `type`.

CHoCH = слом ориентации (reversal); BOS = продолжение (continuation).
"""
from __future__ import annotations

import sys
import pathlib
from dataclasses import dataclass
from typing import Literal

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from candle import Candle


Side = Literal["bullish", "bearish"]
EventType = Literal["CHoCH", "BOS"]


@dataclass(frozen=True)
class MarketStructureEvent:
    type: EventType
    side: Side
    fractal_idx: int          # индекс центральной свечи фрактала
    fractal_level: float      # high (FH) для bullish break / low (FL) для bearish break
    break_idx: int            # индекс свечи закрытия за уровнем


def _is_fractal_high(candles: list[Candle], center: int, p: int) -> bool:
    """LuxAlgo bullf (FH) — high[center] строго выше high[center±k] для k=1..p."""
    if center - p < 0 or center + p >= len(candles):
        return False
    pivot = candles[center].high
    for k in range(1, p + 1):
        if candles[center - k].high >= pivot:
            return False
        if candles[center + k].high >= pivot:
            return False
    return True


def _is_fractal_low(candles: list[Candle], center: int, p: int) -> bool:
    if center - p < 0 or center + p >= len(candles):
        return False
    pivot = candles[center].low
    for k in range(1, p + 1):
        if candles[center - k].low <= pivot:
            return False
        if candles[center + k].low <= pivot:
            return False
    return True


def scan_market_structure(
    candles: list[Candle],
    length: int = 5,
    min_break_depth_pct: float = 0.0,
) -> list[MarketStructureEvent]:
    """Сканирует серию баров и выдаёт CHoCH/BOS события по канону LuxAlgo.

    Алгоритм (на каждом баре n):
      1. Если бар n-p — confirmed FH или FL: обновить `upper`/`lower`, iscrossed=False.
      2. Bullish break: close[n] > upper.level AND close[n-1] <= upper.level AND not upper.iscrossed.
         Тип: BOS если os ∈ {0, +1}, CHoCH если os == -1. После: os := +1.
      3. Bearish break: close[n] < lower.level AND close[n-1] >= lower.level AND not lower.iscrossed.
         Тип: BOS если os ∈ {0, -1}, CHoCH если os == +1. После: os := -1.
    """
    if length < 3:
        raise ValueError("length must be >= 3")
    p = length // 2
    events: list[MarketStructureEvent] = []

    upper_level: float | None = None
    upper_idx: int | None = None
    upper_crossed = True

    lower_level: float | None = None
    lower_idx: int | None = None
    lower_crossed = True

    os: int = 0

    for n in range(len(candles)):
        # Confirm fractal at n-p
        center = n - p
        if center >= 0:
            if _is_fractal_high(candles, center, p):
                upper_level = candles[center].high
                upper_idx = center
                upper_crossed = False
            if _is_fractal_low(candles, center, p):
                lower_level = candles[center].low
                lower_idx = center
                lower_crossed = False

        if n == 0:
            continue

        # Bullish break (close cross upper)
        if upper_level is not None and not upper_crossed:
            threshold = upper_level + min_break_depth_pct * upper_level / 100
            if candles[n].close > threshold and candles[n - 1].close <= upper_level:
                ev_type: EventType = "CHoCH" if os == -1 else "BOS"
                events.append(MarketStructureEvent(
                    type=ev_type, side="bullish",
                    fractal_idx=upper_idx, fractal_level=upper_level,
                    break_idx=n,
                ))
                upper_crossed = True
                os = 1

        # Bearish break (close cross lower)
        if lower_level is not None and not lower_crossed:
            threshold = lower_level - min_break_depth_pct * lower_level / 100
            if candles[n].close < threshold and candles[n - 1].close >= lower_level:
                ev_type = "CHoCH" if os == 1 else "BOS"
                events.append(MarketStructureEvent(
                    type=ev_type, side="bearish",
                    fractal_idx=lower_idx, fractal_level=lower_level,
                    break_idx=n,
                ))
                lower_crossed = True
                os = -1

    return events


def detect_choch(candles: list[Candle], **kwargs) -> list[MarketStructureEvent]:
    """Только CHoCH-события (reversal)."""
    return [e for e in scan_market_structure(candles, **kwargs) if e.type == "CHoCH"]


def detect_bos(candles: list[Candle], **kwargs) -> list[MarketStructureEvent]:
    """Только BOS-события (continuation)."""
    return [e for e in scan_market_structure(candles, **kwargs) if e.type == "BOS"]
