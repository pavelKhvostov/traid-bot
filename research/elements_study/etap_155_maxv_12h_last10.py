"""etap_155: Последние 10 значений maxV на 12h для BTC.

maxV логика (см. vic_levels.calculate_vic_d) обобщённая на любое HTF-окно:
  1. Взять все LTF-свечи внутри HTF-окна
  2. Разделить на bull (close>open) и bear (close<open)
  3. max_bull = макс объём среди bull, max_bear = макс объём среди bear
  4. Если max_bull > max_bear -> maxV = close той bull-свечи
     Иначе -> maxV = close той bear-свечи (равенство -> bear)

LTF=5m для 12h (Pine mlt=100: 720/100=7.2m, closest valid = 5m).
"""
from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists(): _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path: _sys.path.insert(0, str(_ROOT))

import pandas as pd
from data_manager import load_df


SYMBOL = "BTCUSDT"
HTF_HOURS = 12
LTF_MINUTES = 5
LAST_N = 10


def calculate_vic_window(df_1m: pd.DataFrame, window_start: pd.Timestamp,
                          window_end: pd.Timestamp, ltf_minutes: int) -> tuple[float | None, str | None, float | None, pd.Timestamp | None]:
    """Возвращает (maxV_close, type ('bull'/'bear'), volume, ltf_candle_open_time)."""
    mask = (df_1m.index >= window_start) & (df_1m.index < window_end)
    win_df = df_1m.loc[mask]
    if win_df.empty:
        return None, None, None, None

    if ltf_minutes > 1:
        win_df = win_df.resample(
            f"{ltf_minutes}min", origin="epoch", label="left", closed="left",
        ).agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }).dropna(subset=["close"])
        if win_df.empty:
            return None, None, None, None

    bull = win_df[win_df["close"] > win_df["open"]]
    bear = win_df[win_df["close"] < win_df["open"]]

    max_bull = bull["volume"].max() if not bull.empty else 0
    max_bear = bear["volume"].max() if not bear.empty else 0

    if max_bull == 0 and max_bear == 0:
        return None, None, None, None

    if max_bull > max_bear:
        idx = bull["volume"].idxmax()
        return float(bull.loc[idx, "close"]), "bull", float(max_bull), idx
    idx = bear["volume"].idxmax()
    return float(bear.loc[idx, "close"]), "bear", float(max_bear), idx


def main():
    df_1m = load_df(SYMBOL, "1m")
    print(f"1m data: {df_1m.index[0]} -> {df_1m.index[-1]}  ({len(df_1m)} rows)")
    print()

    # 12h candles align to 00:00 and 12:00 UTC.
    # Last fully-closed 12h window: window_end must be <= last 1m timestamp + 1min.
    last_ts = df_1m.index[-1]
    # Find last 12h open that has full data
    # 12h open times are multiples of 12h from epoch (aligned 00:00 UTC)
    # For Binance: 12h candles open at 00:00 and 12:00 UTC.
    step = pd.Timedelta(hours=HTF_HOURS)

    # Find the latest 12h open such that open + 12h <= last_ts + 1min (window closed)
    # Simplest: iterate from a recent rounded 12h-open going back
    last_12h_close = last_ts.floor(f"{HTF_HOURS}h")  # last 12h-open at or before last_ts
    # Check if this 12h window is fully closed
    if last_12h_close + step > last_ts + pd.Timedelta(minutes=1):
        last_12h_close -= step  # take previous fully-closed
    # Now collect LAST_N windows ending at last_12h_close + step (going backward)
    windows = []
    cur_open = last_12h_close
    for _ in range(LAST_N):
        cur_close = cur_open + step
        windows.append((cur_open, cur_close))
        cur_open -= step
    windows.reverse()  # chronological order

    print(f"Последние {LAST_N} закрытых 12h-свечей BTC (LTF={LTF_MINUTES}m):")
    print(f"{'-'*100}")
    print(f"{'#':>2}  {'12h open (UTC)':<20}  {'12h close (UTC)':<20}  "
          f"{'type':<5}  {'maxV close':>11}  {'LTF candle open':<20}  {'volume':>14}")
    print(f"{'-'*100}")
    for i, (w_open, w_close) in enumerate(windows, 1):
        maxv, kind, vol, ltf_open = calculate_vic_window(df_1m, w_open, w_close, LTF_MINUTES)
        if maxv is None:
            print(f"{i:>2}  {w_open.strftime('%Y-%m-%d %H:%M'):<20}  "
                  f"{w_close.strftime('%Y-%m-%d %H:%M'):<20}  no data")
            continue
        ltf_str = ltf_open.strftime('%Y-%m-%d %H:%M') if ltf_open is not None else "-"
        print(f"{i:>2}  {w_open.strftime('%Y-%m-%d %H:%M'):<20}  "
              f"{w_close.strftime('%Y-%m-%d %H:%M'):<20}  "
              f"{kind:<5}  {maxv:>11.2f}  {ltf_str:<20}  {vol:>14,.2f}")


if __name__ == "__main__":
    main()
