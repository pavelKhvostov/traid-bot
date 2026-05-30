---
tags: [session, elements, projects, vc, bearish-sweep, smc-lib, canon, refactor]
date: 2026-05-27
related: [[2026-05-27-12h-fractal-or-basket-c3-c4-c5-ob-liq-canon-update]], [[2026-05-26-vc-3-variants-rules-md-fractal-or-basket]]
---

# 2026-05-27 (evening) — новые элементы, projects, bearish liquidity-sweep candle

Продолжение [[2026-05-27-12h-fractal-or-basket-c3-c4-c5-ob-liq-canon-update]]. Большая структурная работа над smc-lib + новый элемент + наблюдение общего паттерна.

## I. Расширение OR-basket С6+С7

| # | Условие | keep | conf | P(W) | imp |
|---|---|---:|---:|---:|---:|
| **С6** | sweep TrendLine HMA-200 D LIVE | 49 | 40 | **81.6%** | 1 |
| **С7** | FIRST 50%-sweep block_orders multi-TF | 54 | 48 | **88.9%** | 1 |

Basket после C1-C7: **654 / 66.8% / 15 imp**. Осталось 3 missed: **#14, #15, #48**.

С6 принесло +1 imp (#29). С7 — 0 уникальных imp (полностью overlap с C1-C6), но качественный фильтр для precision.

## II. Структурный рефакторинг smc-lib

### Раздел `projects/` создан

`~/smc-lib/projects/` — прикладные пайплайны (semi-canon), отдельно от atomic primitives:
- `README.md` — описание раздела
- `pred12h-fractal-three-candles.md` — полный canon проекта (F1-F3 + C1-C7, basket, missed, semantics)

Семантическое различие:
- `elements/` — atomic SMC primitives (canon с зоной)
- `vc/` — predicate (predicate, не зона)
- `indicators/` — numeric features
- `projects/` — целостные пайплайны на основе всего вышеперечисленного
- `scripts/` — research / backtest (НЕ canon)

### VC вынесен в top-level

`elements/vc/` → `~/smc-lib/vc/`. Обоснование: VC — **предикат, не зона**. Не SMC primitive. Логически принадлежит top-level рядом с `elements/`, `indicators/`.

Обновлены: code.py sys.path, tests, 3 scripts (callers), rules.md, zone_of_interest.md, README.md, memory, vault note.

## III. Новые элементы canon

### run_3candles_sweep (`~/smc-lib/elements/run_3candles_sweep/`)

3-свечный liquidity grab continuation. Три однонаправленные свечи; c2 фитилём снимает экстремум c1, c2.wick ≥ 2.5× c2.body.

| Параметр | SHORT | LONG |
|---|---|---|
| Direction | 3 bear подряд | 3 bull подряд |
| Sweep | c2.high > c1.high | c2.low < c1.low |
| Wick ratio | c2.upper_wick ≥ 2.5 × body | c2.lower_wick ≥ 2.5 × body |
| Entry | `max(c2.o,c2.c) + 0.3 × upper_wick` | `min(c2.o,c2.c) − 0.3 × lower_wick` |
| SL | c2.high | c2.low |
| TP | c3.low | c3.high |

Эталон BTC 8h SHORT 2026-05-26: wick_ratio=6.34, RR=1.44.

**4h backtest 6y**: 89 filled / WR 46.1% / R/trade **+0.612** / Total **+54R**. Edge есть, но WR < 50%. SHORT WR хуже LONG (39% vs 52%).

### ob_sweep_liq_4candles (`~/smc-lib/elements/ob_sweep_liq_4candles/`)

Снятие ликвидности Williams 5-bar FH/FL свечой Y.

> ⚠️ Имя `_4candles` — историческое. После рефакторинга 2026-05-27 канон не привязан к строго 4-свечному окну. Reference = Williams FH/FL anchor любой давности.

**SHORT** (anchor = FH, mirror для LONG):
1. y.open < anchor.high (приход снизу)
2. y.high > anchor.high (sweep FH)
3. y.close < anchor.open (close ниже зоны OB = тела bull-FH-bar)

API: `detect_ob_sweep_liq_4candles(anchor, y, direction)`. Caller валидирует Williams FH/FL отдельно.

Эталон BTC 6h SHORT 2026-05-26: anchor 2026-05-25 15:00 (Williams FH 77906, BULL), y 2026-05-26 15:00 (BEAR sweep). Подтверждено визуально + численно на 2 кейсах разных TF (6h, 2h).

## IV. Bearish liquidity-sweep candle (наблюдение паттерна)

Пользователь показал **4 примера** на разных TF:
- #1: 6h 2026-05-26 15:00 — upper wick rejection + close near low
- #2: 2h 2026-02-09 01:00 — huge upper wick + close near low
- #3: 1h 2026-03-30 01:00 — no upper wick + close middle (breakdown)
- #4: 20m 2026-02-24 16:20 — huge lower wick + close near top (rejection from low)

Изначальная гипотеза («upper wick rejection» как у #1+#2) — НЕ обобщилась.

### Реально общие признаки (6)

1. **BEAR direction**
2. **Range ≥ 2× max prev 5 range** (резкий expansion)
3. **Low строго ниже min prev 5 low** (outside на LOW)
4. **Close строго ниже min prev 5 close**
5. **Снимает ≥3 prior Williams FL за ~50 баров** (множественный sweep низ-ликвидности)
6. **Снимает ≥3 prior Williams FH** (HTF контекст)

Это **«liquidity sweep candle on LOW side»** — большая bear-свеча, которая range охватывает структурный low-sweep, regardless of upper-wick form.

### Scan на BTC показал

Несколько недавних кандидатов на разных TF:
- 1h 2026-05-10 23:00 (rng 2.3×, breakdown-style)
- 4h 2026-02-16 15:00 (rng 2.6×, upper wick rejection — копия стиля #1/#2)
- 8h 2025-10-10 19:00 (rng 4.3×, lower wick rejection — стиль #4)
- 12h 2025-06-05 15:00

Паттерн **реален и регулярен** на BTC across TFs.

### НЕ создан как canon элемент

Не оформлен как `elements/<name>/` пока. Возможные имена для будущего: `bearish_liquidity_sweep`, `expansion_breakdown`, `bear_displacement_sweep`. Решение отложено.

## V. Открытые задачи

- **С8** для оставшихся 3 missed (#14, #15, #48) — кандидаты пока не найдены
- **run_3candles_sweep** (#21) — 8h backtest, confluence-filter для SHORT (WR 39%), OOS
- **Правило 4** (#2) — связь с Правилом 3 не определена
- **dynamic-anchor VWAP** (#10) — implementation не сделана
- **bearish_liquidity_sweep** — оформить как canon-элемент при необходимости
- **OOS** для всего pred12h pipeline (BTC only)

## VI. Артефакты

### Новые в `smc-lib/`:

- `elements/run_3candles_sweep/` (def + code + 7 tests)
- `elements/ob_sweep_liq_4candles/` (def + code + 8 tests; iteratively refactored 3 раза)
- `vc/` (top-level, перенесён из elements/)
- `projects/README.md` + `projects/pred12h-fractal-three-candles.md`
- README.md, rules.md, zone_of_interest.md синхронизированы

### Scripts

- `pred12h_basket_c1c2c3.py` — расширен до C1-C7
- `pred12h_c6_mining.py` — поиск кандидатов С6
- `backtest_run_3candles_sweep_4h.py` — backtest 4h
- `plot_trendline_l78_from_feb1.py` — chart HMA-78 + HMA-200
- Множество ad-hoc analysis скриптов

### Memory обновлено

- [[feedback-ob-liq-no-fractality]] — ob_liq без Williams (вчера)
- [[12h-fractal-orbasket-c1-c5]] (название устарело) — расширено до C1-C7

## VII. Связи

- [[2026-05-27-12h-fractal-or-basket-c3-c4-c5-ob-liq-canon-update]] — утренняя сессия
- [[2026-05-26-vc-3-variants-rules-md-fractal-or-basket]] — VC + OR-basket arch
- [[что такое VC volume confirmation]] — VC canon
- [[что такое OB с явно выраженной зоной ликвидности]] — ob_liq canon
