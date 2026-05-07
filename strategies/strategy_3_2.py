"""Strategy 3.2: FVG-4h → first failed-touch (2 свечи закрылись снаружи зоны) → FVG-1h в окне 8h.

Воронка:
  1. FVG-4h (canon, см. vault/.../универсальные определения OB и FVG.md):
       LONG:  high(c0) < low(c2).   Zone = [high(c0), low(c2)]
       SHORT: low(c0)  > high(c2).  Zone = [high(c2), low(c0)]
  2. Первая 4h-свеча j после `c2_time + 4h`, у которой wick касается зоны:
       LONG:  low(j)  ≤ FVG.top
       SHORT: high(j) ≥ FVG.bottom
  3. Skip если эта свеча пробивает зону насквозь:
       LONG:  close(j) ≤ FVG.bottom (свеча провалилась за нижний край)
       SHORT: close(j) ≥ FVG.top
  4. ОБЕ свечи (j и j+1) должны закрыться СНАРУЖИ FVG-4h в сторону продолжения:
       LONG:  close(j) > FVG.top   AND close(j+1) > FVG.top
       SHORT: close(j) < FVG.bottom AND close(j+1) < FVG.bottom
     Если условие нарушено — setup мёртв.
  5. Внутри 8h окна `[open(j), open(j) + 8h)` — первая FVG-1h того же
     направления, у которой ВСЯ тройка (c0, c1, c2) лежит в окне.
     Overlap с зоной FVG-4h НЕ требуется (по построению FVG-1h уже снаружи
     FVG-4h, т.к. обе 4h-свечи закрылись снаружи).

Entry / SL / TP:
  - entry = mid(fvg_1h)
  - SL    = low(c0_1h)  для LONG / high(c0_1h) для SHORT
  - RR    = 1.0 (TP = entry ± risk)

Если на любом ярусе ничего не нашлось — setup скипается.
"""
from __future__ import annotations

import pandas as pd

from strategies.strategy_1_1_1 import FVGZone, detect_fvg


def _find_first_touch_idx(
    df_4h: pd.DataFrame, search_start: pd.Timestamp,
    fvg: FVGZone,
) -> int | None:
    """Индекс первой 4h-свечи, чей wick касается зоны FVG-4h.

    LONG:  low(j)  ≤ fvg.top
    SHORT: high(j) ≥ fvg.bottom
    """
    if df_4h is None or df_4h.empty:
        return None
    mask = df_4h.index >= search_start
    if not mask.any():
        return None
    start = int(mask.argmax())
    arr_low = df_4h["low"].values
    arr_high = df_4h["high"].values
    n = len(df_4h)
    for j in range(start, n):
        if fvg.direction == "LONG":
            if float(arr_low[j]) <= fvg.top:
                return j
        else:
            if float(arr_high[j]) >= fvg.bottom:
                return j
    return None


def _check_rejection(
    df_4h: pd.DataFrame, touch_idx: int, fvg: FVGZone,
) -> bool:
    """Skip-условие + доп условие закрытия снаружи зоны для (touch, touch+1).

    Возвращает True если setup живой:
      - close(touch) НЕ за противоположным краем (skip-условие)
      - close(touch) и close(touch+1) строго СНАРУЖИ FVG в сторону продолжения
    """
    if touch_idx + 1 >= len(df_4h):
        return False
    c1 = float(df_4h["close"].iloc[touch_idx])
    c2 = float(df_4h["close"].iloc[touch_idx + 1])

    if fvg.direction == "LONG":
        # skip если touch свеча провалилась насквозь
        if c1 <= fvg.bottom:
            return False
        # обе свечи закрылись выше FVG.top
        return c1 > fvg.top and c2 > fvg.top
    else:  # SHORT
        if c1 >= fvg.top:
            return False
        return c1 < fvg.bottom and c2 < fvg.bottom


