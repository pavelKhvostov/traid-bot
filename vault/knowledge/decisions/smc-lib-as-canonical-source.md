---
tags: [decision, smc-lib, architecture, smc, taxonomy]
date: 2026-05-23
related: [[2026-05-23-smc-lib-vwap-entry-experiments]], [[что такое rdrb]]
---

# `~/smc-lib/` — отдельная каноническая библиотека SMC-элементов

## Решение

Создана независимая от traid-bot Python-библиотека `~/smc-lib/` как **первый
источник правды** для формальных определений SMC-примитивов: RDRB, i-RDRB,
FVG (и в будущем — fractal, order block, liquidity, ATR).

Каждый элемент = папка с `definition.md` + `code.py` + `tests/`.

## Почему отдельно от traid-bot

1. **Чистая абстракция без интеграционных деталей**. В `traid-bot/strategies/`
   детекторы исторически связаны с live-сканером, сигналами, форматом
   Telegram, дедуп-ключами. Smc-lib — только геометрия и `detect_*()`.

2. **Тестируемость**. 23 теста проходят на чистых фикстурах без I/O. Каждый
   эталонный пример берётся из реальных BTC данных и фиксируется как тест.

3. **Переиспользуемость**. Скрипты в `~/smc-lib/scripts/` импортируют
   `detect_rdrb`, `detect_i_rdrb`, `detect_fvg` без зависимости от traid-bot.
   В будущем это можно подключать к другим проектам.

4. **Конвенция направлений**. В smc-lib зафиксировано
   `bear C2 → SHORT, bull C2 → LONG` (см. `elements/rdrb/definition.md`).
   В vault `[[что такое rdrb]]` описано более старое определение через
   anchor/mid/trigger Rally-Drop-Rally-Base — это OB1h-семейство стратегий,
   другая мотивация.

## Конвенция между vault и smc-lib

- **Vault `knowledge/smc/*.md`** — concept-level описания для людей, привязка
  к live-боту, ссылки на код traid-bot.
- **smc-lib `definition.md`** — формальная спецификация (предусловия,
  формулы зон, эталонный пример с тестом).
- При расхождении в названиях направлений — smc-lib каноничен. Старые
  vault-заметки помечать с датой.

## Расположение

```
~/smc-lib/
  candle.py          — Candle dataclass
  elements/
    rdrb/
    i_rdrb/
    fvg/
  scripts/           — research-скрипты (бэктесты, сканеры, плоты)
```

Скрипты используют локальные данные `~/traid-bot/data/BTCUSDT_1m_vic_vadim.csv`
(см. `[[btc-data-1m-csv]]` в персональной памяти Claude).

## Когда использовать что

| Задача | Куда смотреть |
|---|---|
| Реализовать новый SMC-элемент | `~/smc-lib/elements/<name>/` |
| Бэктест паттерна на чистой геометрии | `~/smc-lib/scripts/` |
| Live-сигнал для бота | `~/traid-bot/strategies/` |
| Концепт-описание для memory | `vault/knowledge/smc/` |
| Сессия с результатами | `vault/sessions/YYYY-MM-DD-...md` |

## Будущие элементы (приоритет)

1. `elements/order_block/` — bullish/bearish OB (для HTF-фильтра, +4.15pp WR)
2. `elements/atr/` — ATR(N), нужен для R/ATR-нормализации SL (топ-фильтр в `[[i-rdrb-v1-pattern]]`)
3. `elements/fractal/` — Williams FH/FL для liq-таргетов
4. `elements/liquidity/` — иерархия liq на разных ТФ
