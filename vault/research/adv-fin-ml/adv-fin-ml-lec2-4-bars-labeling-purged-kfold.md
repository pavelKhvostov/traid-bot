---
type: external-source
source_file: "ssrn-3257415 (Lec2) + ssrn-3257419 (Lec3) + ssrn-3257420 (Lec4)"
author: "Marcos López de Prado (ORIE 5256)"
ingested: 2026-06-10
tags: [ml, quant, lopez-de-prado, feature-engineering, cross-validation, research]
---

# Adv Fin ML · Lec 2-4 — Bars, Labeling, Meta-labeling, Purged/Embargoed K-Fold

Самый практичный блок курса — прямой инструментарий для feature engineering и валидации. **Прямо применимо к нашему MH ML pipeline** ([[traid-bot-ml-pivot]]).

## Lec 2 — применения ML (углубление Ten Applications)

- **Meta-labeling** ⚡ — вторичная ML-модель поверх первичной: первичная даёт buy/sell, вторичная учится предсказывать, **сработает ли** этот сигнал (label 1=gain, 0=loss). Повышает precision, фильтрует ложные сигналы первичной модели.
- **Structural breaks / outlier detection** — cross-section чувствителен к выбросам: 5% выбросов ломают регрессию.
- **MVO (mean-variance optimization)** проигрывает наивному 1/N out-of-sample; ML-решения бьют и MVO, и 1/N.
- RL для хеджирования — Greek-free, model-free.

🔗 **Meta-labeling = прямой кандидат для нас:** поверх наших каскадных детекторов (1.1.x / C2) обучить вторую модель «сработает ли сетап». Это РОВНО философия prediction-algo calibrator (hit-rate по бакетам, [[traid-bot-ml-pivot]]) — но López de Prado делает это полноценной ML-моделью. **Сильный кандидат.**

## Lec 3 — Financial Data Structures (X), Labeling (Y,T), Sample Weights (W)

### Information-driven bars ⚡ (фундаментальный сдвиг)

- Информация приходит на рынок НЕ с постоянной скоростью (entropy rate непостоянен). Сэмплирование по времени (1h, 1d) → информационное содержание баров неравномерно.
- **Лучше: сэмплировать как subordinated process от активности:**
  - **Tick bars** (N сделок), **Volume bars** (N объёма), **Dollar bars** (N $-оборота), **Volatility/runs bars**, **Order-imbalance bars**, **Entropy bars**.
  - Dollar bars наиболее стабильны по распределению.
- **Dollar Imbalance Bars:** θ_T = Σ b_t·v_t (b = aggressor flag ±1); бар закрывается, когда накопленный imbalance превышает ожидаемый (EWMA). Реагирует на дисбаланс order flow.

🔗 ⚠️ **Для нас:** мы используем **time bars** (1h/2h/4h... фиксированное время) — López de Prado считает это худшим выбором. **Кандидат-эксперимент:** dollar bars / volume bars для крипты (у Binance есть trades/volume). Может улучшить MH features (сейчас 3064 фичи на time bars). Но: ломает всю инфраструктуру (TIMEFRAMES_NATIVE, compose_from_base) → дорого. Отметить как стратегический кандидат, не быстрый.

### Labeling

- ⚠️ Почти все ML-папиры в финансах используют **fixed-time horizon** labeling (return через h баров vs порог τ) — López de Prado считает это плохим (игнорирует path, SL/TP).
- **Triple-Barrier Method** ⚡ — label по трём барьерам: верхний (TP), нижний (SL), вертикальный (timeout). Label = какой барьер тронут первым. 🔗 = РОВНО наша торговая логика (TP/SL/timeout)! Наш бэктест уже это делает по сути. Для ML-меток — формализованный triple-barrier.
- **CUSUM filter** — сэмплировать события при накоплении отклонения (структурный сдвиг), а не на каждом баре.

### Fractionally Differentiated Features ⚡

- Дилемма: ценовые ряды нестационарны (нужна дифференциация), но целочисленная разность (returns) убивает память. **Fractional differentiation** (дробный порядок d∈(0,1)) — делает ряд стационарным, СОХРАНЯЯ максимум памяти.
- 🔗 **Кандидат для MH features:** наши фичи (slopes, distance, EMA) — проверить, стационарны ли; fractional diff может дать более предиктивные фичи без потери памяти.

## Lec 4 — Ensembles + ⭐Cross-Validation in Finance

### Ensemble methods

- 3 типа: **Bagging** (Random Forest), **Boosting** (AdaBoost/Gradient — наш **LightGBM**!), **Stacking** (гетерогенные learners + K-fold cross-training).
- RF: второй уровень рандомизации (подмножество фич на split) → борется с overfit деревьев.
- Boosting: адаптивный (обновляет sample weights), мощнее, но **нельзя параллелить** (последовательный). 🔗 Наш LightGBM n_jobs=3 — это внутрипараллельность, не параллельность по деревьям. Совпадает.

### ⭐ Purged K-Fold + Embargo (критично — у нас УЖЕ применяется)

- **Проблема leakage:** финансовые labels формируются на **overlapping data** (Y_t ≈ Y_{t+1}), поэтому стандартный K-Fold течёт (train «видит» test через перекрытие).
- **Purging:** удалить из train все наблюдения, чьи labels перекрываются по времени с test-labels (triple-barrier: label = sgn return на [t_j,0, t_j,1]).
- **Embargo:** дополнительно выкинуть наблюдения сразу ПОСЛЕ test (из-за serial correlation, ARMA-эффекты).
- 🔗 **Подтверждает наш подход:** мы уже используем **Purged K-Fold** в ML-pivot ([[traid-bot-ml-pivot]], etap_160). López de Prado — первоисточник. Проверить: применяем ли мы **embargo** дополнительно к purging? Если нет — добавить (дёшево, важно для serial-correlated фич).

### Feature importance + hyper-param tuning с CV

- Избегать моделей, опирающихся на несколько фич; балансировать importance, performance по месяцам и таргетам (= Numerai-критерии). 🔗 Наша проблема «стабильность по месяцам плохая 35-60%» ([[traid-bot-ml-pivot]]) — López de Prado прямо адресует: исключать месяцы где модель плоха, балансировать.

## Action items для проекта (приоритет)

1. ☐ **Meta-labeling** поверх каскадов 1.1.x/C2 — вторичная ML «сработает ли сетап» (= улучшенный calibrator).
2. ☐ **Embargo** в дополнение к нашему Purged K-Fold (проверить, есть ли).
3. ☐ **Triple-barrier labeling** для ML-меток (формализовать наш TP/SL/timeout).
4. ☐ **Fractional differentiation** фич MH (стационарность + память).
5. ☐ **Dollar/volume bars** вместо time bars (стратегический, дорого — ломает инфру).

Следующий: Lec 5-7. Каталог: [[adv-fin-ml-индекс]]. Связь: [[traid-bot-ml-pivot]], [[traid-bot-empirical-laws]].
