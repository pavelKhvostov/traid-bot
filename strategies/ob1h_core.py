"""Общее ядро всех 5 стратегий: поиск первого OB 1h внутри Zone."""
from __future__ import annotations

from typing import Optional

import pandas as pd

from strategies.base import Signal, Zone


def _intersects_zone(low: float, high: float, zb: float, zt: float) -> bool:
    return not (high < zb or low > zt)


def _is_ob1h_long(prev, cur):
    """OB-1h LONG. Возвращает (zone_bottom, zone_top) или None."""
    if (prev["Close"] < prev["Open"]) and (cur["Close"] > prev["Open"]):
        zb = min(float(prev["Low"]), float(cur["Low"]))
        zt = float(prev["Open"])
        return (zb, zt)
    return None


def _is_ob1h_short(prev, cur):
    """OB-1h SHORT. Возвращает (zone_bottom, zone_top) или None."""
    if (prev["Close"] > prev["Open"]) and (cur["Close"] < prev["Open"]):
        zb = float(prev["Open"])
        zt = max(float(prev["High"]), float(cur["High"]))
        return (zb, zt)
    return None


def find_first_ob1h_in_zone(zone: Zone, df_1h: pd.DataFrame) -> Optional[dict]:
    """Первый OB 1h внутри зоны после её trigger_time. None если зона умерла/не сработала."""
    if df_1h is None or df_1h.empty:
        return None

    df = df_1h
    trigger = pd.to_datetime(zone.trigger_time, utc=True)

    # строго после trigger_time
    mask = pd.to_datetime(df["Open time"], utc=True) > trigger
    sub = df[mask].reset_index(drop=True)
    if sub.empty:
        return None

    zb, zt = float(zone.zone_bottom), float(zone.zone_top)
    if zb > zt:
        zb, zt = zt, zb

    # 1) ждём первого возврата в зону
    first_return_idx = None
    for i in range(len(sub)):
        row = sub.iloc[i]
        if _intersects_zone(float(row["Low"]), float(row["High"]), zb, zt):
            first_return_idx = i
            break
    if first_return_idx is None:
        return None

    first_return_time = pd.to_datetime(sub.iloc[first_return_idx]["Open time"], utc=True)

    # 2) начиная с первого возврата ищем OB 1h
    for i in range(first_return_idx + 1, len(sub)):
        prev = sub.iloc[i - 1]
        cur = sub.iloc[i]

        # смерть зоны по close cur
        close_cur = float(cur["Close"])
        if zone.direction == "LONG" and close_cur < zb:
            return None
        if zone.direction == "SHORT" and close_cur > zt:
            return None

        # prev должна пересекать зону
        if not _intersects_zone(float(prev["Low"]), float(prev["High"]), zb, zt):
            continue

        if zone.direction == "LONG" and _is_ob1h_long(prev, cur):
            return {
                "first_return_time": first_return_time,
                "ob1h_prev_time": pd.to_datetime(prev["Open time"], utc=True),
                "ob1h_prev_open": float(prev["Open"]),
                "ob1h_prev_high": float(prev["High"]),
                "ob1h_prev_low": float(prev["Low"]),
                "ob1h_prev_close": float(prev["Close"]),
                "ob1h_cur_time": pd.to_datetime(cur["Open time"], utc=True),
                "ob1h_cur_open": float(cur["Open"]),
                "ob1h_cur_high": float(cur["High"]),
                "ob1h_cur_low": float(cur["Low"]),
                "ob1h_cur_close": close_cur,
            }
        if zone.direction == "SHORT" and _is_ob1h_short(prev, cur):
            return {
                "first_return_time": first_return_time,
                "ob1h_prev_time": pd.to_datetime(prev["Open time"], utc=True),
                "ob1h_prev_open": float(prev["Open"]),
                "ob1h_prev_high": float(prev["High"]),
                "ob1h_prev_low": float(prev["Low"]),
                "ob1h_prev_close": float(prev["Close"]),
                "ob1h_cur_time": pd.to_datetime(cur["Open time"], utc=True),
                "ob1h_cur_open": float(cur["Open"]),
                "ob1h_cur_high": float(cur["High"]),
                "ob1h_cur_low": float(cur["Low"]),
                "ob1h_cur_close": close_cur,
            }

    return None


def scan_zones_to_signals(zones: list[Zone], df_1h: pd.DataFrame) -> list[Signal]:
    """Для каждой зоны ищем первый OB 1h и собираем Signal'ы с дедупом
    перекрывающихся зон на одной OB-свече."""
    raw_signals: list[Signal] = []
    for z in zones:
        hit = find_first_ob1h_in_zone(z, df_1h)
        if hit is None:
            continue
        meta = {
            "source_tf": z.source_tf,
            "zone_bottom": float(z.zone_bottom),
            "zone_top": float(z.zone_top),
            "trigger_time": pd.to_datetime(z.trigger_time, utc=True).isoformat(),
            "first_return_time": hit["first_return_time"].isoformat(),
            "ob1h_prev_time": hit["ob1h_prev_time"].isoformat(),
            "ob1h_cur_time": hit["ob1h_cur_time"].isoformat(),
            "ob1h_cur_close": hit["ob1h_cur_close"],
        }
        # проброс стратегия-специфичных полей (fvg_top/bottom, c1..c5 и т.д.)
        for k, v in (z.meta or {}).items():
            meta.setdefault(k, v)

        raw_signals.append(Signal(
            strategy=z.strategy,
            symbol=z.symbol,
            timeframe="1h",
            direction=z.direction,
            confirm_time=hit["ob1h_cur_time"],
            price=hit["ob1h_cur_close"],
            meta=meta,
        ))

    # Дедуп: (symbol, source_tf, direction, ob1h_cur_time) -> самая узкая зона,
    # tie-break по самому раннему trigger_time.
    best: dict[tuple, Signal] = {}
    for s in raw_signals:
        key = (s.symbol, s.meta["source_tf"], s.direction, s.meta["ob1h_cur_time"])
        cur = best.get(key)
        if cur is None:
            best[key] = s
            continue
        s_width = float(s.meta["zone_top"]) - float(s.meta["zone_bottom"])
        cur_width = float(cur.meta["zone_top"]) - float(cur.meta["zone_bottom"])
        if s_width < cur_width or (
            s_width == cur_width and s.meta["trigger_time"] < cur.meta["trigger_time"]
        ):
            best[key] = s

    deduped = sorted(best.values(), key=lambda x: x.meta["ob1h_cur_time"])

    print(
        f"[OB1H_CORE] scan_zones_to_signals: zones={len(zones)}, "
        f"raw_signals={len(raw_signals)}, after_dedup={len(deduped)}"
    )
    return deduped


