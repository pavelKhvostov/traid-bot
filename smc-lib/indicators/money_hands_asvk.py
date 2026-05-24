"""Money Hands — ASVK.

Reference: ~/traid-bot/research/money_hands/plot_money_hands.py
Canon: ~/traid-bot/vault/knowledge/indicators/money-hands-asvk.md

Состав:
1. **bw2** (WaveTrend LazyBear, wt2):
       ap = hlc3
       esa = EMA(ap, 9)
       d = EMA(|ap - esa|, 9)
       ci = (ap - esa) / (0.015 * d)
       wt1 = EMA(ci, 12)
       wt2 = SMA(wt1, 4) = bw2
2. **Color state** (bw2 vs SMA(bw2, 14)):
       bw2 > 0  ∧  bw2 >= sma14 → 🟢 (bullish strengthening)
       bw2 > 0  ∧  bw2 <  sma14 → ⚪ (bullish weakening)
       bw2 < 0  ∧  bw2 <= sma14 → 🔴 (bearish strengthening)
       bw2 < 0  ∧  bw2 >  sma14 → ⚪ (bearish weakening)
3. **Money Flow** (HA + SMA60):
       HA candles → raw = (HA_close - HA_open)/(HA_high - HA_low) * 200
       MF = SMA(raw, 60) - 2.25
4. **Двойной Stochastic**:
       rsiMod    = SMA(Stoch(close, high, low, 40), 2)
       stcRsiMod = SMA(Stoch(close, high, low, 81), 2)

OB/OS зоны: ±60, ±75.
"""
from __future__ import annotations


def _ema(values: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) < n:
        return out
    alpha = 2.0 / (n + 1)
    init = sum(values[:n]) / n
    out[n - 1] = init
    for i in range(n, len(values)):
        out[i] = alpha * values[i] + (1 - alpha) * out[i - 1]
    return out


def _sma(values: list[float | None], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    buf = []
    for i, v in enumerate(values):
        if v is None:
            buf = []  # сбрасываем буфер на None
            continue
        buf.append(v)
        if len(buf) > n:
            buf.pop(0)
        if len(buf) == n:
            out[i] = sum(buf) / n
    return out


def money_hands(
    bars: list[tuple[float, float, float, float, float]],   # (o, h, l, c, v) — v unused
) -> dict:
    """Полный расчёт Money Hands: bw2, color, MF, stochastics."""
    n = len(bars)
    if n == 0:
        return {"bw2": [], "color": [], "mf": [], "rsi_mod": [], "stc_rsi_mod": []}

    closes = [b[3] for b in bars]
    highs = [b[1] for b in bars]
    lows = [b[2] for b in bars]
    aps = [(highs[i] + lows[i] + closes[i]) / 3.0 for i in range(n)]

    # WaveTrend
    esa = _ema(aps, 9)
    abs_diff = [(abs(aps[i] - esa[i]) if esa[i] is not None else None) for i in range(n)]
    d = _ema([(x if x is not None else 0.0) for x in abs_diff], 9)
    # Маскируем d там где abs_diff было None
    for i in range(n):
        if abs_diff[i] is None:
            d[i] = None
    ci: list[float | None] = [None] * n
    for i in range(n):
        if esa[i] is None or d[i] is None or d[i] == 0:
            continue
        ci[i] = (aps[i] - esa[i]) / (0.015 * d[i])
    wt1 = _ema([(x if x is not None else 0.0) for x in ci], 12)
    for i in range(n):
        if ci[i] is None: wt1[i] = None
    bw2 = _sma(wt1, 4)

    # Color state machine
    bw2_sma14 = _sma(bw2, 14)
    color: list[str | None] = [None] * n
    for i in range(n):
        if bw2[i] is None or bw2_sma14[i] is None:
            continue
        if bw2[i] > 0:
            color[i] = "green" if bw2[i] >= bw2_sma14[i] else "white_weak_bull"
        elif bw2[i] < 0:
            color[i] = "red" if bw2[i] <= bw2_sma14[i] else "white_weak_bear"
        else:
            color[i] = "neutral"

    # Money Flow (HA)
    ha_open = [0.0] * n; ha_close = [0.0] * n; ha_high = [0.0] * n; ha_low = [0.0] * n
    if n > 0:
        o0, h0, l0, c0, _ = bars[0]
        ha_close[0] = (o0 + h0 + l0 + c0) / 4
        ha_open[0] = (o0 + c0) / 2
        ha_high[0] = max(h0, ha_open[0], ha_close[0])
        ha_low[0] = min(l0, ha_open[0], ha_close[0])
        for i in range(1, n):
            oi, hi, li, ci_, _ = bars[i]
            ha_close[i] = (oi + hi + li + ci_) / 4
            ha_open[i] = (ha_open[i - 1] + ha_close[i - 1]) / 2
            ha_high[i] = max(hi, ha_open[i], ha_close[i])
            ha_low[i] = min(li, ha_open[i], ha_close[i])

    raw: list[float | None] = [None] * n
    for i in range(n):
        rng = ha_high[i] - ha_low[i]
        raw[i] = ((ha_close[i] - ha_open[i]) / rng * 200) if rng > 0 else 0.0
    mf_sma = _sma(raw, 60)
    mf = [(x - 2.25) if x is not None else None for x in mf_sma]

    # Двойной Stochastic
    def stoch(close: list[float], high: list[float], low: list[float], window: int) -> list[float | None]:
        out: list[float | None] = [None] * n
        for i in range(window - 1, n):
            hh = max(high[i - window + 1:i + 1])
            ll = min(low[i - window + 1:i + 1])
            if hh > ll:
                out[i] = 100 * (close[i] - ll) / (hh - ll)
            else:
                out[i] = 50.0
        return out

    rsi_mod = _sma(stoch(closes, highs, lows, 40), 2)
    stc_rsi_mod = _sma(stoch(closes, highs, lows, 81), 2)

    return {
        "bw2": bw2,
        "color": color,
        "mf": mf,
        "rsi_mod": rsi_mod,
        "stc_rsi_mod": stc_rsi_mod,
    }
