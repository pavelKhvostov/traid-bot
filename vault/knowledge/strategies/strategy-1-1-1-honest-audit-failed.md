---
tags: [strategy, audit, case-study, overfit, lookahead]
date: 2026-05-08
status: failed-honest-test
related: [research/elements_study/etap_34_strategy_111_honest.py, research/1_1_1/]
---

# Strategy 1.1.1 — HONEST audit failed (2026-05-08)

Case study инфляции backtest-результатов. Стратегия заявляла +46.8R/3y
@ RR=2.2, в честном re-test превратилась в +20R/6.33y @ RR=1.0,
**отрицательная при RR≥1.5**.

## Что заявлялось (research/1_1_1/, до 2026-05-08)

После 3-stage SWEPT optimize @ RR=2.2:
- 115 closed = 34W / 28L / 53 noentry
- WR **54.8%**, **+46.8R**, **R/trade 0.755**
- entry_pct=0.80, sl_pct=0.35 (между ob_htf edge и FVG entry edge)
- 4-stage cascade: OB-{1d,12h} + FVG-{4h,6h} → OB-{1h,2h} + FVG-{15m,20m}
- Тест на 3 года BTCUSDT (2023-2026)

## HONEST re-test (etap_34, 2026-05-08)

С нашими новыми стандартами:
- Anchor-confirm fix ([[lookahead-anchor-confirm-окно-cur_open-cur_close]])
- min_sl = 1% (futures-friendly)
- mid entry (entry_pct = 0.5)
- 6.33 года (2020-2026, после fix [[2022-1m-data-gap-symptom-year-missing]])
- Round RR (1.0, 1.5, 2.0, 2.5)

```
chains: 1d-4h-1h-15m: 95
        1d-4h-2h-15m: 94
        1d-6h-1h-15m: 72
        1d-6h-2h-15m: 71
        12h-4h-1h-15m: 108
        12h-4h-2h-15m: 104
        12h-6h-1h-15m: 69
        12h-6h-2h-15m: 75
total chain setups: 688, deduped unique: 446

RR=1.0: WR 53.8%, +20.0R,  R/tr +0.076  freq 1.35/wk
RR=1.5: WR 33.2%, -35.0R,  R/tr -0.171
RR=2.0: WR 22.8%, -58.0R,  R/tr -0.315
RR=2.5: WR 16.2%, -75.0R,  R/tr -0.434
```

Year-by-year @ RR=1.0:

| Год | n | WR | Total R |
|---|---|---|---|
| 2020 | 42 | 55% | +4.0 |
| 2021 | 57 | 58% | +9.0 |
| 2023 | 40 | 52% | +2.0 |
| 2024 | 48 | 56% | +6.0 |
| 2025 | 62 | 52% | +2.0 |
| 2026 (4мес) | 13 | 38% | -3.0 |

(2022 не попал в выборку — либо нет setups в bear, либо фильтрация
chain-валидности отрезала 2022. Не data gap — fix этап 27 применён.)

**RR>1 разваливается катастрофически.** В отличие от C2 где RR=1
оптимум, у 1.1.1 RR=1 уже маргинальный, а попытка увеличить R/trade
через RR ломает стратегию.

## 2-stage baseline (OB-1d × FVG-15m)

Чтобы понять, чем 4 уровня помогают:

```
RR=1.0: WR 47.1%, -15.0R, R/tr -0.057
RR=1.5: WR 36.2%, -22.0R, R/tr -0.095
```

**2-stage baseline даже WORSE** чем 4-stage. То есть промежуточные
уровни (FVG-htf, OB-1h) добавляют ~+35R к baseline, но финальный
результат всё равно отстаёт от C2 (+70R) на +50R.

## Сравнение: заявленное vs HONEST

| Метрика | Заявленное (RR=2.2) | HONEST (RR=1.0) | Δ |
|---|---|---|---|
| WR | 61.7% | 53.8% | **−8pp** |
| R/trade | 0.755 | 0.076 | **−10× меньше** |
| Total R / year | +15.6 | +3.16 | **−5× меньше** |
| RR доходный | 2.2 | только 1.0 | RR>1.5 убыточен |

## Источники inflation

1. **Anchor cur_time bug** ([[lookahead-anchor-confirm-окно-cur_open-cur_close]]):
   anchor зона использовалась с момента `cur_open`, не `cur_close`.
   Окно поиска включало 1d/12h × 48 баров недоступной информации.
   Цена внутри формирующегося анкера систематически идёт В сторону
   зоны → искусственный +10pp WR.

