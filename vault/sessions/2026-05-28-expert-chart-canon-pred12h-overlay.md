---
tags: [session, expert-chart, chart-format, pred12h, vwap, hma, smc-lib, canon]
date: 2026-05-28
related: [[2026-05-27-evening-elements-projects-bearish-sweep]], [[2026-05-27-12h-fractal-or-basket-c3-c4-c5-ob-liq-canon-update]]
---

# 2026-05-28 — Экспертный график канонизирован + chart_format база

Длинная итеративная сессия по визуализации. Результат — две новые канонические сущности в `smc-lib`:
1. **`chart_format.md`** — база чарт-шаблона (свечи, ось, layout, текущая цена, заголовок)
2. **`expert_chart.md`** — экспертный композит (база + Pred-12h overlay + HMA + VWAPs)

Плюс параллельно завершены: Правило 7 (TrendLine HMA 78+200 default), оптимизация и переоценка `run_3candles_sweep`, fetch-pattern для live-данных.

## I. Правило 7 — TrendLine ASVK default

Канон длин HMA зафиксирован в `~/smc-lib/rules.md`:

| Параметр | Значение |
|---|---|
| Mode | `Hma` (Hull MA) |
| Length 1 | **78** (основной TrendLine) |
| Length 2 | **200** (медленный TrendLine) |
| Source | close |
| Value | **LIVE** (HMA[i] = computed on close[i-1], strict-causal) |
| TF (типовые) | 12h, D |

Helpers в `~/smc-lib/indicators/trend_line_asvk.py`:
- `trend_line_hma_78(closes)`
- `trend_line_hma_200(closes)`

Происхождение: проект Pred-12h (С5 = HMA-78 12h∪D, С6 = HMA-200 D, оба LIVE).

Memory: [[feedback-trendline-hma-78-200-default]].

## II. Discovery: intra-bar fill+exit bug в backtesters

При проверке примера 2026-05-10 LONG (run_3candles_sweep) — старый 1h-симулятор посчитал WIN +7.06R, но в реальности (1m развёртка) entry заполнился в 23:44, **и в той же минуте** пробил SL. Реально LOSS −1R.

**Корень бага**: в 1h симуляторе при одновременном касании fill + SL + TP в одном баре использовалась эвристика "близость open к SL/TP". Для wide-RR setups это давало систематические false WIN.

**Фикс**: переписал симулятор на **1m intra-bar walk** с pessimistic правилом (SL первым в баре). Создал `~/smc-lib/scripts/optimize_run_3candles_1h_1m.py` как эталон.

**Результат после fix**: R/tr на baseline run_3candles_sweep упал с +0.65 до +0.03. Edge мифа. Истинное состояние — marginal positive.

Task #28 (pending): зафиксировать правило в smc-lib backtest_guidelines.

## III. run_3candles_sweep: полная переоценка

С honest 1m симулятором:

| Конфиг | n | WR | R/tr (avg) |
|---|---:|---:|---:|
| canon (wick≥2.5, entry 0.3, oба) | 317 | 31.5% | +0.030 |
| immediate entry next_open + TP 2R + wick≥3.5 | 376 | 31.4% | +0.057 |
| **SHORT-only canon на 4h** | **89** | **37.1%** | **+0.302** ⭐ |

Сюрприз: с каноном (pullback entry) **4h — лучший TF**, не 1h. R/tr +0.30 = +4.5 R/год. Pullback-фильтр работает как implicit confluence.

Direction split разный по TF:
- 1h, 8h — SHORT
- 2h, 4h, D — LONG (4h LONG: +3.5 R/год)
- 6h — оба

Portfolio (4h LONG + 1h SHORT + 6h обе + 8h SHORT) = ~12 R/год на BTC standalone.

Task #21 → in_progress (нужна validation на ETH/SOL с честным симулятором).

## IV. chart_format.md — база чарт-шаблона

Создан `~/smc-lib/chart_format.md` + эталон-скрипт `~/smc-lib/scripts/plot_chart_format_template.py`.

Зафиксировано итеративно:

| Параметр | Значение |
|---|---|
| TF | 6h |
| Окно | 60 дней |
| Bull color | `#01a648` |
| Bear color | `#131b1b` |
| Wick | того же цвета что тело |
| Linewidth | 1.1 |
| Промежуток между барами | 0.5 |
| Сетка | выкл |
| Y-шкала | справа, шаг 1000 |
| X-ticks | понедельники + сегодня (DD-MM) |
| Текущая цена | пунктирная `#c62828` + плашка |
| Сегодня | плашка `#c62828` на X-оси |
| Заголовок | одна строка `ASSET \| TF \| DD-MM-YYYY \| HH:MM MSK`, жирный |
| Footer / Y-label | убраны |
| Z-order | линии (≤1), свечи (≥3), маркеры (≥5) |
| Авто-fetch 1m | обязательно |

