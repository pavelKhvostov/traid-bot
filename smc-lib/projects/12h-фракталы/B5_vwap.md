# B5 — VWAP (anchored Volume-Weighted Average Price)

Был **C8** → B8 → **B5** (swap 2026-06-06).

## Идея

Sweep anchored-VWAP уровней — индикатор объёмного баланса от выбранной anchor-точки. Когда цена снимает несколько VWAP'ов, выровненных с Weekly направлением, это указывает на возможное формирование Williams n=2 фрактала.

## Sub-conditions

### B5C1 — ≥2 W-aligned swept VWAPs

На pivot bar сняты **≥2 anchored-VWAP**, выровненных с Weekly direction.

Anchored from fractals N_FRACTAL=2, per memory [[feedback-anchored-vwap-from-fractals]].

**Causality:** ✅ VWAP computed forward from anchor (past fractals), level evaluated at bar i.

**Цифры (на A4-baseline 1356, canonical 2026-06-06):**
n = 95 · conf = 76 · **WR 80.00%** · Δ +31.40 pp

## Канон / код
- VWAP recipe: memory [[feedback-anchored-vwap-from-fractals]]
- Plot template: `plot_fhfl_vwap_4h*`
- Basket scoring: `~/smc-lib/scripts/pred12h_basket_c1c2c3.py`

## TODO
- Пересчитать B5C1 на A4-baseline 1356 (окно 2020-01-01 → now)
- VWAP-anchor — fractals (N_FRACTAL=2). На каком TF? (W-aligned намекает на W).
- Causality-аудит ([[feedback-b-series-strict-causal-i]])
- Возможные B5Cx (расширение VWAP-семейства):
  - B5C2 — sweep одного W-aligned VWAP (более recall, меньше precision)
  - B5C3 — ≥3 W-aligned VWAPs (стрictly precision)
  - B5C4 — sweep VWAP + volume confirmation
  - B5C5 — sweep multi-TF VWAP (W + D anchors)

## Связанные memories
- [[feedback-anchored-vwap-from-fractals]] — recipe (N_FRACTAL=2, Reds/Greens градиенты, шаблон plot_fhfl_vwap_4h)
- [[feedback-b-series-strict-causal-i]] — strict causality для B-серии
