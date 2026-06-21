"""Strategy i-RDRB+FVG — композит: i-RDRB(C1-C4) + FVG(C3,C4,C5) того же направления.

Canon паттерна: smc-lib/elements/i_rdrb_fvg/definition.md (5 свечей V1).
  C1=idx-2, C2=idx-1, C3=idx (последняя свеча underlying RDRB),
  C4=idx+1 (displacement-разворот за границу block), C5=idx+2 (FVG c3).
  - underlying RDRB(C1,C2,C3) — strategy_rdrb.detect_rdrb (pandas canon)
  - i-RDRB: C4 разворачивает за границу block (close + цвет), направление ПРОТИВ RDRB
  - FVG(C3,C4,C5) того же направления что i-RDRB — strategy_1_1_1.detect_fvg

Entry/SL: Combined-D — validated 6y BTC (+122.6R baseline-units, WR 59.8% / 781 сделок).
  LONG : entry = block.top;    SL = pattern_low  + 0.1·(block.bottom − pattern_low)
  SHORT: entry = block.bottom; SL = pattern_high − 0.1·(pattern_high − block.top)
  TP — политика RR на стороне исполнения (детектор отдаёт entry/sl/risk, как strategy_rdrb).
  См. vault/knowledge/strategies/i-rdrb-fvg-combined-d-block-edge-sl-01.md.

Переиспользует pandas-каноны (детектор = тот же код, что в research-бэктестах и 1.1.x).
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from strategies.strategy_1_1_1 import detect_fvg
from strategies.strategy_rdrb import detect_rdrb

# Combined-D: SL на 10% от pattern-экстремума к ближней границе block.
SL_EDGE_OFFSET = 0.1


@dataclass
class IRDRBFVGSignal:
    direction: str            # "LONG" | "SHORT" — направление i-RDRB (= сделки)
    entry: float              # block edge (Combined-D)
    sl: float
    risk: float               # |entry − sl|
    block: tuple              # (bottom, top) подлежащего RDRB
    pattern_low: float        # min low C1..C5
    pattern_high: float       # max high C1..C5
    c1_time: pd.Timestamp     # open C1
    c3_time: pd.Timestamp     # open C3 (последняя свеча RDRB)
    c5_time: pd.Timestamp     # open C5 (= bar армирования; close = c5_time + TF)
    fvg_zone: tuple           # (bottom, top) FVG(C3,C4,C5)
    rdrb_direction: str       # направление underlying RDRB (противоположно direction)
    zone_version: str


def detect_i_rdrb_fvg(
    df: pd.DataFrame, idx: int, zone_version: str = "V1"
) -> IRDRBFVGSignal | None:
    """Если на свечах (idx-2 .. idx+2) образуется i-RDRB+FVG — вернуть сигнал.

    `idx` указывает на C3 (последнюю свечу underlying RDRB).
    Возвращает None, если паттерн не сложился или геометрия SL/entry невалидна.
    """
    if idx < 2 or idx + 2 >= len(df):
        return None

    rdrb = detect_rdrb(df, idx, zone_version)
    if rdrb is None:
        return None

    c4 = df.iloc[idx + 1]
    c4_open = float(c4["open"])
    c4_close = float(c4["close"])

    # i-RDRB: C4 закрывается ЗА границей block в обратную RDRB сторону + правильный цвет.
    if rdrb.direction == "SHORT":
        if not (c4_close > c4_open and c4_close > rdrb.top):
            return None
        i_dir = "LONG"
    else:  # underlying RDRB LONG
        if not (c4_close < c4_open and c4_close < rdrb.bottom):
            return None
        i_dir = "SHORT"

    # FVG(C3,C4,C5): detect_fvg(df, idx+2) смотрит (C3=idx, _, C5=idx+2).
    fvg = detect_fvg(df, idx + 2)
    if fvg is None or fvg.direction != i_dir:
        return None

    win = df.iloc[idx - 2: idx + 3]
    pl = float(win["low"].min())
    ph = float(win["high"].max())
    block_b, block_t = float(rdrb.bottom), float(rdrb.top)

    # Combined-D entry/SL.
    if i_dir == "LONG":
        entry = block_t
        sl = pl + SL_EDGE_OFFSET * (block_b - pl)
        if not (sl < entry):
            return None
        risk = entry - sl
    else:
        entry = block_b
        sl = ph - SL_EDGE_OFFSET * (ph - block_t)
        if not (sl > entry):
            return None
        risk = sl - entry

    if risk <= 0:
        return None

    return IRDRBFVGSignal(
        direction=i_dir,
        entry=float(entry),
        sl=float(sl),
        risk=float(risk),
        block=(block_b, block_t),
        pattern_low=pl,
        pattern_high=ph,
        c1_time=df.index[idx - 2],
        c3_time=df.index[idx],
        c5_time=df.index[idx + 2],
        fvg_zone=(float(fvg.bottom), float(fvg.top)),
        rdrb_direction=rdrb.direction,
        zone_version=zone_version,
    )


def detect_all_i_rdrb_fvg(
    df: pd.DataFrame, zone_version: str = "V1"
) -> list[IRDRBFVGSignal]:
    """Все i-RDRB+FVG сигналы на df (каузально: каждый зависит только от своих 5 свечей)."""
    out: list[IRDRBFVGSignal] = []
    for idx in range(2, len(df) - 2):
        sig = detect_i_rdrb_fvg(df, idx, zone_version)
        if sig is not None:
            out.append(sig)
    return out
