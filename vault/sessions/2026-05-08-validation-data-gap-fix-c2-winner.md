---
tags: [session, validation, data-gap, lookahead, c2-winner, strategy-1-1-1-audit]
date: 2026-05-08
duration: large
session_type: validation + multi-test
---

# Сессия 2026-05-08 — Validation, 2022 data fix, C2 winner, Strategy 1.1.1 audit

## Главное из сессии

1. **🚨 Найден КРИТИЧЕСКИЙ data gap** — 480 дней (2022-01-01 .. 2023-04-26)
   отсутствовали в `data/BTCUSDT_1m.csv`. Все backtests до этого пропускали
   2022 (медвежий: LUNA + FTX) и первые 4 месяца 2023.
2. **🥇 C2 (OB-6h × FVG-2h pro RR=1.0) — новый абсолютный winner** после fix.
   0 минусовых лет за 7. WR 55.3%, +70R, R/tr 0.105.
3. **D2 потерял корону** — 2022 был −6.25R, теперь 2 минусовых года.
4. **❌ Strategy 1.1.1 не оправдывает себя** в HONEST re-test:
   заявленное +46.8R / 3y → реально +20R / 6.33y, при RR≥1.5 отрицательный.
5. **ICT book filters** (etap 28): hour/weekday/D.O работают **избирательно**,
   только на конкретных базах (C3+T1, C6+T2). Combined T4 — overfit catastrophe.
6. **RDRB+ MMXM concept** (etap 31-33): lookahead bug подтверждён, real edge
   существует только на HTF (12h, 1d), мизерный на LTF.

## Этапы (хронология)

### Часть 1 — Финализация PDF и расширение grid

- **etap_16** — финальный PDF strategies report (12 страниц).
- **etap_17** — extended grid с SWEPT-фильтром на OB и FRSWEEP анкорами (648
  кандидатов). Главный вывод: SWEPT не даёт прорыва, обрезает 50% setups при
  том же WR.
- **etap_18** — fractal deep dive (4 семейства, 372 кандидата): A FRACT-only,
  B FRSWEEP, C HTF×LTF FRSWEEP-trigger, D Multi-TF fractal CONFLUENCE.
  Победитель: D FRACT2X-1d+4h × FVG-2h pro RR=1.0 — WR 64.6%, +61R.

### Часть 2 — 3-stage оптимизация (как Strategy 1.1.1 stages 1-3)

- **etap_19** — 3-stage opt для 4 баз (B1=C1, B2=C2, B3=C3/C4, B4=C6).
  Stage 1: entry sweep — mid (0.5) выиграл во ВСЕХ 4 базах.
  Stage 2: SL sweep — best sl_buf варьируется (B3 любит 0.15, B2 любит 0.5).
  Stage 3: RR sweep — OB-12h уникальная база где total_R РАСТЁТ при RR→3.
- **etap_20** — year-by-year deepdive D1-D5.
- **etap_21** — финальный recommendations PDF (8 страниц).

### Часть 3 — Расширенный grid #2 (confluence/triple/fract-range)

- **etap_22** — 4 новых семейства (608 кандидатов):
  A) Same-TF zone confluence (OB+FVG)
  B) HTF zone + LTF Fractal-trigger
  C) Triple-TF stack (HTF→MID→LTF)
  D) HTF FRACT range as anchor
- **etap_23** — 3-stage opt для best new (N1, N2). Не превзошли D2.
- **Главный вывод:** confluence/triple/fract-range НЕ дают прорыва.
  Простой каскад HTF zone + LTF FVG + pro-trend filter — оптимум.

### Часть 4 — Frequency-edge tradeoff

- **etap_24** — анализ всех 2024 кандидатов из 4 grid'ов. Главное: max R/year
  резко падает с уменьшением частоты. Sniper portfolio из 10 → 6.9 R/year vs
  D2 один → 14.1 R/year. Фильтр n/нед≥1 правильный.
- **etap_25** — deepdive E1 (OB-4h × FVG-1h all) и E2 (FRSWEEP-6h × FVG-15m
  all). Оба деградируют в 2025-26, не лучше D2.

### Часть 5 — 🚨 КРИТИЧЕСКИЙ ФИКС ДАННЫХ

