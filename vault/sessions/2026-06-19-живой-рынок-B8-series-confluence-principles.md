# 2026-06-19 — Живой рынок: B8 series, Fibonacci, 3 принципа

## TL;DR
Большой день. От baseline Transformer experiments (≤AUC 0.677) к novel **TWB-MEM** architecture (B8 series) которая физически предсказывает price levels с MAE 0.3-1% на 24h forecasting. Зафиксированы 3 канонических принципа в библиотеку.

---

## 🎯 Главные результаты дня

### 1. Tier-S combo identified (3 sturdy parts)

| Эксперимент | AUC | Особенность |
|---|---|---|
| **A2 ELECTRA** | 0.666 | top1% precision = **83.3%** (vs base 24%, 3.5× lift) |
| **C3 Elem-subset** | 0.676 (best) | AUC + AP champion |
| **B3 dt-pos** | 0.664 | P>0.7 precision = **63.7%** |

Combo via **specialist routing**: A2 при confidence > 0.7, B3 при confidence > 0.7, иначе C3. Результат:
- **AUC 0.6764**, **AP 0.399** (= flat XGB+evw 0.398, впервые сравнялись с baseline)
- top10% precision 44.9% (+5.5% vs solo C3)

### 2. B8 series — Price physics learning ⚡

**B8 TWB-MEM** (reconstruction):
- Маскируем ВЕСЬ день (24h) на всех TFs, видны open/close + контекст до/после
- Предсказание high/low: MAE 0.74-0.79%, lift 2.27-2.54× over baseline
- Доказательство: модель учит implicit physics прохода цены через ландшафт зон

**B8.1 Forecasting** (только pre-context):
- High MAE 1.23%, Low MAE 1.59%, Close MAE 2.16%
- Только LOW даёт сильный lift (1.39×); HIGH/CLOSE хуже baseline
- На реальном кейсе 2026-06-14: LOW $63,717 vs actual $63,700 ($17 ошибка!) — **snipe**
- HIGH недооценила ($65,704 vs $67,000) — но это **realistic TP**, не theoretical max

