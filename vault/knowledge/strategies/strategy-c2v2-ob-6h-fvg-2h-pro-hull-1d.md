---
tags: [strategy, candidate, smc, ob, fvg, hull-ma, btc-only]
date: 2026-05-08
status: BTC-specific-edge-confirmed-fails-OOS-on-ETH
related: [research/elements_study/etap_36_c2_filter_overlay.py, research/elements_study/etap_37_c2v2_audit_oos.py]
---

# Strategy C2v2 — OB-6h × FVG-2h pro × Hull-1d trend

⚠ **Status update 2026-05-08 (после audit + OOS):**
1. Найден lookahead bug в etap_36 — magnitudes inflated на ~+35R (53%).
   См. [[htf-lookup-must-use-last-closed-bar-not-forming]].
2. **OOS на ETH провалился катастрофически** (4/4 bad years).
3. **OOS на SOL частично работает** (+37R RR=1.5, 1/4 bad year).
4. После audit: BTC всё ещё показывает edge поверх baseline C2, но
   скромнее заявленного (+13R RR=1.5 vs +50R inflated).

**Verdict:** C2v2 — **BTC-specific edge**, не universal. Не годится для
multi-symbol live deploy.

**Улучшенный C2** через добавление Hull MA(78) на 1d trend filter.
Найден etap_36, audited в etap_37.

## Honest results (etap_37 audit + OOS)

### BTC (in-sample) после lookahead fix

| RR | n_closed | WR | Total R | R/tr | Bad years | vs baseline |
|---|---|---|---|---|---|---|
| 1.0 | 406 | 59.4% | **+76R** | +0.187 | 1/7 | +6R |
| 1.5 | 399 | 46.6% | **+66R** | +0.165 | 1/7 | +13.5R |
| 2.0 | 378 | 37.6% | **+48R** | +0.127 | 1/7 | +13R |

C2 baseline на BTC: RR=1.0 +70R / RR=1.5 +52.5R / RR=2.0 +35R.

**Edge есть** (+13R при RR>1), но:
- 2021 стал минусовым (-2.5R) — потерян «0 bad years» статус
- Frequency упала до 1.56/wk (было 2.33)

### ETH OOS (4.33y) — catastrophic

| RR | n_closed | WR | Total R | Bad years |
|---|---|---|---|---|
| 1.0 | 182 | 46.7% | **−12R** | 3/4 |
| 1.5 | 175 | 33.1% | **−30R** | **4/4** |
| 2.0 | 168 | 27.4% | **−30R** | 3/4 |

ETH baseline тоже weak (+2 / -16 / -36R), но filter ухудшает.

### SOL OOS (4.33y) — partial work

| RR | n_closed | WR | Total R | Bad years |
|---|---|---|---|---|
| 1.0 | 199 | 56.8% | +27R | 1/4 |
| 1.5 | 198 | 47.5% | **+37R** ⭐ | 1/4 (2023 -10.5) |
| 2.0 | 198 | 37.4% | +24R | 1/4 |

SOL baseline: +15 / +22.5 / +24R. Filter добавляет +12-15R на RR=1.0/1.5.

### Sum across symbols (RR=1.5 sweet spot)

| Symbol | C2 baseline | C2v2 SAFE | Δ |
|---|---|---|---|
| BTC | +52.5R | +66R | +13.5R |
| ETH | -16R | -30R | **-14R** |
| SOL | +22.5R | +37R | +14.5R |
| **Total** | +59R | +73R | +14R |

**Net positive only by +14R across 3 symbols. ETH active drag.** Original
inflated claim (+101R BTC alone) was misleading.

### Lookahead inflation breakdown

| Symbol/RR | Buggy (etap_36) | Safe (etap_37) | Inflation |
|---|---|---|---|
| BTC RR=1.0 | +111R | +76R | +35R (46%) |
| BTC RR=1.5 | +101R | +66R | +35R (53%) |
| BTC RR=2.0 | +87R | +48R | +39R (81%) |

См. [[htf-lookup-must-use-last-closed-bar-not-forming]] — pitfall fully
described.

## Спецификация

