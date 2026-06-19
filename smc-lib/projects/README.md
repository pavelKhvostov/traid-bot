# Проекты

Раздел для **прикладных проектов** библиотеки — комбинаций элементов / правил / индикаторов под конкретную предсказательную задачу.

Отличие от других разделов:
- `elements/` — atomic SMC primitives (canon)
- `indicators/` — independent numeric features (canon)
- `rules.md` / `zone_of_interest.md` — общие правила (canon)
- `scripts/` — одноразовые research/backtest (НЕ canon)
- **`projects/`** — целостные прикладные пайплайны, использующие canon (semi-canon, документируются как фиксированные пайплайны)

## 4 активных проекта

| # | Имя | Папка | Тип | Состояние |
|---|---|---|---|---|
| **1** | **12h фракталы** | `12h-фракталы/` | Pure rule-based prediction | ✅ Зафиксирован: (sweep_FH ∪ OB_sweep) ∩ sweep_maxV[i] → 82% HH / 73% LL на BTC 6y |
| **2** | **Скользящие (MA-EMA-HMA ML)** | `скользящие/` | ML на 1h closes | 🔄 Production canon. Phase 1 holdout 82% top-0.5% LONG_3 out-of-sample. Phase 2 sim +6.4%/мес net. CPCV в работе на PC2 |
| **3** | **ob_vc ML** | `ob-vc-ml/` | ML на ob_vc events с wait-window | 🔄 vc_lean s43 в работе на PC1. Two entry types n_FVG=1/≥2 |
| **4** | **ob_vc 2h** | `ob-vc-2h/` | Классическая стратегия 24 типа (T1-T16 × a/b) | ✅ Зафиксирован: +329R/6y, cascade A1+B1 WR 64.5% EV +0.290R |

## Корзина

`_корзина/` — артефакты старых/слитых проектов (pred12h, bounce-or-break, pivot, sync, prediction-algo, andrey-12h, maxv-force-model, PHASE4_SPEC, correlations, bb_dataset). Если понадобится — найти можно там, отголоски былой работы сохранены.

## Структура проекта-документа

Каждый проект включает:
1. **Цель** — что прогнозируем
2. **Ground truth** — на чём измеряем
3. **Methodology** — архитектура (cascade / ML / иное)
4. **Этапы / условия** — таблицы с числами
5. **Текущее состояние** — что в работе

## Связи

- Правила: [`../rules.md`](../rules.md)
- Зоны: [`../zone_of_interest.md`](../zone_of_interest.md)
- Элементы: [`../elements/`](../elements/)
- Литература: [`../literature/`](../literature/) + `pavel-notes/`
