---
tags: [session, expert, candle-patterns, rules, smc-lib, prediction-algo, canon]
date: 2026-05-28
related: [[2026-05-28-expert-chart-canon-pred12h-overlay]], [[2026-05-27-evening-elements-projects-bearish-sweep]]
---

# 2026-05-28 (evening) — раздел expert/, candle_patterns, Правило 8, заявка на ML-алгоритм прогноза зон

Продолжение [[2026-05-28-expert-chart-canon-pred12h-overlay]] (утро того же дня — chart_format, expert_chart canon, Правило 7). Сейчас структурный рефакторинг + новые разделы + новое правило + открытая постановка задачи на обучающийся алгоритм.

## I. Generic 1m fetcher

Создан `~/smc-lib/scripts/fetch_1m_missing.py` — universal Binance puller. Принимает symbol как CLI:

```
python3 fetch_1m_missing.py BTCUSDT
python3 fetch_1m_missing.py SOLUSDT
python3 fetch_1m_missing.py ETHUSDT
```

Старый `fetch_btc_1m_missing.py` оставлен как legacy. Memory `feedback-always-fetch-1m-before-chart` обновлена на новый путь.

Триггер: пользователь спросил почему SOL экспертный график не докачал данные — пришлось признать что fetch был только под BTC, исправить.

## II. expert_chart.py параметризован по asset

`plot_expert_chart.py` теперь принимает ASSET CLI-arg (BTC/ETH/SOL), сам докачивает данные через generic fetcher, авто-адаптирует Y-step под ценовой диапазон (1000/100/10/1/0.1).

Проверено на SOL — корректная работа, ценовой шаг 5 USDT (вместо 1000), правильный фрактал-детект.

## III. Раздел expert/ создан + перенос

Создан `~/smc-lib/expert/`. Перенесены файлы:
- `expert_chart.md` → `expert/chart.md`
- `expert_opinion.md` → `expert/opinion.md`
- `scripts/plot_expert_chart.py` → `expert/chart.py`
- `scripts/expert_opinion.py` → `expert/opinion.py`
- Новый `expert/README.md` — обзор раздела + триггеры

Все пути обновлены в:
- `~/smc-lib/README.md`
- `~/smc-lib/candle_patterns/README.md` + `catalog.md`
- memory: `feedback-expert-chart-trigger`, `feedback-always-fetch-1m-before-chart`, `feedback-expert-opinion-is-multi-tf-cascade`
- `MEMORY.md` index

**Триггеры финальные**:
- «экспертный график» → `python3 ~/smc-lib/expert/chart.py [ASSET]`
- «экспертное заключение» / «куда пойдёт цена» → `python3 ~/smc-lib/expert/opinion.py --tfs W,D,12h,4h,1h,15m`

## IV. Раздел candle_patterns/ создан

Создан `~/smc-lib/candle_patterns/` для японских свечных паттернов (signal-only, БЕЗ entry/SL/TP).

Граница с другими разделами:
- `elements/` — primitives с zone (marubozu, rb)
- `candle_patterns/` — signal-only (engulfing, hammer, doji, morning star)
- `patterns/` — полные setup'ы (run_3candles_sweep)

Создан `candle_patterns/catalog.md` — таксономия ~75 паттернов из Нисона + Bulkowski:
- Single (20): doji variants, hammer, hanging man, shooting star, marubozu, belt hold
- Two-bar (22): engulfing, harami, piercing, dark-cloud, tweezer, kicker, inside/outside bar
- Three-bar (24): morning/evening star, three soldiers/crows, three inside/outside, abandoned baby
- Multi (9): rising/falling three methods, mat hold, breakaway

Создана **галерея 36 паттернов** которые уверенно реализуемы → `~/Desktop/i-rdrb-charts/candle_patterns_known.png`. Рендер-скрипт `scripts/render_candle_patterns_known.py`.

