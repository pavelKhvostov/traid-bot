"""Этап 94: показать ПОСЛЕДНИЙ inverse FVG на BTC 1h с полным контекстом."""
from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

import pandas as pd

import importlib.util
_spec93 = importlib.util.spec_from_file_location(
    "etap93_core", str(_Path(__file__).parent / "etap_93_inverse_fvg.py"))
_e93 = importlib.util.module_from_spec(_spec93)
_sys.modules["etap93_core"] = _e93  # register so dataclass works
_spec93.loader.exec_module(_e93)

from data_manager import load_df


def main():
    df = load_df("BTCUSDT", "1h")
    print(f"[INFO] BTC 1h: {df.index[0]} - {df.index[-1]}, bars={len(df)}")

    # Берём последние 90 дней
    cutoff = df.index[-1] - pd.Timedelta(days=90)
    df = df[df.index >= cutoff].copy()
    df = df.reset_index().rename(columns={"open_time": "time"})
    df.set_index("time", inplace=True)
    print(f"  cropped to last 90 days: {df.index[0]} - {df.index[-1]}, bars={len(df)}")

    results = _e93.find_inverse_fvgs(df)
    print(f"\n[INFO] iFVG found: {len(results)}")
    if not results:
        print("  No iFVG in window")
        return

    # Сортируем по touch time = c1 момент формирования iFVG.
    results_sorted = sorted(results, key=lambda r: r[1].c1_time)
    A, B, touch_idx = results_sorted[-1]
    touch_time = df.index[touch_idx]

    print(f"\n{'='*80}")
    print(f"LAST inverse FVG на BTC 1h")
    print(f"{'='*80}\n")

    # Контекст: 10 баров до formation FVG-A, 10 баров после iFVG-B
    print(f"Период: с {df.index[max(0, A.c0_idx-3)].strftime('%Y-%m-%d %H:%M')} "
          f"по {df.index[min(len(df)-1, B.c2_idx+3)].strftime('%Y-%m-%d %H:%M')} UTC\n")

    print(f"ШАГ 1. Формация ПЕРВОЙ FVG-A:")
    print(f"  Направление: {A.direction}")
    print(f"  c0 (свеча 1): {A.c0_time.strftime('%Y-%m-%d %H:%M')}")
    print(f"  c1 (свеча 2): {A.c1_time.strftime('%Y-%m-%d %H:%M')}")
    print(f"  c2 (свеча 3): {A.c2_time.strftime('%Y-%m-%d %H:%M')}")
    if A.direction == "LONG":
        print(f"  Условие LONG: high(c0)={A.bottom:.2f} < low(c2)={A.top:.2f}")
    else:
        print(f"  Условие SHORT: low(c0)={A.top:.2f} > high(c2)={A.bottom:.2f}")
    print(f"  ЗОНА A: [{A.bottom:.2f} ... {A.top:.2f}], ширина {A.top-A.bottom:.2f}")

    # Бары между A.c2 и touch_idx
    untouched_n = touch_idx - A.c2_idx
    print(f"\n  Untouched период: {untouched_n} бар(а) после c2 A")
    print(f"  Свечи в untouched окне:")
    for k in range(A.c2_idx + 1, touch_idx):
        bar = df.iloc[k]
        # Проверка что НЕ касалась зоны A
        if A.direction == "LONG":
            check = "above zone" if bar['low'] > A.top else "?"
        else:
            check = "below zone" if bar['high'] < A.bottom else "?"
        print(f"    {df.index[k].strftime('%Y-%m-%d %H:%M')}: O={bar['open']:.2f} "
              f"H={bar['high']:.2f} L={bar['low']:.2f} C={bar['close']:.2f}  ({check})")

    print(f"\nШАГ 2. ПЕРВОЕ касание зоны FVG-A (touch свеча):")
    print(f"  Время: {touch_time.strftime('%Y-%m-%d %H:%M')} UTC (бар #{touch_idx})")
    bar = df.iloc[touch_idx]
    print(f"  OHLC: O={bar['open']:.2f} H={bar['high']:.2f} L={bar['low']:.2f} C={bar['close']:.2f}")
    if A.direction == "LONG":
        print(f"  Касание: low={bar['low']:.2f} вошёл в зону A [{A.bottom:.2f}..{A.top:.2f}]")
    else:
        print(f"  Касание: high={bar['high']:.2f} вошёл в зону A [{A.bottom:.2f}..{A.top:.2f}]")

    print(f"\nШАГ 3. Эта свеча — часть формации iFVG-B:")
    print(f"  Направление: {B.direction} (ПРОТИВОПОЛОЖНО A)")
    print(f"  c0: {B.c0_time.strftime('%Y-%m-%d %H:%M')}")
    print(f"  c1: {B.c1_time.strftime('%Y-%m-%d %H:%M')}")
    print(f"  c2: {B.c2_time.strftime('%Y-%m-%d %H:%M')}")
    print(f"  c0_idx={B.c0_idx}, c2_idx={B.c2_idx}, touch_idx={touch_idx}")
    if B.c0_idx == touch_idx:
        c_pos = "c0"
    elif B.c2_idx == touch_idx:
        c_pos = "c2"
    else:
        c_pos = "c1"
    print(f"  Touch-свеча = {c_pos} новой iFVG-B")
    if B.direction == "LONG":
        print(f"  Условие LONG B: high(c0)={B.bottom:.2f} < low(c2)={B.top:.2f}")
    else:
        print(f"  Условие SHORT B: low(c0)={B.top:.2f} > high(c2)={B.bottom:.2f}")
    print(f"  ЗОНА B (iFVG): [{B.bottom:.2f} ... {B.top:.2f}], ширина {B.top-B.bottom:.2f}")

    # Overlap A и B
    overlap_b = max(A.bottom, B.bottom)
    overlap_t = min(A.top, B.top)
    print(f"\n  Пересечение зон A и B: [{overlap_b:.2f} ... {overlap_t:.2f}], "
          f"ширина {overlap_t - overlap_b:.2f}")

    print(f"\nШАГ 4. ИНВЕРСИЯ — что произошло со структурой:")
    if A.direction == "LONG":
        print(f"  ДО: зона [{A.bottom:.2f}..{A.top:.2f}] = bull FVG = SUPPORT")
        print(f"      Цена ожидалась bounce ВВЕРХ от этой зоны.")
        print(f"  ПОСЛЕ iFVG-B (bear): bull FVG пробит, B сверху = RESISTANCE.")
        print(f"      Структура развернулась: BULLISH -> BEARISH")
    else:
        print(f"  ДО: зона [{A.bottom:.2f}..{A.top:.2f}] = bear FVG = RESISTANCE")
        print(f"      Цена ожидалась bounce ВНИЗ от этой зоны.")
        print(f"  ПОСЛЕ iFVG-B (bull): bear FVG пробит, B снизу = SUPPORT.")
        print(f"      Структура развернулась: BEARISH -> BULLISH")

    # Что произошло после iFVG-B (5 баров после c2 B)
    print(f"\nШАГ 5. Что произошло ПОСЛЕ iFVG (следующие 5 баров):")
    for k in range(B.c2_idx + 1, min(len(df), B.c2_idx + 6)):
        bar = df.iloc[k]
        # Tracking: цена вернулась в зону A? Или нет?
        in_A = False
        if A.direction == "LONG":
            in_A = bar['low'] <= A.top and bar['high'] >= A.bottom
        else:
            in_A = bar['high'] >= A.bottom and bar['low'] <= A.top
        in_B = False
        if B.direction == "LONG":
            in_B = bar['low'] <= B.top and bar['high'] >= B.bottom
        else:
            in_B = bar['high'] >= B.bottom and bar['low'] <= B.top
        flags = []
        if in_A: flags.append("в зоне A")
        if in_B: flags.append("в зоне B")
        flags_str = ", ".join(flags) if flags else "вне обеих зон"
        print(f"    {df.index[k].strftime('%Y-%m-%d %H:%M')}: O={bar['open']:.2f} "
              f"H={bar['high']:.2f} L={bar['low']:.2f} C={bar['close']:.2f}  ({flags_str})")


if __name__ == "__main__":
    main()
