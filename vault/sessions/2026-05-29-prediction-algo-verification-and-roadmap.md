---
tags: [session, prediction-algo, zones, ml, smc, verification, roadmap]
date: 2026-05-29
related: [[2026-05-28-evening-expert-section-candle-patterns-rule8-prediction-algo]], [[2026-05-28-expert-chart-canon-pred12h-overlay]]
---

# 2026-05-29 — Verification walk-forward cadence + анализ ограничений prediction-algo + roadmap из 5 задач

Сессия продолжает [[2026-05-28-evening-expert-section-candle-patterns-rule8-prediction-algo]]. Никаких изменений в код не вносилось — только два запуска экспертных модулей, верификация прошлого результата, концептуальный аудит алгоритма и постановка дальнейшего пути развития.

## I. Два прогона zones_opinion подряд (час разницы)

Цена BTC ≈ 73,666 → 73,691. Margin направления резко вырос за 1 час:

| Прогон | UP first зона | P_first up | DOWN first зона | P_first down | Margin |
|---|---|---|---|---|---|
| 00:14 MSK (≈час раньше) | [73724, 74244] | 0.51 | [73419, 73498] | 0.29 | +0.22 |
| 00:14 MSK (новый) | [73721, 74244] | **0.85** | [73419, 73498] | 0.29 | **+0.56** |

Базовая UP-зона уплотнилась с 5 до 7 элементов (FVG/OB/block_orders/fractal на 1d/1h/4h). Дистанция 31$ / 0.04%. Прогноз: тач 73,983 → магнит [74380, 78080] (P_D=0.67) → далее [74591, 75311]. Invalidation: пробой 73,459 вниз.

Экспертный график сохранён: `~/Desktop/i-rdrb-charts/btc_6h_pred12h_basket_2026-05-28.png`. На графике видна серия SHORT-маркеров pred-12h basket на 18–26 мая и пробой HMA-78/200 12h LIVE сверху вниз — структура восходящего тренда сломана. Это создаёт когнитивное расхождение с zones-прогнозом «вверх», которое разрешается так: zones_opinion даёт **краткосрочный** отскок-в-зону (P_first=0.85 на 31$), а basket warning остаётся для более крупного движения.

## II. Methodology audit — что меняется в training data во время теста

**Вопрос:** «алгоритм учился на 5 годах и тестировался год с переобучением — менялся ли train-датасет?»

**Ответ:** Да. `validate.py:101` использует rolling 365-day window:

```python
train_lo = cut - pd.Timedelta(days=train_window_days)  # default 365
train_data = ds[(ds["cut_off_ts"] >= train_lo) & (ds["cut_off_ts"] < cut)]
```

- Окно **скользит, не растёт.** Старые данные выпадают.
- Тестовые cut-offs становятся частью train следующего retrain (strict cut-off защищает от leakage).
- К концу тест-года train состоит почти полностью из данных самого тест-года — данные первых лет «забыты».

**Фраза в memory «train 1-5 / test 6»** означает только тестовый период = год 6. Сам train — rolling, поэтому это **не** «выучил на 5 годах и удержал», а «постоянно учился на последнем годе и сохранял качество».

## III. Verification: monthly ≈ weekly ≈ one-shot

Запущен `/tmp/verify_retrain_cadence.py` — 3 cadence (monthly / weekly / one-shot=10000d) на test 2025-05-01 → 2026-05-01, 730 cut-offs × ~1820 зон. Каждый прогон ~11 мин.

| Метрика | monthly | weekly | one-shot | spread |
|---|---:|---:|---:|---:|
| Brier_D | 0.0073 | 0.0073 | 0.0074 | 0.0001 |
| **Top-5 hit_D** | **0.871** | 0.868 | **0.856** | **0.014** |
| Top-3 ABOVE | 0.811 | 0.811 | 0.810 | 0.001 |
| Top-3 BELOW | 0.812 | 0.811 | 0.808 | 0.004 |

**Вердикт:** claim в основном подтверждён. Brier и Top-3 идентичны → для production zones_opinion (по сути top-1 на сторону) retrain **не нужен**. Top-5 даёт стабильную просадку 1.4 п.п. у one-shot vs monthly → для широких top-K скринеров monthly retrain стоит держать. Memory `prediction-algo-final-results` остаётся валидной.

## IV. Концептуальный аудит: что именно «выучил» алгоритм

Чёткое разделение:

**НЕ выучено (hard-coded в `zones.py`):**
- Детекция всех 10 типов зон — каноничные SMC-формулы из `smc-lib/elements/`
- Mitigation rules — per-zone канон
- Активность зоны на cut-off — детерминированно
- Границы зон, level, direction

