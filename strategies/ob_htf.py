"""OB_HTF: OB-паттерн из 2 свечей на старшем ТФ. Зона = диапазон prev-свечи."""
from __future__ import annotations

import pandas as pd

from data_manager import load_df
from strategies.base import Zone
from strategies.obx4 import to_ref_format


def _has_confirming_fvg_4h(
    df_4h: pd.DataFrame,
    direction: str,
    zone_bottom: float,
    zone_top: float,
    window_start: pd.Timestamp,
    window_end: pd.Timestamp,
) -> bool:
    """Есть ли в окне [window_start, window_end) свеча c0 на 4h, образующая
    FVG того же направления, чья зона пересекается с [zone_bottom, zone_top]."""
    if df_4h is None or df_4h.empty or len(df_4h) < 3:
        return False

    opens = pd.to_datetime(df_4h["Open time"], utc=True)
    mask = (opens >= window_start) & (opens < window_end)
    positions = [p for p, ok in enumerate(mask.values) if ok]

    for pos in positions:
        if pos < 2:
            continue
        c2 = df_4h.iloc[pos - 2]
        c0 = df_4h.iloc[pos]

        if direction == "LONG":
            h2 = float(c2["High"])
            l0 = float(c0["Low"])
            if h2 < l0:
                fvg_bottom, fvg_top = h2, l0
                if not (fvg_top < zone_bottom or fvg_bottom > zone_top):
                    return True
        else:  # SHORT
            l2 = float(c2["Low"])
            h0 = float(c0["High"])
            if l2 > h0:
                fvg_bottom, fvg_top = h0, l2
                if not (fvg_top < zone_bottom or fvg_bottom > zone_top):
                    return True

    return False


def detect_zones(df: pd.DataFrame, symbol: str, tf: str) -> list[Zone]:
    ref = to_ref_format(df)
    if ref.empty or len(ref) < 2:
        return []

    df_4h_raw = load_df(symbol, "4h")
    df_4h = to_ref_format(df_4h_raw) if not df_4h_raw.empty else None

    tf_td = pd.Timedelta(tf)
    zones: list[Zone] = []
    for i in range(1, len(ref)):
        prev = ref.iloc[i - 1]
        cur = ref.iloc[i]

        po, pc = float(prev["Open"]), float(prev["Close"])
        ph, pl = float(prev["High"]), float(prev["Low"])
        co, cc = float(cur["Open"]), float(cur["Close"])
        ch, cl = float(cur["High"]), float(cur["Low"])

        direction: str | None = None
        zone_bottom: float | None = None
        zone_top: float | None = None
        if pc < po and cc > po:
            direction = "LONG"
            zone_bottom = min(pl, cl)
            zone_top = po
        elif pc > po and cc < po:
            direction = "SHORT"
            zone_bottom = po
            zone_top = max(ph, ch)
        if direction is None:
            continue

        i_open_time = pd.to_datetime(cur["Open time"], utc=True)
        i_close_time = i_open_time + tf_td

        if df_4h is None or df_4h.empty:
            continue
        if not _has_confirming_fvg_4h(
            df_4h, direction,
            zone_bottom, zone_top,
            i_open_time, i_close_time,
        ):
            continue

        zones.append(Zone(
            strategy="OB_HTF",
            symbol=symbol,
            source_tf=tf,
            direction=direction,
            zone_bottom=zone_bottom,
            zone_top=zone_top,
            trigger_time=i_close_time,
            meta={
                "prev_open": po, "prev_close": pc,
                "prev_high": ph, "prev_low": pl,
                "cur_open": co, "cur_close": cc,
                "fvg4h_confirm": True,
            },
        ))
    return zones
