---
type: external-source
source_file: "arXiv: 1408.1159, 2003.10502, 1508.06182, 2302.08819, 2406.01199, 2205.04879"
author: "López de Prado, Lipton, Carr et al."
ingested: 2026-06-10
tags: [quant, arxiv, mean-reversion, backtest-overfit, research]
---

# Quant-статьи arXiv — OTR, mean-reversion exit, derivatives, portfolio

Свод 6 смежных arXiv quant-статей с честной оценкой применимости к нашему **сигнальному боту по BTC/ETH/SOL** ([[traid-bot-project]]). Две — прямо применимы, остальные — нишевые/теоретические.

## ⭐ ПРЯМО ПРИМЕНИМЫ

### 1408.1159 — Determining Optimal Trading Rules Without Backtesting (Carr & López de Prado)

**ПРОЧИТАНА ПОЛНОСТЬЮ (39 стр, включая Python-код).** Авторы — Peter Carr (Morgan Stanley/Courant) + López de Prado.

**Постановка:** калибровка TP/SL перебором по backtest = overfitting. Решение: оценить OU-процесс из ВСЕЙ истории и вычислить оптимальные TP/SL без backtest. Важно: речь про **exit corridor** (как выйти из УЖЕ открытой позиции), не про вход.

**Точная модель (Eq. 2):** дискретный OU на ценах: `P_t = (1−φ)·E[P] + φ·P_{t−1} + σ·ε`, ε~N(0,1).

- **φ = 2^(−1/half-life)** — связь автокорреляции с периодом полураспада. half-life мал → φ мал → быстрый возврат; half-life велик → φ→1 → random walk.
- Стационарность требует φ∈(−1,1).

**Алгоритм OTR (5 шагов, Snippet 1 в приложении — реальный Python):**

1. OLS на линеаризованном OU (Eq.5-7) → оценить κ̂ (скорость), σ̂.
2. Построить меш TP × SL (напр. 21×21, оба ∈ linspace(0,10,21)).
3. Сгенерировать ~100 000 OU-путей из {κ̂,σ̂} с реальными начальными условиями; **maxHP=100** (вертикальный барьер — таймаут).
4. На каждом узле меша применить TP/SL-логику к 100k путям → 100k значений π → посчитать **Sharpe = mean/std** на узле.
5. Выбрать узел с max Sharpe (5a); ИЛИ при заданном TP найти оптимальный SL (5b); ИЛИ при заданном max-SL найти оптимальный TP (5c).

**⭐ КОНКРЕТНЫЕ ЧИСЛЕННЫЕ РЕЗУЛЬТАТЫ (heat-maps, главная ценность):**

- **Zero equilibrium (мартингейл / маркет-мейкер, E[P]=0):** при малом half-life оптимум = **малый TP + большой SL** (держать до маленькой прибыли ценой риска убытка ×5-7), Sharpe ~**3.2**. Худшее = малый SL + большой TP. **Симметричные TP/SL = нейтраль (диагональ).**
- **Positive equilibrium (position-taker / хедж-фонд):** оптимум сдвигается — TP центрирован ~6, SL диапазон 4-10 (прямоугольная зона), Sharpe до ~**12**.
- **Negative equilibrium:** зеркальный негатив positive (худшая зона там, где была лучшая).
- **Чем больше half-life → ближе к random walk → Sharpe падает (12→9→2.7→0.8→0.32) → оптимум размывается.** На random walk оптимума НЕТ — любой backtest-«оптимум» = подгон под шум.

**Вывод (conjecture):** «для цены по дискретному OU существует УНИКАЛЬНАЯ оптимальная пара TP/SL, максимизирующая Sharpe». Closed-form не выведен (решает 2003.10502).

🔗 ⚡ **Для нас (конкретно):** мы подбираем RR/SL перебором (1.1.x, C2 RR=1.0, sl=15%·OB) — ровно описанный overfit. **Ключевой урок:** оптимальная пара TP/SL **зависит от знака equilibrium и half-life**. Для наших зон: если возврат к mid сильный (малый half-life) → **узкий TP + широкий SL** (НЕ симметрия!). Это объясняет, почему C2 с **RR=1.0 (симметрия)** работает скромно, а не оптимально — и намекает, что асимметрия TP>SL или TP<SL под режим может дать больше. Связь с [[floating-tp-only-helps-low-wr-strategies]] и нашим законом про симметрию SL.

### 2003.10502 — Closed-form Optimal Mean-Reverting Trading (Lipton & López de Prado)

**ПРОЧИТАНА ПОЛНОСТЬЮ (32 стр).** Решает open problem из 1408.1159 — даёт **аналитику** через **method of heat potentials** (Lipton, из физики барьерных опционов), для OU **конечной длительности** (не perpetual — в этом новизна vs Bertram et al.).

