---
tags: [session, chains, i-rdrb-fvg, ifvg, rdrb, cross-asset, combined-d, honest-verdicts]
date: 2026-06-19
---

# Сессия: 3 цепочки A/B/C — достроить до cross-asset гейта, честные вердикты

Запрос: «имея массив информации, какие цепочки предложить» → предложил 3 внутри проверенной
каскадной архитектуры (не книжные одиночки) → «сделай все по очереди». Сквозная нить: каждая
цепочка прогоняется через ОДИН гейт — cross-asset + год-стабильность + LONG/SHORT (bull-drift?).

## A — i-RDRB+FVG (Combined-D) → ✅ ЖИВАЯ, live-кандидат №1
Построил **детектор `strategies/strategy_i_rdrb_fvg.py`** (канон V1, 5 свечей, Combined-D entry/SL,
переиспользует detect_rdrb+detect_fvg) + **8 тестов** (зелёные) + **cross-asset бэктест**
`research/i_rdrb_fvg/backtest_cross_asset.py`.
- TF=1h: BTC +127R@RR1 (6/7 лет), ETH +96R@RR1 (солидно), SOL +22R (маргинал).
- BTC +127R воспроизводит валидированный Combined-D (+122.6R/6y) → порт верен.
- **НЕ bull-drift**: BTC+ETH SHORT-сторона положительна (ETH SHORT +61 > LONG). Двусторонний edge.
- clean-structure proxy НЕ сработал (dirty-корзина крошечная). Буст не подтверждён.
- Единственная проверенная цепочка с cross-asset переносом. [[i-rdrb-fvg-cross-asset-live-candidate]]

## B — 1.1.7 iFVG-continuation → BTC-ONLY (не переносится)
Прогнал существующий детектор (etap_95, V2c 4h-only) на полной истории cross-asset
(`research/elements_study/backtest_117_cross_asset_gate.py`):
- BTC RR2.5: +55R/6y, 6/7 лет, двусторонне — реальный middle-tier (лучше прежних 2.3y +37.5R).
- ETH: **−29.5R, 2/7 лет**, обе стороны в минус. Не переносится.
- SOL: +39R — **артефакт 2022** (+37.5 из +39, SHORT в медвежий год). Снять 2022 → ноль.
- Вердикт: iFVG-continuation **BTC-specific** (как 1.1.4 BFJK, 1.1.5 — судьба из ETH OOS памяти).
  «iFVG-как-макро под OB-D» унаследует тот же BTC-специфичный core (гейт режет count, не создаёт edge).
  Обновлена [[strategy-1-1-7-ifvg-continuation]].

## C — RDRB-htf вариант 1.1.1 → грейд-бустер, не замена
Подменил в каркасе 1.1.1 только htf-детектор OB→RDRB (`research/1_1_1_rdrb_htf/backtest_compare.py`):
- avg R/сделку ВЫШЕ (BTC +0.466 vs +0.253; ETH +0.350 vs +0.270), две стороны+.
- НО RDRB на htf в ~3.7× реже (74 vs 283) → total R ниже, год 5/7. Как замена OB-htf проигрывает.
- Это высоко-конвикшн подмножество → **грейд-бустер** (больший сайз когда htf-зона=RDRB),
  ложится на risk-sizing рычаг. [[rdrb-htf-1-1-1-high-conviction-subset]]

## Мета-вывод
Все 3 — внутри проверенной OB+FVG/RDRB-каскадной архитектуры. **A** — реальная новая cross-asset
цепочка (редкость). **B** подтверждает стену «каскады BTC-специфичны кроме 1.1.2». **C** — не цепочка,
а грейд-сигнал. Деньги по-прежнему = каскады 1.1.x + risk-sizing; A расширяет это cross-asset.

## Новый pitfall
high-avg-R + низкая частота ≠ хорошая standalone-цепочка (для цепочки решает total R; низко-частотный
высоко-avg вариант — кандидат в грейд, не в замену). [[known-pitfalls]].

## Что дальше (открыто)
- A → live-обвязка (BTC RR≈2 + ETH RR≈2.5; SOL FLAT/малый). Детектор+тесты готовы.
- C → реализовать «htf=RDRB» как грейд-флаг в 1.1.1 (поверх signal_grade).
- Прежнее: VIC_BOS→WS; грейд-1.1.1→прод; level_engine→andrey; main.py выключен.

## Связи
[[2026-06-18-reversal-слой-грейд-sizing-level-engine-pdf-стратегии]] · [[i-rdrb-fvg-combined-d-block-edge-sl-01]]
