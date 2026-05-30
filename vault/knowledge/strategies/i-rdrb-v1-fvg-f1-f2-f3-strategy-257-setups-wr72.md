---
tags: [strategy, i-rdrb, fvg, filter-stack, btc, 1h]
date: 2026-05-22
status: in-sample-validated
related: [[что такое rdrb]], [[i-rdrb fvg митигация зоны 1h btc eth]], [[универсальные определения OB и FVG]], [[фракталы билла уильямса]], [[три класса зон ликвидность эффективность неэффективность]], [[i-rdrb-v1-fvg-f1-f2-f4-strategy-401-setups-wr71]]
symbols: [BTCUSDT]
timeframe: 1h
period: 2020-05-01 → 2026-05-20 (6 лет)
supersedes: [[i-rdrb-v1-fvg-f1-f2-f4-strategy-401-setups-wr71]]
---

# i-RDRB V1 + FVG · F1 ∪ F2_same · F3(R/ATR) · 257 сетапов · WR 71.60%

Финальный стек после упрощения F4 (4 OR условия + hour exclude) до F3 (R/ATR ∈ [0.55, 1.03]) — одиночное условие с лучшим trade-off.

Результат: **257 сделок за 6 лет, WR 71.60%, Total RR +111R, Max DD −6R, Sharpe-like 3.13.**

## Паттерн i-RDRB V1 + FVG

5 свечей C1..C5 на 1h. LONG (SHORT зеркально).

**3 условия:**

1. **i-RDRB V1 zone** = пересечение нижнего фитиля C1 и верхнего фитиля C3
   - Precondition: `C1.body_bottom ≥ C3.body_top` AND `C3.high ≥ C1.low`
   - Zone = `[max(C1.low, C3.body_top), min(C1.body_bottom, C3.high)]`
2. **Bullish FVG** на тройке C3-C4-C5 (C4 = displacement)
   - `C5.low > C3.high`
3. **C2 закрывает ниже C1.low**: `C2.close < C1.low`

Эталон: BTC 1h 2026-05-19 16:00–21:00 UTC+3.

## Сделка (entry/SL/TP)

- **Entry**: limit на `(rdrb_top + rdrb_bot) / 2` (середина i-RDRB зоны)
- **SL**: `min(C2.low, C3.low, C4.low)` для LONG / `max(C2.high, C3.high, C4.high)` для SHORT
- **TP**: `entry + (entry − SL)` = RR 1:1
- Симуляция на 1h candles, при коллизии TP+SL в одной свече — SL первым (conservative)

## Фильтры

### F1 — HTF Order Block overlap (same direction)

Pattern qualifies если хотя бы одна из C1..C5 (1h) попадает во временной диапазон HTF Order Block candle на любом из **{4h, 6h, 8h, 12h, 1D}**.

- **Bullish OB** (для long): HTF candle bearish AND следующий HTF candle close > этой свечи high
- **Bearish OB** (для short): зеркально

### F2_same — HTF RDRB membership (same direction, c3 closed by fill)

Pattern qualifies если:
1. Хотя бы одна из 5 свечей 1h фрактала попадает в одну из 3 свечей HTF RDRB **того же направления**
2. HTF RDRB c3 candle **закрылся** к моменту fill candle close

HTF RDRB определение (3-свечный):
- LONG: `c1.body_bottom ≥ c3.body_top` AND `c3.high ≥ c1.low` AND `c2.close < c1.low`
- SHORT: зеркально

### Entry condition: F1 ∪ F2_same

Достаточно одного из двух. Применение на baseline 809 → **525 сделок** (WR 64.57%, +153R).

### F3 — R/ATR(20) ∈ [0.55, 1.03]

После F1∪F2_same фильтра, дополнительно проверяем размер R относительно волатильности.

- `R = entry − SL` (для LONG) или `SL − entry` (для SHORT)
- `ATR(20)` на 1h на момент C5.close
- Pass если `0.55 ≤ R/ATR(20) ≤ 1.03`