2. **Custom RR=2.2** = математически peak с overfit-чувствительностью.
   Попытка повторить с round RR (2.0, 2.5) даёт убыток. RR=2.2 был
   сетку-точкой между peak и валидным значением.

3. **3y window без 2022.** Тест 2023-2026 пропустил bear market (2022)
   и захватил bull (2024-2025). Расширение до 6.33 лет резко снижает
   metrics. Этот инсайт — частный случай [[2022-1m-data-gap-symptom-year-missing]]:
   не data gap, а just-don't-test-on-bear.

4. **Узкий SL (`0.15·OB_depth`)** vs наш стандарт `max(15%·OB_depth, 1%·entry)`.
   Узкий SL = высокий R но и высокий churn rate; на честном min_sl=1%
   trades с тонким SL уже не открываются.

5. **4-stage cascade overfit.** Каждый дополнительный фильтр обрезает
   плохие setups в train data, но плодит false positives в OOS.
   Bias-variance: 4 уровня = слишком много свободных параметров для
   крипто-датасета размера 6 лет.

## Что отсюда следует

- **Простые 2-stage стратегии (C2, C3, D2) бьют 4-stage.**
- **WR > 60% на сотнях крипто-сделок = lookahead suspect.** Третий случай
  за исследование (etap_14, etap_31, 1.1.1).
- **Заявленные результаты не воспроизводимы без правильных стандартов.**
  Без honest audit нельзя живо торговать никакую strategy.
- **Live-обвязка 1.1.1 (`strategy_1_1_1_scanner.py`, VPS deployment) на
  паузе** — нужно либо отказаться, либо ждать улучшения.

## Что НЕ делать с 1.1.1

- ❌ Не продолжать live-deployment как production strategy
- ❌ Не использовать заявленный +46.8R / RR=2.2 как референс в новых
  обоснованиях
- ❌ Не строить confluence/triple variants на этой базе — 4-stage уже overfit

## Что МОЖНО делать

- ✅ Использовать как negative case-study для обучения «как НЕ оптимизировать»
- ✅ Пересмотреть 1.1.2, 1.1.3, 1_2_0 на anchor-confirm fix — возможно тот
  же класс bug
- ✅ Сохранить detector-функции (`detect_ob_pair`, `detect_fvg`) — они canon
  и используются и в C2

## Rescue attempt (etap_35, 2026-05-08)

После forensic-анализа 262 closed trades с 14 features:

| Filter | n | RR=1.0 WR | RR=1.5 WR | RR=1.5 total_R |
|---|---|---|---|---|
| baseline | 262 | 53.8% | 33% | **−35R** |
| Hull 4h aligned | 135 | 67.4% | 42% | +5.5R |
| **Hull 4h + EMA200 15m** | 96 | 70.8% | 47.9% | **+14.5R** ✅ |
| Hull 4h + ICT(L\|NY) | 49 | 73.5% | 56.8% | +15.5R ✅ |
| Score ≥ 4 of 5 features | 68 | 75.0% | 51.9% | +15.5R ✅ |

**Filter из 2-3 топ-фич спасает RR=1.5/2.0 в плюс.** Но даже rescued
1.1.1 даёт ~0.29 setups/wk (vs criterion 4: ≥1/wk) и +6-8R/year (vs
C2 +11R/year).

**Главные edge sources, найденные на 1.1.1:**
1. Hull MA(78) на 4h aligned with direction: WR +13.6pp
2. Money Flow (HA-based) sign aligned: WR +9.8pp
3. Daily-open premium/discount (ICT): WR +7.3pp
4. EMA200 align на 15m: WR +6.9pp
5. ICT NY session: WR +9.2pp

См. [[2026-05-08-strategy-111-forensic-indicator-filters]] — полный отчёт.

## Связи

- [[strategy_1_1_1]] — оригинальная спецификация (исторически)
- [[strategy-c2-ob-6h-fvg-2h-pro-rr1]] — head-to-head winner
- [[2026-05-08-strategy-111-forensic-indicator-filters]] — forensic + rescue attempt
- [[7-criteria-of-good-strategy]] — какие критерии 1.1.1 не проходит
- [[lookahead-anchor-confirm-окно-cur_open-cur_close]] — main bug source
- [[confluence-lookahead-and-rr22-bugs]] — связанные ранее найденные баги
- [[strategy-1-1-1-rr-sweet-spot]] — устаревший анализ RR (был на baited data)
- [[asvk-trend-line-hull]] — Hull-4h как мощнейший filter
- `research/elements_study/etap_34_strategy_111_honest.py` — honest backtest
- `research/elements_study/etap_35_strategy_111_forensic.py` — forensic + filters
