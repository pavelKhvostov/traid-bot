"""Сканирует BTCUSDT на нескольких ТФ, ищет последние примеры RDRB V1/V2 long/short.

Цель: вытащить 3 самых свежих long + 3 short для каждого варианта на 6 ТФ.
Итого 12 примеров.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from candle import Candle
from elements.rdrb.code import detect_rdrb

MSK = timezone(timedelta(hours=3))

# (binance_interval, candles_to_fetch)
TFS = [
    ("15m", 1000),  # ~10.4 дней
    ("1h",  1000),  # ~41 день
    ("4h",  1000),  # ~166 дней
    ("6h",  1000),  # ~250 дней
    ("12h", 1000),  # ~500 дней
    ("1d",  1000),  # ~2.7 года
]


def fetch(interval: str, limit: int):
    url = f"https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval={interval}&limit={limit}"
    out = subprocess.check_output(["curl", "-s", url], timeout=30)
    return json.loads(out)


def to_candles(klines):
    return [
        Candle(
            open=float(k[1]),
            high=float(k[2]),
            low=float(k[3]),
            close=float(k[4]),
            open_time=int(k[0]),
        )
        for k in klines
    ]


def fmt_msk(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(MSK).strftime("%Y-%m-%d %H:%M")


# Собираем все найденные паттерны в bucket'ы
buckets: dict[tuple[str, str], list] = {
    ("V1", "long"): [],
    ("V1", "short"): [],
    ("V2", "long"): [],
    ("V2", "short"): [],
}

for tf, limit in TFS:
    klines = fetch(tf, limit)
    candles = to_candles(klines)
    for i in range(len(candles) - 2):
        r = detect_rdrb(candles[i], candles[i + 1], candles[i + 2])
        if r is None:
            continue
        buckets[(r.variant, r.direction)].append((tf, r))

# Для каждого ТФ и варианта находим latest long и latest short.
# Затем оптимально распределяем 6 ТФ как 3 long + 3 short (максимум суммарной свежести).
import itertools

TF_ORDER = [tf for tf, _ in TFS]

latest_per_combo: dict[tuple[str, str, str], object] = {}
for (variant, direction), items in buckets.items():
    for tf, r in items:
        key = (tf, variant, direction)
        if key not in latest_per_combo or r.c1.open_time > latest_per_combo[key].c1.open_time:
            latest_per_combo[key] = r


def best_3_3_partition(variant: str) -> list[tuple[str, str, object]]:
    """Для variant: подбираем партицию 6 ТФ на 3 long + 3 short с макс. свежестью."""
    best_score = -1
    best_assignment: list[tuple[str, str, object]] = []
    for long_tfs in itertools.combinations(TF_ORDER, 3):
        short_tfs = [t for t in TF_ORDER if t not in long_tfs]
        ok = all((tf, variant, "long") in latest_per_combo for tf in long_tfs)
        ok = ok and all((tf, variant, "short") in latest_per_combo for tf in short_tfs)
        if not ok:
            continue
        score = sum(latest_per_combo[(tf, variant, "long")].c1.open_time for tf in long_tfs)
        score += sum(latest_per_combo[(tf, variant, "short")].c1.open_time for tf in short_tfs)
        if score > best_score:
            best_score = score
            best_assignment = (
                [(variant, "long", tf, latest_per_combo[(tf, variant, "long")]) for tf in long_tfs]
                + [(variant, "short", tf, latest_per_combo[(tf, variant, "short")]) for tf in short_tfs]
            )
    return best_assignment


picked: list = []
for variant in ("V1", "V2"):
    picked.extend(best_3_3_partition(variant))
# отсортируем внутри варианта: сначала long по ТФ, потом short по ТФ
picked.sort(key=lambda x: (x[0], 0 if x[1] == "long" else 1, TF_ORDER.index(x[2])))

# Печатаем
print(f"{'#':<3} {'Variant':<5} {'Dir':<6} {'TF':<5} {'C1 time (MSK)':<18} {'POI':<28} {'block':<28} {'liq':<28}")
print("-" * 130)
for i, (variant, direction, tf, r) in enumerate(picked, 1):
    poi = f"[{r.poi[0]:.2f}, {r.poi[1]:.2f}]"
    block = f"[{r.block[0]:.2f}, {r.block[1]:.2f}]"
    liq_str = "∅" if r.liq is None else f"[{r.liq[0]:.2f}, {r.liq[1]:.2f}]"
    print(f"{i:<3} {variant:<5} {direction:<6} {tf:<5} {fmt_msk(r.c1.open_time):<18} {poi:<28} {block:<28} {liq_str}")

print()
print("Counts found:")
for (variant, direction), items in buckets.items():
    print(f"  {variant} {direction}: {len(items)} (across all TFs)")