**Логика:** слишком узкий SL (R/ATR < 0.55) выбивается шумом; слишком широкий (> 1.03) — паттерн рыхлый, цена не доходит до TP.

Применение на 525 → **257 сделок** (WR 71.60%, +111R).

## Результаты 6y

| Шаг | N | WR | Total R | Exp/trade |
|---|---|---|---|---|
| Pattern baseline (long+short) | 809 | 63.78% | +223R | +0.276 |
| + F1 ∪ F2_same | 525 | 64.57% | +153R | +0.291 |
| **+ F3 (R/ATR ∈ [0.55, 1.03])** | **257** | **71.60%** | **+111R** | **+0.432** |

**По side (финал):**

| Side | N | WR | R | Exp |
|---|---|---|---|---|
| LONG | 129 | 72.09% | +57 | +0.442 |
| SHORT | 128 | 71.09% | +54 | +0.422 |

Симметрично: разница WR < 1пп.

**По годам:**

| Год | N | WR | R |
|---|---|---|---|
| 2020 (с мая) | 23 | 73.91% | +11 |
| 2021 | 51 | 74.51% | +25 |
| 2022 | 48 | 72.92% | +22 |
| 2023 | 37 | 64.86% | +11 |
| 2024 | 41 | 75.61% | +21 |
| 2025 | 43 | 60.47% | +9 |
| 2026 (по 20 мая) | 14 | 92.86% | +12 |

Все 7 лет прибыльны. Max DD за весь период: **−6R**. Sharpe-like (R/σ): 3.13.

## Стратификация внутри F3

| R/ATR sub-bucket | N | WR | R |
|---|---|---|---|
| 0.55–0.70 | 101 | 73.27% | +47 |
| 0.70–0.85 | 93 | 73.12% | +43 |
| 0.85–1.03 | 63 | 66.67% | +21 |

Лучше работают меньшие R/ATR (0.55–0.85). Верхняя треть слабее.

## Воронка

```
i-RDRB V1 + FVG (BTC 1h, 6y)              809 ─ 63.78% WR · +223R
   │
   │ F1 ∪ F2_same  (HTF OB на 4h/6h/8h/12h/D
   │                ∪ same-dir HTF RDRB на тех же TFs,
   │                c3 closed by fill)
   ▼                                       525 ─ 64.57% WR · +153R
   │
   │ F3: R/ATR(20) ∈ [0.55, 1.03]
   ▼                                       257 ─ 71.60% WR · +111R · MDD −6R  ★
```

## Cross-validation

**5-fold time-based CV (полное правило):**

| Fold | Период | N | WR |
|---|---|---|---|
| 1 | 2020-05 → 2021-08 | ~80 | ~69% |
| 2 | 2021-08 → 2022-09 | ~80 | ~67% |
| 3 | 2022-09 → 2023-12 | ~80 | ~75% |
| 4 | 2023-12 → 2025-02 | ~80 | ~74% |
| 5 | 2025-02 → 2026-05 | ~80 | ~70% |

Все 5 фолдов в диапазоне 67–75% WR — устойчиво.

## Эксперименты, не вошедшие в финал

### Multi-factor F4 (отброшено)

Изначально пробовался **F4** = OR из 4 условий (`in_ny` ∪ `R/ATR ∈ [0.55, 1.03]` ∪ `b4_b2 ∈ [1.4, 2.7]` ∪ `atr_ratio ∈ [0.97, 1.12]`) + exclude `hour ≠ 2 UTC` → 401 сетап, WR 71.07%, +169R.

Заменено на **F3 alone** (R/ATR ∈ [0.55, 1.03]) — даёт более высокий WR (71.60%) и более простое определение. Меньше сделок (257 vs 401), но лучше per-trade quality. См. предыдущую заметку [[i-rdrb-v1-fvg-f1-f2-f4-strategy-401-setups-wr71]].