- **etap_27** — пользователь спросил "почему в 2022-23 годах провал по данным".
  Проверка показала:
  ```
  2022: 1 бар (КРИТИЧЕСКИЙ ПРОБЕЛ)
  2023: 358,707 (~3/4 года, отсутствовали Jan-Apr)
  Точный gap: 2022-01-01 00:00 → 2023-04-26 21:33 (480 дней)
  ```
  Загружено 692,561 1m баров через Binance REST. Combined: 3,328,483 баров.
- **Re-run etap_15 (C1-C7) и etap_20 (D1-D5)** на полных данных.
- **Радикальная перестановка топов:**
  - C2: +48R → **+70R** (+22R благодаря 2022!)
  - D2: WR 47.2% → 44.4%, R/tr 0.297 → 0.221 (2022 был −6.25R)
  - C1: 2022 −10R, всего 3 минусовых года
  - C6: 2022 −3R, теперь 2 минусовых
- См. [[2022-1m-data-gap-symptom-year-missing]].

### Часть 6 — ICT-book фильтры

- **etap_28** — применение T1 (hour 7-17), T2 (Mon-Thu), T3 (D.O prem/disc),
  T4 (combined) к C2/C3/C6.
- Результаты:
  - **C3 + T1:** WR 58% → 62%, R/tr 0.16 → 0.24 ★
  - **C6 + T2:** WR 62% → 66.5%, R/tr 0.24 → 0.33 ★
  - C2 + любой: только хуже
  - T4 (combined): catastrophic во всех случаях (overfit)
- Книга работает избирательно. Stacking всех фильтров — типичная ошибка.

### Часть 7 — FVG → RDRB hypothesis

- **etap_29** — proverka гипотезы "после FVG образуется RDRB".
  ```
  Δ vs random baseline везде близко к 0 (-0.7 .. +0.9 pp).
  RDRB density 12% → встречается случайно в 92% окон 20 баров.
  ```
- **etap_30** — узкая гипотеза "RDRB inside FVG zone same-dir within 5 bars":
  только 0.9-1.4% FVGs соответствуют → not actionable.
- **Закономерности нет.**

### Часть 8 — RDRB+ MMXM concept

- **etap_31** — base test "RDRB+ = balanced range above FVG protects it".
  9.3% FVGs имеют RDRB+ структуру.
- **etap_32** — fair entry comparison (one-shot @ c2 close):
  RDRB+ дал +10-15pp WR на всех TF, **но это lookahead inflation**.
- **etap_33** — honest test (entry на confirm_idx.close):
  - 1h-4h: real edge ≈ 0 или отрицательный
  - **12h-1d: real edge есть** (+8-16pp WR), но низкая частота (47-92 setups/6.33y)
  - Lookahead давал inflation +10-13pp WR
- См. [[multi-bar-pattern-confirm-vs-trigger-lookahead]].

### Часть 9 — HONEST audit Strategy 1.1.1

- **etap_34** — заявленное original: WR 61.7% raw, +33R / 3y, после SWEPT
  optimize @ RR=2.2: +46.8R, R/tr 0.755, 115 closed.
- HONEST re-test с нашими стандартами (anchor-confirm fix, min_sl=1%,
  mid entry, 6.33y, round RR):
  ```
  RR=1.0: WR 53.8%, +20R, R/tr 0.076, 446 setups
  RR=1.5: WR 33.2%, -35R (отрицательный!)
  RR=2.0: WR 22.8%, -58R
  RR=2.5: WR 16.2%, -75R
  ```
- **Заявленные цифры были inflation:**
  - WR 61.7% → 53.8% (−8pp)
  - R/tr 0.755 → отрицательный при RR>1
  - Total +46.8R / 3y → +20R / 6.33y (3.5× меньше per year)
- Sources: 4-stage cascade overfit + lookahead в anchor cur_time +
  custom RR=2.2 + 3y window без 2022 stress + 0.15·OB_depth узкий SL.
- **2-stage baseline (OB-1d × FVG-15m):** даже WORSE (−15R, WR 47.1%).
  Промежуточные слои добавляют +35R но всё равно отстают от C2 на +50R.
