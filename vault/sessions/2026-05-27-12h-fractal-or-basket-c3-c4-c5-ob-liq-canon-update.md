---
tags: [session, 12h-fractal, or-basket, ob_liq, fvg, trendline, vwap, smc-lib, canon]
date: 2026-05-27
related: [[2026-05-26-vc-3-variants-rules-md-fractal-or-basket]], [[что такое OB с явно выраженной зоной ликвидности]], [[12h-fractal-filter-F1-F2]]
---

# 2026-05-27 — 12h фрактал OR-basket: добавлены С3+С4+С5; ob_liq канон без Williams

Продолжение [[2026-05-26-vc-3-variants-rules-md-fractal-or-basket]]. Расширение OR-basket для 12h Pred-фракталов. Существенное изменение в канон ob_liq.

## I. Прогресс OR-basket (BTC 6y in-sample, baseline F1∩F2∩F3)

Baseline (зафиксирован 2026-05-26): **n=1267 / conf=619 / P(W)=48.9% / imp=18/18**.

Цель: recall 18/18 через union условий. Каждое условие independent на baseline.

### Условия в корзине

| # | Условие | keep | conf | P(W) | Δ | imp |
|---|---|---:|---:|---:|---:|---:|
| **С1** | sweep maxV(i-1) на 1m | 357 | 268 | **75.1%** | +26.2 | 5 |
| **С2** | union P11_count {8,12,16,24}×15m direction-matched | 193 | 141 | **73.1%** | +24.2 | 5 |
| **С3** | FIRST 50%-sweep ob_liq (liq_zone ∪ OB.zone) direction-matched | 115 | 80 | 69.6% | +20.7 | 2 |
| **С4** | FIRST 50%-sweep FVG multi-TF (12h+D+2D+3D+W) direction-matched | 180 | 107 | 59.4% | +10.6 | 3 |
| **С5** | sweep TrendLine HMA-78 (12h ∪ D) LIVE direction-matched | 185 | 124 | 67.0% | +18.2 | 5 |

### Корзина

| Состояние | n | conf | not | P(W) | imp/18 |
|---|---:|---:|---:|---:|---:|
| **Basket = C1∪C2∪C3∪C4∪C5** | **636** | 423 | 213 | **66.5%** | **14** |
| Остаток (в работе) | 631 | 196 | 435 | 31.1% | 4 |

### 4 непойманных imp

- #14 (2026-03-04 15:00 high)
- #15 (2026-03-08 15:00 low)
- #29 (2026-03-29 15:00 low)
- #48 (2026-05-06 03:00 high)

#29 потенциально ловится через HMA-200 sweep (~75% WR), но C6 ещё не утверждено.

## II. Каноническое изменение: ob_liq без Williams-фрактальности

**Решение 2026-05-27**: убрать Williams 5-bar HH/LL условие из канона ob_liq.

### Что изменилось

| Аспект | До 2026-05-27 | После |
|---|---|---|
| Свечной паттерн | 5-свечный (prev-2, prev-1, prev, cur, cur+1) | **2-свечный (prev, cur)** |
| Условий маркера | 3 (wick ≥ 3×, wick > body, Williams HH/LL) | **2** (wick ≥ 3×, wick > body) |
| `detect_ob_liq` signature | 5 args | **2 args** |

### Why

Williams 5-bar условие отрезало много визуально валидных ob_liq случаев из-за наличия соседнего бара с более высокими/низкими экстремумами. Конкретный кейс что вскрыл: BTC 12h 02-16 15:00 / 02-17 03:00 — структурно ob_liq (wick ratios passing), но prev.high < prev-2.high → Williams fail.

### Артефакты

- `~/smc-lib/elements/ob_liq/code.py` — упрощённая 2-арг функция
- `~/smc-lib/elements/ob_liq/definition.md` — описание 2-условный маркер
- `~/smc-lib/elements/ob_liq/tests/test_ob_liq.py` — 6 тестов pass
- `~/smc-lib/zone_of_interest.md`, `~/smc-lib/README.md` — обновлены
- 8 callers в `scripts/` переведены на 2-арг вызов
- Memory: [[feedback-ob-liq-no-fractality]]

После релаксации: total ob_liq на 5 HTFs = 494 (было 210, +135%). FIRST_SWEEP precision упал с 77.6% → 67.4%, но recall improved.

## III. VWAP добавлен как зона интереса (sweep mitigation)

`~/smc-lib/zone_of_interest.md`:
- Новый раздел **7a) VWAP (anchored, ASVK)** — точечная зона во времени (time-varying), класс liquidity/equilibrium
- SHORT VWAP (от FH) = resistance, LONG VWAP (от FL) = support
- Sweep: `wick пересёк VWAP(t)` + close back outside
- Сводная таблица mitigation: VWAP в категории **sweep** (вместе с fractal и marubozu open)

`~/smc-lib/rules.md` Правило 2 синхронизировано.

## IV. VWAPs strategy — exploration

### Правило 6 (зафиксировано 2026-05-26)