Был честный self-assessment:
- 30-40 паттернов сразу могу детектить с дефолтными порогами
- 15-20 знаю концепт, нужна верификация thresholds
- 10-15 поверхностно знаю, нужен референс

## V. Правило 8 — Движение цены ⭐ ключевое концептуальное

Добавлено в `~/smc-lib/rules.md` как **Правило 8 «Движение цены»**.

**Принцип**: цена движется как магнит между двумя классами зон:

Два класса притяжения:
- **Ликвидность** (⛽ топливо) — fractal, rb, ob_liq.liq_zone. Скопления ордеров, крупный игрок «собирает» их.
- **Неэффективность** (🧲 магнит) — fvg, i_fvg, marubozu (тело). Дисбаланс buyer/seller, рынок не успел сформировать справедливую цену.

Третий класс — **эффективность** (OB, RDRB, block_orders, ob_liq.zone) — это точки **исполнения** institutional orders, **НЕ магниты**.

Цикл (3 фазы):
1. **Сбор ликвидности** — wick к fractal/rb/ob_liq.liq_zone, снятие стопов розницы
2. **Заполнение неэффективности** — возврат к FVG/i-FVG/marubozu, закрытие имбаланса
3. **Поход к новой цели** — reaction на efficiency-зоне, движение к следующей liquidity-цели

Практ-чек на каждой зоне:
1. К какому классу относится?
2. Mitigated или actionable?
3. На каком TF? (HTF доминирует)
4. Above / inside / below?
5. Если liquidity/inefficiency → магнит
6. Если efficiency → точка реакции

Композиция с другими правилами зафиксирована (1, 2, 5, 6, 7).

## VI. Экспертный график + экспертное заключение для BTC

Сгенерирован полный композит для BTC 2026-05-28:

**Чарт**: `~/Desktop/i-rdrb-charts/btc_6h_pred12h_basket_2026-05-28.png`

**Заключение** (текущая цена 72,966 USDT):

Trend cascade:
- W: HH+HL → UPTREND (macro)
- D: LH+LL → DOWNTREND
- 12h: LH+LL → DOWNTREND
- 4h: LH+HL → CONTRACTION
- 1h: LH+LL → DOWNTREND
- 15m: LH+LL → DOWNTREND

**Конфликт каскада**: pullback в W up-структуре к D demand zone.

Все LTF indicators bearish, RSI oversold (15m=17, 1h=18, 4h=22).

Resistance cluster:
- 74,300-74,700 (15m FH + 1h ob_liq/fvg + VWAP)
- 76,500-77,000 (major: 12h sweep maxV + 4h fractals + VWAP top 0.752)

Support cluster:
- 72,400-72,700 — критический тонкий VWAP support
- 70,500 — major D fractal low

Три сценария (A bounce / B continue down / C extended) с триггерами и инвалидацией. Подробности в чате.

## VII. Задачи: cleanup

Удалены все 32+ tasks (старые трекинг-задачи). Список чистый — начинаем с нуля для новой темы (prediction algorithm).

## VIII. Открытая постановка задачи — Prediction Algorithm ⭐ продолжаем здесь

Пользователь поставил задачу:
> Написать обучающийся алгоритм, который применяя Правило 8 (Движение цены) + зоны интереса, обучается на 5 годах данных multi-TF (W, 3D, 2D, D, 12h, 8h, 6h, 4h, 3h, 2h, 1h, 20m, 15m), находит закономерности и на крайнем году переобучается. В итоге даёт экспертное заключение: 2 зоны сверху + 2 зоны снизу с вероятностями движения туда.

### Что я ответил (резюме)

Три подхода:
- **A. Эмпирические вероятности** (рекомендую как старт): прозрачно, walk-forward friendly, грунтовка на Правилах
- B. XGBoost — выше точность, риск overfit
- C. LSTM/Transformer — потенциально лучше, чёрный ящик

