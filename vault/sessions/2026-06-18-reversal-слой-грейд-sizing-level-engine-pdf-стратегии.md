---
tags: [session, reversal, signal-grade, level-engine, vic-vadim, ict, descriptive, honest-negatives]
date: 2026-06-18
---

# Сессия: reversal-слой → грейд-sizing → level-strength engine → PDF-стратегии

Очень длинная сессия. Сквозная нить — **дисциплина «descriptive или KILL»**: всё, что не
бьёт permutation-null + год-стабильность + cross-asset, помечается честно, без подделки.
4-й…7-й независимые подтверждения стены «направление=монетка / фильтр не бьёт случай».

## 1. Reversal-структура дня/недели (описательно)
`reversal.py` + `etap_255`: детекция разворотной точки ДНЯ (rev_up/down + пивот) и НЕДЕЛИ
(свип PWH/PWL), маркер ▲/▼ на чарте `etap_225` + caption `etap_227` + `signal_context`.
Адверс-проверка: направление после разворота = монетка; fill%/«свип-магнит» = геом. конфаунд
(убит контролем близости). → только ОПИСАНИЕ. [[reversal-структура-дня-недели-описательный-слой]]

## 2. Грейд как ПРАВИЛО РАЗМЕРА (деньги = риск, не R)
`signal_grade.size_mult` (TIERED) + строка в build_context. etap_257: на 1.1.1 SKIP(net≥0) даёт
≈тот же ΣR, но **просадка 13.6R→3.0R, ΣR/DD 5.3→25.7, плюс 7/7 лет** → при равном риске сайз
×~4.5. На **1.1.2 НЕ переносится** (etap_258: net≥0 47% vs net<0 47%). 1.1.2 оставлен FLAT.
[[грейд-как-правило-размера-pnl-и-непереносимость-на-1-1-2]]

## 3. Выгрузка на ветку andrey
Коммит `584ca5a` (143 файла, +21k строк): reversal/grade/etap_198-263/vault. Артефакты
(output/, new/, catboost_info, val-csv) в .gitignore. Секреты (.env/state/data) не утекли.

## 4. Level-strength engine (самое большое) — `research/level_engine/`
Запрос: нейро-модуль, все зоны ±15k с 2020, уровень=скопление зон 10 TF + ликвидность,
рекурсивный пересмотр, сила 1-10 + аргументы. Построено 7 модулей (le_zones/cluster/interact/
belief/engine/validate), причинность доказана (future-mutation тест байт-в-байт).
- **Предиктив УБИТ**: сила→hold/break AUC 0.531 (BTC)/0.545(ETH), density-matched стратиф-null
  **p=0.467** (наивный shuffle-y p=0.001 — ловушка!). order-flow absorption AUC 0.504.
- **2 раунда самокритики** (workflows): v2 8-факторный + исправлена инверсия свежести; v2.1 —
  W=согласие TF, Q оживлён (τ270), directional support≠resistance, +order-flow descriptive.
  Спред 3-6→4-7. **#8 HTF-кластеризация ПОПРОБОВАНА→ОТВЕРГНУТА** (мега-якоря; C-сатурация =
  плотность данных, не кластеризация). Едет как ОПИСАТЕЛЬНАЯ карта (`predicts_hold=False`),
  отрисована на TV. [[level-strength-engine-описательный-предиктив-kill]]

## 5. Стратегии из PDF-материалов (ICT/SMC/Bulkowski/Dalton/ViC) → сигналы как 1.1.x
Агент-обзор vault → топ-3. Построил и честно убил:
- **#1 ViC-Vadim 12h** (`backtest_v1_signal_rr.py`): precision 75-93% (предиктор), но как СДЕЛКА
  KILL — BTC +0.037 R/сд, ETH +0.151, **SOL отрицателен**, год-нестаб. **precision ≠ expectancy**
  (меряет, что фрактал формируется = структура, не что цена разворачивается прибыльно).
- **#2 ICT-2022 displacement-gate** (`etap_264/264b`): выглядел кросс-ассет+, но permutation-null
  **p=0.10-0.67** (фильтр не бьёт случай), остаток = **bull-drift** (LONG+/SHORT~0 на всех 3).
- **#3 Bulkowski** — не тестил (паттерн стены очевиден).
**Мета-вывод:** готовые книжные стратегии системно упираются в стену. Деньги в проекте =
только OB+FVG каскады (1.1.x) + risk-sizing по грейду. [[ict-double-fvg-формации-по-контексту]],
strategy-note ViC-Vadim (status → execution-KILL).

## Новые pitfalls (known-pitfalls.md)
proximity-конфаунд в fill/revisit · ORB узкий-стоп cost-в-R · **permutation-null: гейт обязан
бить «случайный отбор той же мощности», наивный shuffle-y ложно подтверждает** · **occurrence-
precision ≠ tradable signal** (бэктест entry/SL/TP обязателен).

## Инфра-заметки
- TV-десктоп CDP рвётся → `tv_launch` (kill_existing) перезапускает; после релонча возможен
  stale-заголовок цены — сверять `quote_get`. Правило: **`draw_clear` ВСЕГДА перед отрисовкой**.
- Binance REST периодически таймаутит (D.fetch без ретраев) → fallback на CSV (но стейл).
- Тесты: signal_context 102 зелёных, level_engine 8 зелёных.

## Что дальше (открыто)
- VIC_BOS (+37R/3y BTC, готов) — только WS-подключить (модест, BTC-only).
- Грейд-sizing 1.1.1 → прод-правило (доказанный риск-рычаг).
- level_engine на ветку andrey (ещё не коммитил после 584ca5a).
- Прод main.py — выключен; кнопочный бот @new_edge_neiro_bot поднять заново.

## Связи
[[2026-06-16-frontier-v2-интеграция-1.1.1-грейд-ict-fvg]] · [[модель-анализа-v2-расследование-вердикты-и-ядро]]
