---
name: feedback-candle-zone-liquidity-methodology
description: "Методология анализа зон / ликвидности для 12h свечи: baseline = prior candle's high (long) / low (short), НЕ собственный open; backward higher-highs chain для liquidity"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 935dc13c-ff07-4b9a-8e0d-e35a63c1d0be
---

# Методология анализа зон / ликвидности для одной свечи

## Принципы

### 1. Baseline (нижняя граница окна поиска)

Для каждой свечи определяется **окно поиска** зон и ликвидности на её "long path" (open → high для bull candle) или "short path" (open → low для bear candle).

**Правило baseline (универсальное):**
Смотрим направление ПРЕДЫДУЩЕЙ 12h свечи (close vs open):
- **prior BULL** (close > open) → `baseline = prior.HIGH`
- **prior BEAR** (close < open) → `baseline = prior.LOW`

**Why:** Предыдущая свеча "победила" в своём направлении. Её крайний экстремум по направлению движения становится frontier для текущей: зоны/ликвидность по эту сторону frontier уже отработаны prior-свечой. Каждая последующая свеча работает в "новом окне" за этим frontier.

**Примеры:**

*2026-03-04 (две BULL подряд):*
- Candle 1 (00:00 UTC, BULL): prior = 03-03 12:00 — нужно проверять её direction. Если BEAR → baseline = prior.LOW.
- Candle 2 (12:00 UTC, BULL): prior = Candle 1 BULL → baseline = **Candle 1.HIGH = 71,893** ✓

*2026-03-08 (BULL → BEAR смена):*
- Candle 1 (00:00 UTC, BULL): prior = 03-07 12:00 BEAR (C=67,263 < O=68,010) → baseline = **prior.LOW = 66,915**
- Candle 2 (12:00 UTC, BEAR): prior = Candle 1 BULL → baseline = **Candle 1.HIGH = 68,200**

### 2. Zone interactions

Zone interacts with candle если её диапазон **пересекается с окном [baseline, candle.high]**:
- Range zone: `zone.lo <= candle.high AND zone.hi >= baseline`
- Fractal high: `candle.high > level AND level >= baseline`

### 3. Liquidity (backward higher-highs / lower-lows chain)

**КАНОНИЧЕСКАЯ методология — backward chain, НЕ raw bar highs/lows в region.**

⚠️ **Ошибка**: считать все 4h/6h/etc bar highs, попадающие в region (это перекрытие — многие highs уже «сняты» более поздними higher highs, не являются активной liquidity).

✅ **Правильно**: backward HH (для long-направления) / LL (для short-направления) chain.

#### Алгоритм для long-candle (взгляд вверх):
1. Идём backward по barам TF (ТОЛЬКО закрытые до candle.open)
2. Поддерживаем `pointer` = самый высокий high из увиденного (изначально -inf)
3. Если `bar.high > pointer`: это **active liquidity level** (untouched higher high)
   - Обновляем pointer
   - Если `bar.high >= baseline`: добавляем в sequence
   - Если `candle.high > bar.high`: **swept** (✓)
   - Иначе: **next target** (✗), остановка

#### Алгоритм для short-candle (взгляд вниз):
Зеркально — backward lower-lows chain, `pointer` = самый низкий low.

Sequence = только active levels (✓ swept или ✗ unswept). Каждый level — реальный untouched stop-cluster.

#### Liquidity в force-search REGION (новое 2026-06-03):
- Те же backward HH/LL chains, фильтрованные по `region_lo ≤ level ≤ region_hi`
- Останавливаемся когда chain выходит за пределы region (level > region_hi для HH, level < region_lo для LL)
- Count of active levels = плотность реальной ликвидности в region (источник force)

### 4. TF subsets

- **Force model**: **8 TFs (1h, 2h, 4h, 6h, 12h, 1d, 2d, 3d)** — 344 коэф. (8h убран 2026-06-03)
- **Liquidity analysis**: **6 TFs (4h, 6h, 12h, 1d, 2d, 3d)** — 1h/2h/8h исключены (1h/2h — шум, 8h — пересечение с 4h/12h)
- **Zone interactions**: **8 TFs (1h, 2h, 4h, 6h, 12h, 1d, 2d, 3d)** — 8h исключён

### 5. Передача эстафеты между свечами

Между consecutive candles:
- **Snapshot zones** делается на каждый candle.open (зоны эволюционируют через mitigation между свечами)
- **3D bars регулярные 72h** с epoch anchor (1970-01-01 Thu) — см. `[[feedback-3d-resample-monday-reset]]`
- **Next target** одной свечи может стать **swept-уровнем** следующей
- При **смене направления** (BULL → BEAR или наоборот) — baseline = prior's extreme в направлении prior's close-движения (т.е. prior.HIGH если был BULL, prior.LOW если был BEAR)

## Реализация

- `~/smc-lib/prediction-algo/zones.py:snapshot_from_events` — снимок активных зон на cut-off
- Liquidity chain: `higher_highs_above_open(df_tf, tf, cut_off_ts, baseline, candle_high)`
- Окно поиска: `[baseline, candle.high]` для long, `[candle.low, baseline]` для short

## Связи

- `[[feedback-3d-resample-monday-reset]]` — корректный 3D anchor (epoch)
- `[[force-model-v2-architecture]]` — pipeline force-model (9 TFs)
- `[[feedback-push-back-on-fact-mismatch]]` — поправлять user при расхождении с данными (этот baseline-fix именно так и обнаружился)
- `[[zone-class-liquidity-inefficiency-block]]` — таксономия зон
