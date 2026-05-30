"""Догоняет недостающие 1m свечи в ~/traid-bot/data/BTCUSDT_1m_vic_vadim.csv с Binance API.

Читает последний timestamp в CSV, докачивает свечи начиная со следующей минуты до текущего момента,
дописывает в существующий файл в том же формате.

Безопасность:
- Не перезаписывает существующие строки.
- Сначала делает dry-run (показывает что будет добавлено) — потом просит подтверждение.
- Записывает только полностью закрытые свечи (open_time < now - 60s).
"""
from __future__ import annotations

import csv
import json
import pathlib
import subprocess
import sys
from datetime import datetime, timedelta, timezone

CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
SYMBOL = "BTCUSDT"
INTERVAL = "1m"
MS_PER_MIN = 60_000


def get_last_timestamp_ms() -> int:
    """Читает последнюю строку CSV без загрузки всего файла."""
    with CSV_PATH.open("rb") as f:
        f.seek(-200, 2)  # ближе к концу
        tail = f.read().decode().splitlines()
    last = tail[-1]
    ts_str = last.split(",", 1)[0]
    return int(datetime.fromisoformat(ts_str).timestamp() * 1000)


def fetch_chunk(start_ms: int):
    url = (
        f"https://api.binance.com/api/v3/klines?symbol={SYMBOL}&interval={INTERVAL}"
        f"&startTime={start_ms}&limit=1000"
    )
    return json.loads(subprocess.check_output(["curl", "-s", url], timeout=30))


def fetch_all(start_ms: int, end_ms: int):
    """Пагинирует, возвращает все закрытые свечи в диапазоне."""
    out: list[list] = []
    cursor = start_ms
    while cursor < end_ms:
        chunk = fetch_chunk(cursor)
        if not chunk:
            break
        for k in chunk:
            ot = int(k[0])
            if ot >= end_ms:
                break
            out.append(k)
        last_ot = int(chunk[-1][0])
        next_cursor = last_ot + MS_PER_MIN
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        if len(chunk) < 1000:
            break
    return out


def format_row(k: list) -> str:
    ot = datetime.fromtimestamp(int(k[0]) / 1000, tz=timezone.utc)
    ts = ot.strftime("%Y-%m-%d %H:%M:%S+00:00")
    # сохраняем максимальную precision как Binance возвращает (строки без trailing zeros)
    return f"{ts},{float(k[1])},{float(k[2])},{float(k[3])},{float(k[4])},{float(k[5])}\n"


now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
# обрезаем до целой минуты и отнимаем 1 минуту, чтобы не захватить незакрытую текущую свечу
cutoff_ms = (now_ms // MS_PER_MIN) * MS_PER_MIN  # включительно эту свечу НЕ берём

last_ms = get_last_timestamp_ms()
print(f"CSV last open_time: {datetime.fromtimestamp(last_ms/1000, tz=timezone.utc)}")
print(f"Cutoff (excl):      {datetime.fromtimestamp(cutoff_ms/1000, tz=timezone.utc)}")

start_ms = last_ms + MS_PER_MIN  # следующая минута
if start_ms >= cutoff_ms:
    print("CSV уже актуален.")
    sys.exit(0)

expected = (cutoff_ms - start_ms) // MS_PER_MIN
print(f"Ожидаем {expected} свечей")

klines = fetch_all(start_ms, cutoff_ms)
print(f"Получено: {len(klines)} свечей")
if not klines:
    print("Пусто, выход.")
    sys.exit(0)

first_ts = datetime.fromtimestamp(int(klines[0][0]) / 1000, tz=timezone.utc)
last_ts = datetime.fromtimestamp(int(klines[-1][0]) / 1000, tz=timezone.utc)
print(f"Диапазон: {first_ts} → {last_ts}")

# Проверка отсутствия gap'ов и дубликатов
ts_list = [int(k[0]) for k in klines]
gaps = [(ts_list[i-1], ts_list[i]) for i in range(1, len(ts_list)) if ts_list[i] - ts_list[i-1] != MS_PER_MIN]
if gaps:
    print(f"⚠ Найдено {len(gaps)} пропусков в данных Binance (биржа была off?):")
    for a, b in gaps[:5]:
        print(f"  ...{datetime.fromtimestamp(a/1000, tz=timezone.utc)} → {datetime.fromtimestamp(b/1000, tz=timezone.utc)}")

if ts_list[0] != start_ms:
    print(f"⚠ Первая полученная свеча ({first_ts}) не совпадает с ожидаемой ({datetime.fromtimestamp(start_ms/1000, tz=timezone.utc)})")

# Запись
mode = "--apply" in sys.argv
if not mode:
    print("\nDRY-RUN. Запустите с флагом --apply для дозаписи.")
    print(f"Первые 2 строки для добавления:")
    for k in klines[:2]:
        print(f"  {format_row(k).rstrip()}")
    print(f"Последняя строка:")
    print(f"  {format_row(klines[-1]).rstrip()}")
    sys.exit(0)

with CSV_PATH.open("a") as f:
    for k in klines:
        f.write(format_row(k))

print(f"\n✓ Дописано {len(klines)} строк. Новая последняя свеча: {last_ts}")
