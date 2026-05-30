---
tags: [session, i-rdrb, fvg, evot, vwap, fl, sl-optimization, feature-mining]
date: 2026-05-24
status: done
related: [[2026-05-23-smc-lib-vwap-entry-experiments]], [[i-rdrb fvg митигация зоны 1h btc eth]], [[i-rdrb-v1-fvg-f1-f2-f3-strategy-257-setups-wr72]], [[vic-asvk-indicator-python]]
---

# 2026-05-24 — i-RDRB+FVG: EVoT / VWAPs ASVK / 15m FL / 15m RDRB / SL-grid optimization

Продолжение [[2026-05-23-smc-lib-vwap-entry-experiments]]. В фокусе — feature mining на 239 LONG WIN сделках i-RDRB+FVG (BTC 1h, 6y baseline +112R / 57% WR) с целью найти структурные предикторы. Также VWAPs ASVK как фильтр (не как entry).

## Baseline (для контекста)

BTC 1h 6y, i-RDRB+FVG:
- 808 паттернов, 798 trades с fill (98.8%)
- 392 LONG: 239 WIN / 153 LOSS — **WR 60.97%, ΣR +86R**
- 388 SHORT: 203 WIN / 185 LOSS — WR 52.32%, ΣR +18R
- TOTAL: WR 57.02%, ΣR **+112R**, R/tr +0.140

## 1. EVoT (ASVK ViC maxV) внутри окна паттерна

Источник: [[vic-asvk-indicator-python]]. Для каждого LONG-паттерна посчитан maxV в диапазоне C1-C5 close (1m granularity, LTF auto для 1h chart = 1m).

### EVoT direction (внутри паттерна)

| Side / direction | n | WR% | ΣR | R/tr |
|---|---:|---:|---:|---:|
| LONG, EVoT=BULL | 234 | 59.40 | +44 | +0.188 |
| LONG, EVoT=BEAR | 158 | **63.29** | +42 | +0.266 |
| SHORT, EVoT=BULL | 145 | **49.66** ↓ | −1 | −0.007 |
| SHORT, EVoT=BEAR | 243 | 53.91 | +19 | +0.078 |

**Direction matching гипотеза опровергнута** (двух-example bias). На полной выборке `LONG+BEAR` чуть лучше `LONG+BULL` (контринтуитивно).

### EVoT by time bucket (LONG)

Чем раньше maxV в паттерне, тем выше WR — bears выгрузили объём рано, реверс надёжнее:

| MaxV в | n | WR% |
|---|---:|---:|
| C1 | 37 | **64.86** |
| C2 | 116 | **65.52** |
| C3 | 44 | 63.64 |
| C4 | 119 | 57.98 |
| C5 | 76 | 55.26 |

### EVoT by distance from entry (LONG, R-units)

**Бимодальное распределение:**

| Distance | n | WR% | ΣR | R/tr |
|---|---:|---:|---:|---:|
| **≤ −0.5R (deep below)** | 106 | **66.98** ⬆ | +36 | **+0.340** |
| (−0.5, −0.2) | 39 | 48.72 | −1 | −0.026 |
| (−0.2, 0) | 19 | 47.37 | −1 | −0.053 |
| **≥ 0 (выше entry)** | 84 | **66.67** ⬆ | +28 | +0.333 |

maxV "глубоко под entry" OR "выше entry" → ~67% WR. "Под, но близко" (-0.5..0) → 47-48% anti-edge.

### **🎯 Главная находка — R/ATR(14, 1h) sweet spot**

| R/ATR bucket | n | WR% | ΣR | R/tr | Δprec |
|---|---:|---:|---:|---:|---:|
| <0.5 | 192 | 49.48 | −2 | −0.010 | **−7.19** ↓ |
| **[0.5, 0.85)** | **305** | **63.28** ⬆ | **+81** ⬆ | **+0.266** | **+6.61** ⬆ |
| [0.85, 1.1) | 121 | 52.89 | +7 | +0.058 | −3.77 |
| [1.1, 1.5) | 88 | 53.41 | +6 | +0.068 | −3.26 |
| ≥1.5 | 74 | 58.11 | +12 | +0.162 | +1.44 |

