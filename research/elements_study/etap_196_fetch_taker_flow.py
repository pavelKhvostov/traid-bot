"""etap_196 — фетч klines С taker-buy потоком (для trend-continuation pullback study).

Зачем: live-пайплайн (data_manager.normalize_df) дропает taker_buy_base/quote —
остаётся чистый OHLCV. Для order-flow части синтеза 3 книг (Harris: CVD/delta,
absorption) нужны поля index 9/10 из klines. Этот скрипт качает их в ОТДЕЛЬНЫЕ CSV,
не трогая боевые data/<SYM>_<tf>.csv.

Выход: research/elements_study/data/<SYM>_<tf>_flow.csv с колонками:
  open_time, open, high, low, close, volume, quote_volume, trades,
  taker_buy_base, taker_buy_quote, delta, cvd, taker_buy_ratio

delta = 2*taker_buy_base - volume   (Harris §4.2)
cvd   = cumsum(delta)
taker_buy_ratio = taker_buy_base / volume   ∈ [0,1]

Запуск (proxy сниму прямо тут, см. pitfall socks-proxy-блокирует-binance-rest):
  venv/Scripts/python.exe research/elements_study/etap_196_fetch_taker_flow.py
"""
from __future__ import annotations

# ВАЖНО: на ЭТОЙ локальной Windows-машине Binance доступен ТОЛЬКО через
# системный прокси (VPN, прописан в реестре Windows — requests подхватывает его
# автоматически, хотя env-переменные HTTP_PROXY/etc пустые). НЕ ставить
# NO_PROXY="*" и НЕ снимать прокси — иначе прямое соединение к api.binance.com
# виснет на read-timeout. Это ОБРАТНАЯ ситуация к pitfall
# «socks-proxy-блокирует-binance-rest» (тот был про VPS с SOCKS-env + нет pysocks).
import sys
import time
from pathlib import Path

import pandas as pd
import requests

# Windows-консоль по умолчанию cp1251 → юникод (стрелки/кириллица) в print падает.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# data-api.binance.vision — профильный публичный market-data хост (стабильнее
# api.binance.com для bulk-выкачки, без geo/rate сюрпризов).
BINANCE_KLINES_URL = "https://data-api.binance.vision/api/v3/klines"

KLINE_COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "trades",
    "taker_buy_base", "taker_buy_quote", "ignore",
]
KEEP = ["open", "high", "low", "close", "volume", "quote_volume", "trades",
        "taker_buy_base", "taker_buy_quote"]

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
TFS = ["1h", "12h"]
START = "2020-01-01"

OUT_DIR = Path(__file__).resolve().parent / "data"


def tf_to_ms(tf: str) -> int:
    unit, n = tf[-1], int(tf[:-1])
    return n * {"m": 60_000, "h": 3_600_000, "d": 86_400_000}[unit]


def _get(url: str, params: dict, retries: int = 5) -> requests.Response:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=30)
            r.raise_for_status()
            return r
        except (requests.exceptions.ConnectionError,
                requests.exceptions.Timeout) as e:
            last = e
            wait = 2 ** (attempt + 1)
            print(f"  [WARN] net error {attempt+1}/{retries}: {type(e).__name__}, retry {wait}s")
            time.sleep(wait)
    assert last is not None
    raise last


def fetch_flow(symbol: str, tf: str) -> pd.DataFrame:
    start_ms = int(pd.Timestamp(START, tz="UTC").timestamp() * 1000)
    step = tf_to_ms(tf)
    now_ms = int(time.time() * 1000)
    end_ms = (now_ms // step) * step  # отсечь незакрытый бар
    rows: list[list] = []
    cur = start_ms
    while True:
        params = {"symbol": symbol, "interval": tf, "startTime": cur,
                  "endTime": end_ms, "limit": 1000}
        batch = _get(BINANCE_KLINES_URL, params).json()
        if not batch:
            break
        rows.extend(batch)
        last_open = batch[-1][0]
        cur = last_open + step
        if len(batch) < 1000 or cur >= end_ms:
            break
        time.sleep(0.15)
    if not rows:
        return pd.DataFrame(columns=["open_time"] + KEEP)

    df = pd.DataFrame(rows, columns=KLINE_COLUMNS)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df = df.set_index("open_time")
    for c in KEEP:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df[KEEP]
    df = df[~df.index.duplicated(keep="last")].sort_index()

    # отрезать незакрытый бар на всякий
    if not df.empty:
        last_open_ms = int(df.index[-1].timestamp() * 1000)
        if last_open_ms + step > now_ms:
            df = df.iloc[:-1]

    # производные потока (Harris)
    df["delta"] = 2 * df["taker_buy_base"] - df["volume"]
    df["cvd"] = df["delta"].cumsum()
    df["taker_buy_ratio"] = (df["taker_buy_base"] / df["volume"]).where(df["volume"] > 0)
    return df


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for sym in SYMBOLS:
        for tf in TFS:
            print(f"[fetch] {sym} {tf} ...", flush=True)
            df = fetch_flow(sym, tf)
            if df.empty:
                print(f"  EMPTY (нет данных)")
                continue
            path = OUT_DIR / f"{sym}_{tf}_flow.csv"
            df.index.name = "open_time"
            df.to_csv(path)
            # sanity: доля баров с taker_buy<=volume (должна быть ~100%)
            ok = float((df["taker_buy_base"] <= df["volume"] + 1e-6).mean())
            print(f"  {len(df)} bars {df.index[0].date()}..{df.index[-1].date()} "
                  f"| ratio med={df['taker_buy_ratio'].median():.3f} "
                  f"| taker<=vol {ok:.1%} | -> {path.name}", flush=True)


if __name__ == "__main__":
    main()
