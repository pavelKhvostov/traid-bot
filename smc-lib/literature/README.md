# Литература

Каноническая библиотека книг по трейдингу, рыночному анализу и ML для финансов.
Каждая книга включена с целью извлечения концепций для применения в `~/smc-lib/`.

## Состав

| Файл | Книга | Автор | Год | Pages | Релевантность |
|---|---|---|---|---|---|
| `lopez_de_prado_advances_in_financial_ml.pdf` | **Advances in Financial Machine Learning** | Marcos López de Prado | 2018 | 481 | ⭐⭐⭐ напрямую для force-model |
| `williams_master_the_markets.pdf` | **Master the Markets** (VSA) | Tom Williams | 1993/2000/2019 | 333 | ⭐⭐⭐ volume-аналитика, smart money |
| `nison_japanese_candlestick_charting.pdf` | **Japanese Candlestick Charting Techniques** | Steve Nison | 1991 | 330 | ⭐⭐ candle patterns (marubozu, doji, RB) |
| `bulkowski_encyclopedia_chart_patterns_preview.pdf` | **Encyclopedia of Chart Patterns** (preview 30p из ~1000) | Thomas Bulkowski | 2021 | 30 | ⭐ pattern statistics baseline |

## Конкретное применение к нашим модулям

### Lopez de Prado → `prediction-algo/`, `force_model_v3/`

