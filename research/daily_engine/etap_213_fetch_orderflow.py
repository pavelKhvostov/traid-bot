"""etap_213 — догрузить ORDER FLOW (taker_buy) из Binance klines.

Пайплайн проекта дропает taker_buy при чистке в OHLCV (Harris: signed order flow —
нетронутый фронтир). Тащим raw 1h klines с taker_buy_base/quote + num_trades,
сохраняем отдельный CSV. Дельта = 2*taker_buy − volume (= taker_buy − taker_sell).

Запуск: venv/Scripts/python.exe research/daily_engine/etap_213_fetch_orderflow.py
"""
from __future__ import annotations
import sys, time
from pathlib import Path
import numpy as np, pandas as pd, requests

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

URL = "https://api.binance.com/api/v3/klines"
OUT = Path(__file__).resolve().parent.parent.parent / "data" / "BTCUSDT_1h_orderflow.csv"
START = pd.Timestamp("2020-01-01", tz="UTC")


def get(params, tries=5):
    for i in range(tries):
        try:
            r = requests.get(URL, params=params, timeout=20)
            if r.status_code == 200:
                return r.json()
            time.sleep(1.5 * (i + 1))
        except Exception:
            time.sleep(1.5 * (i + 1))
    return []


def main():
    start_ms = int(START.timestamp() * 1000)
    end_ms = int(time.time() * 1000)
    rows, cur = [], start_ms
    print("Тащу 1h klines с taker_buy...")
    while cur < end_ms:
        data = get(dict(symbol="BTCUSDT", interval="1h", startTime=cur, limit=1000))
        if not data:
            break
        rows += data
        cur = data[-1][0] + 3600_000
        if len(rows) % 10000 < 1000:
            print(f"  {len(rows)} баров... до {pd.to_datetime(data[-1][0], unit='ms')}")
        time.sleep(0.25)
    df = pd.DataFrame(rows, columns=["open_time", "open", "high", "low", "close", "volume",
                                     "close_time", "quote_vol", "num_trades",
                                     "taker_buy_base", "taker_buy_quote", "ignore"])
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    for c in ["open", "high", "low", "close", "volume", "taker_buy_base", "taker_buy_quote", "num_trades"]:
        df[c] = pd.to_numeric(df[c])
    df = df.drop_duplicates("open_time").set_index("open_time").sort_index()
    df["delta"] = 2 * df["taker_buy_base"] - df["volume"]          # taker_buy − taker_sell
    df["delta_norm"] = df["delta"] / df["volume"].replace(0, np.nan)
    keep = ["open", "high", "low", "close", "volume", "taker_buy_base", "num_trades", "delta", "delta_norm"]
    df[keep].to_csv(OUT)
    print(f"Saved {len(df)} rows → {OUT}")
    print(f"  range {df.index[0]} → {df.index[-1]}")
    print(f"  delta_norm: mean {df['delta_norm'].mean():+.3f} std {df['delta_norm'].std():.3f}")


if __name__ == "__main__":
    main()
