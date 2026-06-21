# Эмпирические находки (12 июня 2026)

## Главная: MA-family доминирует edge

### Permutation importance fold 2 SHORT_3 (baseline 0.93)

| Rank | Feature | TF | Δ WR при shuffle |
|---|---|---|---|
| 1 | MA_MA_130 | **1w** | −16pp |
| 2 | MA_MA_130 | 15m | −11pp |
| 3 | MA_HMA_180 | **4h** | −11pp |
| 4 | MA_HMA_170 | **1w** | −11pp |
| 5-15 | HMA-90/130/140/170 на 6h/12h, EMA-200 1h, HMA-200 4h | mixed | −9pp каждая |

**Все top-15 — MA-family.** SMC элементы НЕ попадают.

### Permutation importance fold 1 LONG_3 (baseline 0.37)

| Rank | Feature | TF | Δ |
|---|---|---|---|
| 1 | MA_MA_100 | **1h** | −14pp |
| 2 | MA_HMA_10 | **1d** | −12pp |
| 3-15 | MA-90/HMA-10/40/90 на 15m/2h/6h, MA-30 12h, EMA-50 2h | mixed | −7/−9pp |

Снова **все top-15 — MA-family**. Короткие периоды (10-100) vs длинные (130-200) для SHORT.

### Permutation importance fold 3 LONG_3 (baseline 0.23, bull rally)

В bull rally появляются:
- MA-family как обычно (8 фичей в top-15)
- **NMA_2h** (RSI/ATR/volume) +8pp
- **SEQ_2h** (consecutive colors, body expansion) +7pp
- **SMC_OB_VC**, **SMC_OB_LIQ**, **SMC_i_RDRB** в позициях 16-30 — slight contribution

Это **единственный fold где SMC слегка появляется**. В bear/chop — даже не близко.

## Закон распределения фич по регимам

| Регим | Доминирующие фичи | Архетип сетапа |
|---|---|---|
| **Bear / chop** (folds 0, 2) | HMA HTF (1w/6h/4h/1d) длинные (130-200) | "Rally в HTF resistance MA confluence → SHORT" |
| **Recovery** (fold 1) | MA short periods (10-100) на LTF (1h/15m/2h) | "Reclaim MA-100 1h + HMA-10 1d cross → LONG" |
| **Bull rally** (fold 3) | MA mix + NMA_2h + SEQ_2h + слабо SMC | "Multi-signal confluence: trend + momentum + structure" |
| **Distribution** (fold 4) | MA на 4h-1d, HMA-170/180, **SHORT 86% top-0.5%** | "Top fade — entry near resistance MAs" |

## Что НЕ работает (опровергнутые гипотезы)

### Гипотеза 1: Label heterogeneity (2d/14d horizon)
**Тест:** Strict 2d horizon vs 14d vs 60d.
**Результат:**
- 14d ≈ 60d (no improvement)
- 2d **-1 to -8pp** на top-5% — потеряли drift winners
**Вывод:** horizon ≥ 14d optimal для tabular ML

### Гипотеза 2: Path filter (clean entry only)
**Тест:** y=1 only if winner AND pct_move_since_low < 5%
**Результат:** Refuted **до train** — WR uniform (25.6%/26.8%/26.5%) поперёк pct_move_since_low групп
**Вывод:** «У дна» entries НЕ имеют преимущества в WR vs «late». Phase в move не предсказывает успех.

### Гипотеза 3: 3 модели per regime (routing)
**Тест:** Train 3 separate FT моделей на BULL/BEAR/CHOP subsets, route val by regime
**Результат:** **−5 to −9pp** на всех metrics
**Причина:**
1. BEAR data sparse (~743 train points per fold → undertrained)
2. Train/val regime mismatch (fold 0 val 0% BULL, но 19k BULL шли в train зря)
3. Loss of cross-regime info
**Вывод:** Routing вреден; regime как FEATURE (что мы потом сделали) даёт +25pp

### Гипотеза 4: Regime classification per-row (EMA-based)
**Тест:** Считать regime per timestamp по D-EMA-50/200/slope
**Результат:**
- BTC LONG_3: BULL 0.263 / BEAR 0.273 / CHOP 0.261 — **uniform**
- ETH similarly uniform
**Вывод:** Простая EMA-based классификация **не отделяет winners**. Need HMM или volatility-based для лучшей discriminative силы.

## Что работает

### ✅ TCN sequence channel
+3-9pp uplift на baseline FT, особенно SHORT в bear-периодах
**Эпохи:** sustained 0.66, 0.67 top-0.5% SHORT_3 на folds 0, 1 (LUNA, post-FTX)

### ✅ Regime feature как INPUT
+25-27pp top-0.5% LONG_3 (от 0.365 baseline до 0.617 single seed, 0.538 4-seed)
**Механизм:** Модель учит условные правила: "if BULL + signal → P_high; if BEAR + same → P_low"

### ✅ 4-seed ensemble averaging
+5-13pp над одиночными seeds на breakthrough metrics
**Эффект:** Снижает variance, фильтрует init-specific noise

### ✅ Strict 48h labels (только для SHORT)
SHORT_3 fold 2 = 0.86, fold 4 = 0.88 на top-0.5% (4-seed anchored)
Anchored ensemble 4-seed: top-0.5% SHORT_3 mean = **0.576** (2/6 ≥65%)

### ❌ Strict 48h labels (для LONG)
**Killят LONG**: top-0.5% LONG_3 mean 0.260 vs 60d baseline 0.538

### ✅ Anchored walk-forward
Fold 5 train становится 4.5y вместо 2y (vs sliding) → улучшение акйцептанса в позднних folds

### ✅ Clustering / Cooldown filter (post-hoc)
Reduce 1h-предсказания до 5-10 trades/мес at 55-60% WR
**Critical:** model часто confident на 3-5 consecutive 1h bars → 1 кластер = 1 trade

## Сводный закон model behavior

**Модель — не "fingerprint matcher", а conditional rule learner.**

Через regime feature она выучила:
- В BULL рынке: trust short-period MAs reclaim signals, weight NMA/SEQ context
- В BEAR/CHOP: trust HTF MA confluence resistance, ignore short-term anatomy
- В RECOVERY (transition): focus on **reclaim** patterns (MA-100 1h, HMA-10 1d cross)

Это **не разные модели**, а **разные части одного модельного "знания"** активируемые regime input.

## Что СПОНТАННО появилось во время research

- **SMC слабо появляется в bull rally** (fold 3) — i_RDRB на 12h, OB_VC на 1h/2h
- **NMA_2h** ловит ATR/RSI/volume confluence в bull (только)
- **SEQ_2h** консекутивные свечи/body expansion в bull (только)
- **Weekly MAs** на bear/chop — magnet levels с многолетним trend memory
