"""Этап 93: Inverse FVG (iFVG) детектор + демонстрация на BTC 1h.

Определение (от пользователя):
  iFVG = FVG противоположного направления, который формируется в зоне
  ранее образованной FVG, и его свечи ПЕРВЫМИ перекрывают зону первой FVG.
  Т.е. до образования iFVG зона первой FVG была untouched.

Логика детекции:
  1. Найти все FVG хронологически.
  2. Для каждой FVG-A:
     - Если ещё untouched (ни одна свеча не входила в зону) — кандидат.
     - Найти первую свечу j, входящую в зону FVG-A после c2.
  3. Проверить: эта свеча j является частью FVG-B (как c0/c1/c2)?
     - FVG-B.direction != FVG-A.direction
     - FVG-B.zone пересекает FVG-A.zone
  4. Если да — FVG-B это iFVG.

Что означает iFVG (SMC интерпретация):
  - До FVG-A зона была валидной support (bull) / resistance (bear).
  - iFVG-B приходит и "инвертирует" — теперь зона действует наоборот.
  - Bull FVG -> стал resistance (после iFVG bearish сверху)
  - Часто iFVG = сигнал смены тренда/структуры.
"""
from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

import pandas as pd
from dataclasses import dataclass

from data_manager import load_df


@dataclass
class FVG:
    direction: str
    bottom: float
    top: float
    c0_time: pd.Timestamp
    c1_time: pd.Timestamp
    c2_time: pd.Timestamp
    c0_idx: int
    c2_idx: int


def detect_all_fvgs(df: pd.DataFrame) -> list[FVG]:
    """Все FVG в df хронологически. Bull: high[i]<low[i+2]. Bear: low[i]>high[i+2]."""
    out = []
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    times = df.index
    n = len(df)
    for i in range(n - 2):
        c0_h, c0_l = highs[i], lows[i]
        c2_h, c2_l = highs[i+2], lows[i+2]
        if c0_h < c2_l:
            out.append(FVG("LONG", float(c0_h), float(c2_l),
                            times[i], times[i+1], times[i+2], i, i+2))
        elif c0_l > c2_h:
            out.append(FVG("SHORT", float(c2_h), float(c0_l),
                            times[i], times[i+1], times[i+2], i, i+2))
    return out


def first_touch_idx(df: pd.DataFrame, fvg: FVG) -> int | None:
    """Индекс первой свечи после c2, чей фитиль входит в зону FVG."""
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    n = len(df)
    # Bull FVG: касание = low <= fvg.top (свеча упала в gap сверху)
    # Bear FVG: касание = high >= fvg.bottom (свеча выросла в gap снизу)
    for j in range(fvg.c2_idx + 1, n):
        if fvg.direction == "LONG":
            if lows[j] <= fvg.top:
                return j
        else:
            if highs[j] >= fvg.bottom:
                return j
    return None


def zones_overlap(b1, t1, b2, t2) -> bool:
    return not (t1 < b2 or t2 < b1)


def find_inverse_fvgs(df: pd.DataFrame) -> list[tuple[FVG, FVG, int]]:
    """Найти все пары (FVG-A, iFVG-B, touch_idx).

    iFVG-B = первая FVG, чьи свечи (c0..c2) включают touch_idx FVG-A
    и которая в противоположную сторону с пересекающейся зоной.
    """
    fvgs = detect_all_fvgs(df)
    results = []

    # Индекс FVGs по c0_idx для быстрого поиска
    fvgs_sorted = sorted(fvgs, key=lambda x: x.c0_idx)

    for A in fvgs:
        # Проверим untouched до touch_idx
        touch = first_touch_idx(df, A)
        if touch is None:
            continue

        # Ищем FVG-B противоположную, чьи свечи захватывают touch
        for B in fvgs_sorted:
            if B.direction == A.direction:
                continue
            if B.c0_idx <= touch <= B.c2_idx:
                # touch_idx внутри окна формации B
                if zones_overlap(A.bottom, A.top, B.bottom, B.top):
                    # ВАЖНО: B.c0 должен быть >= A.c2 (B формируется ПОСЛЕ A)
                    if B.c0_idx > A.c2_idx:
                        results.append((A, B, touch))
                        break  # первая подходящая = iFVG

    return results


