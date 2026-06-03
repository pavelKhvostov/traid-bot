# López de Prado — Advances in Financial Machine Learning (2018)

481 pages. Wiley. 22 chapters in 5 parts.

## Связь с нашими задачами

Эта книга — **roadmap** для force-model v3 → v4. Большинство наших проблем (labels overlap, walk-forward overfit, feature substitution) уже решены здесь.

---

## Part 1: Data Analysis

### Chapter 2 — Financial Data Structures

**Идея:** time bars (1m, 12h) — плохой sampling, статистически нестабильны. Альтернативы:
- **Tick bars** — N трейдов = 1 bar
- **Volume bars** — N контрактов = 1 bar
- **Dollar bars** — N USD объёма = 1 bar
- **Information-driven bars (CUSUM)** — event-based

Применение: наши 12h bars — time-based. Volume / dollar bars дали бы более однородные returns.

### Chapter 3 — Labeling ⭐ (наш ключевой вопрос)

#### 3.2 Fixed-Time Horizon (что у нас сейчас)

```
y_i ∈ {-1, 0, 1}
- y_i = 1 если r_i > τ (return через h bars выше threshold)
- y_i = -1 если r_i < -τ
- y_i = 0 иначе
```

**Проблемы:**
- Большинство labels = 0 (если τ велик)
- Single τ для всех — не учитывает volatility
- Time bars статистически плохие

#### 3.4 Triple-Barrier Method ⭐⭐

Три barrier'а:
1. **Upper horizontal (profit-take)** — `pt × trgt` от entry
2. **Lower horizontal (stop-loss)** — `-sl × trgt` от entry
3. **Vertical (expiration)** — N bars max

Label = sign первого touched barrier'а. `trgt` — dynamic volatility estimate (rolling EWMA std of returns).

**Конфигурации [pt, sl, t1]:**
- [1,1,1] стандарт — profit, stop, time
- [0,1,1] — exit by time unless stopped-out
- [1,1,0] — take profit or hold forever (не realistic)
- [0,0,1] — same as fixed-time horizon (худшая)

**Implementation snippet 3.2:** возвращает timestamps первого touched barrier.

**Применение для force-model:**
- Заменить `is_FH = candle is Williams pivot` на triple-barrier
- ptSl = [1.5, 1.0] (asymmetric: больше profit чем loss)
- trgt = ATR(20) × 1.0
- vertical = 6 × 12h bars = 3 дня
- Labels: +1 (pivot up хорошо), 0 (boring), -1 (pivot down плохо)

#### 3.6 Meta-Labeling ⭐⭐ (САМОЕ ВАЖНОЕ)

**Two-step model:**
1. **Primary model:** predicts side (long/short/zero) — может быть rule-based (наш C1-C7 basket?)
2. **Secondary model:** predicts P(profit) given primary's side — это где ML тренируется

Преимущества:
- Уменьшает overfitting (primary не учим, только secondary)
- Можно использовать rule-based primary + ML wrapper для filtering
- Solves problem где primary precision OK, но recall плохой

**Применение к нашему C1-C7 basket + force-model:**
- Primary = C1-C7 basket (catches 15/22)
- Secondary force-model = predicts которые из 15 кандидатов реально станут pivot
- + третья модель: для свечей вне basket (15/22 missed) — отдельный classifier
- Could solve missed #14, #15, #48 как отдельная категория

### Chapter 4 — Sample Weights

#### 4.2-4.4 Overlapping Outcomes / Uniqueness

**Проблема:** наши Williams labels overlap (consecutive 12h candles делят 4 bar confirmation window).

**Solution:**
- `Concurrent labels c_t` = сколько labels active на bar t
- `Uniqueness u_i = (1/c_t) average` — насколько unique label i
- Weight по uniqueness (более unique → больше weight)

**Применение:** в `train.py` пробросить sample_weight в LogisticRegression.fit().

#### 4.5 Bagging Classifiers and Uniqueness

`max_samples = avg_uniqueness` в Random Forest / Bagging — sample только unique observations.

#### 4.7 Time Decay

Recent labels weight больше старых. Exp decay or linear.

**Применение:** не равные веса всех 12h candles за 6 лет; recent больше weight.

### Chapter 5 — Fractionally Differentiated Features ⭐

**Stationarity vs Memory dilemma:**
- `close[t]` имеет memory, но non-stationary (price drifts) → ML breaks
- `returns = close[t]/close[t-1] - 1` stationary, но lost memory (no trend info)

**Solution — fractional differentiation:**
```
y_t = Σ_k (-1)^k C(d, k) close[t-k]
```
где `d ∈ [0, 1]` — non-integer. d=1 → full diff (returns). d=0 → no diff (raw).

Find smallest `d` giving stationarity (ADF test passes) → maximum memory preserved.

**Применение для force-model:**
- Frac-diff `close` series как feature
- Или frac-diff cumulative volume
- Сохраняет trend information + statistically valid

---

## Part 2: Modelling

