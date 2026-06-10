---
type: external-source
source_file: "screencapture-neuralnetworksanddeeplearning-about + chap2 (Nielsen)"
author: "Michael Nielsen — Neural Networks and Deep Learning (онлайн-книга)"
ingested: 2026-06-10
tags: [ml, neural-networks, reference, research]
---

# Neural Networks (Nielsen) — backpropagation как reference

Конспект-указатель на главу 2 книги Michael Nielsen «Neural Networks and Deep Learning» (neuralnetworksanddeeplearning.com). Это **общая ML-теория** (не финансовая) — фундамент нейросетей. Фиксирую как reference, без переписывания общеизвестной теории.

## Что внутри (Chapter 2 — How backpropagation works)

- **Backpropagation** — быстрый алгоритм вычисления градиента cost-функции C по любому весу w / смещению b: ∂C/∂w, ∂C/∂b. «Workhorse обучения нейросетей».
- 4 фундаментальных уравнения backprop (δ output-слоя; δ через слои назад; ∂C/∂b; ∂C/∂w), Hadamard-произведение, chain rule, matrix-based forward pass.
- Даёт не только скорость, но и **insight**: как изменение весов/смещений меняет поведение сети.

## 🔗 Релевантность для нашего проекта

⚠️ **Косвенная.** Наш ML-стек — **LightGBM** (gradient boosting на деревьях, [[traid-bot-ml-pivot]]), НЕ нейросети. Backprop напрямую мы не используем.

- Это reference на случай перехода к **нейросетям** для MH features (3064 фичи) — но López de Prado ([[adv-fin-ml-обзор-lecture1-ten-applications]]) предупреждает: на финансах с низким signal-to-noise НС переобучаются ещё легче деревьев. Для табличных финансовых фич gradient boosting (наш LightGBM) обычно бьёт НС.
- Полезно знать **gradient descent / cost function / overfit** общую базу — но для табличных фич deep learning избыточен.
- Если в будущем — sequence-модели (LSTM/Transformer) на сырых барах вместо hand-engineered фич — эта база пригодится. Сейчас: **держим как reference, не приоритет.**

## Вывод

Общая ML-теория. Не меняет наш выбор LightGBM для табличных фич. Закладка на будущее (deep learning на крипте — отдельное большое направление, не текущий трек). Финансовая специфика обучения — в курсе López de Prado, не здесь.

Каталог: [[adv-fin-ml-индекс]]. Связь: [[traid-bot-ml-pivot]].
