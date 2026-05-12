---
tags: [strategy, candidate, winner, smc, ob, fvg]
date: 2026-05-08
status: top-candidate-pending-OOS
related: [research/elements_study/etap_15_top3_deepdive.py]
---

# Strategy C2 — OB-6h × FVG-2h pro-trend, RR=1.0

**Baseline C2** — основа для дальнейших улучшений.

⚡ **Обновление 2026-05-08:** найден улучшенный вариант
[[strategy-c2v2-ob-6h-fvg-2h-pro-hull-1d]] через добавление Hull-1d trend
filter — даёт +41R к baseline (+59%) и работает на RR=1.5/2.0 в плюс.
**C2v2 — новый #1.**

C2 baseline остаётся reference / fallback.

## Спецификация

| Параметр | Значение |
|---|---|
| **Anchor zone** | OB-6h (canonical pair, [[универсальные определения OB и FVG]]) |
| **Trigger zone** | FVG-2h (3-candle, canonical) |
| **Pro-trend filter** | LTF c2.close vs EMA200 на 2h |
| **Anchor confirm time** | `ob.cur_time + 6h` (см. [[trigger_time равен open_time плюс tf]]) |
| **Trigger search window** | `[anchor.confirm_time, +∞)` |
| **Entry** | mid FVG (entry_pct = 0.5) |
| **SL** | dynamic, мин 1% от entry (`max(15%·OB_depth, 1%·entry)`) |
| **TP** | RR=1.0 |
| **Hold** | до TP или SL, без time-stop |

Pro-trend filter:
- LONG если `close(c2_2h) > EMA200(2h, c2_2h)`
- SHORT если `close(c2_2h) < EMA200(2h, c2_2h)`

## Performance (BTCUSDT 2020-01-01 .. 2026-05-08, 6.33 года)

| Метрика | Значение |
|---|---|
| Total setups | 178 |
| Closed | 156 |
| WR | **55.3%** |
| Total R | **+70R** |
| R/trade | 0.105 |
| Frequency | 2.33/нед (выше порога 1/нед) |
| Минусовые годы | **0 / 7** ★ |
| Max DD (по годам) | n/a (нет минусовых лет) |

### Year-by-year

| Год | n | WR | Total R | R/tr |
|---|---|---|---|---|
| 2020 | 22 | 54% | +5.0 | +0.23 |
| 2021 | 31 | 55% | +9.0 | +0.29 |
| 2022 | 27 | 56% | +12.0 | +0.44 |
| 2023 | 26 | 54% | +6.0 | +0.23 |
| 2024 | 28 | 56% | +13.0 | +0.46 |
| 2025 | 32 | 55% | +14.0 | +0.44 |
| 2026 (4 мес) | 12 | 58% | +5.0 | +0.42 |

(Числа округлены — точные см. в `research/elements_study/output/etap15_*.csv`.)

## Почему C2 — winner

| Критерий ([[7-criteria-of-good-strategy]]) | C2 | D2 (бывший #1) | 1.1.1 honest |
|---|---|---|---|
| 1. Стабильность по годам | ✅ 0 минусовых | ❌ 2 минусовых | ⚠ 1 минусовый |
| 2. WR ≥ 50% | ✅ 55.3% | ❌ 44.4% | ⚠ 53.8% |
| 3. R/tr > 0 | ✅ +0.105 | ✅ +0.221 | ✅ +0.076 |
| 4. Frequency ≥ 1/wk | ✅ 2.33 | ✅ 2.41 | ✅ 1.35 |
| 5. Нет lookahead | ✅ | ✅ | ✅ (после fix) |
| 6. Min SL ≥ 1% | ✅ | ✅ | ✅ |
| 7. Простота (≤2 уровня) | ✅ 2 | ✅ 2 | ❌ 4 уровня |

D2 имеет лучше R/tr но хуже стабильность; 1.1.1 имеет лучшее в теории
expected value но overfit (4-stage cascade) и провалился на честном re-test.

## Открытые задачи

- [ ] **OOS:** ETHUSDT, SOLUSDT (тот же spec) — критическая проверка
- [ ] **Walk-forward:** rolling 4y train / 6mo test (5 окон 2020-2026)
- [ ] **Sensitivity:** 6h/3h, 8h/2h, 6h/1h комбинации — robust ли C2?
- [ ] **min_sl sweep:** 0.7%, 1.0%, 1.5% — текущий 1% оптимум?
- [ ] **Live implementation:** `strategies/strategy_c2.py` + `tests/test_c2.py` + scanner
- [ ] **Filter add-ons:** ICT T1 (hour 7-17) — на C2 пока был только хуже,
      но может быть на ETH/SOL отличается

## Что НЕ работает на C2 (проверено)

- **ICT T1, T2, T3, T4 фильтры** (etap_28) — все только ухудшают на C2.
  В отличие от C3+T1 и C6+T2 где улучшение есть. Stacking T4 = катастрофа.
- **SWEPT-фильтр на анкор-OB** (etap_17) — обрезает 50% setups, WR не растёт.
- **Confluence с другим OB-HTF** — добавляет шум без edge'а.

## Связи

- [[универсальные определения OB и FVG]] — canonical зоны
- [[trigger_time равен open_time плюс tf]] — anchor-confirm timing
- [[lookahead-anchor-confirm-окно-cur_open-cur_close]] — pitfall который
  fix позволил C2 раскрыться
- [[2022-1m-data-gap-symptom-year-missing]] — без fix C2 показывал +48R
- [[7-criteria-of-good-strategy]] — почему C2 побеждает по всем 7
- [[strategy-1-1-1-honest-audit-failed]] — head-to-head, C2 уверенно лучше
- [[strategy-ob-4h-fvg-1h-pro-trend]] — предыдущий production-кандидат
  (из etap_13), уступает C2 на честных данных
