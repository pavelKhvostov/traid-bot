"""OB_HTF: OB-паттерн из 2 свечей на старшем ТФ. Зона = диапазон prev-свечи."""
from __future__ import annotations

import pandas as pd

from strategies.base import Zone
from strategies.obx4 import to_ref_format


def detect_zones(df: pd.DataFrame, symbol: str, tf: str) -> list[Zone]:
    ref = to_ref_format(df)
    if ref.empty or len(ref) < 2:
        return []

    zones: list[Zone] = []
    for i in range(1, len(ref)):
        prev = ref.iloc[i - 1]
        cur = ref.iloc[i]

        po, pc = float(prev["Open"]), float(prev["Close"])
        ph, pl = float(prev["High"]), float(prev["Low"])
        co, cc = float(cur["Open"]), float(cur["Close"])

        direction: str | None = None
        if pc < po and cc > po:
            direction = "LONG"
        elif pc > po and cc < po:
            direction = "SHORT"
        if direction is None:
            continue

        zones.append(Zone(
            strategy="OB_HTF",
            symbol=symbol,
            source_tf=tf,
            direction=direction,
            zone_bottom=pl,
            zone_top=ph,
            trigger_time=pd.to_datetime(cur["Open time"], utc=True),
            meta={
                "prev_open": po, "prev_close": pc,
                "prev_high": ph, "prev_low": pl,
                "cur_open": co, "cur_close": cc,
            },
        ))
    return zones
