"""ASVK Custom RSI.

Reference: ~/traid-bot/research/asvk_rsi/plot_asvk_rsi.py
Canon: ~/traid-bot/vault/knowledge/indicators/asvk-custom-rsi.md

Состав:
1. **rsi** — Wilder RSI (period=14)
2. **ema_3** — Adjusted RSI:
       coef = 1.2 if rsi > 50 else 0.8
       adjusted = rsi² * coef / ema5(rsi)
       ema_3 = ema5(adjusted)
3. **adaptive OB/OS** (rolling 200):
       z = count(ema_3 > 50) на окне 200
       above = (z + 200) / 4
       below = 100 - 49*(z + 200) / 200
       (Pine code: above для ema_3 > 50, below для ema_3 < 50)
4. **NWE Gaussian channel** (bw=8, bar=499, effective ~24-32):
       output[i] = Σ ema_3[i-j] * exp(-j²/(2·bw²)) / Σ exp(...)
       band = ±2 * SMA(|ema_3 - output|, 499)

Зоны:
  red    — ema_3 пробил above (вверх)
  yellow_OB — ema_3 в зоне above..above+band
  neutral
  yellow_OS — ema_3 в зоне below-band..below
  green  — ema_3 пробил below (вниз)

Дивергенции (4 типа) — отдельный helper, опускается в minimal version.
"""
from __future__ import annotations

import math


def rsi_wilder(closes: list[float], period: int = 14) -> list[float | None]:
    """Standard Wilder RSI (alpha = 1/period)."""
    n = len(closes)
    out: list[float | None] = [None] * n
    if n < period + 1:
        return out

    gains = [max(0.0, closes[i] - closes[i - 1]) for i in range(1, n)]
    losses = [max(0.0, closes[i - 1] - closes[i]) for i in range(1, n)]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    if avg_loss == 0:
        rsi = 100.0
    else:
        rs = avg_gain / avg_loss
        rsi = 100 - 100 / (1 + rs)
    out[period] = rsi

    for i in range(period + 1, n):
        avg_gain = ((period - 1) * avg_gain + gains[i - 1]) / period
        avg_loss = ((period - 1) * avg_loss + losses[i - 1]) / period
        if avg_loss == 0:
            out[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            out[i] = 100 - 100 / (1 + rs)
    return out


def _ema(values: list[float | None], period: int) -> list[float | None]:
    """EMA пропускает None в начале."""
    n = len(values)
    out: list[float | None] = [None] * n
    # Найти первый non-None
    first = next((i for i, x in enumerate(values) if x is not None), n)
    if n - first < period:
        return out
    alpha = 2.0 / (period + 1)
    init = sum(values[first:first + period]) / period
    out[first + period - 1] = init
    for i in range(first + period, n):
        if values[i] is None: continue
        out[i] = alpha * values[i] + (1 - alpha) * out[i - 1]
    return out


def adjusted_rsi(closes: list[float], period: int = 14) -> dict:
    """Возвращает dict с rsi, adjusted, ema_3, above, below, nwe_out, nwe_upper, nwe_lower."""
    rsi = rsi_wilder(closes, period)
    n = len(rsi)

    # ema5(rsi)
    rsi_ema5 = _ema(rsi, 5)

    # adjusted = rsi^2 * coef / ema5(rsi)
    adjusted: list[float | None] = [None] * n
    for i in range(n):
        if rsi[i] is None or rsi_ema5[i] is None or rsi_ema5[i] == 0:
            continue
        coef = 1.2 if rsi[i] >= 50 else 0.8
        adjusted[i] = rsi[i] ** 2 * coef / rsi_ema5[i]

    ema_3 = _ema(adjusted, 5)

    # Adaptive OB/OS на rolling 200 баров
    above: list[float | None] = [None] * n
    below: list[float | None] = [None] * n
    win = 200
    for i in range(n):
        lo = max(0, i - win + 1)
        slice_ = [x for x in ema_3[lo:i + 1] if x is not None]
        if len(slice_) < win // 2:
            continue
        z_above = sum(1 for x in slice_ if x > 50)
        z_below = sum(1 for x in slice_ if x < 50)
        above[i] = (z_above + 200) / 4
        below[i] = 100 - 49 * (z_below + 200) / 200

    # NWE Gaussian channel — упрощённый, эффективный lookback 24 бара (3·bw, bw=8)
    bw = 8
    eff_window = 25
    nwe_out: list[float | None] = [None] * n
    for i in range(n):
        lo = max(0, i - eff_window + 1)
        sw_sum = 0.0; w_sum = 0.0
        for j in range(lo, i + 1):
            if ema_3[j] is None: continue
            w = math.exp(-((i - j) ** 2) / (2 * bw ** 2))
            sw_sum += ema_3[j] * w
            w_sum += w
        if w_sum > 0:
            nwe_out[i] = sw_sum / w_sum

    # NWE band = ±2 * SMA(|ema_3 - output|, 499) — упрощаем до окна 60 баров
    band_win = 60
    nwe_upper: list[float | None] = [None] * n
    nwe_lower: list[float | None] = [None] * n
    for i in range(n):
        lo = max(0, i - band_win + 1)
        diffs = []
        for j in range(lo, i + 1):
            if ema_3[j] is None or nwe_out[j] is None: continue
            diffs.append(abs(ema_3[j] - nwe_out[j]))
        if len(diffs) >= band_win // 2:
            sma_diff = sum(diffs) / len(diffs)
            nwe_upper[i] = (nwe_out[i] or 0) + 2 * sma_diff
            nwe_lower[i] = (nwe_out[i] or 0) - 2 * sma_diff

    return {
        "rsi": rsi,
        "ema_3": ema_3,
        "above": above,
        "below": below,
        "nwe_out": nwe_out,
        "nwe_upper": nwe_upper,
        "nwe_lower": nwe_lower,
    }


def asvk_zone(ema_3_val: float | None, above_val: float | None, below_val: float | None,
              nwe_upper_val: float | None, nwe_lower_val: float | None) -> str:
    """Zone classifier по ASVK canon: red / yellow_ob / neutral / yellow_os / green."""
    if ema_3_val is None or above_val is None or below_val is None:
        return "neutral"
    if ema_3_val > above_val:
        return "red"   # OB exceeded (extension вверх)
    if ema_3_val < below_val:
        return "green"  # OS exceeded (extension вниз)
    if nwe_upper_val is not None and ema_3_val > nwe_upper_val:
        return "yellow_ob"
    if nwe_lower_val is not None and ema_3_val < nwe_lower_val:
        return "yellow_os"
    return "neutral"
