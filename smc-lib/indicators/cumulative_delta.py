"""Cumulative Delta (proxy через Williams Accumulation/Distribution).

Точных bid/ask trades нет (Binance kline data). Используем формулу
Williams A/D (Larry Williams 1972) как proxy:

    delta_i = volume_i * (2*close - high - low) / (high - low)
    cum_delta_i = sum(delta_0..delta_i)

Williams A/D эквивалентен Money Flow Multiplier, но без |close| (т.е.
signed): чем ближе close к high, тем больше "buying pressure" (+volume);
ближе к low — "selling pressure" (-volume); в середине — 0.

Дегенеративные бары (high == low) пропускаем (delta = 0).
"""
from __future__ import annotations


def bar_delta(o: float, h: float, l: float, c: float, v: float) -> float:
    """Delta для одного бара (Williams A/D)."""
    rng = h - l
    if rng <= 0:
        return 0.0
    return v * (2 * c - h - l) / rng


def cumulative_delta(bars: list[tuple[float, float, float, float, float]]) -> list[float]:
    """bars = [(o, h, l, c, v), ...]. Returns cumulative delta series."""
    out = []
    cum = 0.0
    for o, h, l, c, v in bars:
        cum += bar_delta(o, h, l, c, v)
        out.append(cum)
    return out