# ===== Расширенное подтверждение: OB-1h | FVG-1h | RDRB-1h ===========


def _detect_fvg1h_long(c2, c1, c0):
    h2 = float(c2["High"])
    l0 = float(c0["Low"])
    if h2 < l0:
        return (h2, l0)
    return None


def _detect_fvg1h_short(c2, c1, c0):
    l2 = float(c2["Low"])
    h0 = float(c0["High"])
    if l2 > h0:
        return (h0, l2)
    return None


def _detect_rdrb1h_long(c2, c1, c0):
    h2 = float(c2["High"])
    c1c = float(c1["Close"])
    l0 = float(c0["Low"])
    c0c = float(c0["Close"])
    c0o = float(c0["Open"])
    c2o = float(c2["Open"])
    c2c = float(c2["Close"])
    if c1c > h2 and l0 < h2 and c0c > h2:
        zone_bottom = max(l0, max(c2o, c2c))
        zone_top = min(h2, min(c0o, c0c))
        if zone_top > zone_bottom:
            return (zone_bottom, zone_top)
    return None


def _detect_rdrb1h_short(c2, c1, c0):
    l2 = float(c2["Low"])
    c1c = float(c1["Close"])
    h0 = float(c0["High"])
    c0c = float(c0["Close"])
    c0o = float(c0["Open"])
    c2o = float(c2["Open"])
    c2c = float(c2["Close"])
    if c1c < l2 and h0 > l2 and c0c < l2:
        zone_bottom = max(l2, max(c0o, c0c))
        zone_top = min(h0, min(c2o, c2c))
        if zone_top > zone_bottom:
            return (zone_bottom, zone_top)
    return None


def find_first_confirmation_in_zone(zone: Zone, df_1h: pd.DataFrame) -> Optional[dict]:
    """Возвращает первое подтверждение зоны старшего ТФ из трёх типов
    (OB-1h, FVG-1h, RDRB-1h) или None.

    Идём по 1h-свечам после zone.trigger_time. На каждой свече проверяем три
    паттерна по приоритету: OB-1h → FVG-1h → RDRB-1h. Первый сработавший
    возвращаем, дальше не ищем. Зона "мертва", если close cur вышел за
    границы зоны старшего (LONG: close < zb; SHORT: close > zt).
    """
    if df_1h is None or df_1h.empty:
        return None

    trigger = pd.to_datetime(zone.trigger_time, utc=True)
    mask = pd.to_datetime(df_1h["Open time"], utc=True) > trigger
    sub = df_1h[mask].reset_index(drop=True)
    if len(sub) < 3:
        return None

    zb, zt = float(zone.zone_bottom), float(zone.zone_top)
    if zb > zt:
        zb, zt = zt, zb

    is_long = zone.direction == "LONG"

    for i in range(2, len(sub)):
        c2 = sub.iloc[i - 2]
        c1 = sub.iloc[i - 1]
        c0 = sub.iloc[i]

        close_c = float(c0["Close"])
        if is_long and close_c < zb:
            return None
        if (not is_long) and close_c > zt:
            return None

        cur_time = pd.to_datetime(c0["Open time"], utc=True)

        # ===== OB-1h =====
        ob_zone = _is_ob1h_long(c1, c0) if is_long else _is_ob1h_short(c1, c0)
        if ob_zone is not None:
            ozb, ozt = ob_zone
            if _intersects_zone(ozb, ozt, zb, zt):
                return {
                    "type": "OB-1h",
                    "confirm_time": cur_time,
                    "confirm_close": close_c,
                    "confirm_zone_bottom": ozb,
                    "confirm_zone_top": ozt,
                }

        # ===== FVG-1h =====
        fvg_z = _detect_fvg1h_long(c2, c1, c0) if is_long else _detect_fvg1h_short(c2, c1, c0)
        if fvg_z is not None:
            fzb, fzt = fvg_z
            if _intersects_zone(fzb, fzt, zb, zt):
                return {
                    "type": "FVG-1h",
                    "confirm_time": cur_time,
                    "confirm_close": close_c,
                    "confirm_zone_bottom": fzb,
                    "confirm_zone_top": fzt,
                }

        # ===== RDRB-1h =====
        rdrb_z = _detect_rdrb1h_long(c2, c1, c0) if is_long else _detect_rdrb1h_short(c2, c1, c0)
        if rdrb_z is not None:
            rzb, rzt = rdrb_z
            if _intersects_zone(rzb, rzt, zb, zt):
                return {
                    "type": "RDRB-1h",
                    "confirm_time": cur_time,
                    "confirm_close": close_c,
                    "confirm_zone_bottom": rzb,
                    "confirm_zone_top": rzt,
                }

    return None
