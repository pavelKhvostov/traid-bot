"""Загрузка CRYPTOCAP-индикаторов из TradingView в формат проекта.

Качает USDT.D, TOTAL, TOTAL2, BTC.D и др. из CRYPTOCAP exchange и
сохраняет в `data/<SYMBOL>_<TF>.csv` совместимо с `data_manager.load_df`.

Запуск:
    python fetch_tv_data.py                 # все индикаторы, все ТФ по умолчанию
    python fetch_tv_data.py USDT.D TOTAL    # только указанные

Лимиты анонимного режима: ~5000 баров на запрос. Для daily = ~13 лет, для
1h = ~7 месяцев, для 15m = ~52 дня. Если нужно больше — логин TradingView
(передать username / password в TvDatafeed).
"""
from __future__ import annotations

import datetime as _dt
import re
import sys
from pathlib import Path

import pandas as pd
import requests
from tvDatafeed import Interval, TvDatafeed

from config import DATA_DIR, TV_PASSWORD, TV_SESSION_ID, TV_USERNAME

# tvDatafeed возвращает naive datetime в локальном TZ системы (не в UTC).
# Разница между локальным и UTC берётся динамически (работает с DST).
LOCAL_UTC_OFFSET = _dt.datetime.now().astimezone().utcoffset()

# (TV_SYMBOL, EXCHANGE, FILENAME_BASE)
DEFAULT_SYMBOLS = [
    ("USDT.D",  "CRYPTOCAP", "USDT_D"),   # USDT dominance %
    ("TOTALES", "CRYPTOCAP", "TOTALES"),  # TOTAL без всех stablecoins
    ("BTC1!",   "CME",       "BTC1"),     # CME continuous Bitcoin futures
]

# (TF_LABEL, Interval, n_bars). 5000 — анонимный лимит.
TFS = [
    ("1d",  Interval.in_daily,    5000),
    ("4h",  Interval.in_4_hour,   5000),
    ("1h",  Interval.in_1_hour,   5000),
    ("15m", Interval.in_15_minute, 5000),
]


def auth_token_from_sessionid(sessionid: str) -> str | None:
    """Извлечь auth_token из tradingview.com при заданном sessionid cookie.

    Browser-логин TV кладёт два значения: cookie `sessionid` (для HTTP-сессии)
    и `auth_token` (для WS-данных). Лиа использует только auth_token. Получаем
    его из HTML главной страницы — она содержит inline JSON с этим токеном
    когда запрос идёт от залогиненного юзера.
    """
    cookies = {"sessionid": sessionid}
    headers = {"User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )}
    try:
        r = requests.get("https://www.tradingview.com/disclaimer/",
                         cookies=cookies, headers=headers, timeout=15)
        r.raise_for_status()
    except Exception as e:
        print(f"[WARN] HTTP к TV не удался: {e!r}")
        return None
    m = re.search(r'"auth_token":"([^"]+)"', r.text)
    if not m:
        return None
    return m.group(1)


def fetch_one(tv: TvDatafeed, tv_symbol: str, exchange: str,
              file_base: str, tf_label: str, interval: Interval, n_bars: int,
              retries: int = 3) -> int:
    import time as _time
    df = None
    for attempt in range(1, retries + 1):
        try:
            df = tv.get_hist(symbol=tv_symbol, exchange=exchange,
                             interval=interval, n_bars=n_bars)
        except Exception as e:
            print(f"  [WARN] {tv_symbol} {tf_label} attempt {attempt}: {type(e).__name__}: {e}")
            df = None
        if df is not None and not df.empty:
            break
        if attempt < retries:
            _time.sleep(3 * attempt)  # 3s, 6s backoff
    if df is None or df.empty:
        print(f"  [WARN] {tv_symbol} {tf_label}: пусто после {retries} попыток")
        return 0

    # tvDatafeed возвращает naive index (UTC seconds -> naive datetime).
    # Локализуем к UTC, чтобы format совпал с data/<BTCUSDT>_<tf>.csv.
    out = pd.DataFrame({
        "open":   df["open"].astype(float),
        "high":   df["high"].astype(float),
        "low":    df["low"].astype(float),
        "close":  df["close"].astype(float),
        "volume": df["volume"].astype(float),
    })
    # tvDatafeed index в локальном TZ → конвертим в UTC.
    out.index = pd.to_datetime(df.index)
    if out.index.tz is None:
        out.index = (out.index - LOCAL_UTC_OFFSET).tz_localize("UTC")
    else:
        out.index = out.index.tz_convert("UTC")
    out.index.name = "open_time"
    out = out.sort_index()
    out = out[~out.index.duplicated(keep="last")]

    # Отрезаем последний незакрытый бар (если попался).
    # Для тщательности: TF в минутах * 60 секунд, проверяем что
    # last_open + tf_seconds <= now.
    tf_seconds = {"1d": 86400, "4h": 14400, "1h": 3600,
                  "30m": 1800, "15m": 900, "5m": 300, "1m": 60}.get(tf_label, 0)
    if tf_seconds:
        now = pd.Timestamp.now(tz="UTC")
        last = out.index[-1]
        if last + pd.Timedelta(seconds=tf_seconds) > now:
            out = out.iloc[:-1]

    path = DATA_DIR / f"{file_base}_{tf_label}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path)
    print(f"  {tv_symbol} {tf_label}: {len(out)} строк -> {path}")
    return len(out)


def main() -> None:
    args = sys.argv[1:]
    if args:
        # Фильтр по TV-символу: python fetch_tv_data.py USDT.D TOTAL
        symbols = [(s, e, f) for s, e, f in DEFAULT_SYMBOLS if s in args]
        missing = set(args) - {s for s, _, _ in DEFAULT_SYMBOLS}
        if missing:
            print(f"[WARN] неизвестные символы: {missing}")
    else:
        symbols = DEFAULT_SYMBOLS

    tv = TvDatafeed()  # стартуем как анонимный, перезапишем токен если есть
    if TV_SESSION_ID:
        token = auth_token_from_sessionid(TV_SESSION_ID)
        if token:
            tv.token = token
            print(f"[INFO] tvDatafeed (auth via sessionid, token len={len(token)})")
        else:
            print(f"[WARN] sessionid задан, но auth_token не извлечён — fallback to anonymous")
    elif TV_USERNAME and TV_PASSWORD:
        print(f"[INFO] tvDatafeed (logged in as {TV_USERNAME})")
        tv = TvDatafeed(username=TV_USERNAME, password=TV_PASSWORD)
    else:
        print(f"[INFO] tvDatafeed (anonymous), лимит ~5000 баров на запрос")
        print(f"      Для логина: TV_USERNAME/TV_PASSWORD или TV_SESSION_ID в .env")
    print(f"[INFO] символы: {[s for s, _, _ in symbols]}")
    print(f"[INFO] ТФ: {[t for t, _, _ in TFS]}")
    print()
    total_rows = 0
    for tv_symbol, exchange, file_base in symbols:
        print(f"--- {tv_symbol} ({exchange}) -> {file_base} ---")
        for tf_label, interval, n_bars in TFS:
            try:
                total_rows += fetch_one(
                    tv, tv_symbol, exchange, file_base,
                    tf_label, interval, n_bars,
                )
            except Exception as e:
                print(f"  [ERROR] {tv_symbol} {tf_label}: {e!r}")
        print()

    print(f"[DONE] записано строк: {total_rows}")
    print()
    print("Использование в коде:")
    print("  from data_manager import load_df")
    print("  df = load_df('USDT_D', '1d')")
    print("  df = load_df('TOTAL', '4h')")


if __name__ == "__main__":
    main()
