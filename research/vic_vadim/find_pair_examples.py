"""ViC Vadim — поиск пар D-свечей подряд, у которых:
  - close > maxV для обеих свечей
  - maxV в нижней тени (low ≤ maxV ≤ min(open, close)) для обеих

LTF=15m по соглашению проекта (см. vic_levels.py / VIC_LTF_MINUTES=15).
Скрипт фетчит 15m с Binance, агрегирует в 1d, считает maxV для каждой D-свечи.

Запуск:
    .venv/bin/python research/vic_vadim/find_pair_examples.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from vic_levels import calculate_vic_d

SYMBOL = "BTCUSDT"
INTERVAL_15M = "15m"
BINANCE_URL = "https://api.binance.com/api/v3/klines"
# 2 года данных — компромисс между скачиванием и покрытием
START = pd.Timestamp("2024-05-01", tz="UTC")
END = pd.Timestamp("2026-05-20", tz="UTC")
CACHE = ROOT / "data" / f"{SYMBOL}_15m_vic_vadim.csv"


def fetch_15m(start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    if CACHE.exists():
        df = pd.read_csv(CACHE, parse_dates=["open_time"], index_col="open_time")
        df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
        if df.index.min() <= start and df.index.max() >= end - pd.Timedelta(minutes=15):
            print(f"cache hit: {len(df)} 15m bars from {df.index.min()} to {df.index.max()}")
            return df

    rows: list[list] = []
    cur = start
    while cur < end:
        params = {
            "symbol": SYMBOL,
            "interval": INTERVAL_15M,
            "startTime": int(cur.timestamp() * 1000),
            "limit": 1000,
        }
        r = requests.get(BINANCE_URL, params=params, timeout=20)
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        rows.extend(batch)
        last_close = pd.to_datetime(batch[-1][6], unit="ms", utc=True)
        if last_close <= cur:
            break
        cur = last_close + pd.Timedelta(milliseconds=1)
        time.sleep(0.15)
        print(f"  fetched up to {last_close.date()}, total {len(rows)} bars", end="\r")

    print()
    df = pd.DataFrame(rows, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "qav", "trades", "tbv", "tqv", "ignore",
    ])
    df = df[["open_time", "open", "high", "low", "close", "volume"]].copy()
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = df[c].astype(float)
    df = df.set_index("open_time").sort_index()
    df = df[~df.index.duplicated(keep="first")]
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(CACHE)
    print(f"saved cache: {CACHE} ({len(df)} bars)")
    return df


def aggregate_to_daily(df_15m: pd.DataFrame) -> pd.DataFrame:
    d = df_15m.resample("1D", origin="epoch", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna(subset=["close"])
    return d


def main() -> None:
    df_15m = fetch_15m(START, END)
    # calculate_vic_d ожидает 1m, но при ltf_minutes=15 ресемплит сам.
    # У нас уже 15m → передадим как есть, выставив ltf_minutes=1 (no-op resample).
    df_in = df_15m.copy()
    df_in.index.name = None

    df_d = aggregate_to_daily(df_15m)
    print(f"\n{len(df_d)} D-свечей с {df_d.index.min().date()} до {df_d.index.max().date()}")

    # maxV для каждой D-свечи: считаем напрямую из 15m баров этого дня
    maxv_list: list[float | None] = []
    for day in df_d.index:
        v = calculate_vic_d(df_in, day, ltf_minutes=1)  # 15m свечи уже native
        maxv_list.append(v)
    df_d["maxV"] = maxv_list
    df_d = df_d.dropna(subset=["maxV"])

    # Новое условие 1 (LONG-сетап):
    #   D[i-1] = bearish (close < open) — "short" в смысле красная
    #   D[i]   = bullish (close > open) — "long"  в смысле зелёная
    #   close(D[i-1]) > maxV(D[i-1]) И close(D[i-1]) > maxV(D[i])
    #   open(D[i])    > maxV(D[i-1]) И open(D[i])    > maxV(D[i])
    # Поскольку на BTC 1d Binance close(i-1) == open(i), точка стыка выше обоих maxV.
    df_d["is_red"] = df_d["close"] < df_d["open"]
    df_d["is_green"] = df_d["close"] > df_d["open"]

    prev_red = df_d["is_red"].shift(1).fillna(False).astype(bool)
    prev_close = df_d["close"].shift(1)
    prev_maxv = df_d["maxV"].shift(1)

    cond_colors = prev_red & df_d["is_green"]  # red → green
    cond_close_above_both = (prev_close > prev_maxv) & (prev_close > df_d["maxV"])
    cond_open_above_both = (df_d["open"] > prev_maxv) & (df_d["open"] > df_d["maxV"])
    df_d["pair_long"] = cond_colors & cond_close_above_both & cond_open_above_both

    print(f"\nкрасных D-свечей: {df_d['is_red'].sum()}, зелёных: {df_d['is_green'].sum()}")
    print(f"red→green пар: {cond_colors.sum()}")
    print(f"   + close(i-1) > обоих maxV: {(cond_colors & cond_close_above_both).sum()}")
    print(f"   + open(i)    > обоих maxV: {(cond_colors & cond_close_above_both & cond_open_above_both).sum()}")
    print(f"итого LONG-кандидатов: {df_d['pair_long'].sum()}")

    pairs = df_d[df_d["pair_long"]]
    if pairs.empty:
        print("\nПар не найдено — нужно ослабить условие или расширить окно.")
        return

    print(f"\n=== Первые {min(3, len(pairs))} LONG-примеров (red→green) ===\n")
    for k in range(min(3, len(pairs))):
        end_day = pairs.index[k]
        end_pos = df_d.index.get_loc(end_day)
        s1 = df_d.iloc[end_pos - 1]
        s2 = df_d.iloc[end_pos]
        print(f"Пример {k+1}: {s1.name.date()} (red) → {s2.name.date()} (green)")
        for tag, row in (("  D[i-1]", s1), ("  D[i]  ", s2)):
            o, h, l, c, m = row["open"], row["high"], row["low"], row["close"], row["maxV"]
            color = "red" if c < o else ("green" if c > o else "doji")
            print(
                f"{tag} {color:5}: o={o:>9.2f} h={h:>9.2f} l={l:>9.2f} "
                f"c={c:>9.2f} maxV={m:>9.2f}",
            )
        junction = s1["close"]  # = s2["open"] на 24/7 рынке
        m1, m2 = s1["maxV"], s2["maxV"]
        print(
            f"  стык: close(i-1)={s1['close']:.2f} == open(i)={s2['open']:.2f}, "
            f"выше maxV(i-1)={m1:.2f} на {junction - m1:+.2f}, "
            f"выше maxV(i)={m2:.2f} на {junction - m2:+.2f}",
        )
        print()


if __name__ == "__main__":
    main()
