# B4 — HMA (Hull Moving Average sweep)

Был **C5 + C6** в старом каноне (HMA-78 и HMA-200 как отдельные блоки). 2026-06-06 объединены в одно семейство и перемещены сюда (через B5 в B4 при swap).

## Идея

Sweep HMA (Hull Moving Average) уровня на pivot bar. HMA — каноничная trend-line per memory [[feedback-trendline-hma-78-200-default]] (Hma mode, LIVE value, Правило 7).

«Снятие HMA» — индикатор того, что цена дошла до уровня тренда и развернулась → формирование Williams n=2 фрактала.

## Sub-conditions

### B4C1 — HMA-78 sweep (12h ∪ D LIVE)

Sweep HMA-78 на 12h либо D (LIVE value, per Правило 7).

**Causality:** ✅ HMA-78 — past-only weighted MA; check на баре i.

**Цифры (на A4-baseline 1356, canonical 2026-06-06):**
n = 194 · conf = 128 · WR 65.98% · Δ +17.38 pp

### B4C2 — HMA-200 sweep (D LIVE)

Был **C6** в старом каноне → B6 → B5C2 → **B4C2** (2026-06-06).

Sweep HMA-200 на D (LIVE).

**Causality:** ✅ HMA-200 past-only.

**Цифры (на A4-baseline 1356, canonical 2026-06-06):**
n = 54 · conf = 42 · WR **77.78%** · Δ +29.18 pp

### B4 union (canonical 2026-06-06)

`B4 = B4C1 ∪ B4C2`. **n = 234 · conf = 157 · WR = 67.09% · Δ +18.49 pp.**

Overlap B4C1 ∩ B4C2 = 194 + 54 − 234 = 14 событий (≈ 26% от B4C2 — HMA-200 редко пересекается с HMA-78).

## Канон / код
- HMA helpers: `~/smc-lib/indicators/trend_line_asvk.py`
  - `trend_line_hma_78(closes)`
  - `trend_line_hma_200(closes)`
- Memory: [[feedback-trendline-hma-78-200-default]] — HMA 78 + 200 default
- Basket scoring: `~/smc-lib/scripts/pred12h_basket_c1c2c3.py`

## TODO

- Пересчитать B4C1, B4C2 и union на A4-baseline 1356
- Overlap analysis: B4C1 ∩ B4C2 — насколько HMA-78 и HMA-200 ловят одни и те же pivot'ы
- Возможные B4Cx (расширение HMA-семейства):
  - B4C3 — HMA-78 + retest (close back через линию)
  - B4C4 — HMA-200 W LIVE (старший TF)
  - B4C5 — HMA sweep + volume confirmation
  - B4C6 — HMA confluence (касание обоих 78 и 200 одновременно)
- Causality-аудит ([[feedback-b-series-strict-causal-i]])
