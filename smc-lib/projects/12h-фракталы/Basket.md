# Basket (OR-union B1..B9)

Финальная фильтрация predicted pivot.

## Логика

```
для каждого pivot k из A4-output:
    Basket(k) = B1(k) ∨ B2(k) ∨ … ∨ B9(k)
```

Pivot считается «принят басketom», если хотя бы один B-блок выстрелил на нём.

## Direction matching

B-блок direction должен совпадать с pivot direction:
- FH pivot (high) → проверяются B-блоки с `direction="short"` (sweep вверх)
- FL pivot (low) → проверяются B-блоки с `direction="long"` (sweep вниз)

## Версии

### Basket_v2 (текущий канон в архиве)

Состав: B1=B1_v2 (251/64.5%) ∪ B2..B9 как старые C1..C9.
Цифры: **654 fires / 437 conf / WR 66.8%**.

### Basket_v3 (canonical 2026-06-06)

Состав: B1_v4 ∪ B2(B2C1 OB + B2C2 ob_liq) ∪ B3(maxV) ∪ B4(HMA-78 + HMA-200) ∪ B5(VWAP) ∪ B8(force div ∪3) ∪ B9(P11 4-OR).

**Цифры:** n = **724** / conf = **483** / WR = **66.71%** / Δ +18.11 pp от baseline.

Запущено через `~/smc-lib/projects/12h-fractal-new/scripts/run_all.py`.
Selectivity 724/1356 ≈ 53%. B6 RSI и B7 MoneyHands пока не имплементированы — войдут позже.

## Imp / target

Per memory [[feedback-pred12h-window-and-noimp]]:
- **НЕТ imp / target tracking**.
- Метрики: только `n / conf / WR / Δ`.

## Selectivity

`n_Basket ≪ n_A4` (basket reduces 1 356 → 724 ≈ 53%).
Trade-off: precision (WR) растёт с +48.6% (baseline) до **+66.71%** (basket). Δ ≈ +18.1 pp.

## Дальше

- **W (weight) layer** — взвешивание B-блоков (а не наивный OR).
- Базовый подход: logistic regression `P(W | B1, B2, ..., B9)` на A4-output.
- Эксперимент уже описан в [[empirical-tf-weight-rejected]] (ML over next-bar Williams — failed).
- Подход через **per-zone-event labeling** — open для будущей работы.

## Код

- **Basket builder:** `~/smc-lib/scripts/pred12h_basket_c1c2c3.py`
- **Per-B evaluator:** разрозненные скрипты в `~/smc-lib/scripts/pred12h_c*.py`
- **TODO:** объединить в `~/smc-lib/scripts/pred12h_Basket_v3.py`.
