---
tags: [strategy, vic-evot, spec, prd]
date: 2026-04-27
status: spec-ready
authors: [Павел, Клод]
implementer: Андрей
---

# VIC_EVOT — новая стратегия №8

> **Статус:** спецификация готова, ждёт реализации.
> **Принципиальное отличие от 7 существующих стратегий:**
> другой ТФ подтверждения (15m вместо 1h), другой тип «зоны» (уровень
> вместо диапазона), новый источник данных (1m свечи).

## 1. Идея

Уровень **maxV (VIC Day)** — это close 1m-свечи с максимальным объёмом
за день, либо среди bull (`close>open`), либо среди bear (`close<open`)
свечей — той группы, у которой суммарный объём выше.

Гипотеза: на следующий день цена возвращается к этому уровню, и его
пробой/откат с подтверждением даёт сигнал в направлении тренда дня.

## 2. Расчёт maxV

Источник истины для определения уровня — Pine-индикатор **'ViC ASVK'** на
TradingView с настройками:
- `Data from = LTF`
- `Auto = true`
- `mlt = 100`

На 1D-чарте Pine считает: `LTF = chart_TF / mlt = 1440 / 100 = 14.4 min`.
Далее `timeframe.from_seconds(864)` возвращает ближайший валидный TF из
стандартного набора Pine — из `{600s=10m, 900s=15m}` ближе 900s (Δ36 vs
Δ264). То есть maxV ищется по **15m-агрегатам** 1m-свечей дня.

Конфиг: `VIC_LTF_MINUTES = 15` в `config.py`. Сверено вручную с TV-графиком
ASVK ViC (BTC 2026-04-26: мой 78417.41 ≈ TV 78416 ±1, погрешность чтения
с графика). На LTF=14m было расхождение +165, что подтвердило: Pine
использует 15m, не 14m.

Если индикатор настраивается иначе (другой `mlt`, другой chart_TF) или
TV покажет значимое расхождение на других днях — пересчитать `VIC_LTF_MINUTES`
(вероятный кандидат — 10m).

```python
def calculate_vic_d(
    df_1m: pd.DataFrame, day: pd.Timestamp, ltf_minutes: int = 1,
) -> Optional[float]:
    """
    Возвращает уровень maxV для дня `day` (UTC, normalized).

    Если ltf_minutes > 1, ресемплит 1m свечи дня в LTF-бары через
    pandas.resample(origin='epoch') — выравнивание по UTC-эпохе.
    Default 1 (no-op resample) — для тестов и явного 1m-режима.

    None — если за день нет данных или нет ни одной bull/bear свечи.
    Тай-брейкер при равных max_bull == max_bear: bear (else-ветка).
    """
    next_day = day + pd.Timedelta(days=1)
    mask = (df_1m.index >= day) & (df_1m.index < next_day)
    day_df = df_1m.loc[mask]
    if day_df.empty:
        return None

    if ltf_minutes > 1:
        day_df = day_df.resample(
            f"{ltf_minutes}min", origin="epoch", label="left", closed="left",
        ).agg({
            "open": "first", "high": "max", "low": "min",
            "close": "last", "volume": "sum",
        }).dropna(subset=["close"])
        if day_df.empty:
            return None

    bull = day_df[day_df["close"] > day_df["open"]]
    bear = day_df[day_df["close"] < day_df["open"]]

    max_bull = bull["volume"].max() if not bull.empty else 0
    max_bear = bear["volume"].max() if not bear.empty else 0

    if max_bull == 0 and max_bear == 0:
        return None

    if max_bull > max_bear:
        return float(bull.loc[bull["volume"].idxmax(), "close"])
    return float(bear.loc[bear["volume"].idxmax(), "close"])
```

В рантайме (`vic_scanner.py`, `backtest_vic_evot.py`) функция вызывается
с явным `ltf_minutes=VIC_LTF_MINUTES`. Тесты в `tests/test_vic_levels.py`
покрывают оба режима — default (1m) и LTF=14.

Кэшируется в `state/vic_levels.json` с ключом `{symbol}|{YYYY-MM-DD}`.

> **Важно при деплое:** при апгрейде с 1m-режима на LTF=14m существующий
> `state/vic_levels.json` содержит старые (1m-based) уровни. Их нужно
> либо удалить (`rm state/vic_levels.json`), либо дождаться следующего
> close 1d — он перезапишет кэш через `on_closed_1d`.

## 3. Логика стратегии

После закрытия дневной свечи D-1 у нас есть `maxV(D-1)` и `close(D-1)`.

**Направление цепочки на день D:**
- `close(D-1) > maxV(D-1)` → **LONG**-цепочка
- `close(D-1) < maxV(D-1)` → **SHORT**-цепочка
- равенство → пропуск (None)

**На 15m свечах дня D ищем 5 условий подряд:**

1. **Касание уровня:** где-то в дне D на 15m свече:
   - LONG: `low ≤ maxV` (опускалась к/ниже уровня)
   - SHORT: `high ≥ maxV`

2. **LL/HH-фрактал на свече i** (i = `last_closed_15m - 2 шага`):
   - LONG: `low(i)` строго меньше четырёх соседей (i-2, i-1, i+1, i+2)
   - SHORT: `high(i)` строго больше четырёх соседей
   - LONG: `low(i) < maxV` (фрактал ниже уровня)
   - SHORT: `high(i) > maxV` (фрактал выше уровня)
   - Касание из п.1 случилось НЕ ПОЗЖЕ свечи i

