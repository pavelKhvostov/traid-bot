"""
Pivot detection на 1h TF.

Базовое определение: Williams fractal N=2 (5-bar swing) на 1h.
  - FH (Fractal High) = SHORT-pivot (точка разворота вниз)
  - FL (Fractal Low)  = LONG-pivot  (точка разворота вверх)

Подтверждение приходит через N=2 бара после центра.

Дополнительные опциональные фильтры:
  - hold_bars: pivot не свипнут K следующих 1h баров (FH не пробит вверх, FL не пробит вниз)
  - magnitude_pct: цена после pivot развернулась минимум на X% от уровня pivot

Эти фильтры делают pivot'ы "значимыми" — отсекают шум.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pandas as pd

SMC_LIB = Path(os.environ.get("SMCLIB_ROOT", str(Path.home() / "smc-lib")))
sys.path.insert(0, str(SMC_LIB))
sys.path.insert(0, str(SMC_LIB / "prediction-algo"))

from candle import Candle  # noqa: E402
from elements.fractal.code import detect_fractal  # noqa: E402
from resample import resample_one  # noqa: E402


PivotDirection = Literal["short", "long"]   # short = FH = top, long = FL = bottom


@dataclass(frozen=True)
class Pivot:
    direction: PivotDirection
    center_ts: pd.Timestamp        # центр Williams (бар-пивот)
    confirm_ts: pd.Timestamp       # подтверждается через N=2 бара
    level: float                   # high (FH) или low (FL)
    n: int                         # параметр Williams (по умолчанию 2)
    held_bars: int | None = None   # сколько 1h баров pivot НЕ был свипнут (None = не считали)
    max_reversal_pct: float | None = None  # макс. разворот цены после подтверждения, в %


def detect_1h_pivots_williams(df_1h: pd.DataFrame, n: int = 2) -> list[Pivot]:
    """
    Найти все Williams N=2 fractals на 1h DataFrame.

    df_1h: 1h OHLCV с DatetimeIndex (UTC).
    Returns: список Pivot, отсортированных по center_ts.
    """
    out: list[Pivot] = []
    win = 2 * n + 1
    for i in range(win - 1, len(df_1h)):
        candles = [
            Candle(
                float(df_1h["open"].iloc[i-win+1+k]),
                float(df_1h["high"].iloc[i-win+1+k]),
                float(df_1h["low"].iloc[i-win+1+k]),
                float(df_1h["close"].iloc[i-win+1+k]),
            )
            for k in range(win)
        ]
        fr = detect_fractal(candles, n=n)
        if fr is None:
            continue
        center_idx = i - n
        center_ts = df_1h.index[center_idx]
        confirm_ts = df_1h.index[i]
        direction: PivotDirection = "short" if fr.direction == "high" else "long"
        out.append(Pivot(
            direction=direction,
            center_ts=center_ts,
            confirm_ts=confirm_ts,
            level=fr.level,
            n=n,
        ))
    return out


def annotate_hold_and_reversal(
    pivots: list[Pivot],
    df_1h: pd.DataFrame,
) -> list[Pivot]:
    """
    Для каждого pivot посчитать held_bars и max_reversal_pct, используя 1h бары после confirm_ts.

    held_bars:
      FH: число баров пока ни один следующий bar.high > level
      FL: число баров пока ни один следующий bar.low  < level

    max_reversal_pct:
      FH: max((level - subsequent_low) / level * 100) — насколько глубоко вниз ушла цена
      FL: max((subsequent_high - level) / level * 100) — насколько вверх

    Считаем по всем последующим 1h барам до конца df_1h.
    """
    out: list[Pivot] = []
    for piv in pivots:
        future = df_1h.loc[df_1h.index > piv.confirm_ts]
        if future.empty:
            out.append(piv)
            continue

        held = 0
        max_rev = 0.0
        for ts, row in future.iterrows():
            h, l = float(row["high"]), float(row["low"])
            if piv.direction == "short":
                # held = последовательность баров где high ≤ level
                if h > piv.level:
                    break
                held += 1
                rev = (piv.level - l) / piv.level * 100
                max_rev = max(max_rev, rev)
            else:  # long pivot (FL)
                if l < piv.level:
                    break
                held += 1
                rev = (h - piv.level) / piv.level * 100
                max_rev = max(max_rev, rev)

        out.append(Pivot(
            direction=piv.direction, center_ts=piv.center_ts, confirm_ts=piv.confirm_ts,
            level=piv.level, n=piv.n,
            held_bars=held,
            max_reversal_pct=max_rev,
        ))
    return out


def find_1h_pivots(
    df_1m: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
    n: int = 2,
    min_hold_bars: int = 0,
    min_reversal_pct: float = 0.0,
) -> list[Pivot]:
    """
    Высокоуровневая обёртка: 1m → 1h → Williams pivots → annotate hold/reversal → filter.

    start, end: границы анализа (используется как cut_off_ts для resample = end + 1h).
    min_hold_bars / min_reversal_pct: пороги фильтрации pivot'ов на "значимость".
    """
    # Resample 1m → 1h до конца окна
    end_plus = end + pd.Timedelta(hours=1)
    df_1h = resample_one(df_1m, "1h", end_plus)
    df_1h = df_1h.loc[(df_1h.index >= start) & (df_1h.index <= end)]

    pivots = detect_1h_pivots_williams(df_1h, n=n)
    pivots = annotate_hold_and_reversal(pivots, df_1h)

    if min_hold_bars > 0:
        pivots = [p for p in pivots if (p.held_bars or 0) >= min_hold_bars]
    if min_reversal_pct > 0:
        pivots = [p for p in pivots if (p.max_reversal_pct or 0) >= min_reversal_pct]
    return pivots
