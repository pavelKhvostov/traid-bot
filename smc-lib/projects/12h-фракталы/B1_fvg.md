# B1 — FVG (Fair Value Gap)

Был **C4** в старом каноне. Под-корзина B1C1..B1C6.

## Идея

«Неэффективность FVG» — sweep'ы и реакции на FVG-зоны (multi-TF) указывают на формирование Williams n=2 фрактала.

Каждый B1Cx — независимое **causal** условие на одной из трёх осей:
- **Lifecycle** (когда FVG считается «живой»)
- **Sweep / Reaction** (что считается событием на FVG)
- **Filter** (отбор зон по width / age / TF)

`B1 = B1C1 ∪ B1C2 ∪ B1C3 ∪ B1C4 ∪ B1C5 ∪ B1C6` (OR-union)

⚠️ **Causality:** все B1Cx используют только данные ≤ i. См. memory [[feedback-b-series-strict-causal-i]].

## Текущий канон B1_v4 (causal-only, 2026-06-06)

| B1Cx | name           | params                                | n   | conf | WR     | роль |
|----|----------------|---------------------------------------|----:|-----:|-------:|------|
| B1C1 | strict sweep   | L0 / S100 / WIDE                      | 35  | 33   | **94.29%** | precision anchor (full puncture, wide zones) |
| B1C2 | strict sweep   | L0 / S50 / AGE-WIDE                   | 63  | 55   | 87.30% | aged-wide classic |
| B1C3 | strict sweep   | L0 / S70 / AGE50                      | 130 | 98   | 75.38% | aged deeper sweep |
| B1C4 | strict sweep   | L0 / S50 / HTF-WIDE                   | 53  | 41   | 77.36% | HTF wide precision |
| B1C5 | volume spike   | L0 / S50 + vol_z ≥ +2σ                | 66  | 48   | 72.73% | institutional volume (rolling 50 past) |
| B1C6 | retest         | L0 / S50 → close inside (≤3 баров)    | 38  | 26   | 68.42% | re-mitigate after sweep (pivot @ retest bar) |
| | **UNION B1**   |                                       | **226** | **162** | **71.68%** | canonical 2026-06-06 |

## Оси

### Lifecycle (когда FVG считается активной)
- `L0` — никогда не abandon (default)
- `L1` — abandon при первом wick ≥ 50% (mitigated)
- `L2` — abandon при первом wick ≥ 100% (full fill)
- `L3` — abandon при первом close inside zone
- `L4` — abandon после N=120 баров без события (timeout)

### Sweep / Reaction (causal-only)
- `S50/S70/S100` — wick ≥ X% ширины + close **OUTSIDE** far edge (rejection) — все на баре i
- `W50/W100` — pure wick-fill (no close requirement) — *в каноне не используется, дало WR ниже baseline*
- `CINS` — wick ≥ 70% + close **INSIDE** zone — *anti-edge, исключено*
- `EDGE` — shallow pen 5-25% + close outside — *кандидат для B1C7+*
- `iFVG` — broken (close THROUGH) → opposite-side touch — *кандидат, WR слабый*
- **B1C5 vol_spike** — sweep S50 + объём sweep-бара z ≥ +2σ (rolling 50 past) ✅ causal
- **B1C6 retest** — sweep S50 + close inside в течение ≤3 баров (fire @ retest bar) ✅ causal

### Filter
- `ANY` — все FVG
- `12h` — только 12h-FVG
- `HTF` — D / 2D / 3D / W
- `AGE50` — age FVG ≥ 50 12h-баров (causal)
- `WIDE` — width ≥ 0.7 × ATR(14, past)
- комбинации: `AGE50_WIDE`, `HTF_WIDE`, `HTF_AGE50`

## История

### B1_v4 (2026-06-06 day) — **текущий канон**

**Удалён B1C5 REJ_BAR** — нарушал causality (использовал `body_pct[i+1]`, `c12[i+1]`).
Renumbered:
- B1C5 ← VOL_SPIKE (был B1C6)
- B1C6 ← RETEST    (был B1C7)
- B1C7 (removed)

Результат: 255/74.12% (v3 с lookahead) → **226/71.68%** (v4 honest, -29 fires, -2.44 pp).
Это «правильное» число — оно ниже v3, потому что v3 имел unfair advantage от заглядывания в i+1.

### B1_v3 (2026-06-06 morning) — **deprecated, lookahead**

Состав: B1C1..B1C4 strict + REJ_BAR + VOL_SPIKE + RETEST. WR 74.12%.
🚨 **B1C5 REJ_BAR** использовал bar i+1 → lookahead. Отвергнут.

### B1_v2 (2026-06-06 morning) — устар.

D1..D6 с wick-fill компонентами (L1/W50, L2/W100). 251/64.5%.
Wick-fill дали WR ниже среднего (55%/52%) — заменены в v3.

### B1_v1 (default — старый канон)

`L0 / S50 / ANY` standalone: 182/59.9%.

## Кандидаты на расширение (B1C7+)

Из grid `pred12h_c4_d7_d14.py` (нужен causality-аудит каждого!):

| кандидат (script name) | n_uniq | WR_uniq | causality | вердикт |
|---|---:|---:|---|---|
| EDGE (pen 5-25% / WIDE)      | 71 | 53.5% | ✅ causal (fire @ shallow touch bar) | 🟡 возможно B1C7 в v5 |
| iFVG (broken → re-touch)      | 256 | 45.7% | ✅ causal (broken_at known по past) | большой объём, WR < 50% → нужен фильтр |
| FRAC_CONF (Williams ≤30b)     | 15 | 53.3% | ✅ causal (past Williams confirmation) | мало n |
| HMA_CONF (≤1×ATR от HMA)      | 79 | 48.1% | ✅ causal (HMA past-only) | пересечение с B5/B6 |
| CINS (close inside)           | 100 | 37.0% | ✅ causal | 🔴 anti-edge, отбросить |
| ~~REJ_BAR (k+1 reject)~~      | 26 | 92.3% | 🔴 lookahead | **отвергнут, см. v4** |

## Код

- **Causal grid scanner:** `~/smc-lib/scripts/pred12h_c4_subbasket.py`
- **Sub-basket builder (greedy):** `~/smc-lib/scripts/pred12h_c4_basket_build.py`
- **B1_v4 union evaluator:** `~/smc-lib/scripts/pred12h_b1_v4_union.py` ← **текущий**
- ~~B1_v3 evaluator: `pred12h_c4_v3_union.py`~~ — deprecated (имеет REJ_BAR lookahead)
- **Extended candidates grid:** `~/smc-lib/scripts/pred12h_c4_d7_d14.py` (требует causality-аудита перед adoption)

## Канон зоны интереса

Smc-lib каноны:
- `~/smc-lib/elements/fvg/` — детектор FVG (3-свечный паттерн, multi-TF)
- `~/smc-lib/zone_of_interest.md` — mitigation models (wick-fill / strict / sweep)

## Связанные memories

- [[feedback-b-series-strict-causal-i]] — strict causality rule для B-серии
- [[pred12h-c4-subbasket-architecture]] — устаревшее имя; обновить до B1
- [[feedback-fvg-wick-fill-mitigation]] — wick-fill канон для FVG (используется в L1/L2 lifecycle gates)
- [[feedback-untraded-area-is-magnet]] — untraded area как магнит, fundamental SMC