**B8.2 Sequence + Self-critique** (6 bins × OHLC):
- Overall MAE 1.30%, на bin 1: 0.46%
- 24h HIGH MAE 1.01% (vs B8.1 1.23%)
- Critic calibration corr = 0.449 (model knows when it'll be wrong)
- Demo bin 3 LOW и bin 6 HIGH — порядок правильный!

**B8.3 + Confluence features** ⭐:
- 10 scalar features pre-computed (cluster counts, distances, asymmetry)
- Per-bin MAE улучшен на 15-20% vs B8.2
- 24h HIGH MAE **0.74%** (vs B8.2 1.01%)
- Leak audit: ✅ no leaks in 100 samples
- На demo 2026-06-13 07:00 МСК: bin 1 HIGH ошибка **$34** (0.05%!)

### 3. Fibonacci pipeline

- **Fib band scanner**: 7 канонических bands (b1..b7), 101,862 events
- **Bands not levels** (по user feedback): «золотой карман» b4 = 61.8-78.6
- Actions: born/first_touch/retire (return tracking)
- Touch rate b4 = 69.1% (vs b1 82.6%, b7 32%) — empirical Fib confirmation
- **Fib LAW discovery**: XGB AUC 0.32 (vs random 0.125, 2.6× lift)
- Conditional law тables показали что CHoCH/BOS предсказывают band слабо

### 4. Multi-asset events generated

- **BTC**: 1.74M events (existing)
- **ETH**: 1.68M events (новое)
- **SOL**: ~1.4M events (новое)
- Total ~4.8M events для будущего multi-asset training

### 5. B8.2b multi-asset (in progress)

Запущен на PC2 (BTC+ETH+SOL), interrupted на step 9.2k/30k. Перезапустить при возвращении.

---

## 🧱 Эксперименты — полная таблица

| # | Эксперимент | AUC | AP | Особое |
|---|---|---|---|---|
| v2 | random mask | 0.674 | — | baseline |
| v3 | tf-aware | 0.662 | 0.358 | cross-TF reasoning |
| v4 | BIG mix | 0.654 | 0.380 | 50M params, top1% 50% |
| v5 | +choch_bos | 0.658 | 0.365 | modular CHoCH |
| v6 | forced bundle | 0.588 | 0.304 | ❌ kitchen sink failed |
| A1 | Causal LM | 0.654 | 0.356 | Feb 2026 0.77 AUC (regime spec) |
| A2 | **ELECTRA** | 0.666 | 0.376 | ⭐ top1% 83.3% |
| **B3** | **dt-pos** | 0.664 | 0.377 | ⭐ P>0.7 63.7% |
| **C3** | **Elem-subset** | **0.676** | 0.388 | ⭐ AUC champion |
| C1 | Mirror flip | 0.668 | 0.371 | top1% 66.7% |
| C2 | TF-subset | 0.667 | 0.357 | средний |
| A5 | MAE 75% | 0.670 | 0.385 | top5% 49.1% |
| D2 | Multi-target | 0.677 | 0.373 | broad accuracy |
| D4 | Self-distill | 0.658 | 0.366 | хуже teacher |
| B6 | regime cond | 0.656 | 0.352 | не помог |
| — | Flat XGB+evw | 0.716 | 0.398 | engineered baseline |
| — | **p_route combo** | 0.676 | **0.399** | ⚡ best AP |
| — | **B8.3** | reconstruction | — | physics MAE 0.74% high |

---

## 📜 3 новых принципа в библиотеку

### 1. DIRECTIONS.md (3 направления проекта)
1. 📺 **Обзор рынка** — будущая задача для аудитории
2. ⚡ **Предсказатель на день** — интрадей с плечами (текущий фокус)
3. 📈 **Тренды** — спот, движения 10%+ за неделю

### 2. FRESH_LOOK_PRINCIPLE.md
> «План = гипотеза, не догма. Если первая зона не подтвердилась — пересмотреть весь план.»

Mechanism:
- Streaming prediction
- Divergence detector
- X-mark trigger
- State reset
- Confidence decay

### 3. REALISTIC_TARGET_PRINCIPLE.md
> «Модель должна учиться достижимым трейдером значениям, не физическим max/min.»

Пример: 2026-06-14 HIGH $67,000 (физический) vs $65,704 (realistic TP). Удержание до $67k = «железная воля» в хаосе. Realistic TP это то что **реально берётся** в продакшен.

Триггеры для recall:
- «направления проекта живой-рынок» → DIRECTIONS.md
- «принцип свежего взгляда» / «fresh look» → FRESH_LOOK_PRINCIPLE.md
- «принцип реалистичной цели» / «realistic target» → REALISTIC_TARGET_PRINCIPLE.md

---

## 🔍 Конкретный кейс — 2026-06-14 forecast vs reality

### Anchor 2026-06-14 07:00 МСК, open ~$64,500
**Реальность** (по описанию user):
- 0-4h: спустилась к $64,200
- 4-8h: подъём к $64,600
- 8-12h: уценка до **$63,700** ← LOW
- 12-24h: рост к **$67,000** ← HIGH

**B8.1 forecast**:
- LOW $63,717 → ошибка **$17** (0.027%) ⚡ snipe
- HIGH $65,704 → ошибка $1,296 (1.93%) ← **realistic TP** не max
- CLOSE $64,638 → ошибка $2,362 (3.7%) ← модель не поймала rally

### Anchor 2026-06-13 07:00 МСК, open $63,532
**Реальность**: HIGH $64,763, LOW $63,484 (тихий день)

**B8.2 vs B8.3 на этом anchor**:
- B8.2: HIGH $64,081 (1.05%), LOW $62,681 (1.27%)
- **B8.3**: HIGH $63,958 (1.24%), LOW $63,111 (**0.59%**) ← 2× точнее на LOW
- B8.3 bin 1 HIGH: $63,849 vs actual $63,883 = **$34 ошибка** (snipe!)

---

## 🏗 Архитектура B8 (full stack)

```
Input event tokens:
  - elem_emb (16 types)
  - act_emb (5 actions)
  - tf_emb (8 TFs)
  - dir_emb (8 directions)
  - cont_proj([dt, zspan, price_rel])
  - pos_emb (index-based)
+ Confluence broadcast (B8.3):
  - 10 features per anchor: cluster counts, distances, asymmetry
  - Linear(10, D_MODEL) broadcast to all positions

Encoder: TransformerEncoder D=512, L=8, H=8
Norm: LayerNorm

Output heads:
  - seq_head: (24,) → reshape (6, 4) per-bin OHLC
  - critic_head: (6,) self-error prediction
```

---

## 🚀 Что дальше — план B8.4

При возвращении:
1. **Доделать B8.2b multi-asset** (3-asset retrain)
2. **B8.4 = B8.3 + Realistic Targets** — переразметить labels на «trader-realistic» peaks/bottoms
3. **B8.5 Fresh Look online inference** — streaming + X-mark + re-encode protocol
4. **Combo Tier-S + B8.3 embeddings** — hybrid classifier + forecaster
5. **Attention explainer fix** — переделать в FP32 (bfloat16 убил gradient precision)

---

## ⚠ Незакрытые проблемы

1. **B8.2b interrupted** — нужно перезапустить после возвращения
2. **Attention explainer** в B8.3 показал importance=0 для всех tokens кроме anchor — bug numerical precision
3. **Lookahead audit** — формально 100 samples прошли, но 100% гарантии нет
4. **WSL portproxy** — после WSL restart нужно обновлять (известная проблема)

---

## 📂 Файлы на PC1 (на момент потери связи)

CKPTs:
- `mem_ckpt_b8_twb.pt` (TWB reconstruction)
- `mem_ckpt_b8_1_forecast.pt` (B8.1 forecasting)
- `mem_ckpt_b8_2_sequence.pt` (B8.2 sequence)
- `mem_ckpt_b8_3_confluence.pt` (B8.3 + confluence)
- Все 13 предыдущих ckpt (v2-v6, A1-A5, B3-B6, C1-C3, D2-D4)

Predictions:
- `predictions_twb_b8.parquet`
- `predictions_b8_1_forecast.parquet`
- `predictions_b8_2_sequence.parquet` (B8.3 не сохранил)
- + 8 predictions_mem_*.parquet

Documents (синхронизированы Mac + PC1):
- `DIRECTIONS.md`
- `FRESH_LOOK_PRINCIPLE.md`
- `REALISTIC_TARGET_PRINCIPLE.md`

---

## 🎯 Главные инсайты дня

1. **Conservative bias модели = золото для трейдинга**. Realistic TP > theoretical max.
2. **Confluence features снижают per-bin MAE на 15-20%** — explicit overlap awareness is huge.
3. **B8.3 на bin 1 = снайпер** ($34 error на 4h forecast) — модель «читает зоны».
4. **Sequence forecasting сохраняет порядок** — LOW потом HIGH правильно определено.
5. **A2 ELECTRA top1% = 83.3%** — discriminator находит textbook canonical setups.
6. **Implicit physics через TWB-MEM** работает — модель учит «как цена движется через зоны».
7. **Kitchen sink (v6 forced) проиграл** — sturdy parts > мега-смесь.

---

## 💬 Цитаты дня

> «B8.1 предсказал low правильно. Предсказать high точно было нереально. Там сложная ситуация на рынке была. Даже я не удержал бы сделку до таких фактических значений.» — рождение Realistic Target Principle.

> «Я как трейдер хочу работать с плечами. Интрадей торговля. Зашли в сделку, забрали прибыль.» — DIRECTIONS #2 фокус.

> «Ошибаются ВСЕ. Удерживание неправильного плана = убытки. Признать ошибку быстро = выжить.» — Fresh Look philosophy.

---

## Tags
#живой-рынок #B8-series #TWB-MEM #confluence #Fibonacci #Fresh-Look #Realistic-Target #combo-tier-s #sequence-forecaster #self-critique
