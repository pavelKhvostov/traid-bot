"""
HAMMER: молот (классический + перевёрнутый), который
одновременно является фракталом и образует OB-связку с следующей свечой.
"""
from __future__ import annotations

import pandas as pd

from strategies.base import Zone
from strategies.obx4 import to_ref_format

BODY_RATIO_MAX = 0.30
WICK_TO_BODY_MIN = 2.0
SHORT_WICK_RATIO_MAX = 0.30  # короткий фитиль ≤ 30% длины тела


def _is_ll_fractal(ref: pd.DataFrame, i: int) -> bool:
    if i < 2 or i >= len(ref) - 2:
        return False
    lo = float(ref.iloc[i]["Low"])
    return all(lo < float(ref.iloc[k]["Low"])
               for k in (i - 2, i - 1, i + 1, i + 2))


def _is_hh_fractal(ref: pd.DataFrame, i: int) -> bool:
    if i < 2 or i >= len(ref) - 2:
        return False
    hi = float(ref.iloc[i]["High"])
    return all(hi > float(ref.iloc[k]["High"])
               for k in (i - 2, i - 1, i + 1, i + 2))


def detect_zones(df: pd.DataFrame, symbol: str, tf: str) -> list[Zone]:
    ref = to_ref_format(df)
    n = len(ref)
    if n < 5:
        return []

    tf_td = pd.Timedelta(tf)
    zones: list[Zone] = []

    # Нужны i+1 и i±2 → диапазон от 2 до n-3 (i+2 валиден для фрактала,
    # i+1 валиден для OB)
    for i in range(2, n - 2):
        cur = ref.iloc[i]      # молот
        nxt = ref.iloc[i + 1]  # следующая (для OB)

        o = float(cur["Open"])
        h = float(cur["High"])
        l = float(cur["Low"])
        c = float(cur["Close"])

        rng = h - l
        if rng <= 0:
            continue
        body = abs(c - o)
        if body <= 0:
            continue  # доджи — игнорируем

        body_ratio = body / rng
        if body_ratio > BODY_RATIO_MAX:
            continue

        body_top = max(o, c)
        body_bottom = min(o, c)
        upper_wick = h - body_top
        lower_wick = body_bottom - l

        nxt_open = float(nxt["Open"])
        nxt_close = float(nxt["Close"])

        # ---- LONG HAMMER ----
        if c < o:  # красная свеча
            if (lower_wick >= WICK_TO_BODY_MIN * body and
                upper_wick <= SHORT_WICK_RATIO_MAX * body and
                _is_ll_fractal(ref, i) and
                nxt_close > o):

                zone_bottom = min(l, float(nxt["Low"]))
                zone_top = o

                if zone_top > zone_bottom:
                    open_time_nxt = pd.to_datetime(nxt["Open time"], utc=True)
                    zones.append(Zone(
                        strategy="HAMMER",
                        symbol=symbol,
                        source_tf=tf,
                        direction="LONG",
                        zone_bottom=zone_bottom,
                        zone_top=zone_top,
                        trigger_time=open_time_nxt + tf_td,
                        meta={
                            "hammer_time": pd.to_datetime(cur["Open time"], utc=True).isoformat(),
                            "hammer_open": o,
                            "hammer_high": h,
                            "hammer_low": l,
                            "hammer_close": c,
                            "body_ratio": body_ratio,
                            "lower_wick_to_body": lower_wick / body if body else 0,
                            "next_close": nxt_close,
                            "fractal_type": "LL",
                        },
                    ))

        # ---- SHORT HAMMER ----
        elif c > o:  # зелёная свеча
            if (upper_wick >= WICK_TO_BODY_MIN * body and
                lower_wick <= SHORT_WICK_RATIO_MAX * body and
                _is_hh_fractal(ref, i) and
                nxt_close < o):

                zone_bottom = o
                zone_top = max(h, float(nxt["High"]))

                if zone_top > zone_bottom:
                    open_time_nxt = pd.to_datetime(nxt["Open time"], utc=True)
                    zones.append(Zone(
                        strategy="HAMMER",
                        symbol=symbol,
                        source_tf=tf,
                        direction="SHORT",
                        zone_bottom=zone_bottom,
                        zone_top=zone_top,
                        trigger_time=open_time_nxt + tf_td,
                        meta={
                            "hammer_time": pd.to_datetime(cur["Open time"], utc=True).isoformat(),
                            "hammer_open": o,
                            "hammer_high": h,
                            "hammer_low": l,
                            "hammer_close": c,
                            "body_ratio": body_ratio,
                            "upper_wick_to_body": upper_wick / body if body else 0,
                            "next_close": nxt_close,
                            "fractal_type": "HH",
                        },
                    ))

    return zones
