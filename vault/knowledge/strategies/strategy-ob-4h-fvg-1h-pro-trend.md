---
tags: [strategy, candidate, smc, ob, fvg]
date: 2026-05-08
status: production-candidate (research only, не в live)
session: [[2026-05-08-elements-study-grid-search-production-setup]]
---

# Стратегия: OB-4h + first FVG-1h pro-trend

**Production-кандидат**, найденный grid search'ем 114 комбинаций элементов
на BTCUSDT 2020-2026.

## Логика

Двухступенчатая воронка:
- **HTF zone (anchor):** OB-4h (без size-фильтра!) задаёт макро-зону
  «памяти рынка». Время жизни 5 дней.
- **LTF trigger:** первая FVG-1h того же направления в зоне OB-4h.
- **Direction filter:** FVG-1h должен быть **pro-trend** относительно
  EMA200_1h (close_1h > EMA200 → LONG OK; < → SHORT OK).

## Формальные правила

### Entry
- Detect OB-4h (canon): pair (prev, cur), формула из [[универсальные определения OB и FVG]]
- В окне `(ob.cur_time + 4h, ob.cur_time + 5 days]` детектируется FVG-1h:
  - `f.direction == ob.direction`
  - `f.zone overlap ob.zone` (any pixel)
- На FVG-1h проверяется pro-trend:
  - LONG: `close_1h(f.c2_time) > EMA200_1h`
  - SHORT: `close_1h(f.c2_time) < EMA200_1h`
- **Берётся ТОЛЬКО ПЕРВАЯ FVG-1h на каждый OB** (dedup) — иначе multi-counting
  re-entries в одну торговую идею.

### Order
- **Entry:** limit на `(f.bottom + f.top) / 2` (mid FVG-1h)
- **Stop Loss:**
  ```
  atr_sl = f.bottom - 0.3 · ATR_1h    (для LONG)
  pct_sl = entry - 1% · entry          (фьючерс-friendly минимум)
  sl     = min(atr_sl, pct_sl)         (дальше от entry)
  ```
  Симметрично для SHORT (max → +1%, atr_sl за `f.top`).
- **Take Profit:** `entry + 1.0 × risk` (RR=1.0)
- **Activation:** ждать пока цена коснётся entry (low ≤ entry для LONG / high ≥ entry для SHORT)
- **Timeout:** 14 дней с момента активации (если SL/TP не сработали — close at market).

## Цифры на BTCUSDT 2020-2026

| Метрика | Значение |
|---|---|
| Всего сетапов | 1130 |
| Активировано | ~840 (74%) |
| Не активировано | ~290 |
| **WR** | **56.9%** |
| R/trade | +0.138 |
| Total R | +116R за 6.4 года |
| Частота | 3.43/неделю |
| Median risk | 1.0% от entry |

При risk=1%/trade ≈ **+18% годовых** на голой математике (без слоплага и комиссий).

### По годам (deep-dive показал нестабильность)

| Год | WR | R/tr |
|---|---:|---:|
| 2020 | 66% | +0.32 |
| 2021 | 62% | +0.23 |
| 2023 | 65% | +0.30 |
| **2024** | **51%** | **+0.01** |
| **2025** | **49%** | **−0.01** |
| 2026 (5 мес) | 83% | +0.67 |

**ВНИМАНИЕ:** 2024-2025 edge выгорал. Возможен режимный сдвиг или overfit на
2020-2023. Нужна валидация на forward-data перед live.

## Почему «без size-фильтра» а не «small only»

Изначально (см. этап 1b в session note) я выбрал small (<0.3·ATR_1d) на
основании bounce_1x метрики, которая показывала WR 98-100% для small OB.

**Это была ошибка.** Bounce_1x ≠ realistic WR при RR с фьючерсным SL.

При полном backtest с min_sl=1%:

| Size | n/нед | WR | R/tr | Total R |
|---|---:|---:|---:|---:|
| ALL (без фильтра) | 3.43 | 56.9% | +0.138 | +116R |
| medium (0.3-1.0) | 2.61 | 56.9% | +0.138 | +88R |
| small (<0.3) | 0.50 | 58.4% | +0.168 | +21R |
| large (≥1.0) | 0.32 | 54.4% | +0.089 | +7R |

WR одинаковый (~57%), edge per trade одинаковый (~0.14), но **частота
без фильтра выше в 7×** → лучший total return. Pro-trend filter спасает
даже large.

→ см. [[bounce-1x-не-равно-wr-при-rr]]

## Сравнение с альтернативами

| Setup | WR | R/tr | n/нед | Total R |
|---|---:|---:|---:|---:|
| **★ ALL OB + pro + RR=1.0** | **56.9%** | +0.138 | **3.43** | **+116R** |
| small + pro + RR=1.5 | 55.2% | **+0.380** | 0.50 | +47R |
| medium + all + RR=1.0 | 55.0% | +0.101 | 4.75 | +117R |

Топ-1 даёт лучший total return при WR≥55% и фьючерсной частоте.
Топ-2 (small + RR=1.5) — лучший R/trade, но в 7× реже.

## Реализация (TODO)

Не реализовано. Скрипты-кандидаты в `research/elements_study/`:
- `etap_12_ob_4h.py` — основа detection-логики
- `etap_13_ob_size_sweep.py` — финальный backtest

Для live:
1. `strategies/strategy_<name>.py` (research-only детектор)
2. `tests/test_strategy_<name>.py`
3. `research/<name>/backtest/` (полный бэктест-pipeline)
4. Интеграция в `MultiStrategyScanner` или отдельный сканер

## Открытые вопросы для следующих сессий

1. **Walk-forward на 2024-2025** — почему edge ослаб?
2. **OOS на ETH/SOL** — overfit на BTC?
3. **Pro-trend на 4h EMA200** вместо 1h — даст ли разный результат?
4. **Time-based фильтры** (US session, weekday) — могут поднять WR (наблюдения из etap_10)
5. **Расширение dedup**: не «первая FVG», а «лучшая FVG по pro-trend strength»?

## Связи

- [[универсальные определения OB и FVG]]
- [[2026-05-08-elements-study-grid-search-production-setup]]
- [[bounce-1x-не-равно-wr-при-rr]]
