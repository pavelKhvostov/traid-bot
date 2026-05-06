---
tags: [session, strategy_1_1_1, strategy_1_1_2, strategy_1_1_3, strategy_1_1_4, swept, filters, live-prep]
date: 2026-05-06
related: [[strategy_1_1_1]], [[swept-фильтр-применим-только-к-1-1-1]]
---

# 2026-05-06 — Cross-strategy SWEPT test (1.1.1 vs 1.1.2 vs 1.1.3 vs 1.1.4)

Подготовка к live-integration 4 стратегий 1.1.x. Перед подключением
проверили: применим ли SWEPT-фильтр к 1.1.2/1.1.3/1.1.4 как у 1.1.1.

## Контекст

Пользователь: «надо чтобы в боте были и приходили сигналы по 1.1.1,
1.1.2, 1.1.3, 1.1.4 стратегиям. И надо кидать только оптимизированные
сигналы (это про 1.1.1 со SWEPT). Сначала всё проверим — аккуратно».

Прецедент 1.1.6 (lookahead, найденный визуально) показал что
необдуманное добавление в live даёт мусорные сигналы. 30 минут
research-эксперимента сейчас экономят день дебага потом.

## Гипотеза

SWEPT-фильтр на OB-htf (`min(c1.low,c2.low) < min(prev1.low,prev2.low)`
для LONG, зеркально SHORT) — известно работает для 1.1.1. Применим ли
к остальным версиям с одинаковой структурой OB-htf?

## Метод

Все 4 версии имеют идентичные поля `ob_htf_prev_time`, `ob_htf_cur_time`,
`ob_htf_tf`, `direction`. Скопирована функция `check_swept_for_path` из
`analyze_1_1_1_ob_swept.py` без изменений.

Тест: на default config (entry=mid FVG, SL=15% inside top-OB или
ob_macro для 1.1.6 — в этой сессии не трогали) разделить deduped
сигналы на SWEPT / NOT-SWEPT / ALL. Прогнать через no_entry-симуляцию
на RR=1.0 и RR=2.2.

Создано 2 новых файла:
- `research/1_1_3/analyze/analyze_1_1_3_ob_swept.py`
- `research/1_1_4/analyze/analyze_1_1_4_ob_swept.py`

`research/1_1_2/analyze/analyze_1_1_2_ob_swept.py` уже существовал
(2026-05-04), просто перезапустили.

## Результаты

### 1.1.1 (для контекста — известно из эталона)

```
deduped=144  SWEPT=115 (80%)  NOT-SWEPT=29 (20%)
RR=2.2:  SWEPT  +47R  R/tr +0.42 (с no_entry: 62 closed)
         NOT-SWEPT  -2.4R (убыточен)
```
✅ SWEPT работает.

### 1.1.2 (macro=OB, entry=FVG младшего ТФ)

```
deduped=429  SWEPT=332 (77%)  NOT-SWEPT=97 (23%)

RR=1.0:  ALL       +49R  R/tr +0.20
         SWEPT     +40R  R/tr +0.22
         NOT-SWEPT  +9R  R/tr +0.15

RR=2.2:  ALL       +23.8R  R/tr +0.077
         SWEPT      +7.2R  R/tr +0.031
         NOT-SWEPT +16.6R  R/tr +0.227   ← в 3× лучше SWEPT
```
❌ SWEPT хуже ALL. Применять не надо.

### 1.1.3 (macro=OB, entry=FVG того же ТФ что OB-htf)

```
deduped=117  SWEPT=75 (64%)  NOT-SWEPT=42 (36%)

RR=1.0:  ALL       +10R  R/tr +0.139
         SWEPT      +5R  R/tr +0.106
         NOT-SWEPT  +5R  R/tr +0.200

RR=2.2:  ALL       +18.2R  R/tr +0.188
         SWEPT      +6.2R  R/tr +0.102
         NOT-SWEPT +12.0R  R/tr +0.333   ← в 3× лучше SWEPT
```
❌ SWEPT хуже ALL. Применять не надо.

### 1.1.4 (macro=FVG, entry=FVG того же ТФ что OB-htf)

```
deduped=53  SWEPT=43 (81%)  NOT-SWEPT=10 (19%)

RR=1.0:  ALL       +7R    R/tr +0.226
         SWEPT     +4R    R/tr +0.143
         NOT-SWEPT +3R    R/tr +1.000 (n=3 — шум)

RR=2.2:  ALL       +14.8R  R/tr +0.322
         SWEPT     +13.2R  R/tr +0.347   ← +0.025 R/tr, в пределах шума
         NOT-SWEPT  +1.6R  R/tr +0.200
```
⚠️ SWEPT слабо положителен на RR=2.2, отрицателен на RR=1.0. **Шум** на
малой выборке (10 NOT-SWEPT сделок). Не применять.

