# B7 — MoneyHands (planned)

Закреплённое название для блока B7. **Sub-conditions (B7Cx) ещё не реализованы.**

## Идея

«MoneyHands» — концепция «умных денег» / institutional hands в SMC. Использует pivot-money-hands логику для предсказания формирования Williams n=2 фрактала.

См. [[pivot-money-hands-long-cascade-rule]] — резонанс bear-pivot + cascade ≤ 1h даёт **62.9% LONG accuracy**. SHORT side не работает (асимметрия).

## Кандидаты на B7Cx

(Пока не реализовано. Формализм — TBD.)

- **B7C1** — LONG cascade rule (bear-pivot resonance + cascade ≤ 1h) — пока только LONG side по канон-правилу
- **B7C2** — расширение SHORT side (если найдём асимметричную формулировку)
- **B7C3** — multi-TF cascade depth (различные timeframes для резонанса)
- **B7C4** — MoneyHands + force confluence (B7 ∧ B8 Power Zone)

## Связанные memories

- [[pivot-money-hands-long-cascade-rule]] — основная memory правила: bear+cascade≤1h → 62.9% LONG accuracy, асимметрия SHORT

## TODO

- Зафиксировать формальное определение «money hands» pivot detector
- Найти/написать скрипт реализации (искать в `~/smc-lib/scripts/` по «money_hands» / «pivot_money»)
- Causality-аудит ([[feedback-b-series-strict-causal-i]])
- Подключить к Basket evaluator