| Параметр | Значение |
|---|---|
| **Anchor zone** | OB-6h (canonical pair) |
| **Trigger zone** | FVG-2h |
| **Pro-trend gate (existing)** | LTF c2.close vs EMA200 на 2h |
| **NEW: Trend gate** | Hull MA(78) на 1d aligned with direction |
| **Anchor confirm time** | `ob.cur_time + 6h` |
| **Trigger search window** | `[anchor.confirm_time, anchor.cur_time + 10d]` |
| **Entry** | mid FVG (entry_pct = 0.5) |
| **SL** | dynamic, мин 1% от entry (`max(15%·OB_depth, 1%·entry)`) |
| **TP** | RR=1.0 / 1.5 / 2.0 — все работают |
| **Hold** | до TP или SL, max 3 дня |

### Hull-1d trend filter (формальное правило)

```python
# Pre-compute on 1d data
hull_1d = HMA(close_1d, 78)  # length=49 * 1.6 default
# At signal_time (FVG-2h c2.close):
#   - lookup hull_1d as-of signal_time
#   - lookup close_1d (last closed 1d bar) as-of signal_time
#   - hull_value_at_minus_2 = hull_1d[idx - 2]  (Pine SHULL)
trend_up = close_1d > hull_1d[idx - 2]
# Filter:
if direction == "LONG" and not trend_up: skip
if direction == "SHORT" and trend_up: skip
```

## Year-by-year @ RR=1.5 (best edge × stability)

| Год | n | WR | Total R | R/tr |
|---|---|---|---|---|
| 2020 | 49 | 53.1% | +16.0 | +0.327 |
| 2021 | 63 | 42.9% | +4.5 | +0.071 |
| 2022 | 83 | 47.0% | +14.5 | +0.175 |
| 2023 | 94 | 48.9% | +21.0 | +0.223 |
| 2024 | 62 | 45.2% | +8.0 | +0.129 |
| 2025 | 80 | **56.2%** | **+32.5** | **+0.406** |
| 2026 (4мес) | 18 | 50.0% | +4.5 | +0.250 |

**Все 7 лет в плюс на RR=1.5.** 2025 особенно силён (+32.5R на 80 trades).

## Почему именно Hull-**1d** (не 4h)?

**Сюрприз:** на C2 `hull_4h_align == aligned` показал WR -1.3pp (хуже!),
тогда как на 1.1.1 это была лучшая фича (+13.6pp).

| Strategy | Anchor TF | Best Hull TF | Δ WR |
|---|---|---|---|
| 1.1.1 (4-stage) | 1d, 12h | **4h** | +13.6pp |
| C2 (2-stage) | **6h** | **1d** | +6.8pp |

**Гипотеза:** Hull добавляет максимальный edge когда он на TF выше чем
anchor. C2 anchor = 6h, поэтому Hull-4h слишком близко к anchor (redundant
информация); Hull-1d = новая макро-инфо.

Для 1.1.1 anchor уже 1d/12h, поэтому Hull-4h ниже = добавляет swing-trend
который не покрыт макро-anchor'ом.

**Универсальная эвристика:** для any pro-trend filter — выбирать TF
**на 1-2 ступени выше anchor TF**.

## Counter-trend паттерн на entry TF (counterintuitive)

На C2:
- `ema200_1h counter` → WR 65.8% (+10.5pp), +23R
- `ema200_15m counter` → WR 61.9% (+6.6pp), +38R

Объяснение: внутри **macro trend (Hull-1d)** mean-reversion на entry TF —
это natural pullback момент. EMA200(1h) counter = «цена против короткого
тренда, но в сторону macro» = классический pullback entry.

Эту фичу пока **НЕ включаем** в C2v2 — может overfit. Но интересно для
дальнейших экспериментов.

## Что НЕ сработало на C2 (хотя на 1.1.1 работало)

- **Hull 4h aligned** — flat (-1.3pp)
- **DO discount** — отрицательный (-4.3pp)
- **MH MF aligned** — flat (+0.9pp)
- **ICT London/NY** — отрицательный (-1.8pp)
- **Score≥3 / score≥4** — отрицательные

→ **Урок:** filter-findings на одной стратегии **НЕ переносятся
автоматически** на другую. Каждой стратегии — свой forensic.

## 7 criteria (после audit + OOS)

