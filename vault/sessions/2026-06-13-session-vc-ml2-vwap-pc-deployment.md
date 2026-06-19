---
date: 2026-06-13
duration: ~15 hours
tags: [session, vc-ml2, vwap, phase-3-deployment, infrastructure]
projects: [ma-rr-predictor, vc-ml-predictor, vwap-effective-predictor, ob-vc-ml2]
---

# Сессия 2026-06-13: VC-ML2, VWAP research, инфра-апгрейд

Большая многопроектная сессия. Главные результаты:
1. Открыли новый проект **ob_vc ml2** (weakly-supervised cluster winners)
2. Глубокий research VWAP (двухфазная семантика, 48h calibration, slot 7 paradox)
3. macOS LaunchAgent + Phase 3 architecture pivot (PC1 train / PC2 inference)
4. Honest ml2 validation: **template-matching НЕ предсказывает win** (отрицательный результат, но информативный)

## 1. Инфраструктура

**macOS LaunchAgent для TradingView** ([[../knowledge/launchagent-tv-autostart]])
- TV нужно запускать с `--remote-debugging-port=9222` для CDP/MCP контроля
- LaunchAgent `~/Library/LaunchAgents/com.vadim.tradingview-debug.plist`
- После ребута TV стартует автоматически, MCP сразу видит чарт
- Tested: `launchctl kickstart -k` → TV запустился за 1 сек

**Phase 3 architecture pivot** ([[../knowledge/phase3-pc2-inference]])
- ⚠ Carve-out из правила «всё compute на PC1»
- Heavy training (checkpoint) → PC1 RTX 5070 Ti
- Hourly inference (light, 10 sec/час) → **PC2 RTX 4070**
- Runbook обновлён: `~/smc-lib/projects/скользящие/phase3-runbook.md`

## 2. ma-rr-predictor (skolzyashie) — Phase 3 ready, не задеплоен

### CPCV fold 13 cross-seed verification (PC2)
- Seeds 43, 44, 45 на fold 13 (отдельно от utrennego batch s42)
- **3 из 4 seeds показывают directional bias instability**
- Seed 42 balanced был outlier
- → **Fold 13 drop из production ensemble**

### Phase 3 checkpoint обучен на PC1
- `train_for_phase3_checkpoint.py` finished 19:28 МСК (37.7 мин)
- `phase3_checkpoint/model.pt` (36MB) + scaler + feat_cols + group_sizes готовы
- ⚠ **НЕ задеплоен** — главный bottleneck «edge есть → денег нет»

### Per-threshold (3%/4%/5%) анализ
- SHORT_5 = best Sharpe **3.83** (vs SHORT_3 = 3.79), total **+18.88R**
- LONG_4 = dead zone (Sharpe 0.77)
- Production canon использует L3+S3 → потенциальный upgrade добавлением S5

## 3. VWAP research — много открытий

### Корректировка Правила 6 в памяти
- Прошлый recipe в [[../../smc-lib/elements/...]] говорил «якорь = pivot-свеча»
- Реально: **anchor в диапазоне свечи i+1** (НЕ pivot-close, НЕ generalize на non-D fractals)
- Поправил `feedback-anchored-vwap-from-fractals.md`

### Slot 10 analysis: brute-force 288 кандидатов
- Window 2026-01-30 → 2026-02-01, 15m grid
- **BEST anchor = 2026-01-31 17:00 МСК** (NY-open hours, composite 0.63)
- Pivot: D-fractal 2026-01-28 FH @ 90600
- User's slot 10 (00:00 UTC) = rank 31/288 — valid но не optimal

### 48h calibration window discovery
- VWAP std падает **на 2 порядка** ровно на 48h marker ($506 → $0.5)
- Anchor sensitivity максимальна в первые 48h, потом сходится
- Respect rate в первые 48h радикально выше (0.90 vs 0.57 на 1h)
- 1.16× базового объёма проторговано в первые 48h
- **Setup определяется в 48h, потом 4 месяца жизни предсказаны**

