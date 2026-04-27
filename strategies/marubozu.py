"""
MARUBOZU: одна свеча без значительных фитилей. Тело >= 95% диапазона.
Зона = тело свечи в направлении свечи.
"""
from __future__ import annotations

import pandas as pd

from strategies.base import Zone
from strategies.obx4 import to_ref_format

BODY_RATIO_MIN = 0.95   # тело >= 95% от (high - low)


def detect_zones(df: pd.DataFrame, symbol: str, tf: str) -> list[Zone]:
    ref = to_ref_format(df)
    if ref.empty or len(ref) < 1:
        return []

    tf_td = pd.Timedelta(tf)
    zones: list[Zone] = []

    for i in range(len(ref)):
        row = ref.iloc[i]
        o = float(row["Open"])
        h = float(row["High"])
        l = float(row["Low"])
        c = float(row["Close"])

        rng = h - l
        if rng <= 0:
            continue
        body = abs(c - o)
        if body / rng < BODY_RATIO_MIN:
            continue

        if c > o:
            direction = "LONG"
            zone_bottom = o
            zone_top = c
        elif c < o:
            direction = "SHORT"
            zone_bottom = c
            zone_top = o
        else:
            continue  # доджи

        if zone_top <= zone_bottom:
            continue

        open_time = pd.to_datetime(row["Open time"], utc=True)
        trigger_time = open_time + tf_td

        zones.append(Zone(
            strategy="MARUBOZU",
            symbol=symbol,
            source_tf=tf,
            direction=direction,
            zone_bottom=zone_bottom,
            zone_top=zone_top,
            trigger_time=trigger_time,
            meta={
                "candle_open": o,
                "candle_high": h,
                "candle_low": l,
                "candle_close": c,
                "body_ratio": body / rng,
            },
        ))

    return zones
