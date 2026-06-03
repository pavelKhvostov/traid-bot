"""VC (Volume Confirmation). Спецификация: definition.md.

VC — обобщённая концепция подтверждения объёма. Это **предикат** над HTF-зоной,
не зона. HTF-зона (canonically OB) считается «подтверждённой», если внутри неё
присутствует FVG младшего TF того же направления (containment).

Чисто геометрический расчёт; объём не используется (vestigial name).
"""
from __future__ import annotations

import sys
import pathlib
from typing import Iterable

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from elements.ob.code import OB
from elements.fvg.code import FVG


Interval = tuple[float, float]


def _contains(outer: Interval, inner: Interval) -> bool:
    """Inner ⊆ outer (включительно)."""
    return outer[0] <= inner[0] and inner[1] <= outer[1]


def has_vc(ob: OB, fvg: FVG) -> bool:
    """True если FVG подтверждает OB как VC.

    Условия:
    1. ob.direction == fvg.direction
    2. fvg.zone ⊆ ob.zone
    """
    return ob.direction == fvg.direction and _contains(ob.zone, fvg.zone)


def find_vc_confirmations(ob: OB, ltf_fvgs: Iterable[FVG]) -> list[FVG]:
    """Возвращает список LTF FVG, подтверждающих данную OB (VC-предикат)."""
    return [f for f in ltf_fvgs if has_vc(ob, f)]
