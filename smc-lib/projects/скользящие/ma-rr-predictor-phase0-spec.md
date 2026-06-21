# MA-RR-Predictor — Phase 0 Spec (LOCKED 2026-06-11)

> Production indicator: на каждом закрытии бара модель смотрит на ~2313 features + raw OHLCV
> и на 5-10 раз в месяц говорит «вход в сделку, цена коснётся +3/+4/+5% (или −3/−4/−5%)
> раньше чем −1% против в течение 60 дней» с calibrated honest probability.

---

## 1. Цель и критерий приёмки

**Задача**: для `(t, direction, X∈{3,4,5})` выдать `P(TP_first)` — вероятность что TP касается до SL.

**Acceptance (Гибрид)** ([[feedback-result-quality-bar]]):
- ✅ **Primary**: top-5% WR ≥ **65%** на 4+ из 6 walk-forward folds, n_trades ≥ 30 per fold
- ✅ **Secondary**: top-1% WR ≥ **70%** AND top-0.5% WR ≥ **75%**
- 🎯 **Stretch**: top-0.3% WR ≥ 80% (для production threshold 5-10/мес)
- ❌ **Fail (меняем подход)**: primary < 55% после полного Optuna search

**НЕ цель**: высокий overall WR на всех сделках. Цель — concentrated edge на отфильтрованных setup'ах.

---

## 2. Данные

**Источник**: Binance public REST, 1m OHLCV
**Расположение**: `~/smc-lib/projects/ma-rr-predictor/data/` (PC1, через SSH)
**Файлы**:
- `BTCUSDT_1m_vic_vadim.csv` — 4.43M rows, 99.80% coverage
- `ETHUSDT_1m_vic_vadim.csv` — 3.39M rows, 99.93% coverage

**Окно**: **2020-01-01 → 2026-06-11** (6.5 лет, ровно для обоих)
**Joint**: BTC + ETH в одном датасете с `is_eth ∈ {0,1}` фичей.

---

## 3. Labels — Triple-Barrier path-dependent

Для каждой `(t, asset, direction, X∈{3,4,5})`:

| Параметр | LONG | SHORT |
|---|---|---|
| Entry | `close(t)` | `close(t)` |
| TP | `entry × (1+X/100)` | `entry × (1−X/100)` |
| SL | `entry × (1−0.01)` | `entry × (1+0.01)` |
| Horizon | **60 дней** | 60 дней |

**Алгоритм**:
- Идём вперёд по 1m данным от `t+1m`
- TP first → `y=1`, SL first → `y=0`
- Не достигли за 60d → `y=0` (timeout = не успех)

**Tie-breaker внутрибаровый (Conservative)**: если в одном 1m баре `bar.high ≥ TP` и `bar.low ≤ SL` — считаем что **SL коснулся первым** (worst-case для трейдера, без WR-инфляции).

**6 голов**: `LONG_3`, `LONG_4`, `LONG_5`, `SHORT_3`, `SHORT_4`, `SHORT_5` — независимые бинарные классификаторы.

**Slippage/fees**: НЕ моделируем в Phase 0.

---

## 4. Entry-TF (для Phase 0)

**1h** — единственный entry timeframe в Phase 0 (15m и 4h — в Phase 1 если 1h обнадёжит).

Сэмплов: 1h × BTC+ETH × 6.5y = **~114k сэмплов**.

---

## 5. Фичи

**Все live, no-lookahead** — на момент `t` используется только данные `ts ≤ t` ([[feedback-hma-live-per-tf-at-entry]]):
- HTF (4h+): closed bars + **live partial** из 1m
- LTF (1h, 15m): closed bars ≤ t
- См. раздел #16 (Lookahead guards)

### 5.1 MA Family — 1920 фичей

**8 TFs** × **3 families** × **20 periods** = **480 MA-серий**

