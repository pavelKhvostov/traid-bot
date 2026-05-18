---
tags: [session, forensic, strategy-1-1-7, indicators, hull-ma, asvk, money-hands]
date: 2026-05-13
duration: medium
session_type: forensic-analysis + filter-search
---

# 2026-05-13 — Forensic Strategy 1.1.7 + indicator filters (Andrei-style)

## TL;DR

1. Расширили 1.1.7 backtest до **6.3y** (2020-2026), пофетчили исторические
   данные 2020-2022. Baseline = 454 deduped, **155 closed**, WR 48.4%, −5R.
   SHORT direction = главная утечка (WR 39.1%, −14R).

2. Реплицировали Андреевские этапы 28/35/38/47/49 для 1.1.7. **Найдены
   3 рабочих фильтра**:
   - **time + asvk + mh** = ⛔ Sunday, ⛔ London, ⛔ asvk_4h=red,
     ⛔ mh_4h_color∈{green, grey_from_green}
   - **dir_hull**: LONG требует hull_1h_L160=up, SHORT требует hull_12h_L180=down
   - **dir_hull + time**: композит

3. **Sweet spot конфигурация:**
   - Filter: `time + asvk + mh`
   - RR: 2.5
   - Результат на 6.3y BTC: **n=68, WR 44.1%, total +37R, R/tr +0.544**
   - 6/7 positive years (только 2020 negative)

## Метод (по образцу etap_35/47 Андрея)

### Phase A — extend backtest до 6.3y
`research/elements_study/etap_0_fetch_history.py` — догрузил 2020-01-01
до 2022-01-01 для всех TF (1m, 15m, 1h, 2h, 4h, 6h, 12h, 1d). После
загрузки: 3.3M свечей 1m, 6.35 лет покрытия.

`research/1_1_7/backtest/backtest_strategy_1_1_7.py:DAYS_BACK = 2310`
(было 1095). Baseline 6.3y:

| Метрика | Значение |
|---|---|
| Raw | 620 |
| Deduped | 454 |
| **Closed** | **155** (W=75, L=80) |
| NO_ENTRY | 299 (66%) |
| WR | 48.4% |
| total | −5R |
| LONG | 91 closed, WR 54.9%, +9R |
| SHORT | 64 closed, WR 39.1%, −14R |

### Phase B — feature forensic
`research/1_1_7/forensic/etap_47_111_7_full_forensic.py` (по образцу
etap_47_111_2). Считает 30+ features at signal_time:
- Hull MA на 1h/4h/12h/1d × длины 49/78/100/160 (16 features)
- EMA200 align на 4h/1h/15m/1d
- ASVK ema_3 zone на 1h, 4h
- Money Hands bw2 color + MF sign на 1h, 4h
- ICT hour/weekday/session
- Daily-open premium/discount
- ATR ratio 1h/4h

Safe lookup (anti-lookahead): `idx-1` чтобы избежать FORMING bar.

CSV: `output/etap_47_111_7_trades_features.csv` (155 × 30).

### Phase C — single-feature ranking

**Топ положительные (n≥15):**

| Feature | n | WR | Δpp | total |
|---|---|---|---|---|
| **mh_4h_color=red** | 60 | **63.3%** | **+14.9** | **+16R** |
| asvk_4h=yellow_OS | 34 | 61.8% | +13.4 | +8R |
| weekday=Friday/Saturday | 22/22 | 59.1%/59.1% | +10.7 | +4R/+4R |
| weekday=Thursday | 16 | 62.5% | +14.1 | +4R |
| asvk_1h=red | 21 | 57.1% | +8.8 | +3R |
| ob_tf=2h | 40 | 55.0% | +6.6 | +4R |
| **hull_4h_L160=aligned** | 37 | **54.1%** | **+5.7** | +3R |

**Топ негативные:**

