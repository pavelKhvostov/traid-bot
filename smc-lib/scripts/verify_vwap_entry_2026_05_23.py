"""Проверка VWAP-entry на эталонном паттерне 2026-05-23 LONG.

Алгоритм:
1. Паттерн на 1h: C1=2026-05-23 02:00 MSK, pattern_low = 75220.00 (C2)
2. Найти 5m свечу, содержащую pattern_low → anchor VWAP
3. VWAP по формуле ASVK: cum(vol*close) / cum(vol) с 1m данных
4. Сканировать 1m бары после C5 close, ждать когда vwap попадёт в диапазон [low, high]
5. Проверить ожидание: ~20:20 MSK 2026-05-23
"""
from __future__ import annotations

import csv
import pathlib
import sys
from datetime import datetime, timedelta, timezone

CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MSK = timezone(timedelta(hours=3))


def load_1m_full():
    """Возвращает list[(ts_ms, o, h, l, c, v)]."""
    rows = []
    with CSV_PATH.open() as f:
        reader = csv.reader(f)
        next(reader)
        for r in reader:
            t = datetime.fromisoformat(r[0])
            rows.append((int(t.timestamp() * 1000), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
    return rows


def fmt(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(MSK).strftime("%Y-%m-%d %H:%M")


print("Loading 1m...")
data = load_1m_full()
print(f"Loaded {len(data):,} 1m rows\n")

ts_arr = [r[0] for r in data]


def idx_at(ms):
    lo, hi = 0, len(ts_arr)
    while lo < hi:
        mid = (lo + hi) // 2
        if ts_arr[mid] < ms:
            lo = mid + 1
        else:
            hi = mid
    return lo


# Эталон 2026-05-23 LONG:
# C2 = 2026-05-23 03:00 MSK = 00:00 UTC, low = 75220.00
# Pattern_low = 75220.00, ищем 1m где это произошло
pattern_low = 75220.00
c1_start_msk = "2026-05-23 02:00"
c5_close_msk = "2026-05-23 07:00"  # C5 opens at 06:00, closes at 07:00 MSK

# Найти 1m свечу с low == 75220.00
c2_start_ms = int(datetime.fromisoformat("2026-05-23 00:00:00+00:00").timestamp() * 1000)
c2_end_ms = c2_start_ms + 3600_000

j_low = None
for k in range(idx_at(c2_start_ms), idx_at(c2_end_ms)):
    if data[k][3] == pattern_low:
        j_low = k
        break

if j_low is None:
    # ближайшее минимум
    bestl = float("inf"); bestk = None
    for k in range(idx_at(c2_start_ms), idx_at(c2_end_ms)):
        if data[k][3] < bestl:
            bestl = data[k][3]
            bestk = k
    j_low = bestk
    print(f"Точное low не найдено, ближайший минимум: {data[j_low][3]} в {fmt(data[j_low][0])}")
else:
    print(f"Pattern low 75220.00 найден на 1m свече: {fmt(data[j_low][0])} MSK")

# Якорим VWAP на 5m свече, содержащей этот 1m
# 5m свеча начинается с минуты, кратной 5
low_ms = data[j_low][0]
anchor_5m_ms = low_ms - (low_ms % (5 * 60_000))
print(f"5m anchor: {fmt(anchor_5m_ms)} MSK\n")

# Считаем VWAP с anchor_5m_ms
# Цель entry: проверить, проходит ли VWAP через [low, high] 1m бара после C5 close
c5_close_ms = int(datetime.fromisoformat("2026-05-23 04:00:00+00:00").timestamp() * 1000)  # C5 opens 06:00 MSK = 03:00 UTC, closes 04:00 UTC = 07:00 MSK

block_top = 75500.00  # для эталона

cum_pv = 0.0
cum_vol = 0.0
anchor_idx = idx_at(anchor_5m_ms)
fill_idx = None
fill_vwap = None

# Сначала наберём VWAP до C5 close (не торгуем, только аккумулируем)
for k in range(anchor_idx, len(data)):
    ts, o, h, l, c, v = data[k]
    cum_pv += v * c
    cum_vol += v
    vwap = cum_pv / cum_vol

    # после C5 close — ищем fill
    if ts >= c5_close_ms:
        # check VWAP внутри диапазона свечи (LONG fill)
        if l <= vwap <= h:
            # доп условие: VWAP не выше block.top
            if vwap <= block_top:
                fill_idx = k
                fill_vwap = vwap
                break

if fill_idx is None:
    print("Fill не найден")
else:
    ts = data[fill_idx][0]
    print(f"VWAP entry triggered at {fmt(ts)} MSK")
    print(f"  VWAP value: {fill_vwap:.2f}")
    print(f"  1m bar OHLC: O={data[fill_idx][1]:.2f} H={data[fill_idx][2]:.2f} L={data[fill_idx][3]:.2f} C={data[fill_idx][4]:.2f}")
    print(f"  Check: VWAP {fill_vwap:.2f} <= block.top {block_top}: {fill_vwap <= block_top}")
    print(f"\n  Ожидаемое время от пользователя: 2026-05-23 20:20 MSK")
