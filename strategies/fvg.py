"""FVG: детектор зон на старшем ТФ. Сигналы генерирует ob1h_core."""
from __future__ import annotations

import pandas as pd

from strategies.base import Zone
from strategies.obx4 import to_ref_format


def detect_zones(df: pd.DataFrame, symbol: str, tf: str) -> list[Zone]:
    """Сырые FVG: high[i-2] < low[i] → LONG, low[i-2] > high[i] → SHORT."""
    ref = to_ref_format(df)
    if ref.empty or len(ref) < 3:
        return []

    zones: list[Zone] = []
    for i in range(2, len(ref)):
        c0 = ref.iloc[i - 2]
        c2 = ref.iloc[i]

        h0 = float(c0["High"])
        l0 = float(c0["Low"])
        h2 = float(c2["High"])
        l2 = float(c2["Low"])
        trigger = pd.to_datetime(c2["Open time"], utc=True)

        if h0 < l2:  # LONG FVG
            zones.append(Zone(
                strategy="FVG",
                symbol=symbol,
                source_tf=tf,
                direction="LONG",
                zone_bottom=h0,
                zone_top=l2,
                trigger_time=trigger,
                meta={"fvg_side": "bullish"},
            ))
        elif l0 > h2:  # SHORT FVG
            zones.append(Zone(
                strategy="FVG",
                symbol=symbol,
                source_tf=tf,
                direction="SHORT",
                zone_bottom=h2,
                zone_top=l0,
                trigger_time=trigger,
                meta={"fvg_side": "bearish"},
            ))
    return zones
