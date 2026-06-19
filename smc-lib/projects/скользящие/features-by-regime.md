# Какие фичи в каком режиме доминируют

На основе permutation importance на 3 fold/head парах (v3-regime-feat модель).

## BEAR / CHOP режим (fold 2 SHORT_3 = 0.93)

**Архетип:** "Rally в HTF resistance MA confluence → SHORT entry"

### Top-15 фичей (все MA-family):

| Rank | Token | TF | Type |
|---|---|---|---|
| 1 | MA_MA_130 | 1w | SMA-130 weekly |
| 2 | MA_MA_130 | 15m | SMA-130 на 15-min |
| 3 | MA_HMA_180 | **4h** | HMA-180 4h |
| 4 | MA_HMA_170 | 1w | HMA-170 weekly |
| 5 | MA_HMA_140 | 15m | HMA-140 LTF |
| 6 | MA_EMA_200 | 1h | EMA-200 classic |
| 7 | MA_HMA_150 | 2h | |
| 8 | MA_HMA_200 | 4h | |
| 9 | MA_MA_110 | **6h** | |
| 10 | MA_HMA_90 | 6h | |
| 11 | MA_HMA_130 | 6h | |
| 12 | MA_HMA_140 | 6h | |
| 13 | MA_HMA_170 | 6h | |
| 14 | MA_HMA_170 | 12h | |
| 15 | MA_HMA_40 | 1d | |

### Что доминирует:

- **6h TF — 5 фичей в топе** (sweet spot для bear/chop)
- **4h TF — 2 фичи** (HMA-180, HMA-200)
- **Weekly TF — 3 фичи** (MA-130, HMA-170)
- **1d/12h — 2 фичи**
- **HMA семейство — 10 из 15** (Hull moving average — наш канонический trend-line)
- **Длинные периоды (130-200)** — long-term trend memory

### Что НЕ доминирует:
- ❌ SMC (ниже top-20)
- ❌ Anatomy (body ratio, wicks)
- ❌ NMA (RSI, ATR, volume)
- ❌ SEQ stats
- ❌ Short-period MAs (10-30)

## RECOVERY режим (fold 1 LONG_3 = 0.51)

**Архетип:** "Reclaim MA-100 на 1h + HMA-10 cross дневной = LONG entry"

### Top-15 фичей (все MA-family):

| Rank | Token | TF | Type |
|---|---|---|---|
| 1 | MA_MA_100 | **1h** | SMA-100 hourly |
| 2 | MA_HMA_10 | **1d** | HMA-10 daily (short, fast) |
| 3 | MA_MA_90 | 15m | SMA-90 LTF |
| 4 | MA_HMA_10 | 2h | HMA-10 2h fast |
| 5 | MA_HMA_40 | 6h | |
| 6 | MA_MA_30 | 12h | |
| 7 | MA_EMA_10 | 15m | EMA-10 fast |
| 8 | MA_EMA_100 | 15m | |
| 9 | MA_HMA_90 | 15m | |
| 10 | MA_MA_110 | 1h | |
| 11 | MA_MA_170 | 1h | |
| 12 | MA_HMA_100 | 1h | |
| 13 | MA_EMA_50 | 2h | |
| 14 | MA_HMA_100 | 2h | |
| 15 | MA_MA_30 | 4h | |

### Что доминирует:

- **1h TF — 5 фичей** (recovery primary TF)
- **15m TF — 4 фичи** (entry zone)
- **2h TF — 3 фичи**
- **Mix MA/EMA/HMA семейств**
- **Короткие периоды (10-100)** — fast trend signals
- **HMA-10 на дневке** появляется (very fast daily indicator)

### Контраст с BEAR/CHOP:

| Аспект | Bear/chop | Recovery |
|---|---|---|
| Доминирующий TF | 1w / 6h / 4h | **1h / 15m / 2h** |
| Период MA | 130-200 (long) | **10-100 (short)** |
| Семейство | HMA (10/15) | Mix (no dominant) |

