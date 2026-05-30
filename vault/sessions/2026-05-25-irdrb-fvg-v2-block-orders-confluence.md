---
tags: [session, irdrb-fvg, v2, block-orders, confluence, backtest, combined-d]
date: 2026-05-25
duration: длинная сессия (ночь)
status: complete
related: [[2026-05-24-smc-lib-cascade-expert-opinion-indicators]], [[i-rdrb-fvg-v2-definition]], [[i-rdrb-fvg-combined-d-block-edge-sl-01]]
---

# 2026-05-25 — i-RDRB+FVG V2 + block_orders confluence anti-filter

Продолжение работы над стратегией с целью RR≥1 при ~10 trades/мес. Главные находки:
1. **Определён новый паттерн i-RDRB+FVG V2** (6-bar, FVG на C4-C5-C6)
2. **Найден анти-фильтр**: FULL overlap с same-direction block_orders → WR 47.97%, −5R на 125 setups (бесплатный edge boost через exclusion)
3. **Найден quality-filter**: NO overlap с block_orders → WR 62.73%, R/tr +0.255 (best subset)

## I. i-RDRB+FVG V2 — новое определение

Пользователь поделился картинкой 6-свечного паттерна и пояснил: V2 это **сдвинутый FVG**:

| Composite | Candles | Где FVG | Trading-смысл |
|---|---|---|---|
| V1 (canonical) | 5 | FVG на (C3, C4, C5) | displacement-FVG одновременно с i-RDRB reversal |
| **V2 (новое)** | **6** | FVG на **(C4, C5, C6)** | **continuation-FVG ПОСЛЕ i-RDRB reversal** |

В V2 после reversal-свечи C4 импульс продолжается так сильно, что оставляет **отдельный gap** между C4.high и C6.low (LONG) или C4.low и C6.high (SHORT). C5 — серединная свеча FVG.

**Зоны интереса для V2** (обе нужны):
- **i-RDRB.rdrb.POI** (block ± liq) — главная зона входа (наследуется от подлежащего RDRB)
- **FVG.zone на C4-C5-C6** — отдельная зона continuation-импульса, физически **выше** (LONG) / **ниже** (SHORT) i-RDRB block

Подробности → [[i-rdrb-fvg-v2-definition]].

## II. Counts на BTC 1h за 6 лет

```
i-RDRB total (C1-C4):    2,545
├── V1 (FVG C3-C4-C5):     800   (11.1/мес)
├── V2 (FVG C4-C5-C6):     294   (4.1/мес)
└── V1 ∩ V2 overlap:       156   (одна i-RDRB → FVG в обоих местах)
Total V1+V2:             1,094
```

V2 split:
- LONG 159 / SHORT 135
- Underlying RDRB V1: 124, RDRB V2: 170 → V2-FVG чаще над V2-RDRB (58% vs ~43% baseline) — подтверждает интерпретацию "глубокий reversal → сильное follow-through"

Скрипт: `~/smc-lib/scripts/count_irdrb_fvg_v1_v2_split_1h_6y.py`.
CSV-дамп V2: `~/Desktop/i-rdrb-charts/irdrb_fvg_v2_1h_6y.csv` (294 строки).

## III. Backtest Combined D entry/SL @ RR=1.0 на 1094 setups

Entry/SL (canon из [[i-rdrb-fvg-combined-d-block-edge-sl-01]]):
- LONG: `entry = block.top`, `SL = pattern_low + 0.1 × (block.bottom − pattern_low)`
- SHORT: `entry = block.bottom`, `SL = pattern_high − 0.1 × (pattern_high − block.top)`
- TP = `entry ± 1.0 × R_unit` (RR 1:1)

| Подвыборка | n_closed | NoFill | WR | ΣR | R/tr | Trades/мес |
|---|---:|---:|---:|---:|---:|---:|
| V1 only | 773 | 27 | 57.70% | +119.0R | +0.154 | 10.7 |
| V2 only | 277 | 17 | 57.40% | +41.0R | +0.148 | 3.8 |
| **V1 + V2** | **1050** | 44 | **57.62%** | **+160.0R** | **+0.152** | **14.6** |

LONG vs SHORT (V1+V2):
- LONG 538 trades, WR 61.90%, +128R
- SHORT 512 trades, WR 53.12%, +32R (SHORT слабее, но не breakeven как раньше)

Скрипт: `~/smc-lib/scripts/backtest_combined_d_v1_v2_1094.py` (поддерживает baseline/RR=1.0/RR=2.2 режимы).

## IV. ⭐ block_orders × i-RDRB+FVG confluence на 1h — ключевая находка

Проверили пересечение свечей i-RDRB+FVG (5 или 6 candles) со свечами 1h block_orders (preceding + N₁ initial + N₂ counter):

| Bucket | n_setups | n_closed | **WR** | **ΣR** | R/tr |
|---|---:|---:|---:|---:|---:|
| ⚠️ **FULL overlap · SAME dir** | 125 | 123 | **47.97%** | **−5.0R** | **−0.041** |
| PARTIAL · SAME dir | 567 | 539 | 59.74% | +105.0R | +0.195 |
| PARTIAL · OPPOSITE dir | 291 | 278 | 55.76% | +32.0R | +0.115 |
| ⭐ **NO overlap (clean)** | 111 | 110 | **62.73%** | +28.0R | **+0.255** |
| TOTAL | 1094 | 1050 | 57.62% | +160.0R | +0.152 |