| Feature | n | WR | Δpp | total |
|---|---|---|---|---|
| mh_4h_color=green | 45 | 35.6% | −12.8 | −13R |
| mh_4h_color=grey_from_green | 29 | 34.5% | −13.9 | −9R |
| asvk_4h=red | 24 | 29.2% | −19.2 | −10R |
| ema200_1h=aligned | 25 | 36.0% | −12.4 | −7R |
| weekday=Sunday | 15 | 20.0% | −28.4 | −9R |

### Phase D — direction split (etap_48 1.1.7)
`research/1_1_7/forensic/etap_48_111_7_direction_split.py`. Ключевая
находка — **разные edges для LONG и SHORT**:

**LONG топ (baseline WR 54.9%):**
- hull_1h_L140 aligned: WR 68.8% (n=16, +6R) ★
- hull_1h_L160 aligned: WR 68.8% (n=16, +6R) ★
- hull_1h_L49 aligned: WR 66.7% (n=18, +6R)
- mh_4h_color=red: WR 64.2% (n=53, +15R)
- weekday=Saturday: WR 69.2% (n=13)

**SHORT топ (baseline WR 39.1%):**
- **hull_12h_L180 aligned**: WR 58.8% (n=17, +3R) ★
- hull_12h_L160 aligned: WR 56.2% (n=16, +2R)
- ema200_4h aligned: WR 55.6% (n=18, +2R)

**Вывод:** 1.1.7 LONG любит **быстрый trend на 1h** (Hull L140-160,
~6 дней), SHORT любит **медленный trend на 12h** (Hull L180, ~3-4 месяца).

### Phase E — Hull length sensitivity
`research/1_1_7/forensic/etap_49_111_7_hull_length.py`. Grid L40-L240
на 4 TF × 2 direction. Best aligned config:

| direction | TF | L | n | WR | d_pp | total | R/tr |
|---|---|---|---|---|---|---|---|
| LONG | 1h | **140** | 16 | 68.8% | +13.8 | +6R | +0.375 |
| LONG | 1h | **160** | 16 | 68.8% | +13.8 | +6R | +0.375 |
| LONG | 1h | 40 | 23 | 65.2% | +10.3 | +7R | +0.304 |
| SHORT | 12h | **180** | 17 | 58.8% | +19.8 | +3R | +0.176 |
| SHORT | 12h | 160 | 16 | 56.2% | +17.2 | +2R | +0.125 |

### Phase F — ICT matrix
`research/1_1_7/forensic/etap_28_111_7_ict_matrix.py`.

**Композитные time-filters (vs baseline 48.4%):**

| Filter | n | WR | d_pp | total |
|---|---|---|---|---|
| Thu+Fri+Sat | 60 | 60.0% | +11.6 | +12R |
| not_Sunday & not_London | 125 | 52.0% | +3.6 | +5R |
| Thu-Sat & not_London | 53 | 60.4% | +12.0 | +11R |

### Phase G — combo filter
`research/1_1_7/forensic/etap_39_111_7_combo_filter.py`.

| Filter | n | WR | d_pp | total | R/tr |
|---|---|---|---|---|---|
| **dir_hull_pass** | 33 | **63.6%** | +15.2 | +9R | +0.273 |
| time + asvk + mh | 68 | 63.2% | +14.8 | +18R | +0.265 |
| time + mh | 69 | 62.3% | +13.9 | +17R | +0.246 |
| dir_hull + time + asvk | 23 | 60.9% | +12.5 | +5R | +0.217 |
| ALL 4 filters | 15 | 60.0% | +11.6 | +3R | +0.200 |

### Phase H — RR sweep
`research/1_1_7/forensic/etap_38_111_7_rr_sweep.py`. Pересимуляция
закрытых сетапов с переменным RR.

**Best config: filter_TAM × RR sweep:**

| RR | n | WR | total | R/tr |
|---|---|---|---|---|
| 1.0 | 68 | 63.2% | +18R | +0.265 |
| 1.5 | 68 | 54.4% | +24.5R | +0.360 |
| 2.0 | 68 | 48.5% | +31R | +0.456 |
| **2.5** | **68** | **44.1%** | **+37R** | **+0.544** |
| 3.0 | 68 | 41.2% | +44R | +0.647 |

