---
name: 12h-fractal-filter-f1-f2
description: "12h fractal filter F1 ∩ F2 ∩ F3 для BTC. Strictly causal на (i-2, i-1, i). Pred-12h (pre-Williams, 1266 candidates/6y, P=48.9%) или Filt-12h (post-Williams, 18/35). 18/18 important preserved."
metadata: 
  node_type: memory
  type: project
  originSessionId: 92a19f52-96e8-4b59-9766-f29ae6786cff
---

# 12h Fractal Filter (F1 ∩ F2 ∩ F3) — Pred и Filt

Универсальное правило для 12h Williams N=2 фракталов BTC. Strictly causal — использует только свечи **(i-2, i-1, i)** + ATR/EMA history. Применимо в двух режимах.

Ground truth: 18 important из 56 фракталов на BTC с 2026-02-04, размечены пользователем.

## F1 = left_ext_5 (universal, обязательное)

```
FH: pivot.high > max(high) последних 5 12h-баров слева [i-5, i-1]
FL: pivot.low  < min(low)  последних 5 12h-баров слева [i-5, i-1]
```

Смысл: фрактал признаётся "новым swing-extreme" только если за 2.5 дня цена не была глубже/выше в ту же сторону.

**Результат:** 41 keep (18 imp + 23 noise), recall 100%, отсёк 15 noise.

## F2 = opp_colors OR three_same_color (применяется к выжившим F1)

```python
opp_colors(i, i-1)        = (i.color != i-1.color) AND ни одна не doji
three_same(i-2, i-1, i)   = (i-2.color == i-1.color == i.color) AND не doji
F2(fractal)               = opp_colors(i, i-1) OR three_same(i-2, i-1, i)
```

Семантика:
- **opp_colors** = классический reversal-candle (i flips i-1). FH = bear-after-bull; FL = bull-after-bear.
- **three_same_color** = exhaustion после длинного импульса. FH = 3 bull → top; FL = 3 bear → bottom.
- Исключает "mixed" 2-same-not-3 (= i==i-1 same color, но i-2 different) — псевдо-pivots без подтверждения.

**Результат:** F1 ∩ F2 = **35 keep (18 imp + 17 noise)**, recall 100%, отсёк ещё 6 noise.

## F3 = pivot bar НЕ марузу-подобный

```python
F3(pivot_bar) = body_pct ≤ 0.80 AND wick_pct ≥ 0.03

где:
  body_pct = |close - open| / range
  wick_pct = relevant_wick / range
    (для FH: upper_wick = high - max(open, close))
    (для FL: lower_wick = min(open, close) - low)
```

Смысл: выкидывает свечи с **большим body и маленьким wick** (марузу-подобные). Такие свечи — это **продолжающийся импульс**, а не разворотный pivot. Они часто пробивают level в следующих 2 барах (= Williams fail).

Все 18 ground truth имеют body_pct ≤ 0.76 и wick_pct ≥ 0.04 — F3 безопасен.

**Результат на 6y pre-Williams:**
- F1 ∩ F2 ∩ F3 = **1 266 keep** (vs 1 408 без F3)
- Williams precision: **48.9%** (vs 45.2% baseline F1∩F2, +3.7 pp)
- Important precision: **~25.6%** (vs 23.0%, +2.6 pp)
- 18/18 important preserved

## Дуальное применение

Поскольку F1 + F2 strictly causal на (i-2, i-1, i), одно и то же правило применяется в двух режимах:

### Pred-12h (pre-Williams, watch list)
Применяется на close каждой 12h-свечи. Свеча `i` ещё **НЕ подтверждена** Williams (нужно ждать i+1, i+2).

```
Все 12h-свечи (6y)           : 4 380
  ↓ pre-Williams check (3-bar local max/min)
Pre-Williams candidates       : 2 891  (66%, baseline P=41.7%)
  ↓ F1 ∩ F2
F1 ∩ F2 candidates            : 1 408  (P=45.2%, ≈19.5/мес)
  ↓ F3 (body ≤ 0.80, wick ≥ 0.03)
Pred-12h watch list           : 1 266  (P=48.9%, ≈17.6/мес)
  ↓ ждём 24h (i+1, i+2)
  ↓ Williams confirm check
Confirmed (48.9% от 1266)     : 619    (≈8.6/мес)
```

Pred-12h = "стоит обращать внимание; через 24h станет известно подтвердится ли".

### Filt-12h (post-Williams, validated)
Применяется после подтверждения Williams (i+1, i+2 не пробили pivot).

```
Williams confirmed fractals   : 56     (за 4-мес ground truth окно)
  ↓ F1 ∩ F2
Filt-12h shortlist           : 35     (18 imp + 17 noise)
```