## BULL RALLY режим (fold 3 LONG_3 = 0.74)

**Архетип:** "Multi-signal confluence — trend + momentum + structure"

### Top-15 фичей (MA + НЕ-MA fields):

| Rank | Token | TF | Δ |
|---|---|---|---|
| 1 | MA_HMA_190 | 1h | +8pp |
| 2 | MA_EMA_190 | 4h | +8pp |
| 3 | MA_EMA_140 | 6h | +8pp |
| 4 | MA_HMA_140 | 6h | +8pp |
| 5 | MA_HMA_70 | 1d | +8pp |
| **6** | **NMA_2h** ⭐ | 2h | **+8pp** |
| 7 | MA_MA_60 | 15m | +7pp |
| 8 | MA_HMA_10 | 15m | +7pp |
| 9 | MA_EMA_150 | 1h | +7pp |
| 10 | MA_EMA_200 | 6h | +7pp |
| 11 | MA_MA_130 | 12h | +7pp |
| 12 | MA_EMA_120 | 1w | +7pp |
| 13 | MA_HMA_190 | 1w | +7pp |
| **14** | **SEQ_2h** ⭐ | 2h | **+7pp** |
| 15 | MA_EMA_60 | 15m | +7pp |

### И в lower позициях SMC элементы (впервые!):

| Token | TF | Δ |
|---|---|---|
| SMC_OB_VC | 2h | +2.1pp |
| SMC_OB_VC | 1h | +2.1pp |
| SMC_i_RDRB | 12h | +2.5pp |
| SMC_FVG | 6h | +1.8pp |
| ANA_6h | 6h | +2.1pp (body/wick anatomy) |
| NMA_12h | 12h | +2.1pp |

### Контраст с другими режимами:

**Bull rally — единственный режим где появляется:**
- ✅ **NMA семейство** (RSI/ATR/volume_zscore)
- ✅ **SEQ семейство** (consecutive colors, body expansion, swing count)
- ✅ **SMC элементы** (i_RDRB best, OB_VC и OB_LIQ secondary)
- ✅ **ANA семейство** (anatomy: body_ratio, wick_asymmetry)

### Гипотеза: В bull moves сигналов БОЛЬШЕ типов

В стабильных трендах (bear/chop = no trend) одного типа сигнала достаточно (MA-distance). В bull rally происходит **multi-confirmation** через РАЗНЫЕ типы:
- MA (trend direction)
- NMA (momentum confirm)
- SEQ (structural impulse)
- SMC (key levels reaction)

## Что НЕ работает ни в одном режиме

| Группа фичей | Importance |
|---|---|
| 15m anatomy (body_ratio, wick_asymmetry) | < top-50 |
| Cross-asset features (IS_ETH alone) | очень низкая |
| Volume z-score | низкая |
| Short MAs на HTF (MA-10 на 1d/1w) | низкая (1d HMA-10 — исключение в recovery) |

## Application для production

### Адаптивные thresholds per regime:

| Regime | Threshold | Cooldown | Logic |
|---|---|---|---|
| BULL | 0.50 | 12h | Trust multi-confirmation signals |
| BEAR | 0.50 | 12h | Trust HTF MA confluence |
| CHOP | **0.55** | **24h** | Filter false signals (model less reliable here) |

### Feature engineering приоритеты для Stage 1:

**ДОБАВИТЬ больше:**
- HMA-90/130/170 на 6h и 4h (наши топы)
- MA-130 на weekly
- EMA-200 на 1h
- NMA-семейство расширить (различные RSI periods, ATR types)

**РАССМОТРЕТЬ удаление:**
- 15m anatomy/SEQ если только bull-rally-relevant
- Cross-asset IS_ETH alone (низкий signal)

Но **полное удаление SMC опасно** — они contribute в bull rally (где НЕ-MA фичи доминируют).