Memory: [[feedback-chart-format-canonical-base]], [[feedback-always-fetch-1m-before-chart]].

Task #29 → completed.

## V. expert_chart.md — экспертный композит ⭐ ключевое

Создан `~/smc-lib/expert_chart.md` + `~/smc-lib/scripts/plot_expert_chart.py`. Триггер «представить экспертный график» → запуск скрипта.

### Состав

1. **База** (chart_format)
2. **Pred-12h basket overlay** — все потенциальные 12h pivot'ы за 60 дней:
   - ▼ SHORT (FH high) красный filled, **сверху** над high бара (+ offset)
   - ▲ LONG (FL low) зелёный filled, **снизу** под low бара (− offset)
   - НЕ разделяем baseline/basket/confirmed (все одинаково)
3. **TrendLine HMA**:
   - HMA-78 12h LIVE — светло-синий штриховой
   - HMA-200 12h LIVE — тёмно-синий штриховой
   - HMA-78 D LIVE — светло-синий сплошной
   - HMA-200 D LIVE — тёмно-синий сплошной
   - Linewidth 0.8 (тонкие), zorder=1
4. **VWAPs ASVK** (anchor-окно 180 дней, Method 1):
   - **Эффективные** (max composite): 2 под ценой (🟠) + 2 над ценой (🔴)
   - **Проработанные** (max interactions): 1 под + 1 над (🟣)
   - Plain anchor marker если в окне, иначе цветная плашка слева с подписью `SIDE DD-MM-YY`

### Терминология VWAP (канон)

| Имя | Что значит |
|---|---|
| **Эффективный** | max composite (reactions/interactions); price respects |
| **Проработанный** | max total_interactions; price visits often |

### Триггер

«представить экспертный график» / «экспертный график» → запуск `plot_expert_chart.py`.

Memory: [[feedback-expert-chart-trigger]].

Task #30 → completed.

## VI. Что осталось open

- Task #2: Правило 4 (LTF FVG усиливает HTF OB)
- Task #9: VWAPs-стратегия с нуля (in_progress, dynamic-anchor TBD)
- Task #10: dynamic-anchor VWAP по Правилу 6 (реализация)
- Task #21: run_3candles_sweep — OOS на ETH/SOL с честным симулятором
- Task #28: зафиксировать intra-bar bug правило в backtest_guidelines.md

## VII. Артефакты сессии

### Новые файлы
- `~/smc-lib/chart_format.md` (база чарт-шаблона)
- `~/smc-lib/expert_chart.md` (канон композит-чарта) ⭐
- `~/smc-lib/scripts/plot_chart_format_template.py` (эталон базы)
- `~/smc-lib/scripts/plot_expert_chart.py` (эталон экспертного графика) ⭐
- `~/smc-lib/scripts/plot_chart_with_pred12h_basket.py` (рабочий клон expert_chart)
- `~/smc-lib/scripts/optimize_run_3candles_1h_1m.py` (1m intra-bar симулятор эталон)
- `~/smc-lib/scripts/diagnose_run3c_v2.py` (полная диагностика паттерна)
- `~/smc-lib/scripts/diagnose_short_only.py`
- `~/smc-lib/scripts/diagnose_btc_all_tfs_canon.py`

### Обновления
- `~/smc-lib/rules.md` — добавлено Правило 7 (TrendLine HMA 78+200)
- `~/smc-lib/README.md` — ссылки на chart_format.md и expert_chart.md
- `~/smc-lib/indicators/trend_line_asvk.py` — helpers `trend_line_hma_78/200`

### Memory (новые)
- [[feedback-trendline-hma-78-200-default]]
- [[feedback-always-fetch-1m-before-chart]]
- [[feedback-chart-format-canonical-base]]
- [[feedback-expert-chart-trigger]] ⭐

## VIII. Главные takeaways

1. **«Экспертный график» — каноничный композит**: при триггер-фразе запускается `plot_expert_chart.py`, без переизобретения.
2. **TrendLine default = HMA 78 + 200** (Hma mode, LIVE), helpers готовы.
3. **Backtest требует 1m intra-bar walk** для wide-RR setups — иначе systematic false WINs.
4. **run_3candles_sweep edge есть но marginal** на 4h (+0.30 R/tr, +4.5 R/год BTC SHORT-only). Не standalone strategy, скорее confluence trigger.
5. **chart_format база утверждена** — все новые plot-скрипты копируют `plot_chart_format_template.py` как базу.

---

**Связано**: [[2026-05-27-evening-elements-projects-bearish-sweep]] (вчерашняя сессия — структурный рефакторинг smc-lib + С6/С7).