Recall important = 100%, отсёк 21 noise из 38 (= 55% noise reduction).

### Архитектурный принцип

- F2 может ТОЛЬКО отрезать (AND с F1), не возвращать
- Parallel-rescue conditions (OR с F1 ∩ F2) могут только возвращать important потерянные F2, не делают exclusion

В текущей конфигурации F2 не теряет важных — rescue не нужен.

## Финальные числа на 6y BTC

| Этап | n | % от предыдущего | freq |
|---|---:|---:|---:|
| All 12h bars | 4 380 | — | 2/день |
| Pre-Williams candidates (3-bar local extreme) | 2 891 | 66% | 40/мес |
| F1 pass (left_ext_5) | 1 889 | 65.3% | 26.2/мес |
| F1 ∩ F2 (+ opp_colors OR three_same) | 1 408 | 74.5% | 19.5/мес |
| **F1 ∩ F2 ∩ F3 (Pred-12h watch list)** | **1 266** | **89.9%** | **17.6/мес** |
| Williams confirmed (after watch list 24h) | 619 | 48.9% precision | 8.6/мес |
| Expected "important" (по ratio 18/35 ≈ 51%) | ~316 | 51% от Williams | 4.4/мес |

### Precision lift по этапам

| Этап | P(Williams) | P(important) | 18 imp recall |
|---|---:|---:|---:|
| Pre-Williams (baseline) | 41.7% | ~11.2% | 18/18 |
| F1 only | 42.9% | ~17.2% | 18/18 |
| F1 ∩ F2 | 45.2% (+3.5pp) | ~23.0% (+11.8pp) | 18/18 |
| **F1 ∩ F2 ∩ F3** | **48.9% (+7.2pp)** | **~25.6% (+14.4pp)** | **18/18** |

## Что НЕ сработало как F2

| Гипотеза | Почему |
|---|---|
| HTF zone interaction (untouched, dir-match) с canon SMC close-mitigation | Все 41 fractals тривиально проходят (recall 100% но 0 cuts) |
| HTF zone interaction с simple first_touch | Теряет 9 fresh-extreme important (#4, 5, 9, 15, 20, 26, 41, 47, 48) |
| dist_same_bars ≥ 4 | Recall 94.4%, теряет #26 (cluster-duplicate) |
| d_left_ext_3 (D-level extreme) | Recall 83%, теряет #3, #11, #41 |
| maxV-block (2 свечи подряд open/close > maxV) | 0/9 fresh-extreme FL caught |
| Williams 5-bar ob_liq | Canon отвергает на 02-08 (neighbor выше). Relaxed ob_liq (без Williams) добавляет 283 detections но не помогает |

## How to apply

### Real-time (Pred-12h mode):
На каждой close 12h-свечи:
1. Проверить pre-Williams: (i.high > i-1.high AND i.high > i-2.high) для FH, mirror для FL
2. F1 = left_ext_5
3. F2 = opp_colors OR three_same_color
4. F3 = body_pct ≤ 0.80 AND wick_pct ≥ 0.03
5. Если все pass → добавить в watch list. Ждать i+1, i+2 для Williams confirm.
6. После 24h: Williams check → confirmed/failed. P(conf)=48.9%; ≈51% из confirmed станут "важными".

### Post-Williams (Filt-12h mode):
После подтверждения 12h Williams фрактала:
1. Применить те же F1, F2, F3 проверки.
2. Если пройдено → "important" candidate. 100% recall на ground truth.

## Артефакты

- `~/smc-lib/scripts/plot_fractals_left_ext_5.py` — иллюстрация F1
- `~/smc-lib/scripts/fractals_12h_candle_patterns.py` — поиск F2 (top: opp_colors OR 3_same)
- `~/smc-lib/scripts/plot_f2_candle_pattern.py` — иллюстрация F2 (6 примеров)
- `~/smc-lib/scripts/pred12h_3bar_predictor.py` — 3-bar predictor для Pred-12h (анализ wick/body)
- `~/smc-lib/scripts/pred12h_F3_search.py` — поиск F3 (body ≤ 0.80 AND wick ≥ 0.03)
- `~/Desktop/i-rdrb-charts/fractals_12h_left_ext_5.png` — chart F1
- `~/Desktop/i-rdrb-charts/f2_candle_pattern.png` — chart F2

## Related

- [[fractal-liquidity-strength-and-sweep]] — общая теория HTF fractal strength
- [[12h-fractal-prediction-final-strategy]] — другая стратегия предсказания HH/LL фракталов через sweep_FH/OB_sweep + maxV
