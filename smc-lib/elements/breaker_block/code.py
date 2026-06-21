"""Breaker Block. Спецификация: definition.md.

Canon v4 (2026-06-15):
    - Activation: close > prev.high (Bullish) / close < prev.low (Bearish)
      в окне bar 3-6 = post_bars[0..3].
    - После активации zone armed.
    - Wick-fill mitigation от свечи ПОСЛЕ activator:
        Bullish breaker (SHORT resist) — тестируется bar.low (price returns from above):
            bar.low > zone_hi → no interact
            bar.low в зоне   → shrink to (zone_lo, bar.low)
            bar.low ≤ zone_lo → CONSUMED
        Bearish breaker (LONG support) — тестируется bar.high (price returns from below):
            bar.high < zone_lo → no interact
            bar.high в зоне    → shrink to (bar.high, zone_hi)
            bar.high ≥ zone_hi → CONSUMED
"""
from __future__ import annotations

import sys
import pathlib
from dataclasses import dataclass
from typing import Literal, Optional

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from candle import Candle
from elements.ob.code import OB, detect_ob


Direction = Literal["bullish", "bearish"]   # семантика flip'нутого breaker'а
Interval = tuple[float, float]

ACTIVATION_WINDOW_BARS = 4   # bar 3-6 = post_bars[0..3]


@dataclass(frozen=True)
class BreakerBlock:
    direction: Direction          # 'bullish' = SHORT resist, 'bearish' = LONG support
    ob: OB                        # исходный OB
    activated_at_idx: int         # индекс activator в post_bars (0..3)
    initial_zone: Interval        # зона на момент активации
    current_zone: Interval        # после wick-fill shrinks (= initial если 0 shrinks)
    consumed_at_idx: Optional[int]   # индекс bar где CONSUMED (в post_bars), None если жив
    shrink_count: int             # кол-во partial shrinks

    # ─── legacy aliases для совместимости с downstream-код ────────
    @property
    def zone(self) -> Interval:
        """Initial zone (legacy interface — для event_detector / snapshot_builder)."""
        return self.initial_zone

    @property
    def return_idx(self) -> int:
        """Совместимый legacy alias: armed-момент = activated_at_idx."""
        return self.activated_at_idx

    @property
    def bos_idx(self) -> int:
        """Legacy: v4 не имеет отдельного BOS-бара; armed-момент сам по себе."""
        return self.activated_at_idx

    @property
    def is_active(self) -> bool:
        return self.consumed_at_idx is None


def detect_breaker(
    ob: OB,
    post_bars: list[Candle],
    activation_window_bars: int = ACTIVATION_WINDOW_BARS,
) -> Optional[BreakerBlock]:
    """Canon v4 детекция Breaker'а на основе OB + post_bars.

    1. Compute breaker zone (проткнутый фитиль prev).
    2. Scan post_bars[0..activation_window_bars-1] for close-cross активации:
       - Bullish OB → close > prev.high → ARMED Bullish Breaker (SHORT resist)
       - Bearish OB → close < prev.low → ARMED Bearish Breaker (LONG support)
    3. Если в окне нет activator → breaker НЕ формируется (return None).
    4. От свечи ПОСЛЕ activator применить wick-fill mitigation до consume или конца.
    5. Вернуть BreakerBlock со state (active или consumed).
    """
    # Breaker zone (canon 2026-06-14) = проткнутый фитиль prev.
    if ob.direction == "long":
        br_low, br_high = ob.prev.open, ob.prev.high
        threshold = ob.prev.high
        breaker_side: Direction = "bullish"
    else:
        br_low, br_high = ob.prev.low, ob.prev.open
        threshold = ob.prev.low
        breaker_side = "bearish"

    if br_high <= br_low:
        return None    # дегенерат: prev без фитиля с нужной стороны

    # ─── Activation scan в окне bar 3-6 = post[0..3] ────────────
    activated_at = None
    n_window = min(activation_window_bars, len(post_bars))
    for k in range(n_window):
        b = post_bars[k]
        if ob.direction == "long":
            if b.close > threshold:   # close > prev.high
                activated_at = k
                break
        else:
            if b.close < threshold:   # close < prev.low
                activated_at = k
                break

    if activated_at is None:
        return None

    # ─── Wick-fill mitigation от свечи ПОСЛЕ activator ───────────
    zone_lo, zone_hi = br_low, br_high
    consumed_at = None
    shrink_count = 0

    for k in range(activated_at + 1, len(post_bars)):
        b = post_bars[k]
        if breaker_side == "bullish":
            # SHORT resist tested from above by bar.low (price returns down)
            if b.low > zone_hi:
                continue
            if b.low <= zone_lo:
                consumed_at = k
                break
            # partial shrink: zone_hi spускается к bar.low
            zone_hi = b.low
            shrink_count += 1
        else:  # bearish
            # LONG support tested from below by bar.high
            if b.high < zone_lo:
                continue
            if b.high >= zone_hi:
                consumed_at = k
                break
            # partial shrink: zone_lo поднимается к bar.high
            zone_lo = b.high
            shrink_count += 1

    return BreakerBlock(
        direction=breaker_side,
        ob=ob,
        activated_at_idx=activated_at,
        initial_zone=(br_low, br_high),
        current_zone=(zone_lo, zone_hi),
        consumed_at_idx=consumed_at,
        shrink_count=shrink_count,
    )


def scan_breakers(
    candles: list[Candle],
    **params,
) -> list[BreakerBlock]:
    """Скан всей серии: ищет OB-пары → для каждого пытается найти Breaker."""
    results = []
    for i in range(1, len(candles) - 1):
        ob = detect_ob(candles[i - 1], candles[i])
        if ob is None:
            continue
        post = candles[i + 1:]
        br = detect_breaker(ob, post, **params)
        if br is None:
            continue
        # Сохраняем абсолютные индексы: activated_at становится в шкале candles
        results.append(BreakerBlock(
            direction=br.direction,
            ob=br.ob,
            activated_at_idx=br.activated_at_idx + i + 1,
            initial_zone=br.initial_zone,
            current_zone=br.current_zone,
            consumed_at_idx=(br.consumed_at_idx + i + 1
                             if br.consumed_at_idx is not None else None),
            shrink_count=br.shrink_count,
        ))
    return results