**305 трейдов (39% выборки) дают +81R из +104R total (78% всего edge)**. Независимо переоткрыт фильтр из [[i-rdrb-v1-pattern]] (R/ATR ∈ [0.55, 1.03]) — подтверждение, что это core driver edge.

## 2. VWAP от FH/FL 4h (pre-pattern)

Гипотеза: VWAPs якорятся от ближайших pre-C1 fractal highs/lows на 4h. VWAP-FL для LONG-патернов часто работает как target/resistance.

### Reference example 2026-05-19 LONG (WIN)

- FH 4h: 2026-05-19 03:00 MSK при 77414.62
- FL 4h: 2026-05-17 03:00 MSK при 77721.19
- На exit (TP): VWAP-FH = 76805, VWAP-FL = 77047
- **TP = 77127 — почти совпадает с VWAP-FL** → VWAP-FL сработала как resistance/target

### Reference 2026-05-23 LONG (LOSS) — противоположная картина

- VWAP-FL на fill = 76837 (= **+4.88R над entry**)
- TP 75770 = на 1067 пунктов НИЖЕ VWAP-FL → недостижим
- Цена ушла к SL = LOSS

### Фильтр по distance VWAP-FL от entry (LONG)

| Bucket | n | WR% | ΣR | R/tr |
|---|---:|---:|---:|---:|
| [0, 1) R над entry | 88 | 65.91 | +28 | +0.318 |
| **[1, 2) R** | 53 | **67.92** ⬆ | +19 | **+0.358** |
| [2, 3) R | 20 | 55.00 | +2 | +0.100 |
| ≥ 3R (далеко) | 21 | **47.62** ↓ | −1 | −0.048 |

Лучший зона [1, 2)R над entry — 67.92% WR. Слишком далеко (≥3R) — anti-edge (TP недостижим).

## 3. 15m FL (Williams) в зоне [pattern_low, block.bottom]

**Правила валидного FL** (после уточнения user):
- Williams N=2 на 15m
- FL формируется ПОСЛЕ pattern_low по времени (`open_ts > pattern_low_ts`)
- FL.low СТРОГО выше pattern_low (`low > pattern_low`)
- Цена FL.low ∈ [pattern_low, 1h block.bottom]
- Confirmation `≤ C5 close`

### Распределение в 239 LONG WIN

| Кол-во FL | Winners | % |
|---:|---:|---:|
| **0** | **149** | **62.3%** |
| 1 | 83 | 34.7% |
| 2 | 7 | 2.9% |

Всего 97 валидных FL в WIN-сделках. Avg 0.41 FL/winner.

### 15m FL как support (на 90 winners с FL = 97 FL events)

| | n | % |
|---|---:|---:|
| FL.low УДЕРЖАЛ до TP | **69** | **71.1%** |
| FL.low ПРОБИТ до TP | 28 | 28.9% |

**FL.low удерживает в 71% случаев** в winning trades. Структурно надёжный support.

### FL.low как SL — тест

Не дал улучшения (наоборот, WR падает до 55%, ΣR −9R). Tighter SL теряет больше wins, чем экономит на losses. Но при fixed-$-risk sizing edge может быть.

## 4. Multi-TF bullish FVG в [pattern_low, block.bottom]

Условия: FVG сформирован в окне C1-C5, FVG.bottom ≥ pattern_low, FVG.top ≤ block.bottom, не митигирован до C5 close.

