"""OBX4: паттерн из 4 свечей с чередованием + FVG на 5-й.

Функции is_bearish, is_bullish, body_size, body_top, body_bottom,
has_common_body_intersection, detect_obx4_bullish, detect_obx4_bearish,
detect_all_obx4, detect_signal_on_last_closed_candle перенесены один-в-один
из reference/obx4_original.py. Математика не изменена.
"""
from __future__ import annotations

import pandas as pd

from strategies.base import Signal, Zone


# --- локальный normalize_df (в reference используется внутри
#     detect_signal_on_last_closed_candle; без него функция не работает) ---

def _normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=[
            "Open time", "Open", "High", "Low", "Close", "Volume", "Close time"
        ])

    out = df.copy()

    out["Open time"] = pd.to_datetime(out["Open time"], utc=True, errors="coerce")
    if "Close time" in out.columns:
        out["Close time"] = pd.to_datetime(out["Close time"], utc=True, errors="coerce")

    for col in ["Open", "High", "Low", "Close", "Volume"]:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")

    out = out.dropna(subset=["Open time", "Open", "High", "Low", "Close"])
    out = out.sort_values("Open time")
    out = out.drop_duplicates(subset=["Open time"], keep="last")
    out = out.reset_index(drop=True)

    return out


def is_bearish(c) -> bool:
    return c["Close"] < c["Open"]


def body_size(c) -> float:
    return abs(c["Close"] - c["Open"])


def is_bullish(c) -> bool:
    return c["Close"] > c["Open"]


def body_top(c) -> float:
    return max(c["Open"], c["Close"])


def body_bottom(c) -> float:
    return min(c["Open"], c["Close"])


def has_common_body_intersection(c1, c2, c3, c4):
    common_top = min(
        body_top(c1),
        body_top(c2),
        body_top(c3),
        body_top(c4),
    )
    common_bottom = max(
        body_bottom(c1),
        body_bottom(c2),
        body_bottom(c3),
        body_bottom(c4),
    )
    return common_bottom < common_top, common_bottom, common_top


def detect_obx4_bullish(df: pd.DataFrame) -> pd.DataFrame:
    results = []
    if len(df) < 5:
        return pd.DataFrame(results)

    for i in range(len(df) - 4):
        c1 = df.iloc[i]
        c2 = df.iloc[i + 1]
        c3 = df.iloc[i + 2]
        c4 = df.iloc[i + 3]
        c5 = df.iloc[i + 4]

        # red -> green -> red -> green
        if not (
            is_bearish(c1) and
            is_bullish(c2) and
            is_bearish(c3) and
            is_bullish(c4)
        ):
            continue

        # body c1 должно быть больше body c2
        if body_size(c1) <= body_size(c2) and body_size(c1) <= body_size(c3):
            continue

        # 4-я зеленая закрывается выше открытия 1-й красной
        if c4["Close"] <= c1["Open"]:
            continue

        # bullish FVG
        if c5["Low"] <= c3["High"]:
            continue

        # общее пересечение по телам
        ok, ob_bottom, ob_top = has_common_body_intersection(c1, c2, c3, c4)
        if not ok:
            continue

        results.append({
            "pattern_time": c1["Open time"],
            "direction": "bullish",
            "ob_top": float(ob_top),
            "ob_bottom": float(ob_bottom),
            "fvg_top": float(c5["Low"]),
            "fvg_bottom": float(c3["High"]),
            "c1_time": c1["Open time"],
            "c2_time": c2["Open time"],
            "c3_time": c3["Open time"],
            "c4_time": c4["Open time"],
            "c5_time": c5["Open time"],
        })

    return pd.DataFrame(results)


