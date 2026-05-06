---
tags: [session, live-integration, multi-strategy, strategy_1_1_1, strategy_1_1_2, strategy_1_1_3, strategy_1_1_4]
date: 2026-05-06
related: [[2026-05-06-swept-cross-strategy-test]], [[swept-фильтр-применим-только-к-1-1-1]]
---

# 2026-05-06 — Live integration 6 стратегий 1.1.x через MultiStrategyScanner

Финальный шаг недели по 1.1.x: подключили все 4 версии (1.1.1, 1.1.2,
1.1.3, 1.1.4) в live, причём 1.1.3 и 1.1.4 — обе FVG-версии (v1+v2)
для observability.

## Контекст

Пользователь: «надо чтобы в боте были и приходили сигналы по 1.1.1,
1.1.2, 1.1.3, 1.1.4. Без кружков confluence. Только оптимизированные
сигналы». Cross-strategy SWEPT-test ([[2026-05-06-swept-cross-strategy-test]])
показал что SWEPT работает только для 1.1.1.

Дополнительно: «1.1.3 у нас сигналы должны быть и с v1 и с v2», и для
1.1.4 «обе версии». Итого 6 конфигов в live для observability.

## Архитектура

**`multi_strategy_scanner.py`** (новый) — заменил `Strategy111Scanner`:

- Один WS на BTCUSDT × 5 native ТФ (1m, 15m, 1h, 4h, 1d)
- На каждом 1h close прогоняются ВСЕ 6 стратегий по одному загруженному df_pack
- Конфиг через `STRATEGIES: list[StrategyConfig]`:

```python
StrategyConfig(name, detect_fn, detect_kwargs, macro_pattern, apply_swept, htf_tf_minutes)
```

| name | detect_fn | kwargs | macro | swept | htf_tf_min |
| --- | --- | --- | --- | --- | --- |
| S111_SWEPT | 1.1.1 | {} | FVG | True | False |
| S112 | 1.1.2 | {} | OB | False | False |
| S113_V1 | 1.1.3 | v1 + untouched | OB | False | True |
| S113_V2 | 1.1.3 | v2 + untouched | OB | False | True |
| S114_V1 | 1.1.4 | v1 | FVG | False | True |
| S114_V2 | 1.1.4 | v2 | FVG | False | True |

`htf_tf_minutes=True` означает что детектор не принимает df_15m/df_20m
(1.1.3 и 1.1.4 — entry-FVG того же ТФ что OB-htf).

## Format сигнала (без кружков)

```text
BTC - LONG
POI: Daily OB + 4h FVG
Volume confirmation: 1h OB + 15m FVG
```

- `top_label`: "Daily" если top_tf="1d", иначе сам tf ("12h")
- `macro` = `fvg_macro_tf` если macro_pattern="FVG" (1.1.1, 1.1.4),
  иначе `ob_macro_tf` (1.1.2, 1.1.3)
- `entry`: `fvg_tf` если есть, иначе `ob_htf_tf` (для 1.1.3/1.1.4 они равны)
- **Без указания версии стратегии** — все 6 выглядят одинаково в Telegram.
  Дедуп идёт по name в state, не по тексту.

## Защита от старых сигналов (баг "март в апреле")

Раньше был баг: бот в апреле прислал мартовский сигнал (видимо
`prefill_silent` пропустил часть истории, age-фильтр не сработал
или его не было).

**В новом MultiStrategyScanner усилена защита:**

1. `prefill_silent` для каждой из 6 стратегий независимо при startup
2. `MAX_SIGNAL_AGE_HOURS=1` (было 2 в Strategy111Scanner) — детектор
   триггерится на каждом 1h close, любой сигнал старше 1h = подозрительный
3. На каждом on_closed_1h: `age = now - signal_time`, если `> 1h` →
   `mark_sent(stale)` + log_event INFO с диагностикой (age в часах)

Старые ключи S111|... в `state/sent_signals.json` остаются как мусор
(не матчатся с новыми S111_SWEPT|...), но это безвредно — age-check
их отсечёт при первом on_closed_1h после рестарта.

## Что удалено

- `strategy_1_1_1_scanner.py` — заменён MultiStrategyScanner
- `strategy_1_1_1_confluence.py` — confluence убран (кружки не используем)
- `tv_refresh_loop` — TV-данные больше не нужны live (нет confluence-проверки)

Backwards-compat намеренно нет: live полностью переходит на
MultiStrategyScanner. История старого кода в git.

## Тесты

`tests/test_multi_strategy_scanner.py` — 28 unit-тестов:

- **format_signal** × 6 конфигов × LONG/SHORT (12 кейсов): точная
  проверка строки сообщения
- Регрессия "no circles": 🟢🔴⚪ не должны попасть в текст
- **dedup_key**: tz-naive == tz-aware, разные версии = разные ключи,
  entry в ключе
- **check_swept**: LONG/SHORT True/False/None кейсы на синтетических OB-htf
- **STRATEGIES конфиг**: count=6, unique names, only_111_has_swept,
  macro_pattern, htf_tf_minutes flag, kwargs, MAX_AGE=1, NATIVE_TFS

Все 73 теста проекта зелёные (45 старых + 28 новых).

## Ожидаемый поток сигналов в live

По preview-скрипту на 3y BTC raw baseline:

| Конфиг | n / 3y | n / месяц | RR=1 PnL | RR=2.2 R/tr |
|---|---|---|---|---|
| S111_SWEPT | 112 | 3.1 | +23R / 65% WR | +0.437 |
| S112 | 429 | 11.9 | +51R / 60% WR | +0.098 |
| S113_V1 | 117 | 3.2 | +10R / 57% WR | +0.188 |
| S113_V2 | 144 | 4.0 | -13R / 41% WR | -0.125 |
| S114_V1 | 53 | 1.5 | +7R / 61% WR | +0.322 |
| S114_V2 | 73 | 2.0 | -4R / 46% WR | +0.100 |

**Итого ≈ 25 сигналов/месяц** на подписчика по всем 6 версиям.
1.1.3 v2 — отрицательный edge на бэктесте, но добавлена для observability.

## Что делать после деплоя

1. **Запустить бота на dev-аккаунте** перед prod (логи: prefill_silent
   должен пометить ~700+ сигналов как sent для всех 6 стратегий).
2. **Дождаться первого 1h close** — проверить что не было пачки старых
   сигналов (защита age-фильтра должна сработать).
3. **Через неделю проверить** распределение типов сигналов по 6 версиям
   в `state/sent_signals.json`.
4. **Через месяц проверить** соответствие количества и WR с backtest-предсказанием.

## Файлы

**Созданы:**
- `multi_strategy_scanner.py` (~360 строк)
- `tests/test_multi_strategy_scanner.py` (28 тестов)
- этот session note

**Изменён:**
- `main.py` — MultiStrategyScanner вместо Strategy111Scanner
- `CLAUDE.md` — обновлено описание live (6 стратегий через multi_scanner)

**Удалены:**
- `strategy_1_1_1_scanner.py`
- `strategy_1_1_1_confluence.py`

## Связи

- [[2026-05-06-swept-cross-strategy-test]] — подготовительный research
- [[swept-фильтр-применим-только-к-1-1-1]] — decision про SWEPT
- [[strategy_1_1_1]] — родительская стратегия
- [[strategy_1_1_6]] — параллельная (research-only, в live НЕ интегрирована)