Mitigation auto-фильтрует pre-pattern_low FVG (C2's wick down неизбежно митигирует in-zone FVG, сформированные ранее).

### Counts в 239 LONG WIN

| TF | Winners с ≥1 FVG | % | Sum FVG events |
|---|---:|---:|---:|
| 15m | 67 | 28.0% | 74 |
| 20m | 51 | 21.3% | 55 |
| 30m | 28 | 11.7% | 28 |
| **Нет FVG ни на одном TF** | **154** | **64.4%** | — |
| Есть на ВСЕХ 3 TF | 17 | 7.1% | — |

### WR by TF

| TF | WITH FVG | WITHOUT FVG |
|---|---|---|
| 15m | 59.82% (+22R) | 61.43% (+64R) |
| 20m | 61.45% (+19R) | 60.84% (+67R) |
| 30m | **50.91% (+1R)** ↓ | **62.61% (+85R)** ⬆ |

**🎯 30m FVG в зоне = anti-edge для LONG.** WR падает с 62.61% до 50.91%.

**Composite anti-filter**: FVG ≥1 на ВСЕХ 3 TF = 37 trades, WR **45.95%**, ΣR **−3R**. Чистый mitigation magnet — цену тянет вниз закрывать FVG до TP.

## 5. 15m RDRB в зоне (через `~/smc-lib/elements/rdrb`)

| | Total 392 | WIN 239 | LOSS 153 |
|---|---:|---:|---:|
| Patterns с ≥1 15m RDRB в зоне | 168 (43%) | 101 (42.3%) | 67 (43.8%) |
| Total RDRB events | 202 | 119 | 83 |
| LONG-RDRB (direction) | 176 | 103 | 73 |
| SHORT-RDRB (direction) | 26 | 16 | 10 |

### 15m RDRB block.bottom — поведение в WIN vs LOSS

| | WIN (119 events) | LOSS (83 events) |
|---|---:|---:|
| block.bottom **ПРОБИТ** до TP/SL | 91 (76.5%) | **83 (100%)** |
| block.bottom **УДЕРЖАЛ** до TP | 28 (23.5%) | **0 (0%)** |

**Strong asymmetry**: 0% удержания в LOSS vs 23.5% в WIN. Если RDRB block.bottom держится до выхода — паттерн **гарантированно WIN** (в данных). Но это look-ahead.

**В 87 winners с ровно 1 RDRB**: 66 (75.9%) пробит до TP, 21 (24.1%) удержал.

### Late re-entry trap для RDRB.block.bottom как entry

Лимит at RDRB.block.bottom (vместо 0.5 block) **не работает** на 140 patterns с 1 RDRB:
- ΣR падает с +34R (baseline на subset) до +19R (−15R)
- WR падает с 62.14% до 39.57%

**Причина**: 76% fill, но многие — late fills ПОСЛЕ baseline TP. Цена дошла к TP, потом откатилась к RDRB.block.bottom (fill), потом упала к SL — LOSS. Лимит ловит уже отыгранную трендовую структуру.

## 6. SL Grid Optimization (на 239 baseline winners)

Entry неизменен (0.5 block). TP неизменен (entry + (entry − pattern_low) baseline). SL смещается между pattern_low и block.bottom с шагом.

| SL offset (от pl) | WIN | LOSS | WR% | avg RR/win | **ΣR (new R-units)** |
|---:|---:|---:|---:|---:|---:|
| **0.00 baseline** | 239 | 0 | 100% | 1.00 | **+239.0** |
| **0.10** | 234 | 5 | **97.91** | 1.10 | **+252.9** ⬆ |
| 0.15 | 226 | 13 | 94.56 | 1.16 | +249.6 |
| 0.20 | 218 | 21 | 91.21 | 1.23 | +246.7 |
| 0.30 | 199 | 40 | 83.26 | 1.39 | +235.9 |
| 0.40 | 193 | 46 | 80.75 | 1.59 | +261.6 |
| **0.50** | 179 | 60 | 74.90 | 1.87 | **+275.3** ⬆ |

### Два sweet spots

1. **SL offset 0.10 (conservative)**: только 5 wins → losses, WR 97.91%, ΣR +252.9R (+5.8% vs baseline). Минимальная цена за rounded edge.

2. **SL offset 0.50 (aggressive trend-rider)**: 60 wins → losses, WR 74.90%, но avg RR/win = 1.87 → ΣR +275.3R (+15% vs baseline).

3. **"Долина" 0.15-0.30**: meh — не экстремум ни WR, ни ΣR.

### Прочтение

ΣR в "new R-units" предполагает **fixed-$-risk sizing** (каждая сделка одинаковая по $ risk). Это стандарт professional trading. С fixed contract size результаты слабее.

## Ключевые выводы дня

1. **R/ATR(14) ∈ [0.5, 0.85) — самый сильный single-feature filter** (+6.6pp WR на 39% выборки, +81R из +104 base). Подтверждение фильтра из памяти [[i-rdrb-v1-pattern]].

2. **VWAP-FL 4h [1, 2)R над entry** — 67.92% WR на 53 trades.

3. **Multi-TF FVG в зоне = anti-edge**: чем больше TF, тем сильнее (30m alone WR 50.91%, all-3-TF WR 45.95%).

4. **15m FL.low — надёжный support** (71% удержание в WIN), но как SL не помогает.

5. **15m RDRB.block.bottom — НЕнадёжный support** (24% удержание в WIN), и как entry — late re-entry trap.

6. **SL offset 0.10 — низкорисковый upgrade** baseline (+5.8% ΣR при −2pp WR).

7. **SL offset 0.50 — agressive trend-rider** (+15% ΣR при −25pp WR). Психологически сложнее.

## Открытые направления

1. **Композит**: R/ATR ∈ [0.5, 0.85) ∩ EVoT C1/C2 ∩ VWAP-FL [1,2)R — узкий sniper-setup. Прогнать.
2. **SL offset 0.5 + RR=2**: tighter SL → можно поднять TP. Test ΣR на subset.
3. **Anti-filters**: убрать LONG паттерны с 30m FVG в зоне OR 3-TF FVG confluence (anti-edge).
4. **Walk-forward / OOS** split 2020-2023 vs 2024-2026 для top-фильтров.
5. **SHORT-side проработка** — фильтры и SL optim на LONG; SHORT остался baseline +21R.

## Артефакты

### Скрипты (`~/smc-lib/scripts/`)
- `forensic_winners_vs_losers.py` — full feature dump на 798 trades в `/tmp/i_rdrb_fvg_forensic_798.csv`
- `count_multi_tf_fvg_in_zone.py` — 15m/20m/30m FVG counts
- `count_15m_fl_in_zone.py` — Williams FL на 15m в зоне
- `count_15m_rdrb_in_zone.py` — RDRB на 15m в зоне
- `count_fl_broken_before_tp.py` — FL.low пробит/удержал до TP
- `count_15m_rdrb_pierced_before_tp.py` — RDRB block.bottom пробит/удержал
- `backtest_15m_rdrb_entry.py` — late re-entry trap demo
- `backtest_fl_low_as_sl.py` — FL.low как SL (хуже baseline)
- `optimize_sl_grid.py` — SL grid sweep на 392 LONG
- `sl_grid_on_239_wins.py` — SL grid на 239 baseline winners
- `compute_evot_pattern.py`, `compute_maxv_2026_05_19.py`, `compute_maxv_2026_05_23.py` — EVoT эталоны
- `backtest_maxv_direction_filter.py`, `backtest_evot_pattern_features.py` — EVoT-фильтры
- `backtest_fhfl_vwap_4h_filter.py` — VWAP-FH/FL 4h distance filter
- `plot_pattern_with_4_fl.py` — рендер паттерна с 4 FL
- `plot_fhfl_vwap_4h_2026_05_19.py`, `plot_fhfl_vwap_4h_2026_05_23.py` — VWAP 4h рендеры

### Графики (`~/Desktop/i-rdrb-charts/`)
- `pattern_4fl_15m_2025-12-24.png` — паттерн с 4× FL 15m
- `fhfl_vwap_4h_2026-05-19_long.png` — WIN с VWAP-FL touch на TP
- `fhfl_vwap_4h_2026-05-23_long.png` — LOSS с VWAP-FL вне досягаемости

## Связи

- [[2026-05-23-smc-lib-vwap-entry-experiments]] — родительская сессия (smc-lib build, VWAP experiments)
- [[i-rdrb-v1-fvg-f1-f2-f3-strategy-257-setups-wr72]] — оригинальный F1∪F2_same + R/ATR фильтр
- [[i-rdrb fvg митигация зоны 1h btc eth]] — основная стратегия с zone-mitigation entry
- [[vic-asvk-indicator-python]] — ASVK ViC формула
- [[vadim 12 confluens asvk]] — confluence-score
- [[smc-lib-as-canonical-source]] — где живёт код
