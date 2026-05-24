"""EMA (Exponential Moving Average, adjust=False — как в Pine).

EMA_0 = SMA(values, period) на первых `period` барах.
EMA_i = alpha * values_i + (1 - alpha) * EMA_{i-1}, alpha = 2 / (period + 1).

Output: list[float | None]; None для индексов < period - 1.
"""
from __future__ import annotations


def ema(values: list[float], period: int) -> list[float | None]:
    n = len(values)
    if n == 0 or period < 1:
        return [None] * n
    out: list[float | None] = [None] * n
    if n < period:
        return out
    alpha = 2.0 / (period + 1)
    init = sum(values[:period]) / period
    out[period - 1] = init
    for i in range(period, n):
        out[i] = alpha * values[i] + (1 - alpha) * out[i - 1]
    return out


def ema_200_close(candles_close: list[float]) -> list[float | None]:
    """Удобный alias для EMA-200 на close."""
    return ema(candles_close, 200)