def main():
    print("[INFO] Загрузка BTC 1h")
    df = load_df("BTCUSDT", "1h")
    print(f"  range: {df.index[0]} до {df.index[-1]}, bars={len(df)}")

    # Берём последние ~60 дней для демонстрации
    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=60)
    df = df[df.index >= cutoff].copy()
    df = df.reset_index().rename(columns={"open_time": "time"})  # for clean indexing
    df.set_index("time", inplace=True)
    df = df.iloc[:5000]
    print(f"  cropped: {df.index[0]} до {df.index[-1]}, bars={len(df)}")

    print(f"\n[INFO] Поиск Inverse FVG паттернов...")
    results = find_inverse_fvgs(df)
    print(f"  Найдено iFVG: {len(results)}")

    if not results:
        print("  Нет iFVG в окне")
        return

    # Показать 5 последних
    print(f"\n{'='*90}\nПОСЛЕДНИЕ 5 INVERSE FVG (BTC 1h)\n{'='*90}\n")
    for A, B, touch_idx in results[-5:]:
        touch_time = df.index[touch_idx]
        print(f"FVG-A ({A.direction}):")
        print(f"  formation: c0={A.c0_time.strftime('%Y-%m-%d %H:%M')} -> "
              f"c2={A.c2_time.strftime('%Y-%m-%d %H:%M')}")
        print(f"  zone: [{A.bottom:.2f} ... {A.top:.2f}]")
        print(f"  ширина зоны: {A.top - A.bottom:.2f}")
        print(f"")
        print(f"iFVG-B ({B.direction}) <- inverse:")
        print(f"  formation: c0={B.c0_time.strftime('%Y-%m-%d %H:%M')} -> "
              f"c2={B.c2_time.strftime('%Y-%m-%d %H:%M')}")
        print(f"  zone: [{B.bottom:.2f} ... {B.top:.2f}]")
        print(f"  ширина зоны: {B.top - B.bottom:.2f}")
        print(f"")
        print(f"  TOUCH at: {touch_time.strftime('%Y-%m-%d %H:%M')} (свеча #{touch_idx})")
        print(f"  -> зона FVG-A была untouched {touch_idx - A.c2_idx} баров")
        bar = df.iloc[touch_idx]
        print(f"  -> touch bar OHLC: O={bar['open']:.2f} H={bar['high']:.2f} "
              f"L={bar['low']:.2f} C={bar['close']:.2f}")
        print(f"\n  СМЫСЛ: до iFVG зона [{A.bottom:.2f}..{A.top:.2f}] действовала как")
        if A.direction == "LONG":
            print(f"         SUPPORT (bull FVG). После iFVG (bearish сверху) стала")
            print(f"         RESISTANCE — bearish структура.")
        else:
            print(f"         RESISTANCE (bear FVG). После iFVG (bullish снизу) стала")
            print(f"         SUPPORT — bullish структура.")
        print(f"\n{'-'*90}\n")

    # Статистика общая
    print(f"\nСТАТИСТИКА за {(df.index[-1] - df.index[0]).days} дней:")
    all_fvgs = detect_all_fvgs(df)
    print(f"  Всего FVG: {len(all_fvgs)} (bull: {sum(1 for f in all_fvgs if f.direction=='LONG')}, "
          f"bear: {sum(1 for f in all_fvgs if f.direction=='SHORT')})")
    print(f"  Из них с iFVG (touched first time by counter FVG): {len(results)} "
          f"({len(results)/len(all_fvgs)*100:.1f}%)")
    bull_to_bear = sum(1 for A, B, _ in results if A.direction == "LONG")
    bear_to_bull = len(results) - bull_to_bear
    print(f"  Bull -> iFVG-bear: {bull_to_bear}")
    print(f"  Bear -> iFVG-bull: {bear_to_bull}")

    # Среднее время от FVG-A до iFVG
    delays = []
    for A, B, touch_idx in results:
        delays.append(touch_idx - A.c2_idx)
    if delays:
        print(f"  Среднее время от FVG-A.c2 до touch (iFVG.c1): "
              f"{sum(delays)/len(delays):.1f} баров (медиана {sorted(delays)[len(delays)//2]})")
        print(f"  Min/Max: {min(delays)} / {max(delays)} баров")


if __name__ == "__main__":
    main()