def detect_obx4_bearish(df: pd.DataFrame) -> pd.DataFrame:
    results = []
    if len(df) < 5:
        return pd.DataFrame(results)

    for i in range(len(df) - 4):
        c1 = df.iloc[i]
        c2 = df.iloc[i + 1]
        c3 = df.iloc[i + 2]
        c4 = df.iloc[i + 3]
        c5 = df.iloc[i + 4]

        # green -> red -> green -> red
        if not (
            is_bullish(c1) and
            is_bearish(c2) and
            is_bullish(c3) and
            is_bearish(c4)
        ):
            continue

        # body c1 должно быть больше body c2
        if body_size(c1) <= body_size(c2) and body_size(c1) <= body_size(c3):
            continue

        # 4-я красная закрывается ниже открытия 1-й зеленой
        if c4["Close"] >= c1["Open"]:
            continue

        # bearish FVG
        if c5["High"] >= c3["Low"]:
            continue

        # общее пересечение по телам
        ok, ob_bottom, ob_top = has_common_body_intersection(c1, c2, c3, c4)
        if not ok:
            continue

        results.append({
            "pattern_time": c1["Open time"],
            "direction": "bearish",
            "ob_top": float(ob_top),
            "ob_bottom": float(ob_bottom),
            "fvg_top": float(c3["Low"]),
            "fvg_bottom": float(c5["High"]),
            "c1_time": c1["Open time"],
            "c2_time": c2["Open time"],
            "c3_time": c3["Open time"],
            "c4_time": c4["Open time"],
            "c5_time": c5["Open time"],
        })

    return pd.DataFrame(results)


def detect_all_obx4(df: pd.DataFrame) -> pd.DataFrame:
    bull = detect_obx4_bullish(df)
    bear = detect_obx4_bearish(df)
    out = pd.concat([bull, bear], ignore_index=True)
    if not out.empty:
        out = out.sort_values("pattern_time").reset_index(drop=True)
    return out


def detect_signal_on_last_closed_candle(df: pd.DataFrame):
    """
    Проверяем только один паттерн:
    последние 5 закрытых свечей, где 5-я свеча = последняя свеча в df.
    """
    df = _normalize_df(df)

    if len(df) < 5:
        return None

    last5 = df.iloc[-5:].reset_index(drop=True)

    bull = detect_obx4_bullish(last5)
    if not bull.empty:
        row = bull.iloc[-1].copy()

        # Дополнительная защита:
        # c5_time паттерна должен совпадать с open time последней свечи в df
        if pd.to_datetime(row["c5_time"]) == pd.to_datetime(df.iloc[-1]["Open time"]):
            return row

    bear = detect_obx4_bearish(last5)
    if not bear.empty:
        row = bear.iloc[-1].copy()

        if pd.to_datetime(row["c5_time"]) == pd.to_datetime(df.iloc[-1]["Open time"]):
            return row

    return None


# =========================================================
# Адаптер + публичный detect()
# =========================================================

def to_ref_format(df: pd.DataFrame) -> pd.DataFrame:
    """Формат data_manager (lowercase + DatetimeIndex) -> формат reference (Capitalized + Open time column)."""
    if df is None or df.empty:
        return pd.DataFrame(columns=["Open time", "Open", "High", "Low", "Close", "Volume"])
    out = df.copy()
    if isinstance(out.index, pd.DatetimeIndex):
        out = out.reset_index().rename(columns={"open_time": "Open time"})
    rename = {"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"}
    out = out.rename(columns={k: v for k, v in rename.items() if k in out.columns})
    return out


def detect_zones(df: pd.DataFrame, symbol: str, tf: str) -> list[Zone]:
    """Все OBX4-паттерны истории df -> зоны (OB body-intersection) для ob1h-ядра."""
    ref = to_ref_format(df)
    patterns = detect_all_obx4(ref)
    zones: list[Zone] = []
    if patterns.empty:
        return zones

    tf_td = pd.Timedelta(tf)

    for _, row in patterns.iterrows():
        direction = "LONG" if row["direction"] == "bullish" else "SHORT"
        ob_bottom = float(row["ob_bottom"])
        ob_top = float(row["ob_top"])
        if ob_bottom > ob_top:
            ob_bottom, ob_top = ob_top, ob_bottom

        zones.append(Zone(
            strategy="OBX4",
            symbol=symbol,
            source_tf=tf,
            direction=direction,
            zone_bottom=ob_bottom,
            zone_top=ob_top,
            trigger_time=pd.to_datetime(row["c5_time"], utc=True) + tf_td,
            meta={
                "fvg_top": float(row["fvg_top"]),
                "fvg_bottom": float(row["fvg_bottom"]),
                "pattern_time": pd.to_datetime(row["pattern_time"], utc=True).isoformat(),
                "c1_time": pd.to_datetime(row["c1_time"], utc=True).isoformat(),
                "c2_time": pd.to_datetime(row["c2_time"], utc=True).isoformat(),
                "c3_time": pd.to_datetime(row["c3_time"], utc=True).isoformat(),
                "c4_time": pd.to_datetime(row["c4_time"], utc=True).isoformat(),
                "c5_time": pd.to_datetime(row["c5_time"], utc=True).isoformat(),
            },
        ))
    return zones
