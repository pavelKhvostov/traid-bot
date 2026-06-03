"""OB с имбалансом (ob_vc) — зональная реализация VC (Volume Confirmation).

Canon: see definition.md.

Композит: HTF OB + LTF FVG того же направления, частично пересекающий drop area
(LONG) / rally area (SHORT). FVG.zone лежит между low_ob_vc (drop area low) и
первым LTF Williams N=2 фракталом вне drop/rally area.

Принципы (refined 2026-05-29):
  - Сонаправленность (первый и обязательный фильтр)
  - HTF/LTF пары — фиксированная таблица (см. HTF_TO_LTF)
  - Spatial overlap с drop/rally area (обязательно хотя бы частично)
  - Spatial range FVG.zone ⊆ [low_ob_vc, first_opposite_fractal_level]
  - Time-causality не проверяется
"""
from __future__ import annotations

import sys
import pathlib
from dataclasses import dataclass, field
from typing import Literal, Sequence

import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from candle import Candle
from elements.ob.code import OB
from elements.fvg.code import FVG


# LTF duration in milliseconds — для temporal upper-bound (Williams N+1 bars after center).
LTF_DURATION_MS: dict[str, int] = {
    "15m": 15 * 60 * 1000,
    "20m": 20 * 60 * 1000,
    "90m": 90 * 60 * 1000,
    "1h": 60 * 60 * 1000,
    "2h": 2 * 60 * 60 * 1000,
    "4h": 4 * 60 * 60 * 1000,
    "6h": 6 * 60 * 60 * 1000,
}


Direction = Literal["long", "short"]
Interval = tuple[float, float]


# HTF → tuple of allowed LTF strings. Канон 2026-05-29.
HTF_TO_LTF: dict[str, tuple[str, ...]] = {
    "3d": ("12h",),
    "2d": ("12h",),
    "1d": ("4h", "6h"),
    "12h": ("4h", "6h"),
    "6h": ("1h", "90m", "2h"),
    "4h": ("1h", "90m", "2h"),
    "2h": ("15m", "20m"),
    "1h": ("15m", "20m"),
}


@dataclass(frozen=True)
class OBVC:
    """Композитный элемент OB+FVG (зональная реализация VC)."""
    direction: Direction
    htf: str
    ob: OB
    zone: Interval                  # = ob.zone (full ZoI, см. canon ob/definition.md)
    drop_or_rally_area: Interval    # drop area (LONG) или rally area (SHORT)
    low_ob_vc: float                # = drop area low (LONG) / rally area high (SHORT)
    first_opposite_fractal_level: float  # high первого FH вне drop area (LONG) / low первого FL вне rally area (SHORT)
    allowed_fvg_range: Interval     # [low_ob_vc, first_opp_fractal_level] LONG / [first_opp_fractal_level, high_ob_vc] SHORT
    fvg_components: tuple[tuple[str, FVG], ...]  # ((ltf_tf, fvg), ...) — все валидирующие LTF FVG


def _has_breaker(ob: OB) -> bool:
    """Breaker block exists only при полном пробое prev candle (2026-05-29 canon)."""
    if ob.direction == "long":
        return ob.cur.close > ob.prev.high
    return ob.cur.close < ob.prev.low


def _drop_or_rally_area(ob: OB) -> Interval:
    """Drop area (LONG) или rally area (SHORT) — институциональная подзона OB."""
    if ob.direction == "long":
        return (min(ob.prev.low, ob.cur.low), ob.prev.open)
    return (ob.prev.open, max(ob.prev.high, ob.cur.high))


def _intervals_overlap(a: Interval, b: Interval) -> bool:
    return max(a[0], b[0]) <= min(a[1], b[1])


def _interval_contained(inner: Interval, outer: Interval) -> bool:
    return inner[0] >= outer[0] and inner[1] <= outer[1]


def _first_williams_fh_above(ltf_bars: Sequence[Candle], threshold: float, n: int = 2) -> Candle | None:
    """Найти первый Williams N=n FH (центральная high строго > всех 2n соседей)
    с center.high > threshold. ltf_bars предполагается отфильтрованным по
    after-OB-cur-open временной отметке.
    """
    if len(ltf_bars) < 2 * n + 1:
        return None
    for i in range(n, len(ltf_bars) - n):
        center = ltf_bars[i]
        if center.high <= threshold:
            continue
        neighbors = list(ltf_bars[i - n:i]) + list(ltf_bars[i + 1:i + n + 1])
        if all(center.high > nb.high for nb in neighbors):
            return center
    return None


