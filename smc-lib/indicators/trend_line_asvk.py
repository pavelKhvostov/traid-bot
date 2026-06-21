"""ASVK Trend Line — Hull MA variants (HMA / EHMA / THMA).

Reference: ~/traid-bot/research/asvk_trend_line/plot_asvk_trend_line.py
Canon: ~/traid-bot/vault/knowledge/indicators/asvk-trend-line-hull.md

Каноничные длины (см. Правило 7 в rules.md): 78 и 200.
Helpers: trend_line_hma_78(closes), trend_line_hma_200(closes).

Default: length=49, lengthMult=1.6 → effective length = int(49*1.6) = 78.
mode = 'Hma' (default), 'Ehma', 'Thma'.

HMA(src, n) = WMA(2*WMA(src, n/2) − WMA(src, n), round(√n))
EHMA(src, n) = EMA(2*EMA(src, n/2) − EMA(src, n), round(√n))
THMA(src, n/2)  — для mode=Thma: внутренняя длина = len/2; формула:
   WMA(3*WMA(src, n/3) − WMA(src, n/2) − WMA(src, n), n)

Output:
  HULL: list[float | None] — Hull MA
  SHULL: list[float | None] — Hull MA сдвинут на 2 бара назад (для color/band)
  color: list['up' | 'down' | None] — close > SHULL → up
"""
from __future__ import annotations

import math


def wma(values: list[float], n: int) -> list[float | None]:
    """Weighted MA с линейными весами (1, 2, ..., n)."""
    out: list[float | None] = [None] * len(values)
    if n < 1 or len(values) < n:
        return out
    weight_sum = n * (n + 1) / 2
    for i in range(n - 1, len(values)):
        s = 0.0
        for j in range(n):
            s += values[i - n + 1 + j] * (j + 1)
        out[i] = s / weight_sum
    return out


def ema_series(values: list[float], n: int) -> list[float | None]:
    """EMA как в Pine (adjust=False)."""
    from indicators.ema import ema
    return ema(values, n)


def _sub(a: list[float | None], b: list[float | None], scale_a: float = 1.0, scale_b: float = 1.0) -> list[float | None]:
    out = [None] * len(a)
    for i in range(len(a)):
        if a[i] is None or b[i] is None:
            continue
        out[i] = a[i] * scale_a - b[i] * scale_b
    return out


def _sub3(a: list[float | None], b: list[float | None], c: list[float | None],
          sa: float = 1.0, sb: float = 1.0, sc: float = 1.0) -> list[float | None]:
    out = [None] * len(a)
    for i in range(len(a)):
        if a[i] is None or b[i] is None or c[i] is None:
            continue
        out[i] = a[i] * sa - b[i] * sb - c[i] * sc
    return out


def hma(values: list[float], n: int) -> list[float | None]:
    """Hull MA."""
    half = max(1, n // 2)
    sqrt_n = max(1, int(round(math.sqrt(n))))
    w_half = wma(values, half)
    w_full = wma(values, n)
    diff = _sub(w_half, w_full, 2.0, 1.0)
    # Заполним None в diff нулями для wma input (но wma пропустит начало по None - проверяем)
    # Чтобы wma работала, нужны валидные числа подряд начиная с какого-то индекса.
    cleaned = [(x if x is not None else 0.0) for x in diff]
    # Найдём первый non-None
    first_valid = next((i for i, x in enumerate(diff) if x is not None), len(diff))
    res = wma(cleaned, sqrt_n)
    # Стереть результаты до first_valid + sqrt_n - 1
    cutoff = first_valid + sqrt_n - 1
    return [(res[i] if i >= cutoff else None) for i in range(len(values))]


def ehma(values: list[float], n: int) -> list[float | None]:
    """EHMA (Exponential Hull)."""
    half = max(1, n // 2)
    sqrt_n = max(1, int(round(math.sqrt(n))))
    e_half = ema_series(values, half)
    e_full = ema_series(values, n)
    diff = _sub(e_half, e_full, 2.0, 1.0)
    cleaned = [(x if x is not None else 0.0) for x in diff]
    first_valid = next((i for i, x in enumerate(diff) if x is not None), len(diff))
    res = ema_series(cleaned, sqrt_n)
    cutoff = first_valid + sqrt_n - 1
    return [(res[i] if i >= cutoff else None) for i in range(len(values))]


def thma(values: list[float], n: int) -> list[float | None]:
    """THMA, использует внутренне len/2 как 'n' формулы."""
    inner = max(1, n // 2)
    third = max(1, inner // 3)
    half_inner = max(1, inner // 2)
    w_third = wma(values, third)
    w_half = wma(values, half_inner)
    w_full = wma(values, inner)
    diff = _sub3(w_third, w_half, w_full, 3.0, 1.0, 1.0)
    cleaned = [(x if x is not None else 0.0) for x in diff]
    first_valid = next((i for i, x in enumerate(diff) if x is not None), len(diff))
    res = wma(cleaned, inner)
    cutoff = first_valid + inner - 1
    return [(res[i] if i >= cutoff else None) for i in range(len(values))]


def trend_line_asvk(
    closes: list[float],
    length: int = 49,
    length_mult: float = 1.6,
    mode: str = "Hma",
) -> dict:
    """Returns dict with HULL, SHULL (shifted -2), color list ('up'/'down'/None)."""
    effective_len = int(length * length_mult)
    if mode == "Hma":
        hull = hma(closes, effective_len)
    elif mode == "Ehma":
        hull = ehma(closes, effective_len)
    elif mode == "Thma":
        hull = thma(closes, effective_len)
    else:
        raise ValueError(f"Unknown mode: {mode}")

    shull: list[float | None] = [None] * len(closes)
    for i in range(2, len(closes)):
        shull[i] = hull[i - 2]

    color: list[str | None] = [None] * len(closes)
    for i in range(len(closes)):
        if shull[i] is None:
            continue
        color[i] = "up" if closes[i] > shull[i] else "down"

    return {"mhull": hull, "shull": shull, "color": color, "effective_length": effective_len, "mode": mode}


# ── Каноничные helper'ы (Правило 7) ─────────────────────────────────────────

def trend_line_hma_78(closes: list[float]) -> dict:
    """TrendLine ASVK с канонической length=78 (Hma mode).

    Default основной TrendLine: применяется на 12h и D в проекте Pred-12h.
    Pine эквивалент: length=49, lengthMult=1.6 → effective=78.
    """
    return trend_line_asvk(closes, length=78, length_mult=1.0, mode="Hma")


def trend_line_hma_200(closes: list[float]) -> dict:
    """TrendLine ASVK с канонической length=200 (Hma mode).

    Медленный TrendLine: используется на D как HTF-уровень.
    """
    return trend_line_asvk(closes, length=200, length_mult=1.0, mode="Hma")
