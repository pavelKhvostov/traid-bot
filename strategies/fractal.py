"""FRACTAL: снятие фрактала i±2, зона — фитиль свечи-снятия до тела."""
from __future__ import annotations

import pandas as pd

from strategies.base import Zone
from strategies.obx4 import to_ref_format


def _is_ll_fractal(ref: pd.DataFrame, i: int) -> bool:
    lo = float(ref.iloc[i]["Low"])
    for k in (i - 2, i - 1, i + 1, i + 2):
        if lo >= float(ref.iloc[k]["Low"]):
            return False
    return True


def _is_hh_fractal(ref: pd.DataFrame, i: int) -> bool:
    hi = float(ref.iloc[i]["High"])
    for k in (i - 2, i - 1, i + 1, i + 2):
        if hi <= float(ref.iloc[k]["High"]):
            return False
    return True


def detect_zones(df: pd.DataFrame, symbol: str, tf: str) -> list[Zone]:
    ref = to_ref_format(df)
    n = len(ref)
    if n < 5:
        return []

    zones: list[Zone] = []
    for i in range(2, n - 2):
        is_ll = _is_ll_fractal(ref, i)
        is_hh = _is_hh_fractal(ref, i)
        if not (is_ll or is_hh):
            continue

        frac_row = ref.iloc[i]
        frac_time = pd.to_datetime(frac_row["Open time"], utc=True).isoformat()

        tf_td = pd.Timedelta(tf)

        if is_ll:
            frac_price = float(frac_row["Low"])
            for j in range(i + 3, n):
                jrow = ref.iloc[j]
                jlow = float(jrow["Low"])
                # ждём первую свечу, касающуюся уровня low-ом
                if jlow >= frac_price:
                    continue
                jclose = float(jrow["Close"])
                # первая касающаяся — если закрылась за уровнем, фрактал пропущен
                if jclose <= frac_price:
                    break
                # jlow < frac_price AND jclose > frac_price -> снятие валидно
                j_open = float(jrow["Open"])
                j_high = float(jrow["High"])
                body_bottom = min(j_open, jclose)
                open_time = pd.to_datetime(jrow["Open time"], utc=True)
                close_time = open_time + tf_td - pd.Timedelta(milliseconds=1)
                trigger_time = (close_time - pd.Timedelta(hours=1)).floor("h")
                zones.append(Zone(
                    strategy="FRACTAL",
                    symbol=symbol,
                    source_tf=tf,
                    direction="LONG",
                    zone_bottom=jlow,
                    zone_top=body_bottom,
                    trigger_time=trigger_time,
                    meta={
                        "fractal_time": frac_time,
                        "fractal_price": frac_price,
                        "fractal_type": "LL",
                        "sweep_high": j_high,
                        "sweep_low": jlow,
                        "sweep_open": j_open,
                        "sweep_close": jclose,
                        "sweep_close_time": close_time.isoformat(),
                    },
                ))
                break

        if is_hh:
            frac_price = float(frac_row["High"])
            for j in range(i + 3, n):
                jrow = ref.iloc[j]
                jhigh = float(jrow["High"])
                if jhigh <= frac_price:
                    continue
                jclose = float(jrow["Close"])
                if jclose >= frac_price:
                    break
                j_open = float(jrow["Open"])
                j_low = float(jrow["Low"])
                body_top = max(j_open, jclose)
                open_time = pd.to_datetime(jrow["Open time"], utc=True)
                close_time = open_time + tf_td - pd.Timedelta(milliseconds=1)
                trigger_time = (close_time - pd.Timedelta(hours=1)).floor("h")
                zones.append(Zone(
                    strategy="FRACTAL",
                    symbol=symbol,
                    source_tf=tf,
                    direction="SHORT",
                    zone_bottom=body_top,
                    zone_top=jhigh,
                    trigger_time=trigger_time,
                    meta={
                        "fractal_time": frac_time,
                        "fractal_price": frac_price,
                        "fractal_type": "HH",
                        "sweep_high": jhigh,
                        "sweep_low": j_low,
                        "sweep_open": j_open,
                        "sweep_close": jclose,
                        "sweep_close_time": close_time.isoformat(),
                    },
                ))
                break

    return zones