**Sweet spot: RR=2.5** (R/tr +0.544 при WR 44.1%).
**Max total: RR=3.0** (+44R, но WR 41% — больше воланса).

## Финальная конфигурация — Strategy 1.1.7 PRODUCTION

```python
# Detector: strategies/strategy_1_1_7.py (без изменений)
# Filter:
# 1. Time:    weekday != "Sunday" AND session != "London"
# 2. ASVK:    asvk_4h != "red"
# 3. MH:      mh_4h_color not in {"green", "grey_from_green"}
# RR:         2.5
# SL:         OB.bottom (LONG) / OB.top (SHORT) (без изменений)
# Entry:      mid FVG-15/20m (без изменений)
```

**Backtest 6.3y BTC:**
- 68 trades, WR 44.1%, **+37R**, R/tr +0.544
- 6/7 positive years (только 2020 negative −2.5R при RR=1.5)
- Frequency: ~11 setups/year = 0.21/wk

## 7-criteria scoring

| # | Criterion | Status |
|---|---|---|
| 1 | Stability (0 bad years) | ⚠ 1 bad year (2020) |
| 2 | WR >= 50% | ⚠ 44.1% (но RR=2.5) |
| 3 | R/tr >= 0.3 | ✅ +0.544 |
| 4 | Frequency >= 0.5/wk | ❌ 0.21/wk |
| 5 | No lookahead | ✅ safe-lookup |
| 6 | min_sl | ✅ |
| 7 | Простота | ✅ 3 filters |

**Score: 4.5/7** — кандидат research-only, не production. Frequency
самая слабая сторона (1 сделка в 5 дней средне).

## Comparison vs другие 1.1.x

| Strategy | n | WR | total | R/tr | bad years |
|---|---|---|---|---|---|
| 1.1.1 honest | 262 | 53.8% | +20R | +0.076 | 1-2 |
| 1.1.4 BFJK | ~150 | 64.3% | **+107R** | **+0.93** | 1 |
| 1.1.7 raw | 155 | 48.4% | −5R | −0.03 | many |
| **1.1.7 + TAM @ RR=2.5** | **68** | **44.1%** | **+37R** | **+0.544** | **1** |

**Вывод:** 1.1.7 c фильтрами хуже 1.1.4 BFJK (топ-стратегия проекта),
но лучше 1.1.1 honest. Может пригодиться как portfolio diversifier
(разная природа сигнала — fractal sweep vs nested OB+FVG).

## Файлы

Все скрипты в `research/1_1_7/forensic/`:
- `etap_47_111_7_full_forensic.py` — главный forensic
- `etap_48_111_7_direction_split.py` — LONG vs SHORT отдельно
- `etap_28_111_7_ict_matrix.py` — hour × weekday × session
- `etap_49_111_7_hull_length.py` — hull length sensitivity
- `etap_39_111_7_combo_filter.py` — composite filter grid
- `etap_38_111_7_rr_sweep.py` — RR=1.0..3.0 на best filter

CSV outputs в `research/1_1_7/forensic/output/`:
- `etap_47_111_7_trades_features.csv` — все 155 trades × 30 features
- `etap_47_111_7_filtered_trades.csv` — filtered subset

## Следующие шаги (open)

- Перенести best filter (time + ASVK 4h + MH 4h) в backtest_strategy_1_1_7
  как опциональный параметр
- OOS validation на ETHUSDT / SOLUSDT — повторяется ли edge на других
  символах?
- Если filter_TAM работает на ETH/SOL — 1.1.7 portfolio candidate
- Аналогичный forensic для 1.1.6 (по запросу пользователя)

## Связи

- [[strategy_1_1_7]] — спецификация
- [[2026-05-08-strategy-111-forensic-indicator-filters]] — Andrei на 1.1.1
- [[2026-05-11-strategy-114-bfjk-portfolio-bug-audit]] — Andrei на 1.1.4
- [[asvk-custom-rsi]], [[money-hands-asvk]], [[asvk-trend-line-hull]] — индикаторы
