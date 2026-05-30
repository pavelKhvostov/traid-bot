---
tags: [strategy, i-rdrb, fvg, filter-stack, btc, 1h, superseded]
date: 2026-05-22
status: superseded
related: [[что такое rdrb]], [[i-rdrb fvg митигация зоны 1h btc eth]], [[универсальные определения OB и FVG]], [[фракталы билла уильямса]], [[три класса зон ликвидность эффективность неэффективность]], [[i-rdrb-v1-fvg-f1-f2-f3-strategy-257-setups-wr72]]
superseded_by: [[i-rdrb-v1-fvg-f1-f2-f3-strategy-257-setups-wr72]]
symbols: [BTCUSDT]
timeframe: 1h
period: 2020-05-01 → 2026-05-20 (6 лет)
---

> **⚠ SUPERSEDED**: F4 (4 OR условия + hour exclude) заменён на F3 alone (R/ATR ∈ [0.55, 1.03]). Финальная версия → [[i-rdrb-v1-fvg-f1-f2-f3-strategy-257-setups-wr72]]. Текущий документ оставлен для истории.

# i-RDRB V1 + FVG · стек фильтров F1∪F2 + F4 · 401 сетапов · WR 71.07%

Финал стека фильтров поверх 5-свечного паттерна **i-RDRB V1 + FVG** на BTC 1h.
Результат: **401 сделка за 6 лет, WR 71.07%, Total RR +169R, MaxDD −8R**.

## Содержание

