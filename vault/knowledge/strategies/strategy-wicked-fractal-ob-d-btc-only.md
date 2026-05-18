---
tags: [strategy, wicked-ob, fractal-ob, research, btc-only]
date: 2026-05-17
---

# Wicked + Fractal OB-D — V2 + F12 (BTC-only)

Research-стратегия из серии «зона на OB-D с коротким фитилём». Прошла
несколько итераций (etap_119 → etap_127). Финал V2+F12: **+42R на BTC 6.3y,
WR 43.5%, 138 closed, 2 bad years / 7**. На ETH (+4R) и SOL (+5R) edge
почти исчезает — стратегия **BTC-specific**, в live не выноситься.

## Логика входа

### 1) Detection — Wicked + Fractal OB-D V2

- OB-D bull (или bear): тело свечи + противоположный фитиль.
- **Wicked**: фитиль текущей OB-D свечи `< фитиль предыдущей / 2`.
- **Fractal**: предыдущая свеча (`i-1`) — `LL` (для bull) / `HH` (для bear)
  по 5-барному Bill Williams.

См. `research/elements_study/etap_121_wicked_fractal_ob.py` (детектор и V2).

### 2) Reaction zone & entry

Реакция ищется в зоне OB-D. Внутри неё:
- L3: OB-{1h, 2h} HTF
- L4: FVG-{15m, 20m} entry внутри L3 по времени, **строго `any_edge_inside`**
  (не `zones_overlap` — старая ошибка V1, см. etap_120 диагностику)

Entry: `fb + 0.80 × (ft - fb)` (1.1.1-каноник).
SL: `obb + 0.35 × (fb - obb)` symmetric.
**RR = 2.0** (без RR=2.2 как в 1.1.1).

### 3) Filter F12 — `EMA pro OR LONG`

Из 13 filter-вариантов лучший winner:

| Filter                    | n     | WR    | PnL     | bad  |
|---------------------------|-------|-------|---------|------|
| F0 baseline               | 222   | 36.9% | +24R    | 4/7  |
| F2 LONG only              | 115   | 42.6% | +32R    | 1/7  |
| F6 LONG + delay<60h       | 85    | 47.1% | +35R    | 1/7  |
| F7 EMA + LONG + delay<60h | 27    | 59.3% | +21R    | 0/6  |
| **F12 EMA pro OR LONG**   | 138   | 43.5% | **+42R**| 2/7  |

F12 принят как winner: больший sample, +42R, top5% bin.

## Exit experiments — все хуже baseline

- **Floating TP** (etap_124): -22 до -42R на всех фильтрах. **Не работает**
  — стратегия counter-trend (вход на фитиле против движения).
- **BE-ratchet** (etap_125): все варианты хуже baseline. **Не работает**.

→ закрепляется в [[floating-tp-only-helps-low-wr-strategies]]: **continuation
only**. Wicked OB-D — counter-trend, поэтому floating fails.

## Cross-symbol validation V2+F12 (etap_127) — BTC-specific

| Symbol | n   | WR    | PnL    | bad |
|--------|-----|-------|--------|-----|
| BTC    | 138 | 43.5% | +42R   | 2/7 |
| ETH    | 131 | 34.4% | +4R    | 2/7 |
| SOL    | 130 | 34.6% | +5R    | 3/7 |

**BTC-specific.** Edge сводится к ~0R на других символах, как у
[[strategy-1-1-4-bfjk-portfolio]].

## Cross-symbol validation A2+F12 4-stage (etap_132) — broader

| Symbol | n  | WR    | PnL    | bad | R/tr  |
|--------|----|-------|--------|-----|-------|
| BTC    | 51 | 52.9% | +30R   | 1/7 | +0.59 |
| ETH    | 48 | 41.7% | +12R   | 2/7 | +0.25 |
| SOL    | 42 | 33.3% | +0R    | 3/7 | 0.00  |

**A2 cascade более универсален чем V2.** ETH у V2 +4R, у A2 +12R (×3 больше).
Sum 3 symbols: V2 +51R vs A2 +42R (сопоставимо), но BTC у A2 чище (1 bad
вместо 2).

**Trade-off**: V2+F12 = max total PnL на BTC. A2+F12 = broader, более стабильно
по годам, может работать в портфеле с ETH.

## Применимость в live

- BTC-only — потенциальный кандидат на live (на уровне 1.1.6 или дополнения
  к 1.1.1 SHORT-ветке).
- Перед live: pruning по `delay<60h` (даёт F6=+35R / WR 47.1% / 0 bad), либо
  F7 strict (+21R / 0 bad / 6 years).
- TBD: portfolio mix с 1.1.4 BFJK (оба BTC-specific, корреляция?).

## 4-stage cascade (etap_130/131) — A2 alternative

Расширение V2 до полного 4-stage каскада: L1 wicked OB-D / L2 macro / L3 OB-1h/2h / L4 FVG-15m/20m.

