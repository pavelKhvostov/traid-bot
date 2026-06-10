---
type: external-source
source_file: "ssrn-3257497 (Lec5) + ssrn-3261943 (Lec6) + ssrn-3266136 (Lec7)"
author: "Marcos López de Prado (ORIE 5256)"
ingested: 2026-06-10
tags: [ml, quant, lopez-de-prado, backtest-overfit, bet-sizing, research]
---

# Adv Fin ML · Lec 5-7 — Bet Sizing, опасности backtest (CPCV/PBO), Backtest Stats, HRP

Блок про то, как НЕ обмануть себя backtest'ом — прямо усиливает наши законы про lookahead/overfit ([[traid-bot-empirical-laws]]).

## Lec 5 — Bet Sizing + Dangers of Backtesting

### Bet Sizing из вероятности ⚡

- Из предсказанной вероятности p(x) метки вывести **размер ставки**: для 2 исходов `m = 2·Z(z) − 1`, m∈[−1,1], где z — тест-статистика H0. Для >2 исходов — one-vs-all по max p_i.
- Каждая ставка имеет holding period; при наложении ставок — **усреднять размеры всех активных** (а не override старой), снижает turnover.
- 🔗 **Кандидат для нас:** наш prediction-algo даёт P_hit_D ([[traid-bot-ml-pivot]]) — можно конвертировать в bet size (сейчас сигнал бинарный). Связь с floating-TP/частичной фиксацией. Но мы сигнальный бот, не auto-execution — bet sizing = рекомендация размера.

### ⚠️ Dangers of Backtesting (ядро — = наши законы)

- **«Mission Impossible: The Flawless Backtest»** — даже безупречный backtest обычно неверен.
- **«Even Flawless Backtests are Usually Wrong»** — из-за **multiple testing**: если перебрать много стратегий, max Sharpe завышен случайно (**Expected Maximum Sharpe Ratio** растёт с числом проб).
- Меры против overfit: (1) bagging (если bagging ухудшает стратегию — она была overfit на малой выборке); (2) **не делать backtest, пока всё research не завершено**; (3) **записывать КАЖДЫЙ проведённый backtest** → считать PBO (Probability of Backtest Overfitting).
- **Combinatorial Purged Cross-Validation (CPCV)** ⚡ — вместо одного walk-forward пути генерирует МНОЖЕСТВО train/test комбинаций (с purging) → распределение Sharpe, а не одно число. Backtesting on synthetic data.

🔗 **Прямо подтверждает наши законы** [[traid-bot-empirical-laws]]: WR>60%=подозрение, honest audit 1.1.1 (overfit при переборе). López de Prado: **записывай все backtest'ы, считай PBO**. У нас перебиралось много вариантов 1.1.x — стоит формально оценить PBO. **CPCV** — апгрейд нашего single-path walk-forward в ML-pivot.

## Lec 6 — Backtest Statistics + Type I/II под multiple testing

Полный набор метрик для оценки стратегии (нам сверить наш generate_report):

- Time range, Average AUM, **Capacity** (макс AUM при целевом risk-adjusted return), Leverage, Max position size, **Ratio of longs**, **Frequency of bets/year**, **Average holding period**, Annualized turnover, **Correlation to underlying**, PnL (+ PnL from longs), Annualized return, **Hit ratio** (= наш WR), Average return from hits/misses, broker fees, **slippage per turnover**.
- **Type I (false positive)** vs **Type II (false negative)** под multiple testing — **Deflated Sharpe Ratio** корректирует Sharpe на число проб и non-normality.

🔗 Чек-лист для нашего [[7-criteria-of-good-strategy]] и generate_report: добавить **frequency of bets/year, avg holding period, ratio of longs, correlation to BTC, slippage** если их нет. **Deflated Sharpe** — учесть число протестированных вариантов. Average return from hits vs misses = наш medR-анализ.

## Lec 7 — Hierarchical Risk Parity (HRP)

- **Проблема:** Mean-Variance оптимален in-sample, проваливается OOS (хуже 1/N). Даже risk parity недотягивает.
- **HRP** (Markowitz-free, граф/кластеры вместо инверсии ковариации):
  1. **Tree Clustering** — кластеризовать активы по distance `d = sqrt((1−corr)/2)`, дендрограмма.
  2. **Quasi-diagonalization** — переупорядочить матрицу (похожие рядом).
  3. **Recursive bisection** — распределять веса рекурсивным делением, inverse-variance внутри.
- Königsberg bridges / graph theory как мотивация.

🔗 ⚠️ **Для нас слабо применимо сейчас:** мы сигнальный бот по 3 активам (BTC/ETH/SOL), не портфельный аллокатор. HRP осмыслен, если будем строить portfolio-allocation поверх сигналов (распределение риска между активами/стратегиями). Отметить как будущий кандидат (portfolio layer над сигналами). Distance/clustering техника родственна нашей идее «корреляции зон» (ML-roadmap #2, [[traid-bot-ml-pivot]]).

## Action items для проекта

1. ☐ **Записывать все backtest-варианты + считать PBO** (формализовать; у нас много вариантов 1.1.x).
2. ☐ **CPCV** вместо single-path walk-forward в ML-pivot (распределение Sharpe).
3. ☐ **Deflated Sharpe Ratio** — корректировка на число проб.
4. ☐ Дополнить backtest-метрики (frequency/year, holding period, ratio longs, corr-to-BTC, slippage).
5. ☐ **Bet sizing** из P_hit (prediction-algo) — будущее.
6. ☐ **HRP** — если появится portfolio layer над BTC/ETH/SOL.

Предыдущий: [[adv-fin-ml-lec2-4-bars-labeling-purged-kfold]]. Следующий: Lec 8-10. Каталог: [[adv-fin-ml-индекс]]. Связь: [[traid-bot-empirical-laws]], [[7-criteria-of-good-strategy]].
