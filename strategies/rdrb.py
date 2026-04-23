"""RDRB: 3-свечной паттерн, якорная свеча — i-2, зона = её диапазон."""
from __future__ import annotations

import pandas as pd

from strategies.base import Zone
from strategies.obx4 import to_ref_format


def detect_zones(df: pd.DataFrame, symbol: str, tf: str) -> list[Zone]:
    ref = to_ref_format(df)
    if ref.empty or len(ref) < 3:
        return []

    zones: list[Zone] = []
    for i in range(2, len(ref)):
        a = ref.iloc[i - 2]   # якорная
        m = ref.iloc[i - 1]   # средняя
        c = ref.iloc[i]       # триггер

        a_high = float(a["High"])
        a_low = float(a["Low"])
        m_close = float(m["Close"])
        c_high = float(c["High"])
        c_low = float(c["Low"])
        c_close = float(c["Close"])

        direction: str | None = None
        if c_high > a_low and m_close < a_low and c_close < a_low:
            direction = "SHORT"
        elif c_low < a_high and m_close > a_high and c_close > a_high:
            direction = "LONG"
        if direction is None:
            continue

        zones.append(Zone(
            strategy="RDRB",
            symbol=symbol,
            source_tf=tf,
            direction=direction,
            zone_bottom=a_low,
            zone_top=a_high,
            trigger_time=pd.to_datetime(c["Open time"], utc=True),
            meta={
                "anchor_time": pd.to_datetime(a["Open time"], utc=True).isoformat(),
                "anchor_high": a_high,
                "anchor_low": a_low,
                "mid_close": m_close,
                "trigger_close": c_close,
            },
        ))
    return zones