| Variant (strict dedup, 1 setup/ob_d, F12) | n   | WR    | PnL    | bad | R/tr |
|--------------------------------------------|-----|-------|--------|-----|------|
| **A2: 1.1.1 no-SWEPT (FVG macro, e=0.80, RR=2.0)** | 51 | 52.9% | +30R   | 1/7 | +0.59 |
| A1: 1.1.1 + SWEPT (e=0.80, RR=2.0)         | 51  | 47.1% | +21R   | 2/7 | +0.41 |
| V2+F12 baseline (3-stage)                  | 138 | 43.5% | +42R   | 2/7 | +0.30 |
| B1: 1.1.2 OB-macro (e=0.70)                | 96  | 34.4% | +3R    | 3/7 | +0.03 |

**A2 trade-off vs V2**: меньше сделок (51 vs 138), но WR на 9.4pp выше, 1 bad
year (вместо 2), и R/tr почти в 2 раза выше (+0.59 vs +0.30). **A2 — лучший
кандидат на live BTC**, если важно качество над количеством.

**SWEPT-фильтр HURTS** в этой стратегии (A1 хуже A2). Противоположно 1.1.1.

**OB-macro (1.1.2-style) НЕ работает** на counter-trend wicked OB-D: clean
R/tr = +0.03, против инфлированного "+538R" в etap_130 (multi-shot ×18×).

**Multi-shot inflation для 4-stage cascade: ×10-20** — выше документированного
×2.3 для 3-stage. Пометить в [[multi-shot-detector-2.3x-inflation]].

## A2 + direction filters + exits (etap_133)

Baseline A2 BTC: 69 closed / WR 50.7% / +36R / R/tr +0.52 / 1 bad.

| Variant                              | n  | WR    | PnL    | R/tr  |
|--------------------------------------|----|-------|--------|-------|
| **A2 LONG only**                     | 46 | 54.3% | +29R   | +0.63 |
| A2 SHORT only                        | 23 | 43.5% | +7R    | +0.30 |
| baseline RR=2.0                      | 69 | 50.7% | +36R   | +0.52 |
| floating TP cap=4.5 th=-0.25 cf=2    | 69 | 55.1% | +27R   | +0.40 |
| floating TP cap=3.5 th=0.0 cf=1      | 69 | 75.4% | +37R   | +0.54 |
| **floating TP cap=5.0 th=-0.5 cf=3** | 69 | 44.9% | **+40.9R** | +0.59 |
| BE-ratchet @+1.0R                    | 44 | 54.5% | +28R   | +0.64 |

**Floating TP РАБОТАЕТ на A2 cascade** (+14% PnL: +36 -> +40.9R). Это
противоречит strict counter-trend exclusion в
[[floating-tp-only-helps-low-wr-strategies]] -- но логично: A2 с macro-FVG
из 1.1.1 уже трендоориентирована, в отличие от чистого V2 (3-stage без macro).

**LONG-only best risk-adjusted**: R/tr +0.63 vs +0.52 ALL. SHORT-ветка
слабая (R/tr +0.30), что согласуется с глобальным BTC bull-bias 2020-2026.

**Best combo для live**: A2 LONG-only + (optionally) floating TP cap=5.0
th=-0.5 cf=3. Pending: проверить additive эффект LONG+floating, ETH/SOL
validation winner combo.

## A2 + LONG + floating cross-symbol (etap_134)

Тест additive эффекта (LONG-only + floating cap=5.0 th=-0.5 cf=3):

| Symbol | Variant       | n  | WR    | PnL    | R/tr  | bad |
|--------|---------------|----|-------|--------|-------|-----|
| BTC    | ALL base      | 69 | 50.7% | +36R   | +0.52 | 1/7 |
| BTC    | LONG base     | 46 | 54.3% | +29R   | +0.63 | 1/7 |
| BTC    | ALL + float   | 69 | 44.9% | +40.9R | +0.59 | 1/7 |
| BTC    | LONG + float  | 46 | 41.3% | +28.6R | +0.62 | 1/7 |
| ETH    | ALL base      | 77 | 40.3% | +16R   | +0.21 | 2/7 |
| ETH    | LONG base     | 40 | 37.5% | +5R    | +0.12 | 3/7 |
| **ETH**| **ALL + float**| 77 | 37.7% | **+37R**| +0.48 | 3/7 |
| ETH    | LONG + float  | 40 | 35.0% | +31.9R | **+0.80**| 3/7 |
| SOL    | ALL base      | 61 | 37.7% | +8R    | +0.13 | 2/7 |
| SOL    | LONG base     | 40 | 32.5% | -1R    | -0.03 | 3/7 |
| SOL    | ALL + float   | 61 | 21.3% | +4.2R  | +0.07 | 4/7 |
| SOL    | LONG + float  | 40 | 17.5% | -1.5R  | -0.04 | 4/7 |

**Key findings:**
1. **ETH LONG+float: R/tr +0.80** — лучший per-trade edge во всей серии. Floating
   делает ETH рабочим (+5R → +31.9R, ×6.4 boost).