**Главное открытие**: когда i-RDRB+FVG паттерн **полностью внутри** block_orders **того же направления** — WR падает до 48% и ΣR уходит в минус. **Late entry в already-resolved institutional structure** — momentum иссяк.

**Quality-filter "no overlap"**: паттерн в чистой структуре без HTF consolidation → лучший edge (WR 62.73%, R/tr +0.255).

**Если применить exclusion-filter (выкинуть FULL SAME):**
- 969 setups, 927 closed
- ΣR: +165R (+5R vs baseline)
- WR: 58.9% (+1.3pp)
- R/trade: +0.178 (+17%)
- **Trades/мес: 12.9** (всё ещё выше цели)

**Selective filter (PARTIAL SAME + NO overlap only):**
- 678 setups, ~649 closed
- ΣR: +133R
- WR: 60.2%
- R/trade: +0.205 (+35%)
- **Trades/мес: 9.0** — близко к цели

Скрипт: `~/smc-lib/scripts/backtest_irdrb_fvg_block_orders_confluence.py`.

## V. Терминология "armed window"

Период от формирования паттерна (C5/C6 close) до fill (entry) называется **armed window** ([[i-rdrb-v1-fvg-f1-f2-f4-strategy-401-setups-wr71]] line 17, [[2026-05-24-smc-lib-canon-vwap-asvk-introduction]]).

Состояния setup'a:
- `armed` — лимит выставлен, ждём митигацию зоны
- `in trade` — fill произошёл, ждём SL/TP
- `mitigated` — первое касание entry zone (активирует лимит в canon-стратегии mitigation)

В моём backtest упрощённая модель: первое касание entry price = fill. В canon-стратегии нужна отдельная фаза митигации сначала.

## VI. Что осталось / TODO на завтра

### Приоритет 1 — применение block_orders anti-filter
1. **Apply exclusion-filter** (FULL SAME out) к V1+V2 → официальный baseline strategy
2. **Sub-analysis FULL SAME**: проверить если LONG bias (50% WR) можно спасти доп-фильтром, а SHORT (46%) выкинуть
3. **Cross-TF проверка**: пересечение с block_orders на 4h, 12h, D — может работать наоборот (HTF block = positive)

### Приоритет 2 — cascade-фильтры
- Наложить cascade (W→15m trend, ASVK RSI zone, VIC delta, MH color, Hull) на 969 setups (после anti-filter)
- Цель: WR 65-70% при сохранении ~10-12/мес

### Приоритет 3 — V2 как primitive в smc-lib
- Добавить детектор V2 в `~/smc-lib/elements/i_rdrb_fvg/code.py` с параметром `variant: Literal["V1", "V2"]`
- Или создать отдельный `~/smc-lib/elements/i_rdrb_fvg_v2/`
- Тесты на 6-bar detection

### Приоритет 4 — RR experiments
- Сравнить RR 1.0 vs 1.5 vs 2.2 на отфильтрованном subset
- Найти optimal RR с учётом block_orders фильтра
- Может ladder-TP (50% @ RR 1.0, 50% @ RR 2.2)

### Приоритет 5 — live-screener
- Скрипт ежечасной проверки: появился ли setup, передаёт ли block_orders anti-filter, какой cascade context

## VII. Артефакты

### Новое в `~/smc-lib/scripts/`
- `count_irdrb_fvg_v1_v2_split_1h_6y.py` — раздельный счёт V1/V2
- `count_irdrb_fvg_by_variant_1h_6y.py` — split по underlying RDRB variant (V1/V2 в smc-lib смысле)
- `backtest_combined_d_v1_v2_1094.py` — backtest с режимами baseline / RR=1.0 / RR=2.2
- `backtest_irdrb_fvg_block_orders_confluence.py` — overlap analysis

### Новое в `~/Desktop/i-rdrb-charts/`
- `irdrb_fvg_1h_6y_by_variant.csv` (800 V1 setups с underlying RDRB variant)
- `irdrb_fvg_v2_1h_6y.csv` (294 V2 setups)

### Git status
Запушен commit `0b69228` на `Vadim` branch локально — push на origin не прошёл (auth via VS Code не доступна из терминала). Пользователь запушит сам.

## Связи

- [[2026-05-24-smc-lib-cascade-expert-opinion-indicators]] — предыдущая сессия
- [[i-rdrb-fvg-combined-d-block-edge-sl-01]] — entry/SL canon
- [[i-rdrb-fvg-v2-definition]] — V2 pattern definition (новый knowledge note)
- [[2026-05-24-i-rdrb-fvg-evot-vwap-features-sl-optim]] — feature mining
- [[i-rdrb-v1-fvg-f1-f2-f4-strategy-401-setups-wr71]] — F1/F2/F3/F4 filters, armed window concept
