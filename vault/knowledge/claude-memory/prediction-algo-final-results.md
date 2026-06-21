---
name: prediction-algo-final-results
description: "Prediction-algo v2 (2026-05-30) — top-5 hit_D = 89.7% lift 68×, 10.17M btc_full с ob_vc + per-zone mit. v1 (2026-05-28) deprecated"
metadata: 
  node_type: memory
  type: project
  originSessionId: ff4f5d07-aadb-4148-b954-c32ba7546ea5
---

Pipeline prediction-algo v2 закрыт 2026-05-30. Все 8 задач v1 + 9 подзадач #0 (canon-обновление) закрыты.

## Архитектура

7 канонических модулей в `~/smc-lib/prediction-algo/`:
- `data.py` — загрузка 1m BTC
- `resample.py` — 15 TF, Monday-anchored W, strict cut-off
- `zones.py` — детекция + mitigation 10 типов зон (precompute + snapshot)
- `labels.py` — hit-detection через 1m
- `dataset.py` — сборка датасета + CLI
- `model.py` — иерархическая LookupModel с Laplace smoothing
- `validate.py` — walk-forward harness
- `cli.py` — predict_zones BTC
- `zones_opinion.py` — каноническое экспертное заключение (кластеризация + сценарии). Базовый прогноз направления выбирается через P_first_hit_above/below (модель предсказывает какая зона будет первой на каждой стороне). Margin между UP/DOWN сторонами: ≥0.15 = уверенный, 0.05-0.15 = небольшой, <0.05 = практически equal — нужен внешний контекст для направления
- `tests/` — 66 unit-тестов, все зелёные

## Финальные результаты v2 walk-forward (5y/1y/monthly, PC1 2026-05-30)

| Метрика | v1 (2026-05-28) | **v2 (2026-05-30)** | Δ |
|---|---|---|---|
| Top-5 hit_D | 87.0% | **89.7%** | +2.7pp |
| Top-3 ABOVE | 80.9% | 83.2% | +2.3pp |
| Top-3 BELOW | 81.0% | **84.9%** | +3.9pp |
| Brier D lift | −45% | −44.1% | ≈ same |
| Lift vs random | 72× | 68.2× | random baseline вырос |

### Cadence-проверка (v2)
- main_5y_monthly: 89.70%
- alt_5y_weekly: 89.78%
- alt_5y_oneshot: 89.67%
- **alt_3y_monthly: 90.05% ← лучший** (свежие данные > объём)

Monthly ≈ weekly ≈ oneshot — паттерны стабильны во времени, как и в v1. Но **3 года тренировки дают чуть лучше чем 5** — для оперативности можно сократить.

### Per-type contribution в top-5 (v2)

| type | % of top5 | hit_D when in top5 |
|---|---|---|
| OB | 27.4% | 90.1% |
| block_orders | 20.3% | 91.4% |
| FVG | 20.1% | 88.7% |
| RDRB | 13.7% | 90.0% |
| **ob_vc (NEW)** | **8.3%** | **90.5%** |
| fractal | 3.7% | 83.7% |
| ob_liq | 3.0% | 88.1% |
| iRDRB | 2.8% | 86.4% |
| iFVG | 0.5% | 90.0% |
| marubozu | 0.0% | — |

**ob_vc** доля в top-5 (8.3%) > доли в датасете (7.6%) — модель его выбирает чаще случайного. hit_D 90.5% когда выбран — на уровне OB.

### Per-mitigation contribution в top-5 (v2)
- wick-fill: 93.3% (hit_D 90.0%) ← доминирует
- sweep (fractal): 3.7% (hit_D 83.7%)
- first-touch (ob_liq): 3.0% (hit_D 88.1%)
- sweep-open (marubozu): 0.0% (1 случай)

## Тренировочный датасет v2

`~/Desktop/btc_full.csv` (1.6 GB CSV / 81 MB parquet zstd, **10.17M строк**, 730 test cuts).
Изменения vs v1 (5.49M):
- **+ ob_vc** (10-й тип, 776K rows)
- **− RB** и **− ob_sweep_liq_4candles** (retrospective, удалены)
- **per-zone mitigation models**: wick-fill / sweep / first-touch / sweep-open (4 модели вместо одной общей)
- Cross-TF zone scanner с HTF→LTF mapping

Регенерация на PC1 2026-05-29 (compute-archives/compute-2026-05-29-btc-full-regen).
Walk-forward v2 на PC1 2026-05-30 (compute-archives/compute-2026-05-29-prediction-algo-walkforward).

## Триггеры для будущих сессий

- «**предскажи зоны BTC**» → `python3 ~/smc-lib/prediction-algo/cli.py`
- «**экспертное заключение по зонам**» → `python3 ~/smc-lib/prediction-algo/zones_opinion.py`
  (выдаёт карту кластеров, базовый прогноз, цепочку магнитов, сценарии A/B, invalidation)

## Параметры зафиксированные пользователем (v1 + v2 уточнения)

| # | Параметр | v1 решение | v2 уточнение |
|---|---|---|---|
| 1 | Mitigation | per-zone (wick-fill/first-touch/sweep) | + **sweep-open** (marubozu) = 4 модели |
| 2 | Horizon | 12h + D (multi) | то же |
| 3 | TF set | 1h, 4h, 12h, 1d | то же |
| 4 | Top-K | гибко 2+3 / 3+2 | то же |
| 5 | Re-train | monthly = best | monthly ≈ weekly ≈ oneshot; 3y ≈ 5y train |
| 6 | Universe | BTC only | то же |
| 7 | Cut-off | run-time | то же |
| 8 | Split | train 1-5 / test 6 | rolling 5y train / 1y test (canon) |
| 9 | Zone types | 10/11 | **10/12**: + ob_vc, − RB, − ob_sweep_liq_4candles |

## Connections

- `[[smc-lib-location]]` — корень библиотеки
- `[[btc-data-1m-csv]]` — источник 1m данных
- `[[feedback-zone-mitigation-rules]]` — per-zone канон mitigation (использован для labelling)
- `[[zone-class-liquidity-inefficiency-block]]` — таксономия зон
- `[[feedback-prediction-algo-decisions]]` — параметры задачи (предшественник этой записи)