### Chapter 6 — Ensemble Methods

Bagging vs Boosting в финансах:
- **Boosting** склонен к overfit на noisy financial data → AVOID
- **Bagging (Random Forest)** более robust → PREFER

Sequential bootstrap (Ch 4.5) применять для bagging.

### Chapter 7 — Cross-Validation in Finance ⭐⭐⭐ (НАША ПРОБЛЕМА)

**Why K-Fold CV Fails:**

1. **Serial correlation** — observations not IID. `X_t ≈ X_{t+1}`
2. **Overlapping labels** — `Y_t ≈ Y_{t+1}` если labels на overlapping windows
3. **Multiple testing** — test set reused многократно при tuning

**Solution: Purged K-Fold CV + Embargo:**

1. **Purging:** для каждого testing observation `Y_j`, удалить из train все `Y_i` чьи confirmation windows overlap с `[t_j,0, t_j,1]`
2. **Embargo:** удалить training observations N bars после testing set (защита от serial correlation leak)

```python
# Snippet 7.1 — PurgedKFold class
# Snippet 7.3 — embargo helper
```

**Применение для force-model v3:**
- Сейчас walk-forward split (train < test_split_ts < test) — это OK, эквивалент Purged K-Fold с k=1
- НО для proper validation на 6y нужен **PurgedKFold(n_splits=5, embargo_pct=0.01)**
- Это даст 5 fold scores, СД-bracket для AUC, robust к single-history bias

---

## Part 3: Backtesting

### Chapter 11 — Dangers of Backtesting ⭐

Ключевые мысли:
- Flawless backtest невозможен
- Backtest НЕ research tool — это test tool
- Selection bias: чем больше strategies tested, тем выше шанс случайно "хорошей"
- **Probability of Backtest Overfit (PBO)** — оценка
- **Deflated Sharpe Ratio (DSR)** — adjust Sharpe для N trials

### Chapter 12 — Backtesting through CV ⭐⭐

**Walk-Forward (WF):**
- Pro: clear historical interpretation
- Cons: ONE path tested, sequence-dependent, initial decisions on small data

**Cross-Validation (CV):**
- Тестируем стратегию на 2008 crisis, имея train на 2009+ → stress test
- Не historical accuracy, а "что будет если scenario X произойдёт"

**CPCV (Combinatorial Purged Cross-Validation):** ⭐⭐⭐

Partitions T observations into N groups. Train на (N-k) groups, test на k. Number of paths φ[N, k] = (N choose k) × k / N.

Example: N=6, k=2 → 15 train/test splits → 5 backtest paths.

Each path = combination of test groups. Multiple paths → distribution of Sharpe, robust estimate.

**Применение для force-model v3 финализации:**
- N = 24 (по месяцам 6 лет / 3 = ?), k=4 → много путей
- Distribution of AUC across paths
- Confidence interval для performance

### Chapter 14 — Backtest Statistics

- **Probabilistic Sharpe Ratio (PSR):** prob(SR > 0) given observed SR, skewness, kurtosis
- **Deflated Sharpe Ratio (DSR):** Adjust для multiple trials (избегаем survivorship bias)
- **Implementation Shortfall:** real-world execution costs

---

## Part 4: Useful Financial Features

### Chapter 17 — Structural Breaks (CUSUM) ⭐

**CUSUM filter:**
```
S_t^+ = max(0, S_{t-1}^+ + y_t)
S_t^- = min(0, S_{t-1}^- + y_t)
Reset when |S_t| > h
```

Event = когда CUSUM exceeds threshold. Sample bars при events → information-driven bars.

**Применение:** альтернатива 12h bars — bars по "significant move" events (например abs(return) > 1.5% cumulative).

### Chapter 18 — Entropy Features

**Shannon entropy:** мера информации в bar.
- Low entropy = predictable (trend continuation)
- High entropy = noisy (consolidation)

**Lempel-Ziv:** compression-based entropy estimate.

**Применение:** entropy ratio за N bars как feature для force-model (current vs trailing).

### Chapter 19 — Microstructural Features

Три поколения:
1. **First gen:** price sequence (например, sign of returns)
2. **Second gen:** strategic trade models (Kyle's λ — lambda)
3. **Third gen:** sequential trade models (PIN — probability of informed trading)

**Order flow imbalance:** (buy_volume - sell_volume) / total_volume — proxy для informed trading.

**Применение:** добавить order flow features из 1m bars в force-model.

---

## Главные действия после прочтения

1. **Triple-Barrier labeling** для force-model v4 (вместо strict Williams n=2)
2. **Meta-labeling architecture:** rule-based basket (primary) + ML secondary
3. **Purged K-Fold CV** для proper validation
4. **Sample weight by uniqueness** в LR training
5. **CPCV** для финального robust performance estimate
6. **Frac-diff close** как новая feature
7. **CUSUM bars** альтернатива time-based
8. **Microstructural features** из 1m data
9. **Probabilistic Sharpe / Deflated Sharpe** для backtest reports
