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
    """Возвращает Signal, если все 5 условий §3 спеки выполнены, иначе None.

    Контракт каллера:
      - df_15m: 15m свечи дня D; df_15m.iloc[-1] — свеча с open_time
        last_closed_15m_open_time (т.е. i+2 == последняя закрытая 15m).
      - df_1d:  1d свечи; df_1d.iloc[-1] — последняя ЗАКРЫТАЯ дневная (D-1).
      - vic_level: maxV(D-1), уже посчитан через calculate_vic_d.
      - Колонки lowercase (формат data_manager): open/high/low/close/volume.
      - DatetimeIndex (UTC).
    """
    if vic_level is None:
        return None
    if df_15m is None or len(df_15m) < 5:
        return None
    if df_1d is None or df_1d.empty:
        return None

    # Направление цепочки из close(D-1) vs maxV (§3, "Направление").
    close_d_minus_1 = float(df_1d.iloc[-1]["close"])
    if close_d_minus_1 > vic_level:
        direction = "LONG"
    elif close_d_minus_1 < vic_level:
        direction = "SHORT"
    else:
        return None

    # Позиции i-2, i-1, i, i+1, i+2 — последние 5 свечей df_15m.
    n = len(df_15m)
    pos_im2 = n - 5
    pos_im1 = n - 4
    pos_i = n - 3
    pos_ip1 = n - 2
    pos_ip2 = n - 1

    c_im2 = df_15m.iloc[pos_im2]
    c_im1 = df_15m.iloc[pos_im1]
    c_i = df_15m.iloc[pos_i]
    c_ip1 = df_15m.iloc[pos_ip1]
    c_ip2 = df_15m.iloc[pos_ip2]

    if direction == "LONG":
        # Условие 2: LL-фрактал в i (low(i) строго меньше четырёх соседей)
        # + low(i) ниже уровня maxV.
        low_i = float(c_i["low"])
        if not (low_i < float(c_im2["low"])
                and low_i < float(c_im1["low"])
                and low_i < float(c_ip1["low"])
                and low_i < float(c_ip2["low"])):
            return None
        if not (low_i < vic_level):
            return None

        # Условие 3: FVG между i и i+2 (high(i) < low(i+2)) И FVG над уровнем.
        high_i = float(c_i["high"])
        low_ip2 = float(c_ip2["low"])
        if not (high_i < low_ip2 and low_ip2 > vic_level):
            return None
        entry_price = low_ip2

        # Условие 1: касание уровня (low ≤ maxV) на любой 15m-свече не позже i.
        if not bool((df_15m.iloc[: pos_i + 1]["low"] <= vic_level).any()):
            return None
    else:  # SHORT
        # Условие 2: HH-фрактал в i + high(i) выше уровня.
        high_i = float(c_i["high"])
        if not (high_i > float(c_im2["high"])
                and high_i > float(c_im1["high"])
                and high_i > float(c_ip1["high"])
                and high_i > float(c_ip2["high"])):
            return None
        if not (high_i > vic_level):
            return None

        # Условие 3: FVG между i и i+2 (low(i) > high(i+2)) И FVG под уровнем.
        low_i = float(c_i["low"])
        high_ip2 = float(c_ip2["high"])
        if not (low_i > high_ip2 and high_ip2 < vic_level):
            return None
        entry_price = high_ip2

        # Условие 1: касание уровня (high ≥ maxV) не позже i.
        if not bool((df_15m.iloc[: pos_i + 1]["high"] >= vic_level).any()):
            return None

    # Условия 4 (live, i+2 == last_closed_15m) и 5 (direction match) — на каллере
    # и на ветке direction соответственно: сюда дошли только если всё совпало.

    day_d_minus_1 = pd.to_datetime(df_1d.index[-1], utc=True).normalize()
    fractal_time = pd.to_datetime(df_15m.index[pos_i], utc=True)

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
        },
    )