## Сводная таблица

| Версия | Macro | Entry-FVG | ALL | SWEPT % | RR=2.2 ALL→SWEPT | Вердикт |
|---|---|---|---|---|---|---|
| 1.1.1 | FVG | младший ТФ | 144 | 80% | работает | ✅ ПРИМЕНЯТЬ |
| 1.1.2 | OB | младший ТФ | 429 | 77% | +23.8R → +7.2R | ❌ НЕТ |
| 1.1.3 | OB | тот же ТФ | 117 | 64% | +18.2R → +6.2R | ❌ НЕТ |
| 1.1.4 | FVG | тот же ТФ | 53 | 81% | +14.8R → +13.2R | ⚠️ ШУМ → НЕТ |

## Ключевой инсайт

**SWEPT-фильтр работает только для 1.1.1** — единственной комбинации
`macro=FVG + entry-FVG младшего ТФ`.

Гипотеза почему:
- В 1.1.2/1.1.3 macro=OB уже даёт строгий фильтр (двойной OB top+macro).
  Дополнительный SWEPT на htf-OB избыточен и **отбрасывает первичные
  тесты OB-macro зоны** — лучшие сделки (где цена пришла свежей, без
  снятия дополнительной ликвидности на htf).
- В 1.1.4 macro=FVG, но entry на htf-уровне (не младший ТФ). Видимо,
  именно сочетание «мягкий macro-FVG + точный entry-FVG младшего ТФ»
  делает SWEPT-чек значимым: отсекает мусорные тесты macro-FVG,
  оставляя те, где есть подтверждённое снятие ликвидности.

**SWEPT — не универсальный фильтр качества.** Для каждой геометрии
нужно проверять отдельно. Применение SWEPT по аналогии без теста =
потеря лучших сделок.

## Решение для live

| Версия | Фильтр в live |
|---|---|
| 1.1.1 | SWEPT-фильтр + MAX_SIGNAL_AGE_HOURS=2 |
| 1.1.2 | MAX_SIGNAL_AGE_HOURS=2 (без SWEPT) |
| 1.1.3 | MAX_SIGNAL_AGE_HOURS=2 (без SWEPT) |
| 1.1.4 | MAX_SIGNAL_AGE_HOURS=2 (без SWEPT) |

`MAX_SIGNAL_AGE_HOURS=2` — глобальный фильтр от prefill_silent на
рестарте, был в 1.1.1-live с самого начала.

## Связанные debugging-уроки в этом тесте

Не было. Все скрипты работали с первого прогона. Существующий
`check_swept_for_path` из 1.1.1 идентичен в `analyze_1_1_2_ob_swept.py`
(2026-05-04) — copy-paste без модификаций.

## Что НЕ сделано в этой сессии

- **Не проверена устойчивость по годам** для NOT-SWEPT-сделок 1.1.2/1.1.3.
  +12R и +16.6R могут быть из 2024 (бычий) и нерабочи в 2025-2026.
  Требуется отдельная разбивка по годам.
- **Не проверена альтернативная семантика SWEPT** (например, на macro-OB,
  а не на htf-OB) для 1.1.2/1.1.3.
- **Не проверены extended-режимы** (1.1.2 extended, 1.1.3 extended/baseline).
- **1.1.6 не проверена** — она в research, в live не идёт.

## Файлы

**Созданы:**
- `research/1_1_3/analyze/analyze_1_1_3_ob_swept.py`
- `research/1_1_4/analyze/analyze_1_1_4_ob_swept.py`
- этот session note
- `vault/knowledge/decisions/swept-фильтр-применим-только-к-1-1-1.md`

**Артефакты (gitignored):**
- `signals/analyze_1_1_2_ob_swept_summary.txt`
- `signals/analyze_1_1_3_ob_swept_summary.txt`
- `signals/analyze_1_1_4_ob_swept_summary.txt`

## Следующая сессия

**Live integration:** `multi_strategy_scanner.py` рефактор `Strategy111Scanner`
под N стратегий, format-функция без кружков, 4 стратегии в `main.py`,
дедуп по версии, тесты на format, ручное тестирование.

См. план в [[текущие приоритеты]].

## Связи

- [[swept-фильтр-применим-только-к-1-1-1]] — decision
- [[strategy_1_1_1]] — родительская
- [[2026-05-01-confluence-bugs-swept-noentry]] — где SWEPT впервые
  появился как фильтр для 1.1.1
- [[2026-05-06-strategy-1-1-6-первый-прогон]] — параллельная сессия
  про новую стратегию
