"""VC (Volume Confirmation) predicate. См. vc_concept.md.

Standalone has_vc(ob, fvg) для использования в research-скриптах.
Полная реализация ob_vc element — в code.py этой же папки.
"""
from __future__ import annotations
from typing import Any


def has_vc(ob: Any, fvg: Any) -> bool:
    """VC predicate: подтверждает ли FVG данную OB.

    Variant 1+2 (spatial): FVG.direction == OB.direction AND FVG.zone ⊆ OB.zone
    Variant 3 (temporal): same direction AND OB.tf == FVG.tf ∈ {1h, 2h}
                          AND FVG.c1 = OB.cur + 1
    """
    if ob.direction != fvg.direction:
        return False

    # Variant 1+2: spatial containment FVG.zone ⊆ OB.zone
    ob_lo, ob_hi = ob.zone
    fvg_lo, fvg_hi = fvg.zone
    if fvg_lo >= ob_lo and fvg_hi <= ob_hi:
        return True

    # Variant 3: temporal sequence (same TF, FVG.c1 = OB.cur + 1)
    ob_tf = getattr(ob, "tf", None)
    fvg_tf = getattr(fvg, "tf", None)
    if ob_tf is not None and ob_tf == fvg_tf and ob_tf in ("1h", "2h"):
        ob_cur_close = getattr(ob.cur, "open_time", None)
        fvg_c1_open = getattr(fvg.c1, "open_time", None)
        if ob_cur_close is not None and fvg_c1_open is not None:
            tf_ms = 3_600_000 if ob_tf == "1h" else 7_200_000
            if fvg_c1_open == ob_cur_close + tf_ms:
                return True
    return False


def find_vc_confirmations(ob: Any, fvg_list: list) -> list:
    """Возвращает все FVG из списка, которые подтверждают данный OB."""
    return [fvg for fvg in fvg_list if has_vc(ob, fvg)]