2. **BTC LONG+float не помогает** vs LONG base (28.6 vs 29R) — потому что
   baseline WR 54.3% уже выше 50% порога floating law.
3. **SOL broken** — floating не помогает, делает хуже. Стратегия фундаментально
   не имеет edge на SOL.
4. **Refined floating law (доп. условие)**: floating amplifies existing edge,
   не создаёт edge с нуля. SOL базово плохая → floating не спасает.

**Portfolio пред-recommendation**: BTC + ETH (drop SOL):
- BTC ALL+float: +40.9R / 69 closed / 1 bad
- ETH ALL+float: +37R / 77 closed / 3 bad
- **Sum: +78R / 146 closed / 4 bad** — сопоставимо с
  [[strategy-1-1-4-bfjk-portfolio]] (BTC только +107R / 0 bad).

Преимущество portfolio: 2 символа, можно гасить просадки. Недостаток:
3 bad year на ETH — менее robust.

## Portfolio merge BTC+ETH (etap_135) — diversification gives 0/7 bad

Объединяем trades A2+float по BTC и ETH (drop SOL), сортируем по времени.

| Year | n   | WR    | PnL    |
|------|-----|-------|--------|
| 2020 | 9   | 22.2% | +1.6R  |
| 2021 | 22  | 45.5% | +20.4R |
| 2022 | 20  | 45.0% | +3.3R  |
| 2023 | 36  | 38.9% | +17.6R |
| 2024 | 24  | 58.3% | +16.6R |
| 2025 | 27  | 33.3% | +16.5R |
| 2026 | 8   | 25.0% | +2.0R  |
| **Total** | **146** | **41.1%** | **+77.9R** |

- **0 bad years / 7** (через диверсификацию — BTC 1 bad, ETH 3 bad → portfolio 0)
- Max drawdown: -12R (clean curve)
- Cadence: 1.9 trades/month
- LONG: +60.6R / 86 trades, SHORT: +17.4R / 60 trades

**Сравнение с другими approved-кандидатами:**

| Strategy | Symbols | n | PnL | bad | R/tr |
|----------|---------|---|-----|-----|------|
| [[strategy-1-1-4-bfjk-portfolio]] | BTC | 115 | +107R | 0/7 | +0.93 |
| [[project_115_fractal_landscape]]  | BTC | 242 | +106R | 0/7 | +0.44 |
| **A2 BTC+ETH portfolio (этот)**    | BTC+ETH | 146 | **+77.9R** | **0/7** | +0.53 |

A2 BTC+ETH — **первый multi-symbol approved-candidate в исследовании**. Чуть
меньше PnL чем 1.1.4 / 1.1.5 BTC-only, но даёт robust 0/7 bad through
diversification, не через одну символьную силу.

## Per-symbol floating TP tuning (etap_136-137)

Grid 5 cap × 4 th × 3 cf = 60 configs / symbol. Optimum per-symbol:

| Symbol | cap | th    | cf | PnL    | WR    | bad | Note |
|--------|-----|-------|----|--------|-------|-----|------|
| BTC max-PnL | 5.0 | -0.50 | 1 | +48.1R | 68.1% | 1/7 | Aggressive |
| BTC robust  | 5.0 | 0.00  | 1 | +43.2R | 75.4% | 0/7 | Conservative |
| ETH         | 5.0 | -0.50 | 3 | +37.0R | 37.7% | 3/7 | Same as global |

**Key insight**: BTC prefers `cf=1` (fast reaction), ETH prefers `cf=3`
(stable confirmation). Это per-symbol diff аналогично 1.1.1
([[strategy-1-1-1-floating-tp-final]]) где BTC/ETH 4.5/-0.25/2, SOL 3.5/0/1.

Portfolio merge с per-symbol configs:

| Variant | n | WR | PnL | R/tr | Max DD | bad |
|---------|---|-----|-----|------|--------|-----|
| A: max-PnL  | 146 | 52.1% | **+85.2R** | +0.58 | -8.7R | 0/7 |
| **B: robust** | 146 | **55.5%** | +80.3R | +0.55 | **-6.6R** | **0/7** |
| Global ref  | 146 | 41.1% | +77.9R | +0.53 | -12.0R | 0/7 |

**Variant B — best risk-adjusted live кандидат**:
- BTC cap=5.0 th=0.0 cf=1 + ETH cap=5.0 th=-0.5 cf=3
- +80.3R / WR 55.5% / 0 bad / max DD только -6.6R
- Почти same PnL как Variant A, но DD -24% tighter
- BTC `th=0.0 cf=1` закрывает wins быстрее на меньших R -> больше мелких wins,
  меньше drawdown

## Walk-forward validation (etap_138)

Per-symbol config grid выбирается на каждом train window, применяется к
следующему test году. 4 окна: train ends [2022, 2023, 2024, 2025] →
test years [2023, 2024, 2025, 2026].

