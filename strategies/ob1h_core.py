"""Общее ядро всех 5 стратегий: поиск первого OB 1h внутри Zone."""
from __future__ import annotations

from typing import Optional

import pandas as pd

from strategies.base import Signal, Zone


def _intersects_zone(low: float, high: float, zb: float, zt: float) -> bool:
    return not (high < zb or low > zt)


def _is_ob1h_long(prev, cur) -> bool:
    # prev — красная, cur закрылся выше открытия prev
    return (prev["Close"] < prev["Open"]) and (cur["Close"] > prev["Open"])


def _is_ob1h_short(prev, cur) -> bool:
    # prev — зелёная, cur закрылся ниже открытия prev
    return (prev["Close"] > prev["Open"]) and (cur["Close"] < prev["Open"])


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