Честные ограничения:
1. BTC нестационарен (паттерны 2020 != 2025)
2. Look-ahead bias риск
3. Probability calibration сложная
4. Малая выборка для специфичных конфигураций
5. «Re-train в live» = mlops pipeline, не магия

Архитектура (5+1 фаза):
1. Feature pipeline (multi-TF + zone detection + classification + state + indicator context)
2. Labelling (walk forward + hit zone first + direction)
3. Empirical model (lookup table или XGBoost regression)
4. Walk-forward validation (train years 1-4, predict year 5, monthly re-train, calibration tracking)
5. Inference CLI (predict_zones BTC → top-2 above + top-2 below)
6. Re-train pipeline (опционально)

### Открытые вопросы — ждём ответы пользователя

1. **Что считать «касанием зоны»?** wick touch / wick+close inside / full mitigation
2. **Horizon prediction**: 1 день / 1 неделя / 1 месяц / multi-horizon
3. **TF reduction**: 13 → 6 основных (W, D, 12h, 4h, 1h, 15m)? Или все 13?
4. **Top-2 above + top-2 below** жёстко, или гибко (1 sup + 3 res в downtrend)?
5. **Re-train frequency**: weekly / monthly / quarterly?
6. **BTC only сначала** или сразу universal (BTC/ETH/SOL)?

Альтернатива — я беру defaults (wick-touch / 30d horizon / 6 TF / 2+2 / monthly / BTC only) и стартую с Phase 1.

### ▶️ Точка продолжения

Следующий шаг — **пользователь отвечает на 6 вопросов** или говорит «используй defaults». После этого реализуем Phase 1 (feature pipeline).

## IX. Артефакты сессии

### Новые файлы
- `~/smc-lib/scripts/fetch_1m_missing.py` — generic fetcher
- `~/smc-lib/scripts/render_candle_patterns_known.py` — галерея 36 паттернов
- `~/smc-lib/expert/README.md`
- `~/smc-lib/expert/chart.md` (был expert_chart.md)
- `~/smc-lib/expert/chart.py` (был scripts/plot_expert_chart.py)
- `~/smc-lib/expert/opinion.md` (был expert_opinion.md)
- `~/smc-lib/expert/opinion.py` (был scripts/expert_opinion.py)
- `~/smc-lib/candle_patterns/README.md`
- `~/smc-lib/candle_patterns/catalog.md` (~75 паттернов)
- `~/Desktop/i-rdrb-charts/candle_patterns_known.png` (галерея 36)
- `~/Desktop/i-rdrb-charts/btc_6h_pred12h_basket_2026-05-28.png` (экспертный график)
- `~/Desktop/i-rdrb-charts/sol_6h_pred12h_basket_2026-05-28.png`

### Обновления
- `~/smc-lib/rules.md` — добавлено **Правило 8 «Движение цены»**
- `~/smc-lib/README.md` — ссылки на expert/, candle_patterns/

### Memory updates
- `feedback-always-fetch-1m-before-chart` — generic fetcher path
- `feedback-expert-chart-trigger` — оба триггера (chart + opinion) в новых путях
- `feedback-expert-opinion-is-multi-tf-cascade` — путь к opinion.py

## X. Главные takeaways

1. **Раздел expert/ самостоятелен** — chart.py + opinion.py + chart.md + opinion.md в одной папке. Триггеры маппятся на CLI-команды.
2. **Раздел candle_patterns/** — японская классика, signal-only, отделён от elements/ и patterns/.
3. **Правило 8 «Движение цены»** — концептуальная основа для prediction-алгоритма (магнит-логика, 3 фазы цикла).
4. **Открытая большая задача** — обучающийся алгоритм прогноза 2+2 зон с вероятностями. **6 вопросов ждут ответа**.

---

**Связано**:
- [[2026-05-28-expert-chart-canon-pred12h-overlay]] (утро того же дня — chart_format + expert_chart canon)
- [[2026-05-27-evening-elements-projects-bearish-sweep]] (вчера — structural refactoring)
