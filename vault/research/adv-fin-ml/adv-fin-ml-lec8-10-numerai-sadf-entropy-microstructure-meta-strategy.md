---
type: external-source
source_file: "ssrn-3270269 (Lec8) + ssrn-3274354 (Lec9) + ssrn-3447398 (Lec10) + ssrn-3478927 (Numerai)"
author: "Marcos López de Prado (ORIE 5256)"
ingested: 2026-06-10
tags: [ml, quant, lopez-de-prado, structural-breaks, microstructure, research]
---

# Adv Fin ML · Lec 8-10 + Numerai — SADF/entropy/microstructure, HPC, Meta-Strategy

Финальный блок курса. Lec 8 — самый прикладной для НОВЫХ фич; Lec 10 + Numerai — как организовать research.

## Lec 8 — Structural Breaks, Entropy, Microstructure Features ⚡ (новые фичи!)

### Structural Breaks (детекция смены режима)

- **CUSUM tests** (Brown-Durbin-Evans, Chu-Stinchcombe-White) — тест на структурный сдвиг.
- **Explosiveness / Bubble detection:**
  - Chow-Type Dickey-Fuller — switch random walk → explosive.
  - ⭐**SADF (Supremum Augmented Dickey-Fuller)** — детектор **пузырей**. Обычные unit-root тесты НЕ отличают стационарность от periodically-collapsing bubble. SADF рекурсивно расширяет начало выборки (вложенный двойной цикл по (t0,t)) → ловит explosive-поведение без знания точки слома.

🔗 ⚡ **Сильный кандидат для крипты:** BTC/ETH/SOL — это машина пузырей. **SADF как фича/фильтр режима** (bubble on/off) может резко помочь — наша проблема «overfit регимов, стабильность по месяцам 35-60%» ([[traid-bot-ml-pivot]]) частично от смены режимов. SADF/CUSUM = детектор режима → фича для LightGBM или гейт стратегии. **Дешевле bars-перестройки, высокий потенциал.**

### Entropy Features

- Shannon entropy, entropy of Gaussian process, entropy + generalized mean. Энтропия = мера информационного содержания/предсказуемости участка.
- 🔗 Кандидат-фича: entropy окна как мера «насколько рынок предсказуем сейчас» (низкая энтропия = тренд, высокая = шум).

### Microstructure Features ⚡

- **Roll model** — оценка эффективного спреда из автоковариации.
- **Kyle's lambda** — price impact на единицу order flow (мера ликвидности).
- **Amihud's lambda** — |return| / dollar volume (illiquidity).
- 🔗 Для крипты на Spot частично доступны (volume есть; order flow/aggressor — нужны trades). **Amihud lambda дёшев** (|ret|/volume) → фича ликвидности. Связь с ⛽liquidity Правила 8.

## Lec 9 — HPC + Quantum Annealer

- HPC cluster (тысячи процессоров), 2 уровня параллелизации (master/slave scheduler). Bagging/boosting на кластере.
- **Quantum Annealer** для optimal trading trajectory (multi-period, transaction costs): задача NP-complete, комбинаторная оптимизация → qubits, tunneling, entanglement (= статья [[1508.06182 quantum annealer trading]]).
- 🔗 ⚠️ Не для нас сейчас. Релевантно: у нас 2 PC (PC1 GPU, PC2 CPU grid, [[traid-bot-project]]) — это наш «HPC» в миниатюре. 2-уровневая параллелизация = наш joblib + n_jobs. Quantum — не применимо.

## Lec 10 — Meta-Strategy Paradigm ⚡

- **«Every successful quantitative firm applies the meta-strategy paradigm.»** Не одна стратегия, а **фабрика стратегий** + надстройка (oversight/allocation/risk).
- Классика (stop-out PM по loss-limit) vs Quantitative Meta-Strategy: ранний сигнал пока стиль ещё формируется; для любой просадки — expected time underwater; пересмотр аллокаций.
- **Corollary:** стратегия статзначима, только если max Sharpe выжил после поправки на multiple testing (= Deflated Sharpe, [[adv-fin-ml-lec5-7-betsizing-backtest-overfit-hrp]]).

🔗 **Прямо про нас:** у нас УЖЕ фабрика стратегий (1.1.x, C2, VIC, i-RDRB...) — это и есть meta-strategy подход. Чего не хватает: **надстройки-аллокатора** (сколько веса каждой стратегии, когда отключать). Связь с HRP (Lec7) и нашим live-набором 4 сканеров. Кандидат: meta-allocation слой над стратегиями.

## Numerai Tournament — как организовать ML-research (практика)

- Данные: random distance-preserving transform на X, shuffle строк внутри Era, шифрование имён → защита от leakage и overfitting на конкретику.
- **Era = месяц** (120 eras train). Турнир раз в неделю; payout ∝ stake × performance OOS.
- **MDA (Mean Decrease Accuracy) feature selection:** выбирать фичи с положительным средним приростом Score. Это перестановочная важность (надёжнее MDI).
- ⭐**Балансировка (= решение нашей проблемы стабильности):**
  - **Across Eras:** найти месяцы где модель плоха, исключить.
  - **Across Features:** не полагаться на несколько фич (если они откажут — модель умрёт).
  - **Across Targets:** робастная модель предсказывает разные таргеты.
  - **Variance reduction:** малые bags, контроль источника draws.
- Clustering (agglomerative, distance = correlation / normalized mutual information) → reinforce signal, гасить шум.

🔗 **Прямо адресует нашу боль** «стабильность по месяцам 35-60%, overfit регимов» ([[traid-bot-ml-pivot]]): era-balancing + MDA + feature-balancing. **MDA feature selection** для 3064 MH-фич — сильный кандидат (отсев бесполезных фич перестановкой).

## Action items для проекта (приоритет)

1. ☐ **SADF / CUSUM** как режим-фича (bubble detection для крипты) — высокий потенциал, дёшево.
2. ☐ **MDA feature selection** для 3064 MH-фич (перестановочная важность > MDI).
3. ☐ **Era/month-balancing** при обучении (исключать плохие месяцы, балансировать фичи/таргеты).
4. ☐ **Entropy + Amihud lambda** как новые фичи ликвидности/предсказуемости.
5. ☐ **Meta-allocation слой** над стратегиями (вес/отключение) — связь HRP + meta-strategy.

Предыдущий: [[adv-fin-ml-lec5-7-betsizing-backtest-overfit-hrp]]. Каталог: [[adv-fin-ml-индекс]]. Связь: [[traid-bot-ml-pivot]].
