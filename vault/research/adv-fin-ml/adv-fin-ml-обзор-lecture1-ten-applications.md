---
type: external-source
source_file: "ssrn-3270329 (Lecture 1/10) + ssrn-3197726 (Ten Financial Applications of ML)"
author: "Marcos López de Prado (ORIE 5256)"
ingested: 2026-06-10
tags: [ml, quant, lopez-de-prado, overfit, research]
---

# Adv Fin ML · Lecture 1 + Ten Applications — почему ML, не эконометрика

Вводный блок курса López de Prado. Тезис: **финансовые задачи вне досягаемости эконометрики; нужен ML — но финансы НЕ plug-and-play**.

## Почему эконометрика проваливается в финансах (Lecture 1)

- Финансовые данные: нелинейные, пороговые, иерархические связи; часто нечисловые/неструктурированные (текст, изображения, записи); высокоразмерные (много переменных, мало наблюдений).
- Эконометрика (= по сути multivariate linear regression): полагается на p-values / «statistical significance» (нарушая протоколы ASA); подгоняет variance **in-sample**, а не прогноз out-of-sample; сильные нереалистичные допущения; не разделяет specification search и variable search; игнорирует **обе формы overfit (train И test set)**.
- Историческая причина: эконометрика застряла на регрессиях 1795-1920х (Gauss/Galton/Pearson/Fisher); в отличие от биостатистики/хемометрики, не впитала entropy, clustering, classification, graph theory. Web of Science: ML-термины в эконометрике 0.65% статей vs биология 10% vs химия 15%.
- **Вывод López de Prado: большинство эконометрических инвест-стратегий, вероятно, ложны.**

🔗 Для нас: подтверждает наш сдвиг от чистых формул к ML-pivot ([[traid-bot-ml-pivot]]) и LightGBM (нелинейность, взаимодействия 3064 фич). И наш закон [[traid-bot-empirical-laws]] про overfit/lookahead — López de Prado о том же: «обе формы overfit».

## Что такое ML (Ten Applications)

> «An ML algorithm learns complex patterns in a high-dimensional space without being specifically directed» (AFML 2018, p.15).

- «без указания» — не навязываем структуру, «данные говорят сами».
- «сложные паттерны» — то, что не выразить конечным набором уравнений.
- «высокоразмерное пространство» — много переменных + их взаимодействия.
- Примеры: clustering 1000×1000 корреляционной матрицы → блоки; Titanic survival → иерархия (gender > age > class).

## ⚠️ Главное предупреждение (критично для нашего проекта)

> «A ML algorithm will always find a pattern, even if there is none!»
> «Modelling financial series is harder than driving cars or recognizing faces.»

🔗 = НАШ закон [[traid-bot-empirical-laws]]: WR>60% = подозрение на lookahead. López de Prado формулирует тот же риск академически. Финансы — низкий signal-to-noise, ML переобучается на шуме. Отсюда весь его акцент на cross-validation, Purged K-Fold (у нас уже применяется в ML-pivot).

## Black Swans (можно ли предсказать?)

- Flash crash 6 мая 2010: ордер на продажу 75000 E-mini S&P 500 → дисбаланс order flow → каскад стоп-аутов.
- **Вывод:** «Black swans can be predicted by theory, even if they cannot be predicted by algorithms.» Imbalanced order flow — норма; 10% обвал был black swan, но причины известны microstructure theory.
- 🔗 Order-flow imbalance как предиктор — релевантно нашему направлению (liquidity/imbalance = ⛽/🧲 в Правиле 8, [[traid-bot-ml-pivot]]). Microstructure theory > чистый алгоритм.

## Выводы для проекта

- **Подтверждает ML-pivot** как правильное направление (нелинейность, высокая размерность).
- **Усиливает наши законы про overfit/lookahead** академическим авторитетом.
- **Order-flow imbalance** — теоретическая основа для liquidity-фич (но мы на Spot, см. Futures OI кандидат в [[traid-bot-ict-knowledge]]).
- Дальше в курсе (Lec 2-10) — конкретные техники: financial data structures, labeling, sample weights, Purged K-Fold, feature importance, backtest overfitting. Каждую прикладывать к MH ML pipeline.

Следующий: [[adv-fin-ml-индекс]] → Lec 2. Связь: [[traid-bot-ml-pivot]], [[traid-bot-empirical-laws]].