1. [Паттерн](#паттерн)
2. [Сделка (entry/SL/TP)](#сделка)
3. [Фильтры](#фильтры)
4. [Результаты 6y](#результаты-6y)
5. [Cross-validation](#cross-validation)
6. [Воронка](#воронка)

## Паттерн

5 свечей C1..C5 на 1h, LONG-сетап (SHORT — зеркально).

**3 обязательных условия (i-RDRB V1 + FVG):**

1. **Wick overlap C1 и C3** (пересечение нижнего фитиля C1 с верхним фитилём C3):
   - `C1.body_bottom ≥ C3.body_top` (тело C3 ≤ тело C1)
   - `C3.high ≥ C1.low` (фитили дотягиваются)
2. **Bullish FVG на C3-C4-C5** (displacement = C4):
   - `C5.low > C3.high`
3. **C2 закрывает ниже C1.low**:
   - `C2.close < C1.low`

Зона i-RDRB V1 = `[max(C1.low, C3.body_top), min(C1.body_bottom, C3.high)]`.
В большинстве случаев упрощается до `[C1.low, C3.high]`.

Зона FVG = `[C3.high, C5.low]`.

Эталонный пример: **BTC 1h 2026-05-19 16:00–21:00 UTC+3**.

## Сделка

- **Entry**: limit на `(rdrb_top + rdrb_bot) / 2` (середина i-RDRB зоны)
- **SL**: `min(C2.low, C3.low, C4.low)` для long / `max(C2.high, C3.high, C4.high)` для short
- **TP**: `entry + (entry − SL)` = RR 1:1
- Тайминги без таймаутов
- Симуляция на 1h candles, при коллизии TP+SL в одной свече — **SL первый** (conservative)

## Фильтры

### F1 — HTF Order Block overlap

Pattern qualifies if at least one of C1..C5 (1h) попадает в HTF Order Block
candle на любом из **{4h, 6h, 8h, 12h, 1D}**.

- **Bullish OB** (для long): HTF candle bearish AND следующий HTF candle close > этого candle high.
- **Bearish OB** (для short): зеркально.

### F2_same — HTF RDRB same-direction membership

Pattern qualifies if хотя бы одна из 5 свечей 1h фрактала попадает в одну из
3 свечей HTF RDRB **того же направления**, при условии что HTF RDRB
**сформирована (c3 закрылся)** к моменту fill candle close.

HTF RDRB определение (3-свечный, на {4h, 6h, 8h, 12h, 1D}):
- **LONG-shape**: `c1.body_bottom ≥ c3.body_top` AND `c3.high ≥ c1.low` AND `c2.close < c1.low`
- **SHORT-shape**: зеркально

### Entry condition: **F1 ∪ F2_same**

Достаточно одного из двух. Применение этого правила:
- baseline 809 → **525 сделок** (WR 64.57%, +153R)
- Бонусная подгруппа `F1 ∩ F2_same` (153 сделки, WR 67.97%, +0.359R/trade) —
  eligible для повышенного размера позиции.

### F4 — мульти-фактор фильтр качества (на 525)

Применяется ПОВЕРХ F1 ∪ F2_same.

```
F4 = BASE AND NOT EXCLUDE

BASE (хотя бы одно из 4):
  - in_ny:                 13 ≤ hour_utc < 21 (NY session, 16-00 UTC+3)
  - R_atr20 ∈ [0.55, 1.03]: размер риска (entry−SL) к ATR(20) на 1h
  - b4_b2 ∈ [1.4, 2.7]:    |C4.body| / |C2.body|
  - atr_ratio ∈ [0.97, 1.12]: ATR(20) / ATR(50) на 1h

EXCLUDE:
  - hour_utc == 2 (5 UTC+3, низкокачественный час)
```

**Логика BASE-условий:**

- `in_ny` — институциональное время (CME, Coinbase, фонды). Reliable orderflow.
- `R/ATR ∈ [0.55, 1.03]` — sweet spot размера риска. Q1 (<0.55) выбивает шумом (56% WR), Q4 (>1.03) — паттерн рыхлый (59% WR).
- `b4_b2 ∈ [1.4, 2.7]` — C4 (displacement) в 1.4-2.7x от C2 (drop). Сильный, но не over-extended recovery (Q3: 73% WR vs Q4 > 2.7: 58% WR).
- `atr_ratio ≈ 1.0` — стабильный режим волатильности (нет compression, нет резкого расширения).

**Покрытие по 4 BASE-условиям:**

| Условие | N matching (525) | WR |
|---|---|---|
| in_ny | 173 | 72.83% |
| R/ATR [0.55, 1.03] | 257 | 71.60% |
| b4_b2 [1.4, 2.7] | 125 | 73.60% |
| atr_ratio [0.97, 1.12] | 137 | 70.07% |
| **OR (BASE)** | **422** | **69.67%** |
| **+ EXCLUDE hour 2 UTC** | **401** | **71.07%** |

## Результаты 6y

| Шаг | N | WR | Total R | Exp/trade | MaxDD |
|---|---|---|---|---|---|
| Pattern baseline (long+short) | 809 | 63.78% | +223R | +0.276 | −8R |
| + F1 ∪ F2_same | 525 | 64.57% | +153R | +0.291 | — |
| + F4 (только BASE) | 422 | 69.67% | +166R | +0.393 | — |
| **+ F4 полный (с EXCLUDE)** | **401** | **71.07%** | **+169R** | **+0.421** | — |

**По годам (финальное правило):**

| Год | N | WR | R |
|---|---|---|---|
| 2020 (с мая) | 35 | 74.29% | +17 |
| 2021 | 80 | 67.50% | +28 |
| 2022 | 69 | 71.01% | +29 |
| 2023 | 62 | 69.35% | +24 |
| 2024 | 66 | **77.27%** | +36 |
| 2025 | 66 | 63.64% | +18 |
| 2026 (по 20 мая) | 23 | **86.96%** | +17 |

Все 7 лет прибыльны. 2025 — самый слабый (regime change?).

## Cross-validation

**5-fold time-based CV (полное правило F1∪F2_same + F4):**

| Fold | Период | N | WR |
|---|---|---|---|
| 1 | 2020-05 → 2021-08 | 82 | 69.51% |
| 2 | 2021-08 → 2022-09 | 82 | 67.07% |
| 3 | 2022-09 → 2023-12 | 79 | 74.68% |
| 4 | 2023-12 → 2025-02 | 84 | 73.81% |
| 5 | 2025-02 → 2026-05 | 74 | 70.27% |

Все 5 фолдов в диапазоне **67-75% WR** — устойчиво.

## Воронка

```
i-RDRB V1 + FVG (strict, BTC 1h, 6y)                    809 ─ 63.78% WR · +223R
   │
   │ F1 ∪ F2_same  (HTF OB on 4h/6h/8h/12h/D  OR
   │                same-dir HTF RDRB confirmed by fill on same TFs)
   ▼
                                                         525 ─ 64.57% WR · +153R
   │
   │ F4 BASE (хотя бы одно):
   │   in_ny ∨ R/ATR∈[0.55,1.03] ∨ b4_b2∈[1.4,2.7] ∨ atr_ratio∈[0.97,1.12]
   ▼
                                                         422 ─ 69.67% WR · +166R
   │
   │ F4 EXCLUDE: hour_utc ≠ 2
   ▼
                                                         401 ─ 71.07% WR · +169R  ★
```

## Параллельный отдельный фактор F3 (не используется)

**F3** (parked): 1h FH (для long; FL для short) должен сформироваться (confirmation
закрылся) во время armed window (от C5 close до fill).

- 56% match rate, изолированно WR 64.02% (~baseline)
- В комбинации с F1∩F2_any ухудшает результат
- Парадоксально работает только для LONG (+1.7пп WR) и вредит SHORT (−1.1пп)
- Не включён в финал

## Открытые направления

- Заменить TP +1R на ladder до **liq1/2/3/4** (FH 1h, FH 4h, bearish FVG 1h/2h, bearish FVG 4h/6h)
- Cross-asset validation на ETH/SOL ([[i-rdrb fvg митигация зоны 1h btc eth]] показала cross-asset работоспособность для другого варианта стратегии)
- 2025 regime check — почему WR проседает до 63.64%
- Анализ "bonus" подгруппы F1 ∩ F2_same (153 сделки, +0.359R/trade) — sizing strategy

## Артефакты

- Память Claude: `/Users/vadim/.claude/projects/-Users-vadim/memory/i-rdrb-v1-pattern.md`
- Финальный датасет: `/tmp/i_rdrb_v1_525_dataset.csv` (525 сделок до F4)
- Фичи: `/tmp/i_rdrb_v1_525_features_v2.csv`
- Эталонный рендер: `/tmp/i_rdrb_v1_reference.png`
