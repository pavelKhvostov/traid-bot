"""VIC ASVK — Volume in Candle (Pine ASVK).

Для каждого HTF бара:
  maxV  = close LTF-свечи с макс объёмом среди bull (close>open) или bear (close<open),
          в зависимости от того, у какой группы максимум объёма больше.
  bullV = сумма volume где LTF.close > LTF.open
  bearV = сумма volume где LTF.close < LTF.open
  delta = bullV - bearV
  norm  = delta / total_volume (∈ [-1, +1])

LTF auto-выбор (mlt=100, non-premium):
  tfC = HTF в секундах
  rs_raw = tfC / mlt
  rs = max(60, rs_raw)
  LTF = closest valid TF ≤ min(tfC, rs)

Canonical: ~/traid-bot/vault/knowledge/indicators/vic-asvk-indicator-python.md
Reference impl: ~/traid-bot/vic_levels.py.
"""
from __future__ import annotations

from dataclasses import dataclass


VALID_LTF_SECONDS = [60, 180, 300, 600, 900, 1800, 3600, 7200, 14400, 21600, 28800, 43200, 86400]


@dataclass(frozen=True)
class VICBar:
    htf_open_ms: int
    maxV: float | None      # price (close LTF-бара с макс объёмом)
    bullV: float
    bearV: float
    delta: float
    norm: float             # в [-1, +1]


def auto_ltf_minutes(htf_min: int, mlt: int = 100) -> int:
    """Pine 'ViC ASVK' auto LTF selection (non-premium, mlt=100).

    Pine `timeframe.from_seconds(s)` возвращает наименьший валидный TF ≥ s
    (если точного совпадения нет). Поэтому для D (864 sec → 15m), не 10m.
    """
    tfC = htf_min * 60
    rs_raw = tfC // mlt if mlt > 0 else tfC
    rs = max(60, rs_raw)
    target = min(tfC, rs)
    # Pine: smallest valid TF ≥ target
    for v in VALID_LTF_SECONDS:
        if v >= target:
            return v // 60
    return VALID_LTF_SECONDS[-1] // 60


def calculate_vic_bar(
    ltf_bars: list[tuple[int, float, float, float, float, float]],   # (ts, o, h, l, c, v) внутри HTF бара
) -> VICBar | None:
    """Вычислить VIC для одного HTF-бара по его LTF-составу.

    Returns None если нет данных или ни одной направленной LTF-свечи.
    """
    if not ltf_bars:
        return None
    htf_open_ms = ltf_bars[0][0]
    bullV = 0.0; bearV = 0.0
    max_bull_v = 0.0; max_bull_close = None
    max_bear_v = 0.0; max_bear_close = None
    for _, o, _, _, c, v in ltf_bars:
        if v <= 0:
            continue
        if c > o:
            bullV += v
            if v > max_bull_v:
                max_bull_v = v; max_bull_close = c
        elif c < o:
            bearV += v
            if v > max_bear_v:
                max_bear_v = v; max_bear_close = c

    if max_bull_v == 0 and max_bear_v == 0:
        return None

    if max_bull_v > max_bear_v:
        maxV = max_bull_close
    else:
        maxV = max_bear_close   # canon: при равенстве выбираем bear

    total = bullV + bearV
    delta = bullV - bearV
    norm = (delta / total) if total > 0 else 0.0
    return VICBar(htf_open_ms=htf_open_ms, maxV=maxV, bullV=bullV, bearV=bearV, delta=delta, norm=norm)


def calculate_vic_series(
    ltf_data: list[tuple[int, float, float, float, float, float]],   # 1m или ltf-агрегат
    htf_min: int,
    mlt: int = 100,
) -> list[VICBar]:
    """Расчёт VIC для всех HTF-баров с автоматическим выбором LTF.

    ltf_data: рекомендуется 1m данные (тогда внутренний resample к LTF из auto_ltf).
    """
    ltf_minutes = auto_ltf_minutes(htf_min, mlt)
    ltf_bucket_ms = ltf_minutes * 60_000
    htf_bucket_ms = htf_min * 60_000

    # Group 1m → LTF
    ltf_grouped: dict[int, list] = {}
    for ts, o, h, l, c, v in ltf_data:
        b = ts - (ts % ltf_bucket_ms)
        ltf_grouped.setdefault(b, []).append((ts, o, h, l, c, v))
    ltf_bars = []
    for b in sorted(ltf_grouped):
        rows = ltf_grouped[b]
        rows.sort(key=lambda r: r[0])
        ltf_bars.append((
            b,
            rows[0][1],
            max(r[2] for r in rows),
            min(r[3] for r in rows),
            rows[-1][4],
            sum(r[5] for r in rows),
        ))

    # Group LTF → HTF
    htf_grouped: dict[int, list] = {}
    for ltf in ltf_bars:
        b = ltf[0] - (ltf[0] % htf_bucket_ms)
        htf_grouped.setdefault(b, []).append(ltf)

    out = []
    for htf_open in sorted(htf_grouped):
        r = calculate_vic_bar(htf_grouped[htf_open])
        if r is not None:
            out.append(r)
    return out
