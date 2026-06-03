"""
Labelling: для каждой active zone определить hit/no-hit на горизонтах 12h и D.

Семантика "hit":
  - Range zone (OB/FVG/RDRB/iRDRB/iFVG/block_orders/RB/ob_liq/marubozu body):
       LONG zone [lo, hi] — hit = bar.low ≤ hi (price wick'ом дотянулась снизу)
       SHORT zone [lo, hi] — hit = bar.high ≥ lo (price wick'ом дотянулась сверху)
       (для зон, где price уже inside — hit считается мгновенным; time_to_hit=0)
  - Fractal high (level L) — hit = bar.high > L (strict, sweep canon)
  - Fractal low  (level L) — hit = bar.low  < L (strict, sweep canon)
  - Marubozu long  (open level O) — hit = bar.low  ≤ O (sweep open)
  - Marubozu short (open level O) — hit = bar.high ≥ O

Hit детектируется на 1m данных (независимо от TF зоны) — позволяет точно измерить time_to_hit.

Output: ZoneLabel с полями:
  - hit_12h, hit_D (bool)
  - time_to_hit_minutes (int | None) — минуты от cut_off до первого hit; None если не задет в обоих горизонтах
  - first_hit_horizon: '12h' | 'D' | None
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from zones import ActiveZone


HORIZON_12H = pd.Timedelta(hours=12)
HORIZON_D = pd.Timedelta(days=1)


@dataclass(frozen=True)
class ZoneLabel:
    zone: ActiveZone
    hit_12h: bool
    hit_D: bool
    time_to_hit_minutes: int | None     # None если не задет в пределах max(12h, D) = 1d
    first_hit_horizon: str | None       # '12h' | 'D' | None
    first_hit_above: bool               # True если цена пошла ВВЕРХ и эта зона выше → hit (HH-кандидат)
    first_hit_below: bool               # True если цена пошла ВНИЗ и эта зона ниже → hit (LL-кандидат)


def _zone_hit_predicate(zone: ActiveZone):
    """Возвращает функцию (bar_high, bar_low) → bool, проверяющую hit для данной зоны."""
    if zone.type == "fractal":
        if zone.direction == "high":
            level = zone.level
            return lambda h, l: h > level
        else:  # 'low'
            level = zone.level
            return lambda h, l: l < level

    if zone.type == "marubozu":
        # Sweep open level
        level = zone.level
        if zone.direction == "long":
            return lambda h, l: l <= level
        else:  # 'short'
            return lambda h, l: h >= level

    # Range zone: LONG support (hit от ниже) / SHORT resistance (hit сверху) /
    # RB top (= short-like, resistance) / RB bottom (= long-like, support) / ob_liq (long/short)
    lo, hi = zone.lo, zone.hi
    direction = zone.direction

    # RB: direction = 'top' (short-like) / 'bottom' (long-like)
    long_like = direction in ("long", "bottom")
    short_like = direction in ("short", "top")

    if long_like:
        return lambda h, l: l <= hi
    if short_like:
        return lambda h, l: h >= lo
    raise ValueError(f"Unknown direction for hit: {direction}")


def label_zone(
    zone: ActiveZone,
    df_1m_future: pd.DataFrame,
    cut_off_ts: pd.Timestamp,
) -> ZoneLabel:
    """
    Пометить одну зону на основе будущих 1m баров.

    df_1m_future: 1m bars с индексом > cut_off_ts (можно срезать заранее или передать полностью)
    cut_off_ts: момент прогноза
    """
    end_ts = cut_off_ts + HORIZON_D
    # Берём только bars > cut_off, ≤ end_ts
    df_h = df_1m_future.loc[(df_1m_future.index > cut_off_ts) & (df_1m_future.index <= end_ts)]

    hit_pred = _zone_hit_predicate(zone)

    time_to_hit_minutes: int | None = None
    if not df_h.empty:
        highs = df_h["high"].to_numpy()
        lows = df_h["low"].to_numpy()
        idx = df_h.index
        for k in range(len(df_h)):
            if hit_pred(highs[k], lows[k]):
                # time от cut_off до open этой 1m свечи
                delta = idx[k] - cut_off_ts
                time_to_hit_minutes = int(delta.total_seconds() // 60)
                break

    hit_12h = time_to_hit_minutes is not None and time_to_hit_minutes <= 12 * 60
    hit_D = time_to_hit_minutes is not None and time_to_hit_minutes <= 24 * 60
    first_hit_horizon = "12h" if hit_12h else ("D" if hit_D else None)

    first_hit_above = bool(hit_D and zone.side == "above")
    first_hit_below = bool(hit_D and zone.side == "below")

    return ZoneLabel(
        zone=zone,
        hit_12h=hit_12h,
        hit_D=hit_D,
        time_to_hit_minutes=time_to_hit_minutes,
        first_hit_horizon=first_hit_horizon,
        first_hit_above=first_hit_above,
        first_hit_below=first_hit_below,
    )


def label_zones(
    zones: list[ActiveZone],
    df_1m: pd.DataFrame,
    cut_off_ts: pd.Timestamp,
) -> list[ZoneLabel]:
    """
    Пометить все зоны для одного cut_off. Дополнительно вычисляет 'first_hit_above_only'
    и 'first_hit_below_only' (только для зоны которая была hit FIRST в своей стороне).

    Returns: список ZoneLabel в том же порядке что zones.
    """
    end_ts = cut_off_ts + HORIZON_D
    df_h = df_1m.loc[(df_1m.index > cut_off_ts) & (df_1m.index <= end_ts)]

    labels = [label_zone(z, df_h, cut_off_ts) for z in zones]

    # Найти "first hit" на каждой стороне
    # above-зоны: цена пошла ВВЕРХ → первая зона выше = HH-target
    # below-зоны: цена пошла ВНИЗ → первая зона ниже = LL-target
    above_hits = [(i, l) for i, l in enumerate(labels) if l.zone.side == "above" and l.time_to_hit_minutes is not None]
    below_hits = [(i, l) for i, l in enumerate(labels) if l.zone.side == "below" and l.time_to_hit_minutes is not None]

    above_hits.sort(key=lambda p: p[1].time_to_hit_minutes)
    below_hits.sort(key=lambda p: p[1].time_to_hit_minutes)

    # Заменим first_hit_above / first_hit_below: оставим True только для первой зоны на каждой стороне
    refined: list[ZoneLabel] = []
    first_above_idx = above_hits[0][0] if above_hits else -1
    first_below_idx = below_hits[0][0] if below_hits else -1
    for i, l in enumerate(labels):
        refined.append(ZoneLabel(
            zone=l.zone,
            hit_12h=l.hit_12h,
            hit_D=l.hit_D,
            time_to_hit_minutes=l.time_to_hit_minutes,
            first_hit_horizon=l.first_hit_horizon,
            first_hit_above=(i == first_above_idx),
            first_hit_below=(i == first_below_idx),
        ))
    return refined