### Two-phase VWAP semantics ([[../knowledge/vwap-two-phase]])
- Phase 1 «эффективная» — clean repulsion (89% respect rate, 16R/2B)
- Phase 2 «проработанная» — mixed reactions+breaks (52% respect, 15R/14B)
- Composite по всему окну **скрывает эту динамику** — нельзя single number
- Сохранено в `feedback-vwap-effective-vs-worked`

### Top-10 effective VWAPs computed + uploaded в TV
- Pivot pool: D-Williams-N=2 fractals 2025-11-01 → 2026-05-13
- Per pivot: best anchor argmax Phase 1 composite (96 candidates × 15m grid)
- Top10 в slots 1-10 индикатора `VWAPs - ASVK` (entity VGRyyb)
- Display flags activated через CDP API

### Slot 7 paradox (false negative всех метрик)
- User's slot 7 (2026-04-08 19:00 МСК) — «очень эффективный» интуитивно
- НЕ соответствует Williams N=2 D-fractal в окрестности
- Phase 1 composite = **0.37** (ниже floor 0.67 top-10)
- Tradeable-count net = **−0.5R** на любом RR от 1:0.5 до 1:5
- **Все формальные метрики провалили slot 7 как positive**
- → Создан проект [[../../.../project-vwap-effective-predictor]] для ML extract user's tacit rule

### User's TV setup: 10 VWAPs visually placed
- ±2h tolerance — user не выводил идеально
- User сам не знает rule
- 10 positive labels уже на TV; user готов разметить до 50
- Это идеальная supervised ML postановка

## 4. vc-ml-predictor (ob_vc ml supervised) — нестабильность

### Cross-seed analysis (3 seeds × 6 folds)
| Fold | A-side (LONG h1-h3) mean | std | Verdict |
|---|---|---|---|
| **0** | **0.542** | 0.119 | **STABLE STRONG** ✅ |
| 1 | 0.319 | 0.020 | weak |
| 2 | 0.246 | 0.164 | UNSTABLE |
| 3 | 0.391 | 0.266 | UNSTABLE |
| 4 | 0.436 | 0.185 | moderate |
| 5 | 0.423 | 0.196 | moderate |

- Direction bias seed-dependent (как fold 13 ma-rr)
- Только fold 0 production-ready (lift 2.4× реальный — но я ошибочно сказал 5.4× из-за неверного base rate)
- **Корректный base rate y_LONG_3 = 23.89%**, не 10% как сказал

### Fold 0 = 2020-09 → 2021-01 = start of 2020-2021 bull rally
- Regime-specific edge ($10k → $40k период)
- Не generalizable

## 5. ob_vc ml2 (NEW PROJECT) — главное открытие сессии

[[../../.../project-ob-vc-ml2]] (memory entry created)

### Мотивация: проблема era-heterogeneity supervised ml
- Bull 2020/21, Bear 2022, Chop 2024 имеют разные feature distributions
- Модель learns era-specific артефакты → directional bias seed-to-seed
- Discriminator'у LONG/SHORT нужно различать winners vs losers → шум calendar усложняет

### Подход ml2: weakly-supervised на winners-only
- Берём только winning ob_vc trades (5,834 из 25,072 = 23.27% base rate)
- Unsupervised clustering среди них → subtypes of winning conditions
- Calendar-orthogonal (все winners, разные эпохи перемешаны)

### Pilot 1: 4 clusters на 4000 first winners
- Deep autoencoder 2340 → 32 latent на GPU PC1
- K-means / GMM / Hierarchical Ward в latent space
- 4 архетипа: weekly uptrend, deep discount, deep premium, daily downtrend
- MA-family доминирует в 3/4 архетипах (confirm canon ma-rr-predictor)

### Pilot 2: temporal formation analysis
- 72h pre-entry sequences для всех 5,834 winners
- Initially я визуализировал top-3 features as «flat trajectories»
- ⚠ User correctly pointed out features include 15m → should change
- Per-TF dynamics analysis: 15m has per_event_range = **3.1σ** (huge!)
- Average trajectory across cohort flat because **timing differs per event**
- Real signal в per-event trajectory shapes