**Ch 3 Labeling — Triple-Barrier Method** ⭐
- Наш `is_FH`/`is_FL` (strict Williams n=2) — это fixed-time horizon метод, который автор критикует
- Triple-Barrier: profit-take + stop-loss + time-expiration. Динамические thresholds через rolling ATR
- **Применение для force-model v4:** заменить strict Williams n=2 на triple-barrier с volatility-adjusted ptSl
- **Meta-labeling (Ch 3.6-3.7):** двухступенчатая модель — primary predicts side, secondary predicts size/quality. Может решить проблему missed-imp (#14, #15, #48)

**Ch 4 Sample Weights — Overlapping Outcomes** ⭐
- Наша проблема: labels на consecutive 12h candles перекрываются (n=2 confirmation = 24h)
- Решение: `average uniqueness of label`, time-decay weights, sequential bootstrap
- **Применение:** weight каждой 12h candle по unique-ness её Williams confirmation window

**Ch 5 Fractionally Differentiated Features** ⭐
- Stationarity vs Memory dilemma — close prices non-stationary, returns stationary but потеряли memory
- Fractional differentiation сохраняет memory + достигает stationarity
- **Применение:** для feature engineering — frac-diff цены вместо raw close или simple returns

**Ch 7 Cross-Validation in Finance — Why K-Fold Fails** ⭐⭐
- Наш walk-forward split (train < test_split < test) — единственный кейс где работает
- K-fold CV **ломается** в финансах из-за serial correlation и overlapping labels
- **Решение — Purged K-Fold CV + Embargo:** удалять из train все observations с overlapping confirmation windows
- **Применение к force-model:** для proper validation использовать **PurgedKFold** вместо in-time split

**Ch 8 Feature Importance** ⭐
- Substitution effects — корреляция между фичами скрывает важность
- **MDA (mean decrease accuracy)** + **MDI** — два разных подхода
- **Применение:** проверить какие из 384 коэф force-model реально важны, выкинуть substitution-correlated

**Ch 11-12 Backtesting through CV — CPCV** ⭐⭐
- WF backtest = ОДНА история. Может быть случайно хороша/плоха
- **CPCV (Combinatorial Purged Cross-Validation):** φ[N, k] = много путей одновременно
- **Применение:** finalize force-model v3 через CPCV (не WF) для robust estimate

**Ch 14 Backtest Statistics**
- Sharpe ratio variance, Probabilistic Sharpe, Deflated Sharpe, DSR
- **Применение:** не только AUC, но и risk-adjusted метрики для force-model

**Ch 17 Structural Breaks — CUSUM**
- CUSUM filter для sampling bars based on event-significance
- Уход от time-based bars (12h) к event-based (significant move)
- **Применение:** альтернатива equal-time 12h bars

**Ch 18 Entropy Features**
- Shannon entropy, Lempel-Ziv — измерение информационного content в bar
- **Применение:** entropy как feature для force-model (low entropy = trend, high = consolidation)

**Ch 19 Microstructural Features**
- Three generations of microstructure: price-only, strategic, sequential trade models
- Order flow imbalance, Kyle's lambda, PIN
- **Применение:** добавить order-flow features из 1m данных в force-model

### Williams (VSA) → `vc/` (Volume Confirmation)

**Volume Spread Analysis (VSA)** — анализ соотношения objem/range/close:

| VSA pattern | Что значит |
|---|---|
| **No demand bar** | Up-bar с low volume + narrow range → отсутствие покупателей |
| **No supply bar** | Down-bar с low volume + narrow range → отсутствие продавцов |
| **Stopping volume** | Down-bar с extreme volume + close высоко в range → "smart money" покупает |
| **Climactic action** | Wide range bar с extreme volume → reversal coming |
| **Test bar** | Down-bar low volume после bullish action → проверка спроса |
| **Effort vs Result** | Big volume → small range = high effort low result → reversal |

**Smart Money Footprints:**
- Accumulation: low → low volume → high → high volume (smart money buying quietly)
- Distribution: high → low volume → low → high volume (smart money selling into rally)

**Применение к нашей `vc/`:** VC (Volume Confirmation) у нас простая (FVG-volume vs HTF-zone). Williams даёт богатую таксономию VSA-паттернов:
- `no_supply_bar` / `no_demand_bar` детекторы как новые SMC primitives
- `stopping_volume` как force feature для зоны
- Effort/Result ratio как feature: volume vs range mismatch

### Nison (Candlestick) → `elements/marubozu`, `elements/rb`, `candle_patterns/`

Каноническая референция для **single и multi-candle patterns**:

| Pattern | У нас в `elements/` | Релевантность |
|---|---|---|
| Marubozu (大ぼうず) | ✓ marubozu | open = extremum, sweep open level |
| Hammer / Hanging Man | ✗ — можно добавить | RB-like с body bottom/top |
| Doji (дожи) | ✗ | indecision, частый pivot signal |
| Spinning Top | ✗ | similar to doji |
| Engulfing | ✗ | bullish/bearish pattern |
| Harami | ✗ | inside-bar pattern |
| Tweezer Top/Bottom | ✗ | double-bar pivot |
| Star Patterns (Morning/Evening) | ✗ | 3-bar reversal |
| Three Black Crows | ✗ | 3-bar continuation |
| Three White Soldiers | ✗ | 3-bar continuation |

**Sakata's Five Rules** (San-zan / 3 mountains, etc.) — основа candlestick анализа.

Volume + Open Interest chapter (John Murphy contributor) — комплементарно с Williams VSA.

### Bulkowski → `patterns/`

Encyclopedia of Chart Patterns даёт **статистики** по каждому паттерну (filter %, breakout %, throwback %, performance rank). 30-страничный preview — недостаточно для practical use. **Action item:** найти/получить полную версию для использования как baseline статистик для наших patterns.

## Reading priority

1. **Lopez de Prado Ch 7 (Cross-Validation)** — нужно для proper validation force-model v3
2. **Lopez de Prado Ch 3 (Labeling — Triple-Barrier)** — может улучшить label quality
3. **Williams Sec 2-3** (Trends + Anatomy) — для добавления VSA features
4. **Lopez de Prado Ch 17-19** (Structural Breaks, Entropy, Microstructure) — новые feature ideas
5. **Nison Part 2** (Multi-candle patterns) — новые primitives для `elements/`
6. **Lopez de Prado Ch 11-12** (Backtesting) — finalize force-model через CPCV
7. **Nison Part 3** (Volume, Market Profile) — комплементарно VSA

## Memory

Ключевые findings сохранены в memory (см. `~/.claude/projects/-Users-vadim/memory/`):
- `[[force-model-v3-architecture]]` — текущая ML архитектура (использует ideas из Lopez de Prado)
- `[[force-model-v2-architecture]]` — предыдущая, заменена

## Next study tasks

- [ ] Прочитать Lopez de Prado Ch 7 full (Purged K-Fold CV + Embargo implementation)
- [ ] Прочитать Lopez de Prado Ch 3 full (Triple-Barrier implementation + meta-labeling)
- [ ] Извлечь Williams Sec 2 (volume range analysis) — implement no_demand_bar / no_supply_bar детекторы
- [ ] Каталогизировать Nison patterns которые отсутствуют в `elements/`
- [ ] Найти полную версию Bulkowski Encyclopedia (если будет нужна pattern statistics)
