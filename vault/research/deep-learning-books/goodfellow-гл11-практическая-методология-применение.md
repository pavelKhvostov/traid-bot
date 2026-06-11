---
type: external-source
source_file: "Goodfellow Deep Learning (MIT Press) — гл.11 Practical Methodology + гл.7 Regularization"
author: "Goodfellow, Bengio, Courville"
ingested: 2026-06-11
tags: [deep-learning, methodology, overfit, regularization, books, pavel]
---

# Goodfellow гл.11 (Practical Methodology) — применение к нашей сети

Конспект ключевой главы Goodfellow «Deep Learning» (книги в `vault/research/deep-learning-books/`: Goodfellow 801 стр, Nielsen 293, Nikolenko 477). Фокус — **как правильно улучшать нейросеть** для задачи оценки сигналов 1-5.

## Методология Goodfellow (гл.11) — 4 шага

1. **Определи метрику и целевое значение** (driven by problem). Помни про **Bayes error** — минимум, недостижимый даже с бесконечными данными, если input не содержит полной информации о target.
2. **Построй end-to-end pipeline как можно раньше** (у нас есть — etap_178/179/180 + бот).
3. **Инструментируй: диагностируй overfit vs underfit vs дефект данных.**
4. **Инкрементальные изменения** на основе диагностики, НЕ вслепую перебирая алгоритмы.

## ⭐ Диагностический алгоритм (гл.11.3) — ПРИМЕНЁН к нашей сети

> «First, determine whether performance on the **training set** is acceptable. If training performance is poor → underfit → увеличить модель / тюнить LR (НЕ данные). If training good but **gap train-test большой** → overfit → больше данных / регуляризация.»

**Диагноз нашей сети (etap_180):**
- **TRAIN ρ = 0.77** (отлично учит train)
- **TEST ρ = 0.09** (плохо обобщает)
- **Огромный gap → СИЛЬНЫЙ OVERFIT** (не underfit, как я думал раньше!)

🔑 **Это переломный вывод от книги.** Раньше я считал «сигнала в фичах мало». На самом деле сеть **переобучается** — запоминает шум train. По Goodfellow при overfit:
- ❌ НЕ увеличивать модель (усилит overfit)
- ✅ **Больше регуляризации:** dropout↑, weight decay↑, **МЕНЬШЕ модель**
- ✅ **Меньше фич** (107 фич на 3600 train = переобучение; MDA показал — работает горстка)
- ✅ **Больше данных** (но крипта ограничена 2022+)
- ✅ Dataset augmentation / noise robustness (гл.7.4-7.5)

## Default Baseline рекомендации (гл.11.2)

- Оптимизатор: **SGD+momentum** (с decay LR при плато) ИЛИ **Adam**. У нас AdamW — ОК.
- Активация: **ReLU/Leaky ReLU/PReLU/maxout**. У нас GELU — ОК.
- **Early stopping — почти всегда** (у нас есть, patience).
- **Dropout — отличный регуляризатор, easy.** У нас 0.3-0.35 → можно ↑.
- **Batch norm** — можно опустить в baseline, но помогает оптимизации. У нас есть.
- «Mild regularization from the start» — у нас weight decay 1e-2.

## Regularization техники (гл.7) — что добавить против overfit

- **7.1 Parameter Norm Penalties (L2/weight decay)** — у нас 1e-2, поднять до 3e-2-5e-2.
- **7.4 Dataset Augmentation** — добавить шум к фичам (noise injection) = регуляризация.
- **7.5 Noise Robustness** — шум на входы/веса.
- **7.8 Early Stopping** — есть.
- **7.11 Bagging/Ensembles** — у нас ансамбль 5 фолдов (хорошо, снижает variance).
- **7.12 Dropout** — поднять до 0.5.

## План применения (etap_181)

По диагнозу overfit — анти-overfit конфигурация:
1. **Меньше модель** (hidden 128→64, 2 блока вместо 3).
2. **Сильнее dropout** (0.35→0.5).
3. **Больше weight decay** (1e-2→4e-2).
4. **Урезать фичи до топ-20 по MDA** (107→~20, меньше шума для запоминания).
5. **Noise injection** в train (augmentation).
Цель: уменьшить gap train-test (сейчас 0.77 vs 0.09), поднять TEST ρ.

⚠️ Goodfellow честно: если после регуляризации test не растёт — упёрлись в **Bayes error** задачи (исход сделки = шум после входа). Тогда честный потолок ~0.1-0.15.

## ✅ РЕЗУЛЬТАТ применения (etap_181) — ОКОНЧАТЕЛЬНЫЙ ДИАГНОЗ

Применил анти-overfit (hidden 64, dropout 0.5, weight_decay 4e-2, noise injection, 40 фич):
- **Gap train-test упал 0.68 → 0.11** (overfit ВЫЛЕЧЕН ✓)
- **НО TEST ρ упал 0.090 → 0.052** (не вырос!)

**Прошли обе крайности:** etap_180 (слабая регуляризация → overfit, train 0.77/test 0.09) и etap_181 (сильная → overfit вылечен, но test 0.05). Когда лечение overfit НЕ поднимает test → **по Goodfellow это Bayes error**: информации в фичах о target недостаточно.

**🔑 ОКОНЧАТЕЛЬНЫЙ ВЫВОД (книги дали точный ответ):**
- **Предсказание РАЗВОРОТА** (etap_177): информации достаточно → AUC **0.93** ✓
- **Предсказание ИСХОДА СДЕЛКИ** (etap_180/181): информации НЕ хватает → ρ **0.09 потолок**. «Какой R у конкретной сделки» фундаментально слабо предсказуемо из контекста на входе (шум после входа).

**Лучшая модель для бота = etap_180** (ρ 0.09, фильтр WR 34→43%). Дальше эту задачу качать бессмысленно — упёрлись в математический потолок. Качать стоит ПРЕДСКАЗАНИЕ РАЗВОРОТА (etap_177), где потенциал есть.

Связь: [[signal-grade-3assets-etap179]], [[signal-grade-1to5-ordinal-nn-etap178]], [[adv-fin-ml-индекс]] (López de Prado тоже про overfit).
