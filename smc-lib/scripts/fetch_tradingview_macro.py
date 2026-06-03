"""Скачать с TradingView (через tvDatafeed) macro-индексы для confluence:
  - CRYPTOCAP:USDT.D — USDT dominance (наш Правило 12)
  - CRYPTOCAP:TOTAL  — общая капа (соответствует существующему TOTALES_*.csv)
  - CRYPTOCAP:TOTAL2 — без BTC (для контр-проверки)

Период: с 2020-01-01 до сегодня (~2350 1d баров).
Anonymous mode: до 5000 баров/запрос — хватает.

Output:
  ~/traid-bot/data/USDT_D_1d.csv
  ~/traid-bot/data/TOTAL_1d.csv (renamed from TOTALES_1d to явно указать)
  ~/traid-bot/data/TOTAL2_1d.csv
"""
from __future__ import annotations
import pathlib
from datetime import datetime, timezone
import pandas as pd
from tvDatafeed import TvDatafeed, Interval

tv = TvDatafeed()
DATA = pathlib.Path.home() / "traid-bot/data"

# 2350 баров daily ≈ 6.4 года, покрывает с 2020-01-01 до сейчас
N_BARS = 2400

SYMBOLS = [
    ('USDT.D', 'USDT_D_1d.csv', 'USDT dominance %'),
    ('TOTAL',  'TOTAL_1d.csv',  'Crypto total market cap (incl. stables)'),
    ('TOTAL2', 'TOTAL2_1d.csv', 'Total minus BTC'),
    ('TOTAL3', 'TOTAL3_1d.csv', 'Total minus BTC and ETH'),
]

for symbol, fname, desc in SYMBOLS:
    print(f"\n=== {symbol} ({desc}) ===")
    try:
        df = tv.get_hist(symbol=symbol, exchange='CRYPTOCAP',
                          interval=Interval.in_daily, n_bars=N_BARS)
        if df is None or df.empty:
            print(f"  EMPTY result"); continue
        # Rename to standard format like BTC csv
        df = df.copy()
        df.index = pd.to_datetime(df.index, utc=True)
        df = df[['open','high','low','close','volume']].copy()
        df.index.name = 'open_time'
        out = DATA / fname
        df.to_csv(out)
        print(f"  Bars: {len(df):,}")
        print(f"  Range: {df.index[0]} → {df.index[-1]}")
        print(f"  First close: {df['close'].iloc[0]:.4f}")
        print(f"  Last close:  {df['close'].iloc[-1]:.4f}")
        print(f"  Saved → {out}")
    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {e}")