3. **FVG между i и i+2** (`i+2 == last_closed_15m`):
   - LONG: `high(i) < low(i+2)` (есть гэп) И `low(i+2) > maxV` (FVG над уровнем)
   - SHORT: `low(i) > high(i+2)` И `high(i+2) < maxV` (FVG под уровнем)

4. **Live-правило:** проверка ведётся ТОЛЬКО на свече `i+2 == last_closed_15m`.
   Никаких догоняющих сигналов на старых свечах. Аналог главного правила
   движка для 1h, но для 15m.

5. **Direction match:** найденное направление подтверждения совпадает
   с направлением цепочки из close(D-1).

## 4. Контракт функции детекции

```python
# strategies/vic_evot.py

def detect_vic_evot(
    df_15m: pd.DataFrame,                   # 15m свечи дня D, минимум 5
    df_1d: pd.DataFrame,                    # 1d свечи (нужна последняя закрытая)
    vic_level: float,                        # maxV(D-1), уже посчитан
    symbol: str,
    last_closed_15m_open_time: pd.Timestamp,
) -> Optional[Signal]:
    """
    Возвращает Signal только если ВСЕ 5 условий из §3 выполнены.

    Edge cases (все возвращают None, без исключений):
      • df_15m имеет < 5 свечей за день D
      • vic_level is None
      • close(D-1) == vic_level
      • Касания в дне D не было до момента last_closed_15m
      • Фрактал не подтверждён / FVG не сформирован
      • Direction mismatch между трендом дня и фракталом

    Поля Signal:
      strategy            = "VIC_EVOT"
      symbol              = symbol
      source_tf           = "1d"
      direction           = "LONG" | "SHORT"
      level               = Level(price=vic_level, day=D-1)
      entry_price         = low(i+2) для LONG / high(i+2) для SHORT
      confirmation_time   = last_closed_15m_open_time
      fractal_time        = open_time(i)  # для отладки/верификации
    """
```

Функция чистая (no I/O, no globals). Тестируется фикстурами с искусственными
свечами.

## 5. Level dataclass (в strategies/base.py)

```python
@dataclass(frozen=True)
class Level:
    price: float                # сам уровень maxV
    day: pd.Timestamp           # день D-1, UTC, normalized
    source: str = "VIC"         # на будущее, если появятся другие уровни
```

Signal принимает `Optional[Zone]` И `Optional[Level]`, ровно одно из двух
заполнено. В формате Telegram-сообщения для Level вместо строки
`Зона: 2312.87 – 2338.79` будет `Уровень: 2325.50`.

## 6. Telegram-формат

```
₿ BTCUSDT · 🎯 VIC_EVOT
📈 LONG · уровень maxV(2026-04-26)
Подтверждение: FVG-15m + LL-фрактал

<code>Вход:    65432.10
Уровень: 65250.00
Время:   2026-04-27 14:30 UTC</code>
```

Иконка стратегии: 🎯 (предложение, можно поменять).

## 7. Разделение труда

**Что пишет Андрей** (изолированно, чистые функции):
- `strategies/vic_evot.py` — функция `detect_vic_evot` по §4
- `vic_levels.py` — функция `calculate_vic_d` по §2
- `tests/test_vic_evot.py` — фикстуры с искусственными свечами на все 5 условий + edge cases
- `tests/test_vic_levels.py` — тесты расчёта maxV (включая bull-only, bear-only, пустой день, равенство объёмов)

**Что пишет Павел** (сначала, до старта Андрея):
- `Level` dataclass в `strategies/base.py` + расширение `Signal`
- Расширение `format_signal_telegram` под Level

**Что пишет Павел** (после готовности функций Андрея):
- `vic_scanner.py` — класс `VicScanner` (startup, on_closed_15m, on_closed_1d)
- `config.py` — `TIMEFRAMES_NATIVE += ["1m", "15m"]`, `VIC_TFS = ["1d"]`
- `main.py` — `asyncio.gather` с двумя scanner'ами

**Координация:**
1. Павел сначала пушит `Level` dataclass в main (без него Андрей не сможет компилироваться).
2. Андрей создаёт ветку `feature/vic-evot` ОТ main после этого пуша.
3. Андрей делает PR в main, Павел ревьюит и мерджит.

## 8. Edge cases для тестов

| Случай | Ожидание |
|---|---|
| df_15m пустой | None |
| df_15m 4 свечи (< 5) | None |
| vic_level is None | None |
| close(D-1) == vic_level | None |
| Касания в дне D не было | None |
| Касание было, но фрактала нет | None |
| Фрактал есть, но low(i) > vic_level (LONG) | None |
| Фрактал есть, FVG не сформирован (high(i) ≥ low(i+2)) | None |
| FVG есть, но low(i+2) ≤ vic_level (внутри уровня) | None |
| Все 5 условий — счастливый путь LONG | Signal с правильными полями |
| Все 5 условий — счастливый путь SHORT | Signal с правильными полями |

## 9. Связи

- [[что такое fvg]] — концепция FVG
- [[фракталы билла уильямса]] — определение LL/HH фрактала
- [[главное правило ob только на последней закрытой 1h]] — аналог для 15m
- [[trigger_time равен open_time плюс tf]] — для VIC trigger_time =
  open_time(D), потому что после закрытия 1d-свечи D-1 ждём подтверждение
  на 15m в дне D
- [[архитектура проекта flat layout]] — куда положить новые модули
