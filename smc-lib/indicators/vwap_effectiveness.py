"""VWAP Effectiveness Scoring.

Для anchored VWAP (одной линии) и серии баров на конкретном ТФ:

Bar "взаимодействует" с VWAP если low <= vwap <= high.
- **Reaction**: бар взаимодействовал, но close остался на той же стороне,
  с которой бар пришёл (sign(prev_close - prev_vwap) == sign(close - vwap)).
- **Break**: бар взаимодействовал, и close сменил сторону.

Если бар не взаимодействует (полностью выше или ниже VWAP) — не считаем.

Effectiveness per TF:
    interactions = reactions + breaks
    score_tf = reactions / interactions   (0..1, 1 = идеально respected)

Cascade aggregate:
    effectiveness = Σ_tf (score_tf * log(1 + interactions_tf)) / Σ_tf log(1 + interactions_tf)
    т.е. взвешенное среднее по log-числу взаимодействий — больше данных = больше веса.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class TFEffectiveness:
    tf: str
    interactions: int
    reactions: int
    breaks: int
    score: float       # reactions / interactions, или 0 если нет взаимодействий


@dataclass(frozen=True)
class VWAPEffectiveness:
    anchor_ts: int                      # ms; идентификатор VWAP
    per_tf: tuple[TFEffectiveness, ...]
    total_interactions: int
    composite: float                    # weighted avg по log(1 + interactions)


def effectiveness_per_tf(
    tf_name: str,
    bars: list[tuple[float, float, float, float]],   # (o, h, l, c) после anchor
    vwap_values: list[float | None],                  # parallel to bars
) -> TFEffectiveness:
    """Сравнивает каждый бар с VWAP-значением в момент бара.

    Сторона определяется по close:
      side(bar) = 'above' if close > vwap else 'below'.
    """
    interactions = 0; reactions = 0; breaks = 0

    prev_side: str | None = None
    for (o, h, l, c), vw in zip(bars, vwap_values):
        if vw is None:
            prev_side = None
            continue
        touched = (l <= vw <= h)
        side = 'above' if c > vw else ('below' if c < vw else None)

        if touched and side is not None and prev_side is not None:
            interactions += 1
            if side == prev_side:
                reactions += 1
            else:
                breaks += 1
        prev_side = side

    score = (reactions / interactions) if interactions > 0 else 0.0
    return TFEffectiveness(tf=tf_name, interactions=interactions, reactions=reactions, breaks=breaks, score=score)


def composite_effectiveness(
    anchor_ts: int,
    per_tf: list[TFEffectiveness],
) -> VWAPEffectiveness:
    """Aggregate weighted by log(1 + interactions)."""
    total_int = sum(p.interactions for p in per_tf)
    if total_int == 0:
        return VWAPEffectiveness(anchor_ts=anchor_ts, per_tf=tuple(per_tf), total_interactions=0, composite=0.0)
    weights = [math.log(1 + p.interactions) for p in per_tf]
    w_sum = sum(weights)
    if w_sum <= 0:
        return VWAPEffectiveness(anchor_ts=anchor_ts, per_tf=tuple(per_tf), total_interactions=total_int, composite=0.0)
    composite = sum(p.score * w for p, w in zip(per_tf, weights)) / w_sum
    return VWAPEffectiveness(anchor_ts=anchor_ts, per_tf=tuple(per_tf), total_interactions=total_int, composite=composite)