def _find_first_fvg_1h_in_window(
    df_1h: pd.DataFrame,
    window_start: pd.Timestamp,
    window_end: pd.Timestamp,
    direction: str,
) -> tuple[FVGZone, int] | None:
    """Первая FVG-1h нужного направления, у которой вся тройка (c0,c1,c2) в окне.

    Возвращает (FVGZone, c0_idx_in_df_1h) или None.
    """
    if df_1h is None or df_1h.empty:
        return None
    mask = (df_1h.index >= window_start) & (df_1h.index < window_end)
    if mask.sum() < 3:
        return None
    df_window = df_1h[mask]
    # detect_fvg использует iloc[k-2] и iloc[k] от своего df. После фильтрации
    # индексы перенумеруются — нужно мапить обратно через c0_time.
    for k in range(2, len(df_window)):
        f = detect_fvg(df_window, k)
        if f is None or f.direction != direction:
            continue
        # Условие "вся тройка в окне" = c0_time >= window_start (window_end
        # уже гарантирован, т.к. df_window.iloc[k] = c2 ∈ окне).
        if f.c0_time < window_start:
            continue
        # Найти позицию c0 в исходном df_1h для извлечения low/high.
        c0_idx = df_1h.index.get_loc(f.c0_time)
        return f, c0_idx
    return None


def detect_strategy_3_2_signals(
    df_4h: pd.DataFrame, df_1h: pd.DataFrame, verbose: bool = False,
) -> list[dict]:
    """FVG-4h → first failed-touch (2 свечи rejection) → FVG-1h в 8h окне.

    Args:
        df_4h, df_1h: pandas.DataFrame с UTC-индексом и open/high/low/close/volume.
        verbose: печать счётчиков воронки.

    Returns:
        list[dict] сигналов с полями direction, fvg_4h_*, touch_*, fvg_1h_*,
        signal_time, entry, sl, tp, risk.
    """
    signals: list[dict] = []
    counters = {
        "fvg_4h_long": 0, "fvg_4h_short": 0,
        "touched": 0,
        "rejection_passed": 0,
        "fvg_1h_found": 0,
    }

    n_4h = len(df_4h)
    for idx in range(2, n_4h):
        fvg = detect_fvg(df_4h, idx)
        if fvg is None:
            continue
        if fvg.direction == "LONG":
            counters["fvg_4h_long"] += 1
        else:
            counters["fvg_4h_short"] += 1

        # Поиск touch начинается со свечи, открывшейся не раньше close c2.
        search_start = fvg.c2_time + pd.Timedelta(hours=4)
        touch_idx = _find_first_touch_idx(df_4h, search_start, fvg)
        if touch_idx is None:
            continue
        counters["touched"] += 1

        if not _check_rejection(df_4h, touch_idx, fvg):
            continue
        counters["rejection_passed"] += 1

        touch_time = df_4h.index[touch_idx]
        window_start = touch_time
        window_end = touch_time + pd.Timedelta(hours=8)

        result = _find_first_fvg_1h_in_window(
            df_1h, window_start, window_end, fvg.direction,
        )
        if result is None:
            continue
        fvg_1h, c0_idx = result
        counters["fvg_1h_found"] += 1

        entry = (fvg_1h.bottom + fvg_1h.top) / 2.0
        if fvg.direction == "LONG":
            sl = float(df_1h["low"].iloc[c0_idx])
            risk = entry - sl
            tp = entry + risk
        else:
            sl = float(df_1h["high"].iloc[c0_idx])
            risk = sl - entry
            tp = entry - risk
        if risk <= 0:
            continue

        signals.append({
            "direction": fvg.direction,
            "fvg_4h_c0_time": fvg.c0_time,
            "fvg_4h_c2_time": fvg.c2_time,
            "fvg_4h_zone": (fvg.bottom, fvg.top),
            "touch_time": touch_time,
            "touch_close": float(df_4h["close"].iloc[touch_idx]),
            "touch_plus1_time": df_4h.index[touch_idx + 1],
            "touch_plus1_close": float(df_4h["close"].iloc[touch_idx + 1]),
            "fvg_1h_c0_time": fvg_1h.c0_time,
            "fvg_1h_c2_time": fvg_1h.c2_time,
            "fvg_1h_zone": (fvg_1h.bottom, fvg_1h.top),
            "signal_time": fvg_1h.c2_time,
            "entry": float(entry),
            "sl": float(sl),
            "tp": float(tp),
            "risk": float(risk),
        })

    if verbose:
        print(f"[FUNNEL 3.2]")
        print(f"  FVG-4h: LONG={counters['fvg_4h_long']} "
              f"SHORT={counters['fvg_4h_short']}")
        print(f"  touched: {counters['touched']}")
        print(f"  rejection passed: {counters['rejection_passed']}")
        print(f"  FVG-1h found (signals): {counters['fvg_1h_found']}")
    return signals
