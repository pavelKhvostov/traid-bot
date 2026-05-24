"""Anchored VWAP.

VWAP_t = Σ (typical_price_i * volume_i) / Σ volume_i, для i от anchor_index до t.
typical_price_i = (high_i + low_i + close_i) / 3.

Возвращает list[float | None] длины N (None для индексов < anchor_index).
"""
from __future__ import annotations


def anchored_vwap(
    bars: list[tuple[float, float, float, float, float]],   # (o, h, l, c, v)
    anchor_index: int,
) -> list[float | None]:
    n = len(bars)
    out: list[float | None] = [None] * n
    if not (0 <= anchor_index < n):
        return out
    cum_pv = 0.0
    cum_v = 0.0
    for i in range(anchor_index, n):
        o, h, l, c, v = bars[i]
        tp = (h + l + c) / 3.0
        cum_pv += tp * v
        cum_v += v
        out[i] = (cum_pv / cum_v) if cum_v > 0 else None
    return out
