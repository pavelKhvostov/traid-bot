---
name: force-model-v2-architecture
description: "Force model v2 (2026-06-03): 5 раздельных logistic regressions, 387 коэф., strict Williams-i target на 12h candle. Заменяет старую TF_WEIGHT × hours формулу"
metadata: 
  node_type: memory
  type: project
  originSessionId: 935dc13c-ff07-4b9a-8e0d-e35a63c1d0be
---

# Force model v2 — архитектура (2026-06-03)

**Назначение:** Empirically learned per-zone strength для каждого типа зоны и каждого TF. Заменяет старую `zone_strength()` (formula с naive TF_WEIGHT × age_h × CLASS_W × proximity × mit_w в force_opinion.py:70-85), которая основана на сломанной мультипликации `× hours` ([[empirical-tf-weight-rejected]]).

## Архитектура: 5 раздельных моделей

| Подмодель | Класс | Features × TFs | Коэф. |
|---|---|---|---|
| **FVG** | inefficiency | 9 × 8 | 72 |
| **fractal** | liquidity | 9 × 8 | 72 |
| **OB** | block | 9 × 8 | 72 |
| **block_orders** | block | 8 × 8 | 64 |
| **RDRB** | block | 8 × 8 | 64 |
| **итого** | | | **344** |

**TFs (8):** 1h, 2h, 4h, 6h, 12h, 1d, 2d, 3d. **8h убран 2026-06-03** (пересечение с 4h/12h).

Модели logistic regression (L2). Каждая ячейка `(feature_i, TF_j)` — независимый коэффициент.

## Удалённые типы (по решению пользователя 2026-06-03)

`marubozu`, `ob_liq`, `iRDRB`, `iFVG`, `ob_vc` (последний возвращён как **бинарная фича `has_vc` внутри OB**).

## Per-model feature lists (заморожено)

### FVG (9):
1. `age_bucket` — 3-ordinal (young<5/mid 5-30/old≥30 баров TF)
2. `first_touch` — binary (virgin / touched)
3. `fill_state` — binary (partial / complete by body-close inside)
4. `size_bucket` — binary (`width < 0.5×ATR(14)` small)
5. `direction_match` — зона противоположна direction 12h свечи
6. `htf_trend_match` — slope HMA(78) на TF зоны совпадает
7. `candle_body_atr` — continuous
8. `candle_range_atr` — continuous
9. `candle_direction` — binary bull/bear

⚠️ `prior_n_bars_trend` ВЫРЕЗАН только из FVG (чтобы попасть в 9).

### fractal (9):
1. `age_bucket` — 2-ordinal (new<20 / old≥20 баров TF)
2. `failed_attempts` — binary (0 / ≥1)
3. `wick_size_atr` — binary (`< 1.0×ATR` / ≥)
4. `direction_match`
5. `htf_trend_match`
6. `candle_body_atr`
7. `candle_range_atr`
8. `candle_direction`
9. `prior_n_bars_trend`

### OB (9):
1. `age_bucket` — 2-ordinal
2. `has_vc` — binary (Volume Confirmation present)
3. `size_bucket`
4. `direction_match`
5. `htf_trend_match`
6. `candle_body_atr`
7. `candle_range_atr`
8. `candle_direction`
9. `prior_n_bars_trend`

### block_orders (8):
1. `age_bucket`
2. `size_bucket`
3. `direction_match`
4. `htf_trend_match`
5. `candle_body_atr`
6. `candle_range_atr`
7. `candle_direction`
8. `prior_n_bars_trend`

### RDRB (8):
Identical to block_orders.

## Target (strict, fix prior bug)

`positive = 1` ⟺ измеряемая 12h свеча **сама** = i экстремума Williams n=2. Подтверждается через (N+1)×12h = 36h после open_time свечи.

**Старый bug:** label был «candle_t OR candle_{t+1} = pivot» (lookahead leakage). Убрано.

## Filter rules (PRE-feature engineering)

Полностью отработанные зоны выкидываются ДО labeling:
- **fractal**: `is_swept = true` → drop
- **FVG**: wick-fill consumed → drop
- **OB / block_orders / RDRB**: полное wick-consumption → drop

## TFs (8)

`1h, 2h, 4h, 6h, 12h, 1d, 2d, 3d` — 8h убран 2026-06-03 (см. также методология zone/liquidity).

## Глобальные defaults

- ATR period: 14
- HTF для htf_trend_match: HMA(78) на TF зоны ([[feedback-trendline-hma-78-200-default]])
- candle context: 12h candle ATR-normalized features
- prior_n_bars_trend: linear slope close-цены за N=20 баров до target

## Связи

- [[empirical-tf-weight-rejected]] — отвергнутая старая мультипликативная формула
- [[force-rank-inverted-vs-williams]] — старый тест где force измерял неправильную сущность (атакующий, а не противовес)
- [[zone-class-liquidity-inefficiency-block]] — таксономия 3 классов
- [[feedback-heavy-compute-on-pc]] — полный 6y walk-forward → на Windows PC
- `~/smc-lib/prediction-algo/force_opinion.py:70-85` — старая `zone_strength()` (deprecated после v2)
- Новый модуль: `~/smc-lib/prediction-algo/force_model_v2/`
