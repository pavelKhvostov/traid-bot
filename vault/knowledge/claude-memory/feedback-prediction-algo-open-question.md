---
name: feedback-prediction-algo-decisions
description: Major-задача (2026-05-28) — обучающийся алгоритм прогноза 2+2 зон. 6 параметров определены, готов старт Phase 1
metadata: 
  node_type: memory
  type: project
  originSessionId: 3af6f0d9-c3ee-48ba-ae08-4c05d8c82af3
---

Пользователь поставил задачу 2026-05-28: построить **обучающийся алгоритм** который применяя Правило 8 (Движение цены) + зоны интереса, обучается на multi-TF данных и даёт прогноз — топ-зоны сверху + топ-зоны снизу с вероятностями.

**Why:** Major project направление, может занять много сессий. Полный контекст в Obsidian-сессии `2026-05-28-evening-expert-section-candle-patterns-rule8-prediction-algo`.

**How to apply:**

При возврате к теме НЕ начинать с нуля. Параметры зафиксированы (2026-05-28):

### Решения по 6 вопросам

| # | Параметр | Решение |
|---|---|---|
| 1 | Что считать касанием зоны | **per-zone канон** из [[feedback-zone-mitigation-rules]]: wick-fill (OB/FVG/iFVG/RDRB/block_orders/iRDRB), first-touch (RB/ob_liq), sweep (fractal, marubozu open). НЕ единое правило |
| 2 | Horizon prediction | **multi-horizon: 12h И D** (две prediction-головы) |
| 3 | TF reduction | **TF list — экспериментально подбирать**. Финальный output = зоны (price-range), какие TF в обучении использовать — решает алгоритм/исследование |
| 4 | Top-K | **гибко** — топ-5 zones by P(hit-first) распределяются по сторонам (может быть 2+3, 3+2, 4+1) |
| 5 | Re-train frequency | На крайнем тестовом году — **переучивать постоянно** пока walk-forward метрики не достигнут приемлемого уровня. Production cadence определим потом |
| 6 | Универсум | **BTC only** |
| 7 | Cut-off (момент прогноза) | **По запросу** — пользователь запускает `predict_zones BTC` в любой момент, тот момент = cut-off |
| 8 | Train/test split | **Train: годы 1-5, Test: год 6** (крайний). Walk-forward с агрессивным re-train на году 6 |
| 9 | Стартовый набор зон | **Все типы из `~/smc-lib/elements/`** — OB, ob_liq, FVG, iFVG, RDRB POI, iRDRB POI, RB, fractal, marubozu, block_orders, ... |

### Архитектура (5+1 фаза)
1. Feature pipeline — все 13 TF + zone detection (`elements/`) + classification (Правило 8) + state (Правило 2) + indicator context
2. Labelling — walk-forward, hit zone first + direction + time_to_hit (per-zone mitigation rules); двойная метка для 12h и D horizons
3. Empirical model — начать с подхода A (lookup table / эмпирические вероятности), upgrade к XGBoost если edge мал
4. Walk-forward validation — train years 1-4, test year 5; агрессивный re-train (weekly/monthly/daily) пока calibration не приемлема
5. Inference CLI — `predict_zones BTC` → топ-5 зон отсортированных по P(hit-first), с указанием стороны и horizon
6. Re-train pipeline (опц.)

### Ограничения (фиксировать в дизайне)
- BTC нестационарен — patterns деградируют → walk-forward обязателен
- Look-ahead bias — все features из baremetal 1m CSV [[btc-data-1m-csv]] с строгим cut-off по времени
- Probability calibration — Brier score + reliability curve
- Малая выборка для специфичных configs → разумная регуляризация / pooling
- 13 TF feature pipeline = много фич → risk overfitting, нужен feature importance/selection

### Phase 1 старт
Готов писать `feature_pipeline.py`:
- input: BTC 1m CSV до cut-off timestamp
- resample → 13 TF
- detect zones (все типы из smc-lib/elements/)
- classify by Правило 8 + zone-class taxonomy
- output: snapshot всех активных зон с features в момент cut-off

Зависит от: Правило 8 (концепт), `~/smc-lib/elements/` (zone detection), [[feedback-zone-mitigation-rules]] (labelling), `expert/opinion.py` (база для feature extraction).