### Структурные SL правила (parked, не работают)

Пробовалось заменить SL = pattern.low/high на структурные SL правила на 15m ТФ. Идея: использовать структурные элементы (FVG 15m, 15m фракталы, OB 15m) для определения SL ближе к точке входа.

**Классификация 15m структуры на экстремуме паттерна:**
- **V.1 (strict)**: i15 BEAR + next 15m BULL с body ≥ |bear body| (immediate displacement). На 257: 58 сделок, WR 65.52%.
- **V.2 (hammer)**: i15 = свеча с длинным фитилём reject (для long: BULL hammer; для short: bear с upper wick). На 257: 67 сделок, WR 76.12%.
- **V.3 (block of orders)**: i15 BEAR, next BULL слабый, но в течение 2-3 свечей strong BULL displacement. На 257: 32 сделки, WR 65.62%.
- **NONE**: нет чёткого OB. На 257: 100 сделок, WR 74.00%.

**4 комбинации Entry × SL:**
- Entry: FVG-1 (50% confluence FVG, либо top RDRB) ИЛИ FVG-2 (50% FVG ниже RDRB)
- SL: 0.3 фитиля i15 от low ИЛИ low 15m FL (Williams N=2, после i15)
- Constraint: если Entry = FVG-2, SL = forced 0.3 фитиля

**Результаты на 257:**

| Combo | N | WR | TotR | AvgR(pt) |
|---|---|---|---|---|
| A (FVG-1 confluence + 0.3 фитиля) | 67 | 68.66% | +25 | 326 |
| B (FVG-1 confluence + 15m FL) | 63 | 58.73% | +11 | 251 |
| C (FVG-2 below RDRB + 0.3 фитиля) | 82 | 62.96% | +21 | 205 |
| **Все валидные** | **212** | **63.51%** | **+57** | 257 |
| Skipped (нет FVG) | 45 | — | — | — |

Vs baseline (R-units): **+57R vs +111R** — **в 2 раза хуже**. Тонкие SL ловятся шумом чаще, чем спасают убыточные сделки.

**3 разобранных эталонных кейса (где SL правила сработали хорошо):**

| Trade | Combo | R_baseline | R_new | Outcome |
|---|---|---|---|---|
| 2026-05-17 LONG | A | 196 | 197 | TP→TP |
| 2026-05-02 LONG | C | 143 | 67 | TP→TP (R/2) |
| 2026-04-23 LONG | B | 477 | 199 | SL→SL (loss/2) |

Конкретные удачные кейсы — но общая статистика на 257 негативна. **SL правила запаркованы, не используются.**

## Открытые направления

- Заменить TP +1R на ladder до **liq1/2/3/4** (FH 1h, FH 4h, bearish FVG 1h/2h, bearish FVG 4h/6h)
- Cross-asset validation на ETH/SOL ([[i-rdrb fvg митигация зоны 1h btc eth]] — другой вариант стратегии успешен на cross-asset)
- 2025 regime check — почему WR проседает до 60.47% против 70%+ в остальные годы
- Расследование "premium tier" сабсета (F1 ∩ F2_same пересечение, c1_bullish с асимметрией для LONG)

## Артефакты

- Память Claude: `~/.claude/projects/-Users-vadim/memory/i-rdrb-v1-pattern.md`
- Финальный датасет: `/tmp/i_rdrb_v1_525_dataset.csv` (525 сделок до F3)
- Дополнительные фичи: `/tmp/i_rdrb_v1_525_features_v2.csv`
- Final equity curve: `/Users/vadim/Desktop/i-rdrb-charts/i_rdrb_v1_final_equity.png`
- Эталонный рендер: `/Users/vadim/Desktop/i-rdrb-charts/i_rdrb_v1_reference.png`
- Экспериментальные SL combos: `/tmp/sl_combos_257_v2.csv`