| Критерий ([[7-criteria-of-good-strategy]]) | BTC SAFE | ETH SAFE | SOL SAFE |
|---|---|---|---|
| 1. Стабильность по годам | ⚠ 1/7 bad | ❌ 4/4 bad | ⚠ 1/4 bad |
| 2. WR ≥ 50% | ⚠ 46.6% RR=1.5 | ❌ 33.1% | ⚠ 47.5% |
| 3. R/tr > 0 | ✅ +0.165 RR=1.5 | ❌ -0.171 | ✅ +0.187 |
| 4. Frequency ≥ 1/wk | ✅ 1.56/wk | ✅ 1.46/wk | ✅ 1.45/wk |
| 5. No lookahead | ✅ (после fix) | ✅ | ✅ |
| 6. Min SL ≥ 1% | ✅ | ✅ | ✅ |
| 7. Простота | ✅ | ✅ | ✅ |

- **BTC: 5/7** (criteria 1, 2 marginal)
- **ETH: 3/7** (full fail)
- **SOL: 5/7** (criteria 1, 2 marginal)

Не проходит 7/7 ни на одном символе. Original C2 baseline на BTC даёт
6/7 (single bad criterion: 2 — баланс не идеальный).

## Открытые задачи (новые, после audit)

- [x] ✅ **OOS validation:** ETHUSDT провалилась, SOLUSDT marginal-positive
- [x] ✅ **Lookahead audit:** найден bug, fixed → magnitudes -35R inflation
- [ ] **Re-run etap_35 forensic с safe lookup** — magnitudes на 1.1.1
      тоже inflated, насколько?
- [ ] **Walk-forward:** 4y train / 6mo test BTC для проверки stability
- [ ] **Понять почему ETH не работает:** другая dynamics? Несинхронность
      с BTC 1d trend? Может test Hull-1d на BTC-1d (использовать BTC как
      anchor для ETH trades)?
- [ ] **Hull length sensitivity:** 49, 78, 100, 160 — robust ли default?
- [ ] **Hull mode:** HMA vs EHMA vs THMA
- [ ] ❌ **Live implementation отложен** — не до OOS-fix-up

## Сравнение с другими кандидатами (после audit, BTC only)

| # | ID | Setup | RR | WR | Total R | R/tr | Bad yrs | OOS |
|---|---|---|---|---|---|---|---|---|
| 🥇 | **C2 baseline** | OB-6h × FVG-2h pro | 1.0 | 55.3% | +70R | 0.105 | **0/7** | ⚠ TBD |
| 2 | C2v2 SAFE BTC | + Hull-1d | 1.5 | 46.6% | +66R | 0.165 | 1/7 | ❌ ETH |
| 3 | C2v2 SAFE BTC | + Hull-1d | 1.0 | 59.4% | +76R | 0.187 | 1/7 | ❌ ETH |
| ❌ | C2v2 BUGGY (etap_36) | + Hull-1d | 1.5 | 49.0% | ~~+101R~~ | ~~0.225~~ | ~~0/7~~ | (lookahead) |
| 🥈 | C2v2 RR=1.0 | same | 1.0 | 62.1% | +111R | 0.242 | 0 |
| 🥉 | C2v2 RR=2.0 | same | 2.0 | 40.1% | +87R | 0.204 | 1 |
| 4 | C2 baseline | OB-6h × FVG-2h pro | 1.0 | 55.3% | +70R | 0.105 | 0 |
| 5 | D1 | OB-12h × FVG-2h pro [opt] | 2.5 | 36.1% | +92.5R | 0.263 | 1 |
| 6 | D2 | OB-12h × FVG-2h pro [opt] | 1.75 | 44.4% | +81.2R | 0.221 | 2 |
| ❌ | 1.1.1 honest | 4-stage cascade | 1.0 | 53.8% | +20R | 0.076 | 1 |

**C2v2 RR=1.5 — новый абсолютный winner** по сочетанию edge × stability ×
frequency × R-multiple.

## Связи

- [[strategy-c2-ob-6h-fvg-2h-pro-rr1]] — baseline C2
- [[asvk-trend-line-hull]] — Hull MA(78) спецификация
- [[2026-05-08-strategy-111-forensic-indicator-filters]] — откуда взялась
  идея проверить Hull на C2
- [[7-criteria-of-good-strategy]] — все 7 ✅
- [[strategy-1-1-1-honest-audit-failed]] — почему filter findings нельзя
  слепо переносить
- `research/elements_study/etap_36_c2_filter_overlay.py` — full source
- `research/elements_study/output/etap36_trades_c2_features.csv` — 664 trades
  с 14 features (для дальнейшего ML)
