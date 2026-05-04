# research/

Research-стенд: backtest, optimize, analyze, compare, export, tune для версий 1.1.1 → 1.1.4 и 1.2.0, плюс RDRB и VIC варианты.

В live-боте сейчас работает только Strategy 1.1.1 (через `strategy_1_1_1_confluence.py` + `strategy_1_1_1_scanner.py` в корне репо).

## Структура

| Папка | Содержимое |
|---|---|
| `_shared/` | общие утилиты (backtest_year.py — обёртка для прогона по году) |
| `1_1_1/` | оптимизированная стратегия (SWEPT + 3-stage), эталон для остальных |
| `1_1_2/` | macro-OB вместо macro-FVG |
| `1_1_3/` | entry FVG того же ТФ что OB-htf (без 15m/20m слоя) |
| `1_1_4/` | гибрид (macro-FVG + entry immediate, **WIP**) |
| `1_2_0/` | новая ветка: EMA-200 + sweep + FVG-15m |
| `rdrb/` | 5 RDRB-вариантов (premium/trend/wick/konfetka) — кандидаты на расширение live |
| `vic/` | VIC backtests (out-of-scope текущего рефакторинга) |

## Запуск

Все скрипты запускаются из корня репо:

```bash
./venv/bin/python research/<version>/<subtype>/<script>.py
```

В каждом скрипте есть `sys.path` injection — `data_manager`, `strategies/`, и cross-research импорты в пределах 1.1.1 находятся автоматически.

## Эталоны и метрики

Полный baseline: `vault/baseline/2026-05-04-14-16/metrics.md` + `optimized-baselines.md`.

Для 1.1.1 эталонная конфигурация (SWEPT + 3-stage @ RR=2.2): WR 54.8%, +46.8R на 115 closed сделках, r/trade 0.755.

## Что не трогать

- Файлы в `strategies/` (живые детекторы) — research-скрипты их используют, но не модифицируют.
- Логика любого `detect_*` — изменение только через осознанное обновление canon в `vault/knowledge/smc/`.