def _first_williams_fl_below(ltf_bars: Sequence[Candle], threshold: float, n: int = 2) -> Candle | None:
    """Зеркало для SHORT: первый FL с center.low < threshold."""
    if len(ltf_bars) < 2 * n + 1:
        return None
    for i in range(n, len(ltf_bars) - n):
        center = ltf_bars[i]
        if center.low >= threshold:
            continue
        neighbors = list(ltf_bars[i - n:i]) + list(ltf_bars[i + 1:i + n + 1])
        if all(center.low < nb.low for nb in neighbors):
            return center
    return None


def detect_ob_vc(
    ob: OB,
    htf: str,
    ltf_bars_after_ob: dict[str, Sequence[Candle]],
    ltf_fvgs: dict[str, Sequence[FVG]],
    n_fractal: int = 2,
    df_1m: pd.DataFrame | None = None,
) -> OBVC | None:
    """Возвращает OBVC если найдена хотя бы одна валидирующая LTF FVG, иначе None.

    Args:
        ob: HTF OB.
        htf: TF-строка HTF OB ('4h', '6h', '1d', etc).
        ltf_bars_after_ob: dict {ltf_tf: list[Candle]} — LTF OHLC ПОСЛЕ открытия
            ob.cur (включая cur). Нужны для детекции first opposite fractal.
        ltf_fvgs: dict {ltf_tf: list[FVG]} — все LTF FVG того же направления.
        n_fractal: Williams N для фракталов (canon = 2).
        df_1m: 1m OHLC DataFrame (DatetimeIndex UTC) для проверки условия #9
            (FVG не consumed к моменту first FH confirmation). Если None — #9
            не проверяется (только #1-#8). Production-канон требует df_1m.

    Returns:
        OBVC при наличии ≥1 валидирующего FVG, иначе None.

    Canon (см. definition.md): conditions #1-#9.
    """
    htf_norm = htf.lower()
    if htf_norm not in HTF_TO_LTF:
        return None
    allowed_ltfs = HTF_TO_LTF[htf_norm]

    drop_area = _drop_or_rally_area(ob)

    if ob.direction == "long":
        low_ob_vc = drop_area[0]
        drop_hi = drop_area[1]

        # Найти first FH вне drop area на каждом LTF
        first_fractals: dict[str, Candle] = {}
        for ltf in allowed_ltfs:
            if ltf not in ltf_bars_after_ob:
                continue
            fh = _first_williams_fh_above(list(ltf_bars_after_ob[ltf]), drop_hi, n=n_fractal)
            if fh is not None:
                first_fractals[ltf] = fh
        if not first_fractals:
            return None

        # Собрать валидирующие FVG
        ob_cur_open_ms = ob.cur.open_time or 0
        components: list[tuple[str, FVG]] = []
        best_upper_per_ltf: dict[str, float] = {ltf: fh.high for ltf, fh in first_fractals.items()}
        for ltf in allowed_ltfs:
            if ltf not in first_fractals:
                continue
            upper = best_upper_per_ltf[ltf]
            allowed_range = (low_ob_vc, upper)
            ltf_ms = LTF_DURATION_MS.get(ltf)
            if ltf_ms is None:
                continue
            # Условие #8: temporal upper-bound = first FH confirmation = center.open + (N+1)*LTF
            fh_center = first_fractals[ltf]
            fh_confirm_ms = (fh_center.open_time or 0) + (n_fractal + 1) * ltf_ms
            for fvg in ltf_fvgs.get(ltf, ()):
                if fvg.direction != "long":
                    continue
                # Условие #7: FVG не из прошлого
                if (fvg.c1.open_time or 0) < ob_cur_open_ms:
                    continue
                # Условие #8: FVG закрывается до подтверждения first FH
                fvg_close_ms = (fvg.c3.open_time or 0) + ltf_ms
                if fvg_close_ms > fh_confirm_ms:
                    continue
                if not _intervals_overlap(fvg.zone, drop_area):
                    continue
                if not _interval_contained(fvg.zone, allowed_range):
                    continue
                # Условие #9: FVG не должна быть consumed к моменту FH confirmation
                if df_1m is not None:
                    window_start = pd.Timestamp(fvg_close_ms, unit="ms", tz="UTC")
                    window_end = pd.Timestamp(fh_confirm_ms, unit="ms", tz="UTC")
                    window = df_1m.loc[(df_1m.index >= window_start) & (df_1m.index <= window_end)]
                    if not window.empty:
                        if float(window["low"].min()) <= fvg.zone[0]:
                            # FVG полностью consumed → пропускаем
                            continue
                components.append((ltf, fvg))

        if not components:
            return None

        # Для общего allowed_fvg_range берём минимальный upper по всем LTF
        global_upper = min(best_upper_per_ltf.values())
        return OBVC(
            direction="long",
            htf=htf_norm,
            ob=ob,
            zone=ob.zone,
            drop_or_rally_area=drop_area,
            low_ob_vc=low_ob_vc,
            first_opposite_fractal_level=global_upper,
            allowed_fvg_range=(low_ob_vc, global_upper),
            fvg_components=tuple(components),
        )

    # SHORT
    rally_lo = drop_area[0]
    high_ob_vc = drop_area[1]

    first_fractals_short: dict[str, Candle] = {}
    for ltf in allowed_ltfs:
        if ltf not in ltf_bars_after_ob:
            continue
        fl = _first_williams_fl_below(list(ltf_bars_after_ob[ltf]), rally_lo, n=n_fractal)
        if fl is not None:
            first_fractals_short[ltf] = fl
    if not first_fractals_short:
        return None

    ob_cur_open_ms = ob.cur.open_time or 0
    components_s: list[tuple[str, FVG]] = []
    best_lower_per_ltf: dict[str, float] = {ltf: fl.low for ltf, fl in first_fractals_short.items()}
    for ltf in allowed_ltfs:
        if ltf not in first_fractals_short:
            continue
        lower = best_lower_per_ltf[ltf]
        allowed_range = (lower, high_ob_vc)
        ltf_ms = LTF_DURATION_MS.get(ltf)
        if ltf_ms is None:
            continue
        # Условие #8: temporal upper-bound = first FL confirmation = center.open + (N+1)*LTF
        fl_center = first_fractals_short[ltf]
        fl_confirm_ms = (fl_center.open_time or 0) + (n_fractal + 1) * ltf_ms
        for fvg in ltf_fvgs.get(ltf, ()):
            if fvg.direction != "short":
                continue
            # Условие #7: FVG не из прошлого
            if (fvg.c1.open_time or 0) < ob_cur_open_ms:
                continue
            # Условие #8: FVG закрывается до подтверждения first FL
            fvg_close_ms = (fvg.c3.open_time or 0) + ltf_ms
            if fvg_close_ms > fl_confirm_ms:
                continue
            if not _intervals_overlap(fvg.zone, drop_area):
                continue
            if not _interval_contained(fvg.zone, allowed_range):
                continue
            # Условие #9: SHORT FVG не должна быть consumed к моменту FL confirmation
            if df_1m is not None:
                window_start = pd.Timestamp(fvg_close_ms, unit="ms", tz="UTC")
                window_end = pd.Timestamp(fl_confirm_ms, unit="ms", tz="UTC")
                window = df_1m.loc[(df_1m.index >= window_start) & (df_1m.index <= window_end)]
                if not window.empty:
                    if float(window["high"].max()) >= fvg.zone[1]:
                        # SHORT FVG consumed (high прокусил верх) → пропускаем
                        continue
            components_s.append((ltf, fvg))

    if not components_s:
        return None

    global_lower = max(best_lower_per_ltf.values())
    return OBVC(
        direction="short",
        htf=htf_norm,
        ob=ob,
        zone=ob.zone,
        drop_or_rally_area=drop_area,
        low_ob_vc=high_ob_vc,  # для SHORT семантически "high"; имя поля наследие LONG-case
        first_opposite_fractal_level=global_lower,
        allowed_fvg_range=(global_lower, high_ob_vc),
        fvg_components=tuple(components_s),
    )
