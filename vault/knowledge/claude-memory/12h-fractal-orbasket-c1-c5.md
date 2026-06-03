---
name: 12h-fractal-orbasket-c1-c7
description: "12h Pred-фрактал OR-basket: C1-C7 утверждены. Basket=654/66.8%/15 imp. Missed=3 (#14, #15, #48). Baseline F1∩F2∩F3=1267/48.9%/18. Project canon: ~/smc-lib/projects/pred12h-fractal-three-candles.md"
metadata: 
  node_type: memory
  type: project
  originSessionId: 3af6f0d9-c3ee-48ba-ae08-4c05d8c82af3
---

# 12h Pred-фрактал OR-basket — состояние C1-C7 на 2026-05-27

Полный canon: `~/smc-lib/projects/pred12h-fractal-three-candles.md`. Здесь — короткая сводка для memory.

## Baseline

F1∩F2∩F3 = **1267 pivots / 619 conf / P=48.9% / 18 imp**. BTC 6y in-sample.

## Условия в корзине (independent на baseline)

| # | Условие | keep | conf | P(W) | imp |
|---|---|---:|---:|---:|---:|
| **С1** | sweep maxV(i-1) на 1m | 357 | 268 | 75.1% | 5 |
| **С2** | union P11_count {8,12,16,24}×15m direction-matched | 193 | 141 | 73.1% | 5 |
| **С3** | FIRST 50%-sweep ob_liq (liq_zone ∪ OB.zone) | 115 | 80 | 69.6% | 2 |
| **С4** | FIRST 50%-sweep FVG multi-TF | 180 | 107 | 59.4% | 3 |
| **С5** | sweep TL HMA-78 (12h ∪ D) LIVE | 185 | 124 | 67.0% | 5 |
| **С6** | sweep TL HMA-200 D LIVE | 49 | 40 | **81.6%** | 1 |
| **С7** | FIRST 50%-sweep block_orders multi-TF | 54 | 48 | **88.9%** | 1 |

## Корзина

- **Basket = C1∪…∪C7 = 654 / conf=437 / P(W)=66.8% / 15 imp**
- **Остаток = 613 / 182 / 29.7% / 3 imp**

## 3 непойманных missed (после C1-C7)

| # | MSK | dir |
|---|---|---|
| #14 | 2026-03-04 15:00 | high |
| #15 | 2026-03-08 15:00 | low |
| #48 | 2026-05-06 03:00 | high |

Не реагируют ни на одну из протестированных зон/индикаторов (block_orders, RDRB POI, iFVG, ob_liq, FVG, HMA L=30/49/78/150/200).

## Семантика

### 50%-sweep
`SHORT: high ≥ (lo+hi)/2 AND close < lo` | `LONG: low ≤ (lo+hi)/2 AND close > hi`

### FIRST sweep
Pivot — первый 12h-бар после ready_ms, выполнивший sweep данной зоны.

### LIVE TrendLine
HMA value на pivot bar i = HMA[i-1] (значение из закрытого предыдущего бара = displayed на чарте).

### Direction-matched
FH ← SHORT zone (resistance test from below); FL ← LONG zone (support test from above).

## Принцип принятия условий

Изначально: WR ≥ 70%. Смягчено: принимаются condition < 70% если уникально ловят missed imp (C4 = 59.4%, C5 = 67.0%, C3 = 69.6%). Полный canon принципа: `[[feedback-12h-fractal-or-basket-arch]]`.

## How to apply

- При обсуждении 12h Pred-фрактала — использовать эти 7 условий
- При поиске C8: цель catch ≥1 из 3 missed (#14, #15, #48). Standalone WR желателен ≥70%.
- Каждое условие independent на baseline 1267 (НЕ на residual)

## Related

- [[feedback-12h-fractal-baseline-f1f2f3]] — baseline pinning
- [[feedback-12h-fractal-or-basket-arch]] — OR-basket arch
- [[12h-fractal-filter-F1-F2]] — F1+F2+F3 канон (baseline)
- [[feedback-ob-liq-no-fractality]] — ob_liq без Williams (используется в С3)
- `~/smc-lib/projects/pred12h-fractal-three-candles.md` — полный canon проекта
