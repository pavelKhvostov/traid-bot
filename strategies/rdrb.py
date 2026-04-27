"""RDRB: 3-свечной паттерн, якорная свеча — i-2, зона = её диапазон."""
from __future__ import annotations

import pandas as pd

from strategies.base import Zone
from strategies.obx4 import to_ref_format


def detect_zones(df: pd.DataFrame, symbol: str, tf: str) -> list[Zone]:
    ref = to_ref_format(df)
    if ref.empty or len(ref) < 3:
        return []

    tf_td = pd.Timedelta(tf)
    zones: list[Zone] = []
    for i in range(2, len(ref)):
        a = ref.iloc[i - 2]   # якорная
        m = ref.iloc[i - 1]   # средняя
        c = ref.iloc[i]       # триггер

        a_open = float(a["Open"])
        a_close = float(a["Close"])
        a_high = float(a["High"])
        a_low = float(a["Low"])
        m_close = float(m["Close"])
        c_open = float(c["Open"])
        c_high = float(c["High"])
        c_low = float(c["Low"])
        c_close = float(c["Close"])

        direction: str | None = None
        zone_bottom: float | None = None
        zone_top: float | None = None

        # LONG: prev закрылась выше high якоря, текущая пробила его low-ом вниз,
        # но закрылась снова выше.
        if m_close > a_high and c_low < a_high and c_close > a_high:
            direction = "LONG"
            zone_bottom = max(c_low, max(a_open, a_close))
            zone_top = min(a_high, min(c_open, c_close))
        # SHORT: prev закрылась ниже low якоря, текущая пробила его high-ом вверх,
        # но закрылась снова ниже.
        elif m_close < a_low and c_high > a_low and c_close < a_low:
            direction = "SHORT"
            zone_bottom = max(a_low, max(c_open, c_close))
            zone_top = min(c_high, min(a_open, a_close))

        if direction is None:
            continue
        if zone_top <= zone_bottom:
            continue

        zones.append(Zone(
            strategy="RDRB",
            symbol=symbol,
            source_tf=tf,
            direction=direction,
            zone_bottom=zone_bottom,
            zone_top=zone_top,
            trigger_time=pd.to_datetime(c["Open time"], utc=True) + tf_td,
            meta={
                "anchor_time": pd.to_datetime(a["Open time"], utc=True).isoformat(),
                "anchor_high": a_high,
                "anchor_low": a_low,
                "mid_close": m_close,
                "trigger_close": c_close,
                "trigger_high": c_high,
                "trigger_low": c_low,
            },
        ))
    return zones
