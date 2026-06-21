---
name: prediction-algo-roadmap-5-questions
description: "5 открытых задач после prediction-algo v1 (2026-05-29). Приоритет: #3 отскок/пробой + #2 корреляции зон параллельно. Паттерн: SMC fingers → ML head"
metadata: 
  node_type: memory
  type: project
  originSessionId: f4db015b-597b-4328-ad33-5010538fa5f2
---

После аудита prediction-algo (2026-05-29) определены 5 открытых задач, которые НЕ покрывает текущий зона-центричный калибратор. Все они выходят за рамки lookup-таблицы hit-rates.

**Why:** Текущая модель — empirical calibrator на hand-engineered SMC зонах. Не моделирует траекторию, корреляции, mit-исход, размах, последовательности. Эти пробелы определяют дальнейший roadmap.

**How to apply:** Когда пользователь возвращается к работе над prediction-algo / расширению модели — это исходный roadmap. Стартовать с #3 и #2 параллельно, остальное по результату.

## 5 задач (по приоритету)

| # | Задача | Подход | Приоритет |
|---|---|---|---|
| 3 | Отскочит vs пробьёт | ML-classifier на SMC-фичах (penetration depth, volume on touch, HTF trend, distance-VWAP) | 🔥 высший |
| 2 | Корреляции между зонами | Pairwise / ranking ML (Plackett-Luce, LightGBM Ranker) | 🔥 высокий |
| 4 | Max range движения | Quantile regression / NGBoost + SMC priors (BSL/SSL distances) | 📊 средний |
| 5 | Последовательность касаний кластера | Derived из #1+#2; standalone — Plackett-Luce baseline | 🧪 низкий |
| 1 | Траектория между зонами | Hybrid SMC макро + ML микро (HMM / sequence model) | 🔬 низкий (research) |

## Ключевой принцип

**SMC fingers → ML head:** SMC даёт фичи (zones, mitigation-state, confluence, liquidity-context), ML калибрует вероятности. Чистый ML на raw OHLCV — слабый и нестабильный. Чистая SMC — правила без чисел. Гибрид работает на всех 5 задачах.

## Известные слабости текущей модели (motivation для roadmap)

- P_first **маржинальная** по бакету, **не conditional** на geometry активных зон в cut-off (см. #2)
- Нет path-modelling — модель не знает между какими зонами цена движется (#1)
- first-touch определяется по времени, но модель не учитывает race condition с другими зонами на той же стороне (#2)
- Нет ответа на самый actionable вопрос трейдера — «удержит ли зона» (#3)

## Connections

- [[prediction-algo-final-results]] — что такое текущая модель v1
- [[feedback-prediction-algo-open-question]] — изначальные параметры задачи
