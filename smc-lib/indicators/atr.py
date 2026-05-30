"""ATR (Average True Range, Wilder smoothing).

TR_i = max(high_i - low_i, |high_i - close_{i-1}|, |low_i - close_{i-1}|)
ATR_i = Wilder-smoothing(TR, period) = ((period - 1) * ATR_{i-1} + TR_i) / period
Init: ATR_period = SMA(TR, period) на первых `period` барах.

Output: list[float | None]; None для индексов < period (warmup).
"""
from __future__ import annotations

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from candle import Candle


def atr(candles: list[Candle], period: int = 14) -> list[float | None]:
    n = len(candles)
    if n == 0:
        return []
    tr = [0.0] * n
    tr[0] = candles[0].high - candles[0].low
    for i in range(1, n):
        h, l = candles[i].high, candles[i].low
        prev_c = candles[i - 1].close
        tr[i] = max(h - l, abs(h - prev_c), abs(l - prev_c))

    out: list[float | None] = [None] * n
    if n < period:
        return out
    init = sum(tr[:period]) / period
    out[period - 1] = init
    for i in range(period, n):
        out[i] = ((period - 1) * out[i - 1] + tr[i]) / period
    return out