D-фрактал, dynamic anchor в i+1 D bar, 15m grid (96 candidates), max composite, cascade 1h-12h. Подтверждено сегодня экспериментами:
- 50 крайних D-фракталов: top-5 LONG (FL, max composite), top-5 SHORT (FH), top-5 ANCHOR (most touches)
- 100 D-фракталов с обновлёнными данными (до 2026-05-26 23:14 MSK): EFF и TRD непересекаются (10 unique levels)

### Anchor optimization для контрольных точек

User указал 6 control closes (04-07 21:00, 04-14 03:00, 04-21 15:00, 05-16 09:00, 05-20 21:00, 05-25 15:00) и попросил подобрать оптимальный anchor:

| Search range | Asset | Best anchor | MAE |
|---|---|---|---:|
| 04-07 (1 day) | BTC | 04-07 20:45 MSK | 2.08% |
| 02-04..02-08 | BTC | 02-09 02:00 MSK | 6.71% |
| 02-01..02-19 | BTC | 02-20 02:45 MSK | 6.41% |
| 04-07 (1 day) | SOL | 04-07 20:45 MSK | 1.26% |
| 02-02..02-14 | SOL | **02-02 03:00 MSK** ⭐ start of range! | 2.18% |

**Insight**: BTC — optimum всегда в конце range (up-trend, поздний anchor лучше). SOL — V-shape, optimum в начале (sideways, ранний anchor стабильнее).

## V. TrendLine (HMA) исследование для С5

User-наблюдение: 3 missed (#11, #26, #47) взаимодействуют с TrendLine (12h для #11/#26, D для #47).

Подбор параметров HMA на baseline:

| Variant | #11 | #26 | #47 | keep | P(W) | catches_missed/7 |
|---|:---:|:---:|:---:|---:|---:|---:|
| **L=78 12h∪D LIVE** | ✓ | ✓ | ✓ | 185 | **67.0%** | **3** |
| L=200 D LIVE | ✗ | ✗ | ✗ | 49 | 81.6% ⭐ | 1 (#29) |
| L=30 12h LIVE | ✗ | ✗ | ✗ | 119 | 78.2% | 0 |

Подтверждена user-интуиция: **L=78 12h∪D LIVE** — единственный из тестированных variant ловит все 3 указанных. WR ниже 70% но catches_missed=3.

Принято как **С5**.

## VI. Открытые задачи

- **С6** — ещё не утверждено. Кандидаты: HMA-200 12h∪D LIVE sweep (111 keep, 75.7% WR, +1 missed #29), block_orders 50%-sweep FIRST (54/88.9%/0 missed), RB 50%-sweep FIRST (102/82.4%/0 missed)
- **3 непойманных missed без catch**: #14, #15, #48 — требуют новой идеи
- **Правило 4** (LTF FVG усиливает HTF OB) — связь с Правилом 3 не определена
- **Правило 6 implementation** (dynamic-anchor VWAP) — не реализовано в коде
- **OOS validation** — все condition только на BTC 6y in-sample

## VII. Зафиксированные правила / memory updates

Новые feedback memory:
- [[feedback-ob-liq-no-fractality]] — ob_liq канон 2-свечный без Williams
- [[feedback-12h-fractal-baseline-f1f2f3]] (предыдущий день) — baseline F1∩F2∩F3
- [[feedback-12h-fractal-or-basket-arch]] (предыдущий день) — OR-basket arch

Изменения в правилах (vault):
- [[что такое OB с явно выраженной зоной ликвидности]] — нужно обновить (Williams убран)

## VIII. Артефакты

Скрипты:
- `~/smc-lib/scripts/pred12h_basket_c1c2c3.py` — расчёт C1-C5 basket
- `~/smc-lib/scripts/pred12h_ob_liq_condition.py` — С3 FIRST 50%-sweep ob_liq
- `~/smc-lib/scripts/pred12h_fvg_50sweep_condition.py` — С4 FVG sweep
- `~/smc-lib/scripts/pred12h_trendline_test.py` — initial TrendLine test
- `~/smc-lib/scripts/pred12h_trendline_tune.py` — подбор HMA params
- `~/smc-lib/scripts/pred12h_c6_mining.py` — кандидаты С6
- `~/smc-lib/scripts/vwap_anchor_optim_2026_04_07.py` — BTC anchor optim
- `~/smc-lib/scripts/vwap_anchor_optim_sol_2026_04_07.py` — SOL anchor optim
- `~/smc-lib/scripts/vwap_rule6_100_anchors_selection.py` — Rule 6 selection
- `~/smc-lib/scripts/vwap_compare_methods_d_100.py` — M1 vs M2 anchor comparison
- `~/smc-lib/scripts/plot_trendline_l78_from_feb1.py` — TrendLine визуализация

Charts:
- `~/Desktop/i-rdrb-charts/trendline_l78_l200_12h_d_from_feb1.png`

Canon:
- `~/smc-lib/elements/ob_liq/` — обновлено
- `~/smc-lib/zone_of_interest.md` — VWAP добавлен
- `~/smc-lib/rules.md` — Правило 2 синхронизировано

Данные:
- BTC 1m обновлены до **2026-05-26 23:14 MSK** (+3041 баров, через `fetch_btc_1m_missing.py`)
