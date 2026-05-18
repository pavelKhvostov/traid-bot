"""Этап 89: Python-реализация Pine-индикатора 'Volume in Candle' (ViC ASVK)
для 1h таймфрейма с настройками auto=true, mlt=100, prem=false.

Pine-логика для 1h chart:
  tfC = 3600s (1h)
  rs_raw = tfC / mlt = 3600/100 = 36s
  rs = math.max(60, 36) = 60s  # non-premium минимум
  LTF = timeframe.from_seconds(60) = "1m"

Для каждого 1h бара:
  1. Собираем все 1m бары внутри него.
  2. bV = volume где close>open, sV = volume где close<open, nV где close==open.
  3. bullV = bV.sum(), bearV = sV.sum()
  4. delta = bullV - bearV
  5. maxV = close LTF-бара с максимальным dirVolume:
       - если bV.max() > sV.max() -> close бара из bull-стороны с max volume
       - иначе -> close бара из bear-стороны с max volume

Используем canon-логику из vic_levels.calculate_vic_d, обобщённую на 1h окно.
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

from data_manager import load_df


def calculate_vic_for_1h_bar(
    df_1m: pd.DataFrame,
    bar_open_time: pd.Timestamp,
) -> dict | None:
    """ViC значения для одного 1h бара по 1m LTF.

    bar_open_time — open_time 1h бара (UTC, aligned to hour).
    Возвращает: {maxV, bullV, bearV, neutralV, vol, delta, n_ltf_bars}
    или None если нет 1m данных в окне.
    """
    bar_end = bar_open_time + pd.Timedelta(hours=1)
    mask = (df_1m.index >= bar_open_time) & (df_1m.index < bar_end)
    win = df_1m.loc[mask]
    if win.empty:
        return None

    bull = win[win["close"] > win["open"]]
    bear = win[win["close"] < win["open"]]
    neutral = win[win["close"] == win["open"]]

    bullV = float(bull["volume"].sum()) if not bull.empty else 0.0
    bearV = float(bear["volume"].sum()) if not bear.empty else 0.0
    neutralV = float(neutral["volume"].sum()) if not neutral.empty else 0.0
    vol = bullV + bearV
    delta = bullV - bearV

    # maxV: close LTF-бара с максимальным dirVolume (по правилу Pine).
    max_bull = bull["volume"].max() if not bull.empty else 0
    max_bear = bear["volume"].max() if not bear.empty else 0

    maxV = None
    if max_bull > max_bear:
        maxV = float(bull.loc[bull["volume"].idxmax(), "close"])
    elif max_bear > 0:
        # max_bear >= max_bull (включая равенство — bear выигрывает per Pine spec)
        maxV = float(bear.loc[bear["volume"].idxmax(), "close"])

    return {
        "maxV": maxV,
        "bullV": bullV,
        "bearV": bearV,
        "neutralV": neutralV,
        "vol": vol,
        "delta": delta,
        "n_ltf_bars": int(len(win)),
        "open": float(win.iloc[0]["open"]),
        "close": float(win.iloc[-1]["close"]),
        "high": float(win["high"].max()),
        "low": float(win["low"].min()),
    }


def main():
    print("[INFO] Загружаем BTCUSDT 1m + 1h")
    df_1m = load_df("BTCUSDT", "1m")
    df_1h = load_df("BTCUSDT", "1h")

    if df_1m.empty or df_1h.empty:
        print("[ERROR] нет данных")
        return

    print(f"  1m: {len(df_1m)} баров, range {df_1m.index[0]} -> {df_1m.index[-1]}")
    print(f"  1h: {len(df_1h)} баров, range {df_1h.index[0]} -> {df_1h.index[-1]}")

    # Берём последние 12 закрытых 1h баров.
    # Последний 1h в df_1h может быть незакрытым; берём last_closed.
    now = pd.Timestamp.now(tz="UTC")
    current_hour_open = now.floor("h")
    # last closed 1h bar = bar with open_time = current_hour_open - 1h (closed at current_hour_open)
    # Но если now < current_hour_open + 1h, то bar at current_hour_open ещё не закрыт.
    # Берём все 1h бары до current_hour_open exclusive.
    last_closed = df_1h[df_1h.index < current_hour_open].tail(12)
    if last_closed.empty:
        print("[ERROR] нет закрытых 1h баров")
        return

    print(f"\n[INFO] ViC ASVK (auto=true, mlt=100, non-premium -> LTF=1m) на 1h:")
    print(f"\n{'Open time (UTC)':<20} {'OHLC':<35} {'maxV':>12} {'bullV':>12} {'bearV':>12} {'delta':>10} {'1m bars':>8}")
    print("-" * 130)

    for ts, row in last_closed.iterrows():
        result = calculate_vic_for_1h_bar(df_1m, ts)
        if result is None:
            print(f"{ts.strftime('%Y-%m-%d %H:%M'):<20} (нет 1m данных)")
            continue
        ohlc = f"O={result['open']:.0f} H={result['high']:.0f} L={result['low']:.0f} C={result['close']:.0f}"
        maxV_s = f"{result['maxV']:.2f}" if result['maxV'] is not None else "—"
        print(
            f"{ts.strftime('%Y-%m-%d %H:%M'):<20} {ohlc:<35} "
            f"{maxV_s:>12} {result['bullV']:>12.2f} {result['bearV']:>12.2f} "
            f"{result['delta']:>+10.2f} {result['n_ltf_bars']:>8}"
        )

    print()
    print("ИНТЕРПРЕТАЦИЯ:")
    print("  maxV — close 1m свечи внутри 1h бара с максимальным dirVolume.")
    print("         Это и есть линия которая рисуется на чарте (серая горизонталь).")
    print("  bullV, bearV — суммарный bull/bear volume внутри 1h бара.")
    print("  delta = bullV - bearV — общий imbalance, положит = бычий, отриц = медвежий.")
    print("  n 1m bars — сколько 1m-свечей было в этом 1h окне (норма 60).")

    # Сводка по последнему закрытому бару отдельно.
    last_ts = last_closed.index[-1]
    last_result = calculate_vic_for_1h_bar(df_1m, last_ts)
    if last_result:
        print(f"\n>>> ПОСЛЕДНИЙ ЗАКРЫТЫЙ 1h БАР: {last_ts.strftime('%Y-%m-%d %H:%M')} UTC")
        print(f"   OHLC: O={last_result['open']:.2f} H={last_result['high']:.2f} "
              f"L={last_result['low']:.2f} C={last_result['close']:.2f}")
        print(f"   maxV (уровень индикатора): {last_result['maxV']:.2f}")
        print(f"   bullV = {last_result['bullV']:.2f} BTC")
        print(f"   bearV = {last_result['bearV']:.2f} BTC")
        print(f"   delta = {last_result['delta']:+.2f} BTC "
              f"({'+' if last_result['delta'] > 0 else ''}{last_result['delta']/last_result['vol']*100:.1f}% от vol)")


if __name__ == "__main__":
    main()