**Модель и оценка параметров (раздел 3):** тот же дискретный OU; оценка через ковариации: `κ̂ = cov[Y,X]/cov[X,X]`, `σ̂ = sqrt(cov[ξ̂,ξ̂])`. После безразмерного скейлинга (раздел 4): `dx = (θ−x)dt + dW`, steady-state std = 1/√2. Три выхода: (A) hit π (TP), (B) hit π̲ (SL), (C) t=T (таймаут) — = triple-barrier.

**Метод:** свести задачу к heat potentials → Volterra integral equations 2-го рода → численно решить (Algorithm 1) → получить Sharpe(π,π̲) аналитически (без Monte Carlo). Сверено с Monte Carlo (Figure 1-2 совпадают).

**⭐ ГЛАВНЫЙ ПРАКТИЧЕСКИЙ ВЫВОД (Table 1, θ=1 сильный mispricing):**
> «when the original mispricing is strong (θ=1) it is **NOT optimal to stop losses, but it might be beneficial to take profits**.»

То есть: **цена далеко от equilibrium (сильный сигнал возврата) → SL широкий/отключён + TP узкий.** Полностью совпадает с 1408.1159 (малый TP + большой SL при сильном возврате). Два независимых метода (Monte Carlo + heat potentials) дают один результат.

**Философия (важно):** НЕ «all-weather» правило выхода, а **разные оптимальные TP/SL под текущий рыночный режим** (κ, θ). Подбирать TP/SL под режим, не один фикс на всё.

🔗 ⚡ **Самая применимая из шести.** Наша зональная торговля = mean-reversion к mid зоны (= equilibrium θ). **Конкретный action:** (1) оценить κ̂,σ̂ для поведения цены у наших зон (OU-fit на крипте); (2) если mispricing сильный (цена глубоко в зоне) → **широкий SL + узкий TP**, а не симметрия RR=1.0; (3) TP/SL **под режим** (κ меняется во времени) вместо фикса. ⚠️ Heat-potentials выводить не нужно — достаточно Monte-Carlo версии из 1408.1159 (Snippet 1), результат тот же.

## ⚠️ НИШЕВЫЕ / ТЕОРЕТИЧЕСКИЕ (не для нас сейчас)

### 1508.06182 — Optimal Trading Trajectory via Quantum Annealer (Rosenberg, Carr et al.)

- Multi-period portfolio optimization на D-Wave quantum annealer; transaction costs + market impact; БЕЗ инверсии ковариации. Тот же материал, что Lec 9 ([[adv-fin-ml-lec8-10-numerai-sadf-entropy-microstructure-meta-strategy]]).
- ❌ Не для нас: нет quantum-железа, мы не multi-period portfolio. Концепт «trajectory globally optimal vs series of statically optimal» интересен, но неприменим.

### 2302.08819 — SPX, VIX and scale-invariant LSV (Lipton & Reghai)

- Local Stochastic Volatility модель для **деривативов**; идея из физики — работать с **относительными (безразмерными) параметрами** вместо абсолютных (они стабильнее, интуитивнее, лучше PnL-explanation).
- ❌ Не для нас: мы не торгуем опционы, нет VIX на крипте напрямую. ⚡ Единственный takeaway: **относительные/безразмерные параметры стабильнее абсолютных** — у нас уже так (sl=15%·OB относительный, RR относительный, FVG в % а не $). Подтверждает наш выбор относительных параметров.

### 2406.01199 — Geometric Approach to Asset Allocation with Investor Views (Lipton, López de Prado et al.)

- Geometric/Wasserstein barycenter (GWB) для объединения статистики с investor views; улучшение Black-Litterman; больше гибкости в confidence.
- ❌ Не для нас: portfolio allocation с субъективными views; мы сигнальный бот без allocation-слоя. Релевантно только если появится meta-allocation ([[adv-fin-ml-lec8-10-numerai-sadf-entropy-microstructure-meta-strategy]] Lec10).

### 2205.04879 — Dimension Walks on Generalized Spaces (López de Prado et al.)

- Чистая математика (math.CA): covariance functions, positive-definite kernels на сферах/пространствах. Фундамент для distance-метрик (HRP, clustering).
- ❌ Не для нас напрямую: теоретический базис под distance-метрики из HRP/clustering. Знать о существовании, не применять.

## Итоговые action items

1. ☐ ⭐**OTR / closed-form mean-reversion (1408.1159 + 2003.10502):** вывести оптимальные TP/SL аналитически для наших зон как OU-процесса — против overfit RR-tuning. **Высокий приоритет.**
2. Относительные параметры (2302.08819) — уже делаем, подтверждено.
3. Quantum/GWB/dimension-walks — каталогизированы, не применяем.

Каталог: [[adv-fin-ml-индекс]]. Связь: [[traid-bot-empirical-laws]] (overfit), [[floating-tp-only-helps-low-wr-strategies]].
