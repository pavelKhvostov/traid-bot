---
tags: [strategy, i-rdrb, fvg, v2, pattern-definition]
date: 2026-05-25
status: identified-from-screenshot
related: [[2026-05-25-irdrb-fvg-v2-block-orders-confluence]], [[i-rdrb-fvg-combined-d-block-edge-sl-01]]
---

# i-RDRB+FVG V2 — определение паттерна (6-bar, continuation-FVG)

Вариант i-RDRB+FVG где FVG формируется **после** i-RDRB-разворота, а не вместе с ним. 6-свечный паттерн (вместо canonical 5).

## Структура

```
   C1          C2            C3                   C4                C5            C6
 ┌──┐        ┌───┐                              ┌──────┐
 │  │        │   │                              │      │           ┌────┐       ┌──┐
 │  │        │   │   ↓ displacement down        │      │           │    │       │  │
 │  │        │   │   ┌────┐                     │      │           │    │       │  │
 │  │        │   │   │    │                     │      │           │    │       │  │
 │  │        │   │   │    │                     │      │           │    │       │  │
 │  │        │   │   │    │                     │      │           │    │       │  │
 └──┘        └───┘   │    │                     │      │           └────┘       └──┘
                     └────┘                     └──────┘                            
                       C3 (bear, displ down)    C4 (BIG bull,                       
                                                reversal up)         ↑ FVG gap здесь
                                                                   между C4.high
                                                                   и C6.low
```

## Свечи и их роли

| Index | Свеча | Роль |
|---|---|---|
| **C1** | первая свеча RDRB | anchor |
| **C2** | bear (displacement) | RDRB направление: **SHORT** (C2 bear) |
| **C3** | bull (rejection) | RDRB.C3 — rejection candle, upper wick into C1.lower_wick |
| **C4** | **BIG bull** (или mirror) | i-RDRB.C4 — displacement reversal, close > rdrb.block.top → i-RDRB **LONG** |
| **C5** | continuation candle | FVG.c2 (середина gap) — НЕ FVG.c3 как в V1! |
| **C6** | continuation candle | FVG.c3 — конец gap. **C4.high < C6.low** для LONG → FVG между C4 и C6 |

Для SHORT — зеркально (C2 bull, C3 bear rejection, C4 BIG bear reversal down).

## Условия

1. **i-RDRB на (C1, C2, C3, C4)** — см. `~/smc-lib/elements/i_rdrb/definition.md`.
2. **FVG на (C4, C5, C6)** — см. `~/smc-lib/elements/fvg/definition.md`.
3. **Направления совпадают**: `fvg.direction == i_rdrb.direction`.

Ключевое отличие от V1: FVG-середина = **C5** (НЕ C4 как в V1), FVG-displacement = **C4** само (= i-RDRB.C4).

## Сравнение с V1

| Свойство | V1 (canonical) | V2 (новое) |
|---|---|---|
| Количество свечей | 5 | **6** |
| FVG расположение | (C3, C4, C5) | **(C4, C5, C6)** |
| FVG.c2 (displacement of FVG) | = C4 (одновременно и displacement и FVG middle) | = C5 (отдельная continuation-свеча) |
| FVG.c3 (закрывающая FVG) | = C5 | **= C6** |
| Тип FVG | displacement-FVG (одновременно с reversal) | **continuation-FVG (после reversal)** |
| Зона FVG относительно block | внутри или рядом с RDRB block | **физически выше (LONG) / ниже (SHORT)** RDRB block |
| Armed window starts | C5 close | **C6 close** (один час позже) |
| Trading-смысл | reversal + одновременный gap | **strong follow-through после reversal** |

## Зоны интереса (две, обе нужны)

| Зона | LONG | SHORT | Источник |
|---|---|---|---|
| **i-RDRB.rdrb POI** | `[C1.body_top, block.top]` | `[block.bottom, C1.body_bottom]` | подлежащий RDRB |
| **FVG.zone V2** | `[C4.high, C6.low]` | `[C6.high, C4.low]` | FVG на C4-C5-C6 |

POI = главная зона входа (block ± liq).
FVG.zone V2 = continuation-impulse gap, физически в направлении i-RDRB-разворота (выше для LONG, ниже для SHORT).

## Counts на BTC 1h за 6 лет (2020-05 → 2026-05)

```
i-RDRB total:        2,545
V1 (FVG C3-C4-C5):     800   (11.1/мес)
V2 (FVG C4-C5-C6):     294   (4.1/мес)
V1 ∩ V2 overlap:       156   (одна i-RDRB → FVG в обоих местах)
Unique V1∪V2:          938
```

V2 split:
- LONG 159 / SHORT 135
- Underlying RDRB V1: 124 (42%), RDRB V2: 170 (**58%**)
- → V2-FVG **чаще над V2-RDRB** (block==POI, deeper reversal) — подтверждает интерпретацию

## Backtest @ Combined D entry/SL + RR=1.0

V2 only:
- 294 setups, 277 closed (17 NoFill)
- WR **57.40%**, ΣR **+41.0R**, R/trade **+0.148**

V2 split by side:
- LONG 150 trades, WR 60%, +30R
- SHORT 127 trades, WR 54.33%, +11R

V2 имеет ту же R/trade как V1 (+0.148 vs +0.154) — самостоятельно жизнеспособен, но в 3× реже.

## Применение и фильтры

V2 хорошо комбинируется с V1 (overlap всего 156/1094 = 14%, в основном независимые setups).

Anti-filter из [[2026-05-25-irdrb-fvg-v2-block-orders-confluence]]:
- **FULL overlap с same-direction 1h block_orders** → выкинуть (WR падает до 48%)
- **NO overlap (clean structure)** → boost-filter (WR 62.73%)

## TODO

1. **Реализовать V2-detector в smc-lib** — `~/smc-lib/elements/i_rdrb_fvg/` либо параметром `variant`, либо отдельной функцией `detect_i_rdrb_fvg_v2()`. Добавить тесты.
2. **Визуализировать V2** как PNG для definition.md (по аналогии с другими элементами).
3. **Real example** из BTC 1h history — выбрать одну V2 ситуацию с graphic illustration.

## Связи

- [[i-rdrb-fvg-combined-d-block-edge-sl-01]] — entry/SL canon для обоих вариантов
- [[2026-05-25-irdrb-fvg-v2-block-orders-confluence]] — session note где V2 определён
- [[что такое rdrb]] — подлежащая 3-bar структура (V1/V2 RDRB-pattern — другая концепция, не путать)
- [[2026-05-24-smc-lib-cascade-expert-opinion-indicators]] — где описана canonical V1 структура