| Параметр | Значения |
|---|---|
| TFs | `1w, 1d, 12h, 6h, 4h, 2h, 1h, 15m` |
| Families | `MA, EMA, HMA` |
| Periods | `10, 20, 30, ..., 200` (20 значений, шаг 10) |

**Derived per single MA** (4 фичи):
- `dist_norm = (close − MA) / ATR_14_TF`
- `slope_5 = (MA[i] − MA[i−5]) / ATR_14_TF`
- `slope_sign ∈ {−1, 0, +1}`
- `pos_rank` — percentile rank close vs MA за 100 баров

→ **480 × 4 = 1920 фичей**

**Pair interactions**: ⚠️ **БЕЗ explicit pair columns**. Все cross-family / cross-TF / cross-period взаимодействия (включая HMA_50 1h × EMA_100 4h и т.п.) ловятся через **FT-Transformer self-attention** над 480 MA-токенами (см. #7).

### 5.2 Anatomy одного бара — 56 фичей

Для последнего ЗАКРЫТОГО бара на каждом из 8 TFs:

| Фича | Формула |
|---|---|
| `body_ratio` | `|close − open| / range` |
| `upper_wick_ratio` | `(high − max(o,c)) / range` |
| `lower_wick_ratio` | `(min(o,c) − low) / range` |
| `wick_asymmetry` | `upper_wick − lower_wick` |
| `range_atr` | `range / ATR_14` |
| `direction` | `sign(close − open)` |
| `close_position` | `(close − low) / range` |

→ **7 × 8 = 56 фичей**

**Trader-known patterns** (engulf/marubozu/pin/inside/sweep_reclaim): ❌ **выкинуты** ([[feedback-ml-research-not-validation]]).

### 5.3 SMC Primitives — 224 фичей

**7 элементов** × **4 фичи** × **8 TFs** = **224 фичей**

| Элемент | Канон |
|---|---|
| FVG (bull/bear) | [[feedback-fvg-wick-fill-mitigation]] |
| iFVG | [[feedback-fvg-wick-fill-mitigation]] |
| OB | [[project-ob-vc]] |
| OB_LIQ | [[feedback-ob-liq-no-fractality]] |
| OB_VC | [[feedback-ob-vc-canon-7-relaxed]] |
| i-RDRB | [[i-rdrb-v1-pattern]] |
| Williams fractals (confirmed shift -2) | [[feedback-12h-fractal-baseline-f1f2f3]] |

**Фичи на элемент на TF**:
- `dist_to_nearest_unmit_bull_norm` — расстояние / ATR (положит. если магнит выше)
- `dist_to_nearest_unmit_bear_norm` — расстояние / ATR (положит. если магнит ниже)
- `age_bull` — баров с формирования
- `age_bear` — баров с формирования

**Mitigation правила**:
- FVG / iFVG / OB / i-RDRB POI: **wick-fill**
- OB_LIQ: **first-touch**
- OB_VC: canon #7 relaxed

### 5.4 Sequence stats — 80 фичей

**10 фичей × 8 TFs**:

| Фича | Окно |
|---|---|
| `consec_same_color` | назад от t |
| `body_expansion_5` | mean(body[-5:]) / mean(body[-20:-5]) |
| `bullish_ratio_20` | 20 |
| `max_body_rank_50` | 50 |
| `range_rank_50` | 50 |
| `close_in_range_20` | 20 |
| `volume_ratio_5_vs_20` | 5 vs 20 |
| `high_break_age_50` | 50 |
| `low_break_age_50` | 50 |
| `swing_count_50` | 50 |

### 5.5 Non-MA (Group A только) — 33 фичей

**4 фичи × 8 TFs + is_eth = 33**:

- `atr_14_norm` × 8 TF
- `rsi_14` × 8 TF
- `rsi_bars_since_fresh_exit` × 8 TF ([[feedback-rsi-cumulative-fresh-exit-edge]])
- `volume_zscore_50` × 8 TF
- `is_eth ∈ {0, 1}`

**Не берём**: funding/OI (Phase 1+), macro context (BTC.D/USDT.D), time features.

### 5.6 Итого tabular

**2313 фичей** = 1920 (MA) + 56 (anatomy) + 224 (SMC) + 80 (sequence) + 33 (non-MA)

### 5.7 Sequence input для TCN

**7 multi-resolution OHLCV каналов**:

| TF | Bars | Окно |
|---|---|---|
| 15m | 256 | 2.7 дня |
| 1h | 128 | 5.3 дня |
| 2h | 96 | 8 дней |
| 4h | 64 | 10.7 дней |
| 6h | 64 | 16 дней |
| 12h | 64 | 32 дня |
| 1d | 64 | 64 дня |

5 каналов на каждом TF: open, high, low, close, volume (нормализованные).

---

## 6. TCN Sequence Branch

| Параметр | Значение |
|---|---|
| Дилятационных уровней | 5 |
| Kernel size | 7 |
| Channels | 128 |
| Dropout | 0.2 |
| Weight normalization | True |
| Receptive field | ~190 баров |

Output: per-channel global pool → concat по 7 каналам → **256-dim vector**.
Параметры: ~4.2M.

---

## 7. FT-Transformer Tabular Branch

| Параметр | Значение |
|---|---|
| Granularity | Per-element token (~700 токенов) |
| Embed dim | 128 |
| Layers | 6 |
| Heads | 8 |
| FFN expansion | 4× (512) |
| Dropout | 0.2 |
| Activation | GELU |

**Self-attention учит все pair (и higher-order) interactions** между 480 MA + остальные tokens — включая cross-family + cross-TF + cross-period (например HMA_50 4h × EMA_100 2h) **без explicit pair columns**.

Output: global pool → **256-dim vector**.
Параметры: ~3M.

---

## 8. Fusion + 6 Heads

```
Tabular branch (256) ─┐
                       ├─ concat (512) ─ Linear(512→256) GELU Dropout
Sequence branch (256) ─┘                     ↓
                                       Linear(256→128) GELU Dropout
                                             ↓
                              ┌─ LONG_3:  Linear(128→1) → sigmoid → P
                              ├─ LONG_4:  Linear(128→1) → sigmoid → P
                              ├─ LONG_5:  Linear(128→1) → sigmoid → P
                              ├─ SHORT_3: Linear(128→1) → sigmoid → P
                              ├─ SHORT_4: Linear(128→1) → sigmoid → P
                              └─ SHORT_5: Linear(128→1) → sigmoid → P
```

**Calibration** (post-train on val):
- Temperature scaling per head
- Isotonic regression on val
- Output: calibrated `p ∈ [0, 1]`, honest

**Selective abstention**:
- Per-head threshold tuned на val для top-X% selection
- Production: если `p < threshold` → нет сигнала

Параметры fusion+heads: ~150k.

---

## 9. Training

| Параметр | Значение |
|---|---|
| Loss | Focal (γ=2 default) + Label smoothing (ε=0.05), multi-task weighted |
| Optimizer | AdamW |
| LR schedule | Cosine с warmup 5% |
| Mixed precision | FP16 |
| Optimizations | torch.compile, FlashAttention 3, DataLoader prefetch (num_workers=14), grad checkpointing if needed |
| Augmentation | Mixup ТОЛЬКО на фичах (не на label) |
| Pretraining masked-bar | **Phase 0.5** (не в Phase 0); добавляем если Phase 0 даст 55-64% WR |

---

## 10. Walk-Forward Validation

```
2020 ─── 2021 ─── 2022 ─── 2023 ─── 2024 ─── 2025 ── 2026Q1Q2
[train ][emb][val]
       [train ][emb][val]
              [train ][emb][val]
                     [train ][emb][val]
                            [train ][emb][val]
                                   [train ][emb][val]
                                                  [TEST untouched]
```

| Параметр | Значение |
|---|---|
| Folds | 6 |
| Embargo | 60 дней (= horizon) |
| Purge | Исключаем train-сэмплы чьё label-resolution заходит в val period |
| Test holdout | 2026-04-01 → 2026-06-11 (не трогаем до финала) |

---

## 11. Optuna Search

| Параметр | Значение |
|---|---|
| Trials | 300 |
| Sampler | TPE (Tree-structured Parzen Estimator) |
| Pruner | ASHA (min=5 epochs, max=50, factor=2) |
| Objective | top-5% WR на val, усреднённый по 6 folds |
| Direction | maximize |
| Seeds per config | 5 (для финальных) |

**Search space**:
- `learning_rate`: 1e-5..5e-3 (log)
- `batch_size`: 128 / 256 / 512
- `dropout`: 0.1..0.4
- `weight_decay`: 1e-5..1e-2
- `ft_n_layers`: 4 / 6 / 8
- `ft_embed_dim`: 64 / 128 / 192
- `ft_n_heads`: 4 / 8 / 16
- `tcn_channels`: 64 / 128 / 192
- `tcn_kernel`: 5 / 7 / 9
- `tcn_dilation_levels`: 4 / 5 / 6
- `focal_gamma`: 0 / 1 / 2 / 3
- `label_smoothing`: 0 / 0.05 / 0.1
- `warmup_pct`: 2% / 5% / 10%
- `head_loss_weights`: uniform / inverse_class_freq

---

## 12. Final Ensemble

- **Top-10 trials** by mean top-5% WR
- × **5 seeds** = **50 моделей**
- Каждая re-trained на полном train (2020 → 2026-Q1)
- Aggregation: **average of calibrated probabilities**
- Evaluation: на holdout test (2026-04 → 2026-06)

---

## 13. Reported Metrics

В evaluation отчёте показываем:
- AUC (sanity)
- **WR at top-{0.1, 0.3, 0.5, 1, 5, 10}%** — full curve
- Calibration error (Brier, ECE)
- Net R с EV-threshold
- PF, max DD, Sharpe
- N trades per fold
- Stability: std of top-5% WR across folds

---

## 14. Production Indicator (Phase 1)

После acceptance:

```
[Bar close]
   ↓
[Real-time data feed]: Binance WebSocket → 1m bars
   ↓ aggregate to higher TFs live
[Feature pipeline] (same as Phase 0, no-lookahead, live HMA per-TF)
   ↓
[Ensemble inference] (50 models, average calibrated P)
   ↓ → 6 calibrated probabilities (LONG_3..LONG_5, SHORT_3..SHORT_5)
[Threshold check] (user's choice; default top-0.3% = 5-10 sig/мес)
   ↓
[Signal alert]: Telegram/Push/Email
   "BTC LONG | Target +5% | P=0.83 | Entry $69420, SL -1%, TP +5%"
```

---

## 15. Compute Budget

| Этап | Время | Где |
|---|---|---|
| Feature build + label | 6-12 часов | PC1 CPU (Ryzen 7 7700, 16 threads) |
| No-lookahead audit | ~30 мин | PC1 CPU |
| Sanity baseline (1 trial) | 1-2 часа | PC1 GPU |
| **Optuna 300 trials с ASHA** | **3-4 дня** | **PC1 GPU 5070 Ti 24/7** |
| Финальный ensemble (50 моделей) | ~10 часов | PC1 GPU |
| Evaluation + reports | 0.5 дня | PC1 |
| **TOTAL Phase 0** | **~5-6 дней** | PC1, 4-4.5 дня GPU нагрузки |

**Всё на PC1** ([[feedback-all-compute-on-pc1.md]]). Mac только для chat/планирования/просмотра результатов.

---

## 16. Lookahead Guards (non-negotiable)

История: v3.3 был DEPRECATED из-за lookahead bug в HMA features [[ob-vc-v33-production-canon]], честный AUC оказался 0.54 вместо предполагаемых 0.74.

**Принцип**: на момент `t` все вычисления используют только данные `ts ≤ t`.

### 16.1 HTF live computation

В момент `t` (закрытие 1h-бара entry-TF):
- **HTF (4h, 6h, 12h, 1d, 1w)**: используем закрытые HTF-бары + **live partial** из 1m данных
- **LTF (1h, 15m)**: используем закрытые LTF-бары ≤ t
- MA/EMA/HMA на (closed + partial) — последний бар partial

Пример: `t = 14:00 UTC` на 1h, считаем `HMA_50 4h`:
- 50 закрытых 4h-баров до 12:00
- + 1 partial 4h-бар (12:00→14:00, real-time из 1m)
- HMA(51 значений)

### 16.2 HTF anchor

**0 UTC = 03:00 МСК** ([[feedback-htf-anchor-global-rule]]). Это Binance standard.
- 12h close at 15:00 МСК
- 1d close at 03:00 МСК

### 16.3 Williams fractals

Только **confirmed с shift -2** (требует +2 баров after = всегда видим уже сформированный фрактал). Unconfirmed фракталы — НЕ используем.

### 16.4 Audit-скрипт

**Обязательный** перед любой тренировкой:

```python
def audit_no_lookahead(t, asset, data):
    f1 = compute_features_at_t(t, asset, data[data.ts <= t])
    f2 = compute_features_at_t(t, asset, data[data.ts <= t + add_random_future()])
    for key in f1:
        assert abs(f1[key] - f2[key]) < 1e-9, f"LOOKAHEAD in {key}!"
```

Прогоняется на **100+ random точках**. Любое отклонение — fail, не идём в тренировку.

---

## 17. Структура кода

```
~/smc-lib/projects/ma-rr-predictor/   (на PC1)
├── data/                              # 1m CSV
├── features/
│   ├── ma_family.py                  # 1920 фичей, live per-TF
│   ├── anatomy.py                    # 56 фичей
│   ├── smc_primitives.py             # 224 фичей
│   ├── sequence_stats.py             # 80 фичей
│   ├── non_ma.py                     # 33 фичей
│   ├── build.py                      # orchestrator → parquet
│   └── partial_bar.py                # HTF live partial construction
├── audits/
│   └── no_lookahead.py               # mandatory pre-training check
├── labels/
│   └── triple_barrier.py             # path-dep, 60d, conservative tie
├── models/
│   ├── tcn.py                        # TCN sequence branch
│   ├── ft_transformer.py             # FT-Transformer tabular branch
│   ├── fusion.py                     # concat + dense + 6 heads
│   ├── calibration.py                # temp scaling + isotonic
│   └── ensemble.py                   # 50-model average
├── training/
│   ├── walk_forward.py               # purged WF orchestrator
│   ├── train.py                      # single run
│   ├── optuna_search.py              # TPE + ASHA
│   └── losses.py                     # focal + label smoothing
├── evaluation/
│   ├── metrics.py                    # WR at percentile curve, calibration
│   └── reports.py                    # walk-forward rollup
├── scripts/
│   ├── fetch_data.py                 # docucke свежих 1m
│   ├── update_port_forward.ps1       # WSL IP refresh after PC reboot
│   └── deploy_indicator.py           # Phase 1 production
└── phase0-spec.md                    # this doc
```

---

## 18. Все 42 решения

См. чат `chat-2026-06-11-phase0-decisions.md` (история обсуждения).
Кратко: 13 base + 5 MA family + 5 features + 4 architecture + 9 training + 3 acceptance + 3 lookahead = **42 LOCKED decisions**.

---

## 19. Changelog

| Date | Change | Author |
|---|---|---|
| 2026-06-11 | Initial draft | Claude |
| 2026-06-11 | All 42 decisions confirmed by user, LOCKED | Vadim + Claude |