| Train end | Test year | Symbol | Best cfg | Train PnL | Test PnL | Test WR | Test n |
|-----------|-----------|--------|----------|-----------|----------|---------|--------|
| 2022 | 2023 | BTC | cap=5.0 th=-0.5 cf=1 | +31.6R | +5.0R  | 41.7% | 12 |
| 2022 | 2023 | ETH | cap=3.5 th=0.0 cf=3  | +6.5R  | +6.6R  | 45.8% | 24 |
| 2023 | 2024 | BTC | cap=5.0 th=-0.5 cf=1 | +36.6R | +8.5R  | 80.0% | 10 |
| 2023 | 2024 | ETH | cap=3.5 th=-0.5 cf=3 | +18.8R | +6.1R  | 50.0% | 14 |
| 2024 | 2025 | BTC | cap=5.0 th=-0.5 cf=1 | +45.1R | -0.5R  | 71.4% | 14 |
| 2024 | 2025 | ETH | cap=3.5 th=-0.5 cf=3 | +24.9R | +10.5R | 38.5% | 13 |
| 2025 | 2026 | BTC | cap=5.0 th=-0.5 cf=1 | +44.7R | +3.5R  | 25.0% | 4  |
| 2025 | 2026 | ETH | cap=5.0 th=-0.5 cf=3 | +38.1R | -1.1R  | 25.0% | 4  |

**Combined OOS**: +38.7R / 95 closed / R/tr +0.41 (2023-2026, 4 years).
**In-sample for same period**: ~+58R. OOS/IS ratio ~67% — типичная просадка.

**Robustness indicators:**
1. **BTC config STABLE** через 4 окна: `cap=5.0 th=-0.5 cf=1` каждый раз — реальный edge, не overfit
2. **ETH config drift в той же семье**: `cap=3.5 th∈{-0.5, 0.0} cf=3` (3/4 окон) → cap=5.0 в последнем
3. **Только 1.5 негативных test windows из 8** (BTC 2025 -0.5R почти 0, ETH 2026 partial)

