"""VIC_EVOT: подтверждение FVG-15m + LL/HH-фрактал на уровне maxV(D-1)."""
from __future__ import annotations

import pandas as pd

from strategies.base import Level, Signal


def detect_vic_evot(
    df_15m: pd.DataFrame,
    df_1d: pd.DataFrame,
    vic_level: float | None,
    symbol: str,
    last_closed_15m_open_time: pd.Timestamp,
) -> Signal | None:
    """Возвращает Signal, если все условия §3 спеки выполнены, иначе None.

    Контракт каллера:
      - df_15m: 15m свечи; df_15m.iloc[-1] — свеча с open_time
        last_closed_15m_open_time. Минимум 5 свечей.
        Cross-midnight: свечи i-2/i-1 могут быть из ПРЕДЫДУЩЕГО дня —
        фрактал-проверке это не мешает (фрактал ищется среди свечей day D).
      - df_1d:  1d свечи; df_1d.iloc[-1] — последняя ЗАКРЫТАЯ дневная (D-1).
      - vic_level: maxV(D-1), уже посчитан через calculate_vic_d.
      - Колонки lowercase (формат data_manager): open/high/low/close/volume.
      - DatetimeIndex (UTC).

    Логика (§3 уточнённая):
      • FVG-start i фиксирован на n-3 (i+2 = last_closed = n-1).
      • Фрактал f ищется в day D от pos_i и назад до начала дня — берётся
        ближайший к FVG валидный.
      • Структурная инвалидация: между f и last_closed не должно быть
        противоходного фрактала (HH для LONG, LL для SHORT). Если есть —
        разворот уже опровергнут до FVG, сигнал отвергается.
    """
    if vic_level is None:
        return None
    if df_15m is None or len(df_15m) < 5:
        return None
    if df_1d is None or df_1d.empty:
        return None

    close_d_minus_1 = float(df_1d.iloc[-1]["close"])
    if close_d_minus_1 > vic_level:
        direction = "LONG"
    elif close_d_minus_1 < vic_level:
        direction = "SHORT"
    else:
        return None

    n = len(df_15m)
    pos_i = n - 3        # FVG-start
    pos_ip2 = n - 1      # last_closed = i+2
    c_i = df_15m.iloc[pos_i]
    c_ip2 = df_15m.iloc[pos_ip2]

    # Условие 3 (FVG между i и i+2). Не зависит от позиции фрактала.
    # Уровень vic не привязан к FVG — достаточно касания/фрактала по уровню.
    if direction == "LONG":
        high_i = float(c_i["high"])
        low_ip2 = float(c_ip2["low"])
        if not (high_i < low_ip2):
            return None
    else:
        low_i = float(c_i["low"])
        high_ip2 = float(c_ip2["high"])
        if not (low_i > high_ip2):
            return None

    day_start = pd.Timestamp(last_closed_15m_open_time).normalize()

    # Условия 1+2 — найти ближайший к FVG валидный фрактал в day D.
    # Идём от pos_i назад до начала day D. Фрактал должен быть в day D —
    # иначе касание (которое привязано к day D) не может предшествовать ему.
    found_pos_f: int | None = None
    for pos_f in range(pos_i, -1, -1):
        if df_15m.index[pos_f] < day_start:
            break
        if pos_f - 2 < 0 or pos_f + 2 >= n:
            continue
        c_f = df_15m.iloc[pos_f]

        if direction == "LONG":
            low_f = float(c_f["low"])
            if not (low_f < float(df_15m.iloc[pos_f - 2]["low"])
                    and low_f < float(df_15m.iloc[pos_f - 1]["low"])
                    and low_f < float(df_15m.iloc[pos_f + 1]["low"])
                    and low_f < float(df_15m.iloc[pos_f + 2]["low"])):
                continue
            if not (low_f < vic_level):
                continue
            touch_window = df_15m.iloc[: pos_f + 1]
            touch_window = touch_window[touch_window.index >= day_start]
            if touch_window.empty or not bool((touch_window["low"] <= vic_level).any()):
                continue
        else:
            high_f = float(c_f["high"])
            if not (high_f > float(df_15m.iloc[pos_f - 2]["high"])
                    and high_f > float(df_15m.iloc[pos_f - 1]["high"])
                    and high_f > float(df_15m.iloc[pos_f + 1]["high"])
                    and high_f > float(df_15m.iloc[pos_f + 2]["high"])):
                continue
            if not (high_f > vic_level):
                continue
            touch_window = df_15m.iloc[: pos_f + 1]
            touch_window = touch_window[touch_window.index >= day_start]
            if touch_window.empty or not bool((touch_window["high"] >= vic_level).any()):
                continue

        found_pos_f = pos_f
        break

    if found_pos_f is None:
        return None

    # Структурная инвалидация: между f и last_closed не должно быть противохода.
    # Позиция g фрактала-противохода требует g-2 ≥ 0 и g+2 ≤ n-1, т.е. g ≤ n-3.
    for pos_g in range(found_pos_f + 1, n - 2):
        if pos_g - 2 < 0 or pos_g + 2 >= n:
            continue
        c_g = df_15m.iloc[pos_g]

        if direction == "LONG":
            high_g = float(c_g["high"])
            if (high_g > float(df_15m.iloc[pos_g - 2]["high"])
                    and high_g > float(df_15m.iloc[pos_g - 1]["high"])
                    and high_g > float(df_15m.iloc[pos_g + 1]["high"])
                    and high_g > float(df_15m.iloc[pos_g + 2]["high"])):
                return None
        else:
            low_g = float(c_g["low"])
            if (low_g < float(df_15m.iloc[pos_g - 2]["low"])
                    and low_g < float(df_15m.iloc[pos_g - 1]["low"])
                    and low_g < float(df_15m.iloc[pos_g + 1]["low"])
                    and low_g < float(df_15m.iloc[pos_g + 2]["low"])):
                return None

    # Точка входа — limit на 80% FVG, отсчитывая от ближней к рынку границы
    # к дальней. Малый ретрейс в зону.
    #   LONG  FVG = [high(i), low(i+2)]; market выше → entry ближе к low(i+2):
    #     entry = high(i) * 0.2 + low(i+2) * 0.8
    #     (пример: FVG 70000–71000 → entry 70800)
    #   SHORT FVG = [high(i+2), low(i)]; market ниже → entry ближе к high(i+2):
    #     entry = low(i) * 0.2 + high(i+2) * 0.8
    #     (пример: FVG 70000–71000 → entry 70200)
    if direction == "LONG":
        entry_price = float(c_i["high"]) * 0.2 + float(c_ip2["low"]) * 0.8
    else:
        entry_price = float(c_i["low"]) * 0.2 + float(c_ip2["high"]) * 0.8

    day_d_minus_1 = pd.to_datetime(df_1d.index[-1], utc=True).normalize()
    fractal_time = pd.to_datetime(df_15m.index[found_pos_f], utc=True)

    return Signal(
        strategy="VIC_EVOT",
        symbol=symbol,
        timeframe="1d",
        direction=direction,
        confirm_time=last_closed_15m_open_time,
        price=float(entry_price),
        level=Level(price=float(vic_level), day=day_d_minus_1),
        meta={
            "source_tf": "1d",
            "confirm_type": "FVG-15m + LL-фрактал",
            "fractal_time": fractal_time.isoformat(),
            "vic_level": float(vic_level),
            "fractal_offset_k": pos_i - found_pos_f,
        },
    )
