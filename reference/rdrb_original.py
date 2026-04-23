# RDRB (Red Day Reversal Bar) — простой паттерн из 3 свечей.
#
# Оригинальный код был частью более крупного проекта и использовал внешние
# импорты:
#   from src.core.entities import Event
#   from src.core.enums import Direction, PatternType
# Этих модулей в нашем проекте нет — вместо них в новой реализации будет
# использован общий dataclass Signal из strategies/base.py.
#
# Математика паттерна ОДИН-В-ОДИН перенесена из оригинального кода:
#   LONG:  high[i-2] < close[i-1]  AND  low[i]  < high[i-2]  AND  close[i] > close[i-2]
#   SHORT: low[i-2]  > close[i-1]  AND  high[i] > low[i-2]   AND  close[i] < close[i-2]
#
# Цикл по всем свечам с i=2 до len(df)-1. На каждой позиции проверяется
# и long, и short условие независимо (может встретиться и то и другое на
# одном баре — это нормально, обе записи попадут в events).


from typing import List

import pandas as pd

# ↓↓↓ В оригинале было:
# from src.core.entities import Event
# from src.core.enums import Direction, PatternType
#
# Event — dataclass с полями:
#   symbol, timeframe, pattern_type, direction,
#   occurred_at, bar_index, price, meta
#
# Direction.LONG / Direction.SHORT — просто строковые enum-ы.
# PatternType.RDRB — строковый enum.


def detect_rdrb_events(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
) -> List[dict]:
    """
    Возвращает список событий RDRB как список dict-ов (в оригинале — List[Event]).
    В новой архитектуре этот список будет сконвертирован в List[Signal].
    """
    events: List[dict] = []

    required_cols = ["Open time", "High", "Low", "Close"]
    for col in required_cols:
        if col not in df.columns:
            raise ValueError(f"Missing required column: {col}")

    for i in range(2, len(df)):
        c_im2 = df.iloc[i - 2]
        c_im1 = df.iloc[i - 1]
        c_i = df.iloc[i]

        h_im2 = float(c_im2["High"])
        l_im2 = float(c_im2["Low"])
        cl_im2 = float(c_im2["Close"])

        cl_im1 = float(c_im1["Close"])

        h_i = float(c_i["High"])
        l_i = float(c_i["Low"])
        cl_i = float(c_i["Close"])

        ts = c_i["Open time"]

        # Long RDRB
        if h_im2 < cl_im1 and l_i < h_im2 and cl_i > cl_im2:
            events.append({
                "symbol": symbol,
                "timeframe": timeframe,
                "pattern_type": "RDRB",
                "direction": "LONG",
                "occurred_at": ts,
                "bar_index": i,
                "price": cl_i,
                "meta": {
                    "formation_index": i,
                    "formation_type": "long_rdrb",
                },
            })

        # Short RDRB
        if l_im2 > cl_im1 and h_i > l_im2 and cl_i < cl_im2:
            events.append({
                "symbol": symbol,
                "timeframe": timeframe,
                "pattern_type": "RDRB",
                "direction": "SHORT",
                "occurred_at": ts,
                "bar_index": i,
                "price": cl_i,
                "meta": {
                    "formation_index": i,
                    "formation_type": "short_rdrb",
                },
            })

    return events