**Выучено (lookup-table в `model.py`):**
Для каждого бакета `(tf, type, side, distance_bucket, age_bucket)` хранятся 4 средних:
- `mean(hit_12h)`, `mean(hit_D)` — P касания
- `mean(first_hit_above)`, `mean(first_hit_below)` — P быть first среди своей стороны

**НЕ моделируется вообще:**
- Траектория цены между зонами
- Тренд / режим рынка / волатильность как фичи
- Time-of-day, день недели, сезонность
- Объём
- Корреляции между зонами (race condition)
- Микроструктура, новости
- Representation learning (всё через ручные бакеты)

**Честная характеристика:** это не «самообучающийся алгоритм находящий паттерны», а:
1. Hand-engineered SMC-detectors (зоны)
2. Empirical calibrator поверх них (lookup-таблица hit-rates)

Качество 87% top-5 hit_D — следствие того, что **зоны построены руками очень хорошо**, а не «ML выучил рынок».

## V. First-touch определяется по ВРЕМЕНИ, не по дистанции

`labels.py:148-154`:

```python
above_hits.sort(key=lambda p: p[1].time_to_hit_minutes)
first_above_idx = above_hits[0][0] if above_hits else -1
```

Сортировка по `time_to_hit_minutes` на 1m данных. В типичном случае ближняя зона действительно first-touch (wick должен пройти через неё), но **это эмпирический факт, а не определение**. Edge cases:
- Одновременное касание в один 1m бар → tie-break по порядку в списке (из `zones.py`)
- Разные предикаты hit (range / fractal sweep strict / marubozu open) → близкие уровни срабатывают по-разному

**Ключевая слабость:** модель оценивает зону **изолированно по фичам бакета**, не зная состав активных зон в этом cut-off. P_first — «маржинальная» вероятность по бакету, не conditional на geometry of current zone set. Сегодняшний пример: DOWN-first зона [73419, 73498] получила всего P_first=0.29 — несмотря на то что это **единственная** below-зона в радиусе $400. Модель этого не видит.

## VI. Roadmap — 5 открытых задач, SMC vs ML

| # | Задача | SMC даёт | ML даёт | Рекомендация | Приоритет |
|---|---|---|---|---|---|
| 1 | Траектория между зонами | AMD-каркас, Power-of-3, sweep-displace-mitigate | Sequence-model (LSTM/Transformer), HMM на discrete states, MC-симуляция | Гибрид: SMC макро + ML микро. Дорого, research-tier | 🔬 низкий |
| 2 | Корреляции между зонами | Confluence, кластеризация | Pairwise P(A\|B), Plackett-Luce / LightGBM Ranker, latent factors | **Чистый ML, easy win** на существующем датасете | 🔥 высокий |
| 3 | Отскок vs пробой | first-touch валидна, mitigated=flip, iFVG/BMS confirmation, HTF context | Binary classifier на rich feature space (penetration depth, volume on touch, HTF trend, distance-from-VWAP, time-of-day) | **HEAVY ML, фичи строит SMC** — самый actionable | 🔥 высший |
| 4 | Max range движения | BSL/SSL targets, Daily-range projection | Quantile regression / NGBoost на max-excursion за 12h/D | ML с SMC-приорами, для TP/SL калибровки | 📊 средний |
| 5 | Последовательность касаний кластера | Магнит-логика, untraded-area + liquidity pools | Plackett-Luce, Markov P(next\|current,set), или derived из #1+#2 | Derived task — побочный продукт #1+#2 | 🧪 низкий |

**Стартовать параллельно с #3 и #2** (независимые треки, 1-3 недели каждый, оба низкорисковые). Далее по результату — #4 или углубление #3.

## VII. Общий принцип

В наших данных SMC сильна как **источник фичей**, ML сильно как **калибратор вероятностей**. Чистая SMC даёт правила без чисел, чистый ML без SMC-фичей — слабый. **Паттерн «SMC fingers → ML head»** работает на всех 5 задачах.

## VIII. Артефакты сессии

- Verification-скрипт: `/tmp/verify_retrain_cadence.py` (одноразовый, не сохранён в проект)
- Чарт: `~/Desktop/i-rdrb-charts/btc_6h_pred12h_basket_2026-05-28.png`
- Новых файлов в `smc-lib/` или `prediction-algo/` не создавалось

## Open questions / next steps

- Решение о порядке #3 / #2 (рекомендация: оба параллельно)
- Дизайн фич для #3 (SMC-context features) — отдельная сессия
- Дизайн set-aware ranking для #2 — отдельная сессия
- Возможное обновление memory: добавить нюанс про top-5 retrain spread 1.4пп — пока решено оставить как есть
