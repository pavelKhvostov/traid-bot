---
tags: [decision, ta, gap-analysis, roadmap, order-flow, dalton, honest-negatives]
date: 2026-06-22
---

# Gap-анализ покрытия ТА: чего не хватает (ось ортогональной цене информации)

Картирование всего кода+vault+smc-lib: **мы коснулись почти всего спектра ТА** → вопрос «чего не хватает»
меняется с «какой категории нет» на «какая ОСЬ несёт инфо сверх price-геометрии» (раз price-only = монетка/фольклор,
доказано ригористично; единственное с +OOS: order-flow in-process + конфлюэнс-фильтр зон + pullback по тренду).

## Покрыто (не пробел)
SMC-канон (OB/FVG/breaker/choch/mitigation/RDRB), фигуры/кривые/флаги/клинья (TA-laws), volume_profile (POC/VAH/VAL),
VIC/heatmap, VWAP, fib, level_engine, CVD/cumulative_delta, VSA-свечи, initial_balance, naked_POC, sessions-AMD,
day-type/HAR-RV/DVOL/eff_ratio/regime, confluence (BTC.D/TOTAL/USDT.D), декорреляция, force-model, fractals.
**Доказано монеткой/фольклором:** голые паттерны/свечи/индикаторы/фигуры.

## РЕАЛЬНЫЕ пробелы (по приору ортогональной инфо)
- **A. Auction/Dalton — поведенческие сигналы (не только POC).** Профиль есть, НЕ построены: acceptance/rejection
  value-area (открытие выше/ниже VA → байес = главный Dalton-edge), форма профиля (P/b/D день-тип), миграция value,
  single prints / poor highs-lows (магниты). Высокий лит-приор (Dalton); в памяти помечен как направление-синтез.
- **B. Order-flow В ТОЧКЕ РЕАКЦИИ (не bar-CVD).** Есть bar-CVD+VSA+flow в level_engine, но level-flow убит грубо
  (AUC 0.531, flow-null p=0.467). НЕ изолированы: АБСОРПЦИЯ (большая дельта без хода=разворот), CVD-ДИВЕРГЕНЦИЯ у S/R,
  stopping-volume / effort-vs-result (Wyckoff/VSA по-настоящему). **Единственная ось с +OOS приором** → строить остро.
- **C. Cross-asset lead-lag / относительная сила — ПОЛНЫЙ ПРОБЕЛ.** ETH/SOL ведут BTC? alt-strength ротация, лаг-корр
  как тайминг/режим. Не тестировано вообще.
- **D. Ликвидация/OI как УРОВНИ.** OI/funding убиты как квадранты; кластеры ликвидаций/стопов как ценовые уровни
  («топливо» Вадима количественно из реальных liq/OI) не построены.
- **E. Единая per-level убеждённость.** Куски есть (price-S/R + volume-POC + zone + flow), нет слияния в один
  conviction-скор уровня.

## ОСЬ B ПРОТЕСТИРОВАНА (2026-06-22) — order-flow в точке реакции НЕ несёт edge ❌
`orderflow_reversal.py` (14853 касаний зон BTC/ETH/SOL, CVD из {SYM}_1h_flow.csv, вход open[t+1] lookahead-clean,
абсорпция + CVD-дивергенция). РЕЗУЛЬТАТ: flow-confirmed +0.097R ХУЖЕ flow-absent +0.288R; **NULL: random-отбор
того же размера +0.229R, P(random≥flow)=0.959 → поток ОТБИРАЕТ ХУЖЕ СЛУЧАЙНОГО**. Дивергенция мёртва (−0.06).
Сам baseline +0.223R = БЫЧИЙ ДРЕЙФ, не закон: LONG-поддержка +0.334R(3/3) vs SHORT-сопротивление −0.124R(1/3) —
асимметрия=сигнатура дрейфа. Абсорпция +0.42 = тот же long-канал, null отдельно не бит. **ВЫВОД: даже единственная
ось с +OOS приором (поток) под чистыми стенами (cross-asset+null+lookahead) = монетка/дрейф. Gap-анализ закрыт:
все оси ТА ригористично = ноль.** Новый pitfall: LONG/SHORT асимметрия выхлопа = дрейф-конфаунд (не закон).

## НЕ инвестировать (исчерпано)
Ещё паттерны/свечи/индикаторы (RSI/MACD/Stoch/BB), Elliott (0 файлов, фольклор), голые фигуры — показали монетку.

## Рекомендация
Не хватает не «фигур», а ПОДТВЕРЖДЕНИЯ ОБЪЁМОМ/ПОТОКОМ В ТОЧКЕ РЕАКЦИИ. Острый шаг: **B (абсорпция + CVD-дивергенция
у зон) + A (acceptance/rejection value-area)** через эталонный harness; + **C (lead-lag)** как чистейшая неисследованная
ось. Всё — через наши стены (null/cross-asset/lookahead/net), приор низкий, но это ЕДИНСТВЕННЫЕ оси с остаточным шансом.

## Связи
[[vadim-integration-living-market-laws]] · [[zone-race-first-passage-distance-dominates]] · [[project_neuro_metalabel_no_edge]] ·
[[level-strength-engine-описательный-предиктив-kill]] · [[ta-pattern-taxonomy-direction-vs-extent]]