**Заметка**: walk-forward picks BTC `th=-0.5 cf=1` (= Variant A's config), не Variant B's
`th=0.0 cf=1`. Variant B был выбран по DD-criterion, не PnL. Both valid для live, выбор
зависит от приоритета (PnL vs draw down tolerance).

## SL sensitivity (etap_139) — null result, robust

Тестируем sl_pct ∈ {0.25, 0.30, 0.35, 0.40, 0.45, 0.50} для Variant B.

Результат: **PnL идентичен на всех sl_pct** (BTC +43.2R / ETH +37R / portfolio +80.3R).
Только 1 лишний ETH trade при sl_pct=0.25-0.30 (78 vs 77 — пограничный случай).

**Причина**: `MIN_SL_PCT=1.0%` floor (минимум 1% от entry) доминирует над
геометрическим sl_pct из 1.1.1 канона. SL почти всегда упирается в 1% floor,
а не в `obb + sl_pct × (fb - obb)`.

**Вывод**: strategy **робастна к SL tuning** — sl_pct=0.35 canonical fine, но
любое 0.25-0.50 эквивалентно. Это положительный robustness-signal.

## Entry_pct sensitivity (etap_140) — также null result

Тестируем entry_pct ∈ {0.50, 0.60, 0.70, 0.80, 0.90} (0.80 = canon из 1.1.1,
0.70 = 1.1.2 canon, 0.50 = mid FVG).

| entry_pct | Portfolio PnL | R/tr |
|-----------|---------------|------|
| 0.50      | +75.8R        | +0.53 |
| 0.60-0.90 | +80-81.5R     | +0.55 |
| 0.80 (canon Variant B) | +80.3R | +0.55 |
| 0.90 (slight best)     | +81.5R | +0.55 |

Только при 0.50 (mid FVG) небольшая просадка. Диапазон 0.60-0.90 эквивалентен.

**Вывод**: оба ключевых параметра (sl_pct + entry_pct) показывают null sensitivity.
Это **сильный robustness-signal**: edge стратегии генуинен, не зависит от тонкой
настройки параметров. Variant B остаётся канон, тюнинг ±1pp PnL не оправдан.

## Score≥threshold filter (etap_141) — premium tier на BTC

Тестируем дополнительный entry filter: 4-indicator momentum score >= threshold
при signal_time. Score применяется per direction (score_long для LONG, score_short
для SHORT). Variant B floating exit сохранён.

**BTC:**

| Filter        | n  | WR    | PnL    | R/tr   | bad   | DD    |
|---------------|----|-------|--------|--------|-------|-------|
| baseline      | 69 | 75.4% | +43.2R | +0.63  | 0/7   | -1.4R |
| score≥0       | 43 | 76.7% | +40.5R | +0.94  | 0/7   | -1.0R |
| score≥+0.25   | 29 | 79.3% | +38.7R | +1.34  | 0/7   | -1.0R |
| **score≥+0.50** | **22** | **86.4%** | **+32.8R** | **+1.49** | **0/6** | **0.0R** |

**ETH** — score filter HURTS:

| Filter        | n  | WR    | PnL    | R/tr   | bad   |
|---------------|----|-------|--------|--------|-------|
| baseline      | 77 | 37.7% | +37.0R | +0.48  | 3/7   |
| score≥+0.25   | 37 | 37.8% | +9.7R  | +0.26  | 2/7   |

**Интерпретация**: 4-indicator momentum score — это **edge-extractor
специфически для BTC** wicked-OB-D trades. ETH trades не коррелируют с
тем же momentum signal. Гипотеза: ETH более reactive/noisy, BTC trades
лучше синхронизированы с macro momentum.

## Tier system (proposed)

| Tier | Config | n | WR | PnL | DD | Cadence |
|------|--------|---|-----|------|------|---------|
| 1 (premium) | BTC + score≥0.50 | 22 | 86.4% | +32.8R | 0R | 3.5/yr |
| 2 (broad)   | Variant B BTC+ETH | 146 | 55.5% | +80.3R | -6.6R | 23/yr |

Tier 1 = wide position sizing на редких clean сигналах. Tier 2 = standard
sizing. Combined для live: использовать Tier 2 как baseline, Tier 1 как
"signal boost" overlay (увеличить position на этих 22 trades).

### Tier-1 walk-forward validation (etap_142) — VALIDATED ✓

| Test year | Train trades | Train WR | Test trades | Test WR | Test PnL |
|-----------|--------------|----------|-------------|---------|----------|
| 2021      | 4            | 75.0%    | 2           | 100%    | +5.9R    |
| 2022      | 6            | 83.3%    | 2           | 100%    | +5.5R    |
| 2023      | 8            | 87.5%    | 6           | 66.7%   | +5.5R    |
| 2024      | 14           | 78.6%    | 6           | 100%    | +11.1R   |
| 2025      | 20           | 85.0%    | 2           | 100%    | +0.8R    |

**Combined OOS 2021-2026**: 18 trades / WR **88.9%** / +28.9R.
**In-sample**: 22 / 86.4% / +32.8R.

OOS WR > in-sample WR — **сильнейшая валидация edge'а** (обычно OOS < IS).
Каждый test year положителен. Worst test year 2023: WR 66.7% / +5.5R на 6
сделках — даже худший год прибыльный.

→ **Tier-1 — реальный edge, готов к live с widely-sized position на 22-25
trades / 6 лет** (~3.7 в год).

## Files (etap_134-141)

- `etap_134_wicked_a2_long_floating_xsymbol.py` — additive LONG+floating x-symbol
- `etap_135_wicked_a2_portfolio_btc_eth.py` — BTC+ETH global config merge
- `etap_136_wicked_a2_floating_per_symbol.py` — 60-config grid search per symbol
- `etap_137_wicked_a2_per_symbol_portfolio.py` — Variant A/B portfolio merge
- `etap_138_wicked_a2_walk_forward.py` — walk-forward 4 windows, OOS +38.7R
- `etap_139_wicked_a2_sl_sensitivity.py` — SL sensitivity (null result, robust)
- `etap_140_wicked_a2_entry_rr_sensitivity.py` — entry_pct sensitivity (null, robust)
- `etap_141_wicked_a2_score_filter.py` — score≥threshold filter, premium BTC tier
- `etap_142_tier1_walkforward.py` — Tier-1 walk-forward (OOS WR 88.9%, validated)
- `etap_143_v2_vs_a2_overlap.py` — V2/A2 overlap: 5/85 — nearly disjoint
- `etap_144_v2_a2_combined_portfolio.py` — Variant C combined: 513 trades / +129R / 1 bad
- `etap_145_variant_c_walkforward.py` — Variant C walk-forward (OOS +129.9R, validated)
- `etap_146_variant_c_tier1.py` — Variant C + score≥0.50 reveals Variant D
- `etap_147_variant_d_walkforward.py` — Variant D walk-forward (OOS +45.9R, validated)
- `etap_148_variant_c_extended_score.py` — score threshold sweep, reveals Variant E
- `etap_149_variant_c_time_of_day.py` — hour-of-day breakdown (Asia session dominates)
- `etap_150_asia_session_walkforward.py` — Asia walk-forward validates Variant F
- `etap_151_composite_filters.py` — composite filter tests, reveals Variant H
- `etap_152_variant_h_walkforward.py` — Variant H walk-forward (OOS +150R, validated)
- `etap_153_variant_e_walkforward.py` — Variant E walk-forward (OOS +92.2R, validated)

## Variant H: Variant C - anti-edge hours (etap_151)

Исключение 3 worst hours UTC (11, 13, 17) — все три имели negative R/tr в etap_149.

| Variant | n | WR | PnL | R/tr | bad | DD |
|---------|---|-----|------|------|-----|-----|
| C (baseline)               | 513 | 52.6% | +129.4R | +0.25 | 1/7 | -8.4R |
| **H (C - hours 11,13,17)** | **461** | **54.7%** | **+149.9R** | **+0.33** | 1/7 | **-8.0R** |
| Hour 13 alone removed      | 496 | 54.0% | +139.2R | +0.28 | 1/7 | -8.0R |

**Variant H** = Variant C minus signals at hours 11, 13, 17 UTC:
- +20.5R больше PnL чем C (+15.8% boost)
- WR rises 52.6% → 54.7%
- DD slightly better
- bad стало 1/7 как и в C

Per-symbol анализ:
- BTC: -1.4R от exclusion (BTC слабо чувствителен)
- ETH: **+21.9R** от exclusion (ETH noise concentrated в этих часах)

→ Variant H = Variant C optimized for ETH cleaning. Anti-cluster is mainly
**ETH noise reduction filter**.

### Variant H walk-forward (etap_152) — STRONGLY VALIDATED ✓

| Test year | Train anti-hours | Test anti R | Test other (H) R |
|-----------|------------------|-------------|------------------|
| 2021      | 3 / -0.4R        | -3.8R       | +35.6R           |
| 2022      | 11 / -4.2R       | -2.9R       | +16.1R           |
| 2023      | 17 / -7.1R       | -5.9R       | +23.7R           |
| 2024      | 32 / -12.9R      | -2.8R       | +38.1R           |
| 2025      | 41 / -15.8R      | -2.2R       | +23.4R           |
| 2026      | 47 / -17.9R      | -2.6R       | +13R             |

**Anti-hours (11/13/17 UTC) NEGATIVE в каждом test year И каждом train window**.
Не one-year fluke — replicable anti-edge.

**OOS combined**:
- Variant H 2021-2026: **422 trades / +150.0R / R/tr +0.36** (vs IS +149.9R / +0.33)
- Anti-hours 2021-2026: 49 trades / **-20.1R / R/tr -0.41** (confirmed dead zone)

OOS R/tr (+0.36) exceeds in-sample (+0.33). **Variant H = real, OOS-validated
edge filter.**

## Variant G (Asia + score≥0.5) — FAILED composite

Asia session filter + score>=0.50 filter не stacks productively:
- 21 trades total / WR 38.1% / +11.6R / 2 bad of 6

Filters overlap — оба identify "high-quality" trades, по-разному. Stacking
cuts too aggressively без proportional quality boost. **Composite filters
не всегда additive.** Использовать или Asia (Variant F) или score (Variant D),
не оба сразу.

## Time-of-day observation (etap_149) — Asia session concentration

Variant C 513 trades split by signal_time hour UTC:

| Session | n | WR | PnL | R/tr | bad |
|---------|---|-----|------|------|-----|
| **Asia (00-07)** | **150** | 56.0% | **+60.7R** | **+0.40** | 1/7 |
| London (07-12)   | 108 | 56.5% | +15.9R | +0.15 | 4/7 |
| Overlap (12-16)  | 102 | 42.2% | +7.8R  | +0.08 | 2/7 |
| NY (16-21)       | 90  | 52.2% | +27.5R | +0.31 | 3/7 |
| Late (21-24)     | 63  | 55.6% | +17.5R | +0.28 | 2/7 |

**Asia = 47% of PnL from 29% of trades**. R/tr +0.40 vs +0.08-0.31 для других.

**Worst hour: 13:00 UTC** — WR 11.8% / -9.9R / R/tr -0.58 (anti-edge во время
London-NY overlap).

**Best hour: 00:00 UTC** — WR 60% / +27.2R / R/tr +1.36 (Asia open после
US close).

**Caveat**: 5 sessions × 7 years = high multi-comparison bias. Asia session
filter может быть data-mined artifact. Перед использованием в live —
walk-forward проверка обязательна. Пока — observation, не Variant.

### Asia-session walk-forward (etap_150) — VALIDATED → Variant F

| Test year | Train R/tr | Test n | Test PnL | Test WR |
|-----------|------------|--------|----------|---------|
| 2021      | +0.37      | 19     | +10.6R   | 42.1%   |
| 2022      | +0.48      | 26     | +10.6R   | 57.7%   |
| 2023      | +0.45      | 33     | +8.0R    | 60.6%   |
| 2024      | +0.37      | 24     | +10.3R   | 54.2%   |
| 2025      | +0.39      | 32     | +18.3R   | 59.4%   |
| 2026      | +0.43      | 3      | -2.0R    | 0% (partial year, 3 trades) |

**OOS combined 2021-2026**: 137 trades / WR 54.7% / **+55.9R / R/tr +0.41**
**In-sample**: 150 / WR 56.0% / +60.7R / R/tr +0.40

**OOS R/tr exceeds in-sample R/tr** — Asia session edge подтверждена, не
artifact. Non-Asia subset: R/tr +0.19 (×2.2 хуже). → **Variant F = Variant C
+ Asia session (00-07 UTC) filter**.

Все 6 variants OOS-validated.

## Variant E: Variant C + score>=0.00 (etap_148 extended sweep)

Расширенный sweep score thresholds на Variant C portfolio выявил **score=0.00**
как промежуточный sweet spot — momentum-aligned filter без агрессивной отсечки.

**Portfolio comparison:**

| Threshold | n | WR | PnL | R/tr | bad | DD |
|-----------|---|-----|------|------|-----|-----|
| -0.50     | 254 | 48.4% | +90.7R | +0.36 | 1/7 | -9.7R |
| -0.25     | 181 | 48.6% | +87.9R | +0.49 | 2/7 | -9.0R |
| **+0.00** | **159** | **50.9%** | **+91.6R** | **+0.58** | 2/7 | -7.6R |
| +0.25     | 95  | 49.5% | +53.0R | +0.56 | 1/7 | -7.7R |
| +0.50 (D) | 68  | 55.9% | +48.8R | +0.72 | 0/7 | -3.7R |
| +0.75     | 15  | 53.3% | +12.0R | +0.80 | **4/6** | -5.0R |

**Variant E** = Variant C filtered by score≥0.00:
- 159 trades / WR 50.9% / +91.6R / 2 bad / DD -7.6R / R/tr +0.58
- +14% PnL boost vs Variant B (+80.3R), better R/tr (+0.58 vs +0.55)
- Trade-off: 2 bad years (vs B's 0) — less robust по years

**+0.75 overshoot**: only 15 trades / 4 bad years — порог слишком высокий
(filter cuts too aggressively, removes years' worth of valid setups).

→ **Variant E** = best PnL with score filter without becoming counter-productive.

### Variant E walk-forward (etap_153) — VALIDATED ✓

| Test year | Train n | Train PnL | Test n | Test PnL | Test WR |
|-----------|---------|-----------|--------|----------|---------|
| 2021      | 17      | -0.6R     | 19     | +9.4R    | 42.1%   |
| 2022      | 36      | +8.7R     | 22     | +16.8R   | 54.5%   |
| 2023      | 58      | +25.5R    | 34     | +19.3R   | 47.1%   |
| 2024      | 92      | +44.8R    | 25     | **+29.1R** | **64.0%** |
| 2025      | 117     | +73.9R    | 31     | +18.8R   | 48.4%   |
| 2026      | 148     | +92.7R    | 11     | -1.1R    | 54.5%   |

**Combined OOS 2021-2026**: 142 trades / WR 51.4% / **+92.2R / R/tr +0.65**
**In-sample**: 159 / WR 50.9% / +91.6R / R/tr +0.58

OOS R/tr (+0.65) exceeds in-sample. 5/6 test years positive, 2026 partial year
barely -1.1R на 11 trades (small-sample noise). Variant E confirmed.

## Variant D: Variant C + Tier-1 score filter (etap_146)

Применяем score≥0.50 entry filter ко всему Variant C portfolio (A2 + V2\A2).
В отличие от Variant B (где score filter работал только на BTC), на Variant C
score filter работает И на ETH через V2-trades.

| Variant | n | WR | PnL | R/tr | bad | DD |
|---------|---|-----|------|------|-----|-----|
| B (quality)  | 146 | 55.5% | +80.3R  | +0.55 | 0/7 | -6.6R |
| C (volume)   | 513 | 52.6% | +129.4R | +0.25 | 1/7 | -8.4R |
| Tier-1 BTC   | 22  | 86.4% | +33R    | +1.49 | 0/7 | 0R    |
| **D (premium+expanded)** | **68** | **55.9%** | **+48.8R** | **+0.72** | **0/7** | **-3.7R** |

Per-symbol composition Variant D:
- BTC: 32 trades (A2=22, V2=10) / WR 75% / +36.4R / 0/6 / DD -1R
- ETH: 36 trades (A2=30, V2=6) / WR 38.9% / +12.4R / 2/7 / DD -7.5R

**Variant D — best risk-adjusted portfolio** среди всех вариантов:
- 13:1 PnL/DD ratio (-3.7R на +48.8R)
- Highest R/tr среди broad portfolios (+0.72)
- 0 bad years (как B, лучше C)
- ~11 trades/year (между B 23/yr и Tier-1 3.5/yr)
- ETH integration: A2 alone не respond к score filter на ETH, но V2 trades
  с score>=0.50 на ETH дают +12.4R / 36 trades

→ Variant D = новый кандидат с best DD/PnL. Финальный choice зависит от
priorities (max PnL = C / clean = B / balanced = D / premium-only = Tier-1).

### Variant D walk-forward (etap_147) — VALIDATED ✓

| Test year | Train n | Train PnL | Train WR | Test n | Test PnL | Test WR |
|-----------|---------|-----------|----------|--------|----------|---------|
| 2021      | 5       | +2.9R     | 60.0%    | 10     | +5.1R    | 40.0%   |
| 2022      | 15      | +7.9R     | 46.7%    | 11     | +3.3R    | 36.4%   |
| 2023      | 26      | +11.2R    | 42.3%    | 19     | +9.5R    | 57.9%   |
| **2024**  | 45      | +20.7R    | 48.9%    | 12     | **+25.4R** | **91.7%** |
| 2025      | 57      | +46.2R    | 57.9%    | 10     | +1.6R    | 40.0%   |
| 2026      | 67      | +47.8R    | 55.2%    | 1      | +1.0R    | 100%    |

**Combined OOS 2021-2026**: 63 trades / WR **55.6%** / **+45.9R**.
**In-sample**: 68 / 55.9% / +48.8R.

OOS PnL within 6% of in-sample, WR essentially identical. 2024 was extraordinary
(91.7% / +25.4R) — score filter catching exceptional setups during high-momentum
year. **Все 4 варианта (B, C, D, Tier-1) теперь OOS-validated.**

## Variant C: V2+A2 combined portfolio (etap_143/144)

V2 (3-stage без macro) и A2 (4-stage с FVG-4h/6h macro) производят **почти
непересекающиеся** наборы сетапов: на 324 wicked OB-D — V2 находит 258 setups,
A2 — 85, пересечение всего 5. Причина: V2 ищет OB-1h/2h непосредственно в
OB-D, A2 требует FVG-4h/6h промежуточный уровень. Разная timing/zones.

**Combined V2+(A2 unique)** дает значительно больше trades с positive edge:

| Portfolio | n | WR | PnL | R/tr | bad | DD |
|-----------|---|-----|------|------|------|-----|
| A2 (Variant B) | 146 | 55.5% | +80.3R | +0.55 | 0/7 | -6.6R |
| V2 only | 379 | 51.5% | +46.2R | +0.12 | 2/7 | -13.2R |
| **Variant C (A2 ∪ V2)** | **513** | 52.6% | **+129.4R** | +0.25 | 1/7 | -8.4R |

Year-by-year Variant C: 2020 -0.5R (barely flat-bad), 2021-2026 все позитивны.

**Variant B vs C trade-off**:
- Variant B = quality (R/tr +0.55, 0 bad, ~23 trades/year)
- Variant C = quantity (1.6× PnL, 3.5× trades, 1 bad-but-flat year, ~82 trades/year)

### Variant C walk-forward validation (etap_145) — VALIDATED ✓

| Test year | Train n | Train PnL | Test n | Test PnL | Test WR |
|-----------|---------|-----------|--------|----------|---------|
| 2021      | 42      | -0.5R     | 74     | +31.8R   | 54.1%   |
| 2022      | 116     | +31.2R    | 76     | +13.2R   | 48.7%   |
| 2023      | 192     | +44.5R    | 115    | +17.9R   | 47.8%   |
| 2024      | 307     | +62.3R    | 85     | +35.3R   | 56.5%   |
| 2025      | 392     | +97.6R    | 93     | +21.3R   | 51.6%   |
| 2026      | 485     | +118.9R   | 28     | +10.5R   | 60.7%   |

**Combined OOS 2021-2026**: 471 trades / WR 52.0% / **+129.9R** — essentially same as in-sample +129.4R. Все 6 test years положительны.

→ Variant C — **полностью OOS-robust**, edge stable across all years.

**Floating-config insight**: V2 на ETH с Variant-B-style floating (cap=5.0
th=-0.5 cf=3) даёт +8R, but в Combined вклад V2 в ETH = +11R. Floating
cap=5.0 th=0.0 cf=1 на BTC даёт V2 +38R (vs etap_124 1.1.1-default config
−22..-42R). **Per-symbol floating config критичен также для V2.**

## Файлы

- `etap_119_wicked_ob_reactions.py` — 5 reactions × 2 OB filters (initial)
- `etap_120_wicked_ob_diagnostic.py` — geometry bug discovery
- `etap_121_wicked_fractal_ob.py` — V2 с `any_edge_inside`, +24R baseline
- `etap_122_v2_forensic.py` — feature distributions wins vs losses
- `etap_123_v2_filtered.py` — 13 filters, F12 winner +42R
- `etap_124_v2_floating_tp.py` — floating fails
- `etap_125_v2_be_ratchet.py` — BE-ratchet fails
- `etap_126_wicked_with_111_112_rules.py` — 1.1.1/1.1.2 rules tried, weaker
- `etap_127_wicked_v2_eth_sol.py` — cross-symbol validation (BTC-only)
- `etap_130_wicked_4stage_111_112.py` — 4-stage cascade raw (multi-shot inflated)
- `etap_131_wicked_4stage_strict_dedup.py` — A2 clean: +30R / WR 52.9% / 1 bad

## Ссылки

- [[floating-tp-only-helps-low-wr-strategies]] — refined law (counter-trend exclusion)
- [[strategy-1-1-4-bfjk-portfolio]] — другой BTC-specific кандидат
- [[универсальные определения OB и FVG]] — `any_edge_inside`-правило