### Pilot 3: max-similarity search
- All 5,834 winners, autoencoder embeddings 128-dim
- Top 500 events with max k-NN density (avg sim to top-100 nearest)
- Universal pattern: **LOW ATR на ВСЕХ TFs** (universal signature)
- + positive HTF slopes (4h-1d), high weekly pos_rank, fresh i_RDRB on 12h, LTF RSI lift

### Pilot 4: archetype historical test
- 5-condition rule (low ATR + pos slope + weekly high + i_RDRB + RSI lift)
- На всех 25,072 events: full 5/5 satisfied → 1,923 events, **WR 27.20%** (lift 1.17×)
- Это **marginal edge** — выше baseline 23.3%, но не дотягивает до 30%+
- Net 1:3 RR: +169R за 6.5 лет = 2R/мес (marginal positive)

### Pilot 5: per-direction max-similar pair search
- LONG best pair: BTC 2023-10-14 ↔ BTC 2024-05-04 (203 дня, 88/629 matches)
- SHORT best pair: BTC 2022-11-07 ↔ ETH 2026-03-19 (1228 дней, 101/629 matches)
- SHORT more universal (cross-asset, cross-regime template robust)
- LONG more context-sensitive

### Pilot 6: template library count
- LONG winners: 2,987
- With ≥1 partner ≥100 matching (relaxed corr 0.85): **1,373 templated events**
- Top event = BTC 2023-05-27 with **93 partners**
- 9,935 LONG pairs at threshold 100+ matching features

### Pilot 7: consensus template
- Center = BTC 2023-05-27, 93 partners
- 272 features consistent ≥70% across all partners
- HMA 105, EMA 75, MA 71, SMC 16, ...
- 1h-1w TFs dominate, 15m НЕ contributes
- Partners span 2020-2026, BTC+ETH, all 3 regimes (CHOP 55, BULL 24, BEAR 14)

### Pilot 8: **HONEST validation на ВСЕХ 12,725 LONG events** ⚠
- Per candidate: count library matches ≥100 (past only, no time leakage)
- **Distribution:** mean 4.8, median 0, max 124
- **Baseline LONG WR 23.47%**
- 0 matches: **24.17% WR** (выше baseline!)
- 1-5: 24.59%
- 6-10: 20.20%
- 11-20: 18.85%
- 21-50: 21.58%
- 51-100: 20.11%
- **101-200: 0% WR** ⚠

### Главный вывод ml2 (NEGATIVE result)
- **Template-matching НЕ предсказывает win** — наоборот, inverted signal
- Library была построена из winners, но **losers возникают в таком же context**
- Pre-entry features описывают **режим/setup**, не **исход**
- Density similarity ≠ edge

### Следующий step: supervised contrastive
- Использовать выбранный feature subset (MA/EMA/HMA × 1h-1w + SMC i_RDRB/OB_VC)
- Обучить binary classifier на winners vs losers
- Это правильный путь — discriminator, не density descriptor

## Открытые items в конце сессии

1. **Phase 3 deploy** (5 мин работы, не сделан) — bottleneck «edge есть → денег нет»
2. **VWAP-effective-predictor** — user готов разметить до 50 positive labels
3. **4 новых SMC элемента** (breaker_block, mitigation_block, choch, inducement) — добавлены в smc-lib/elements сегодня в 12:45-12:51 МСК, **НЕ интегрированы** в vc-ml-predictor dataset
4. **Supervised contrastive ml** на winners-vs-losers — правильный путь после negative ml2 result

## Memory entries created

- `feedback-phase3-inference-on-pc2.md` — carve-out PC1 rule
- `feedback-vwap-effective-vs-worked.md` — two-phase VWAP semantics
- `project-vwap-effective-predictor.md` — ML extract user tacit rule
- `project-ob-vc-ml2.md` — weakly-supervised cluster winners
- `feedback-do-not-decide-for-user.md` — НЕ принимать destructive решений без команды

## Связи

- Parent: [[ob-vc-canon-reference]]
- Связано: [[2026-06-11-ma-rr-predictor-phase0]], [[2026-06-09-ob-vc-ml-lookahead-bug-honest-results]]
- Литература: [[../knowledge/adv-fin-ml-lec8-10-numerai...]] (era-balancing)
