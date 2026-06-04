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
    """Pine 'ViC ASVK' auto LTF selection — CEIL rule (verified 2026-06-04).

    Pine `timeframe.from_seconds(s)` behavior (consolidated from vault docs +
    user verification):
      target_seconds = max(60, tfC / mlt)
      LTF_minutes = ceil(target_seconds / 60)

    Pine accepts arbitrary integer-minute custom TFs (e.g. 8m, 16m, 32m).

    Examples (all verified):
      12h + mlt=100: target=432s, ceil(432/60)=8m
      12h + mlt=45:  target=960s, ceil(960/60)=16m  ⭐ (12h strategy)
      D + mlt=100:   target=864s, ceil(864/60)=15m
      D + mlt=45:    target=1920s, ceil(1920/60)=32m  ⭐ (D maxV)
      D + mlt=144:   target=600s, ceil(600/60)=10m

    См. memory:
      - feedback-pine-ltf-d-chart-integer-rule.md
      - vault: pine-ltf-12h-chart-ceil-round-up-to-integer-minutes.md
    """
    import math
    tfC = htf_min * 60
    rs_raw = tfC / mlt if mlt > 0 else tfC
    rs = max(60.0, rs_raw)
    target = min(float(tfC), rs)
    return int(math.ceil(target / 60))


def calculate_vic_bar(
    ltf_bars: list[tuple[int, float, float, float, float, float]],   # (ts, o, h, l, c, v) внутри HTF бара
) -> VICBar | None:
    """Вычислить VIC для одного HTF-бара по его LTF-составу.

    Canon (verified 2026-06-04 user values):
      maxV = close LTF-бара с АБСОЛЮТНЫМ макс объёмом (любого направления),
             НЕ "sided/dominant max" как было раньше (bug fixed 2026-06-04).
      bullV / bearV — суммарные объёмы по направлениям (для delta/norm).

    Returns None если нет данных или ни одной направленной LTF-свечи.

    См. memory: feedback-vic-maxv-absolute-not-sided.md
    """
    if not ltf_bars:
        return None
    htf_open_ms = ltf_bars[0][0]
    bullV = 0.0; bearV = 0.0
    # Find ABSOLUTE max-volume bar (any direction)
    max_v = -1.0; max_close = None
    for _, o, _, _, c, v in ltf_bars:
        if v <= 0:
            continue
        if c > o:
            bullV += v
        elif c < o:
            bearV += v
        # Absolute max-vol bar tracking
        if v > max_v:
            max_v = v
            max_close = c

    if max_close is None:
        return None

    maxV = max_close
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