- **C2 побеждает 1.1.1 head-to-head во ВСЕХ метриках.**

## Финальный ranking (после всех уточнений)

| # | ID | Setup | RR | WR | Total R | R/tr | Bad yrs |
|---|---|---|---|---|---|---|---|
| 🥇 | **C2** | OB-6h × FVG-2h pro | 1.0 | 55.3% | **+70R** | 0.105 | **0** ★ |
| 🥈 | C3 | OB-12h × FVG-2h pro | 1.0 | 58.0% | +60R | 0.160 | 0 |
| 🥉 | D1 | OB-12h × FVG-2h pro [opt] | 2.5 | 36.1% | +92.5R | 0.263 | 1 (2020) |
| 4 | D2 | OB-12h × FVG-2h pro [opt] | 1.75 | 44.4% | +81.2R | 0.221 | 2 |
| 5 | C6 | FRACT2X × FVG-2h pro | 1.0 | 62.2% | +60R | 0.244 | 2 |
| ❌ | 1.1.1 HONEST | OB-{1d,12h}×FVG-{4h,6h}×OB-{1h,2h}×FVG-15m | 1.0 | 53.8% | +20R | 0.076 | 1 (2026) |

C2 — единственная стратегия проходящая ВСЕ 7 критериев удачной стратегии
([[7-criteria-of-good-strategy]]).

## Главные lessons

1. **Полнота данных = критическая зависимость.** Если год выпадает из
   year-by-year breakdown — это не «не было setups», это data gap.
   Записано в [[2022-1m-data-gap-symptom-year-missing]].

2. **Multi-bar pattern detection требует waiting period.** Detect at trigger
   time + waited N bars → entry на confirm_idx. Иначе типичный inflation
   +10-15pp WR (etap_31 lookahead vs etap_33 honest).

3. **Заявленные результаты сложных стратегий обычно overfit.** 4-stage
   cascade + custom RR + 3y window + узкий SL = recipe для inflated
   backtest, который live развалится. Strategy 1.1.1 — case study.

4. **WR>60% на сотнях крипто-сделок = первый кандидат на проверку lookahead.**
   Третий случай за исследование (etap_14, etap_31, 1.1.1).

5. **Combined filter stacking (T1+T2+T3) — overfit catastrophe.** Книги
   обычно описывают фильтры по очереди, не одновременно. Применять отдельно.

6. **Простота побеждает.** C2 (2 уровня) бьёт 1.1.1 (4 уровня) в 3.5× по
   total_R и по всем 7 критериям.

## Открытые задачи

- [ ] OOS: запустить C2 на ETHUSDT, SOLUSDT
- [ ] Walk-forward: rolling 4y train / 6mo test для C2
- [ ] Re-baseline остальных research-стратегий (1.1.2, 1.1.3, 1_2_0)
  на anchor-confirm fix — возможно тот же класс bug
- [ ] Live-implementation C2 в strategies/strategy_*.py + tests + scanner
- [ ] Тест C2 sensitivity: 6h/3h, 8h/2h, 6h/1h комбинации
- [ ] Тест min_sl ∈ [0.7%, 1.0%, 1.5%] для C2 — может ли быть лучше?

## Артефакты

PDF reports в `research/elements_study/output/`:
- `etap16_strategies_report.pdf` (12 стр) — журнал исследования
- `etap21_FINAL_RECOMMENDATIONS.pdf` (8 стр) — top-3 финальные
- `etap26_ULTIMATE_FINAL_REPORT.pdf` (15 стр) — capstone, со всеми deepdive

Скрипты: etap_14 .. etap_34 в `research/elements_study/`.

## Связи

- [[2022-1m-data-gap-symptom-year-missing]] — критический pitfall
- [[multi-bar-pattern-confirm-vs-trigger-lookahead]] — pitfall #2
- [[7-criteria-of-good-strategy]] — критерии оценки
- [[strategy-c2-ob-6h-fvg-2h-pro-rr1]] — спецификация C2
- [[strategy-1-1-1-honest-audit-failed]] — почему 1.1.1 не оправдывает себя
- [[lookahead-anchor-confirm-окно-cur_open-cur_close]] — связанный pitfall
