# Patterns

Раздел для **setup-паттернов** — полных торговых сетапов с Entry/SL/TP, в отличие от atomic zone-elements в `elements/`.

| Раздел | Что |
|---|---|
| `elements/` | atomic SMC primitives (canon zone) — описывают **где ждать реакцию** |
| `patterns/` | **setup-паттерны** (canon + полный setup) — описывают **как торговать** |

## Различие

| Аспект | `elements/` | `patterns/` |
|---|---|---|
| Что возвращает detector | объект с zone (lo, hi) | объект с **entry, sl, tp** |
| Назначение | zone of interest, mitigation, confluence | **полный торговый setup** |
| Backtest нужен | опционально | **обязательно** (есть entry/SL/TP) |
| Имя detector | `detect_<name>(...)` | `detect_<name>(...)` (то же) |
| Прямое применение | как часть стратегии | как самостоятельная стратегия |

## Текущие patterns

| Pattern | Описание | In-sample эмпирика |
|---|---|---|
| [run_3candles_sweep](run_3candles_sweep/definition.md) | 3 same direction + sweep c1 high/low + c2 wick ≥2.5×body | BTC 4h: 89 filled / WR 46% / R/tr +0.61 |
| [i_rdrb_fvg](i_rdrb_fvg/definition.md) | i-RDRB (C1-C4) + FVG (C3-C4-C5) same direction. 5-свечный композит | 1h BTC baseline 780 сделок |

## Структура pattern-папки

```
patterns/<name>/
├── definition.md      # canon: условия + setup (entry/SL/TP) + эталон + backtest
├── code.py            # detect_<name>(c1, c2, c3, direction) → <name>Result | None
└── tests/
    └── test_<name>.py # юнит-тесты (включая happy + edge cases)
```

## Связи

- Atomic zones: [`../elements/`](../elements/)
- Predicate: [`../vc/`](../vc/)
- Indicators: [`../indicators/`](../indicators/)
- Project pipelines: [`../projects/`](../projects/)
