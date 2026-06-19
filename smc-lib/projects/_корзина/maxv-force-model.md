# maxV Force Model — Phase 1 canonical spec

**Status:** Phase 1 closed 2026-06-04. Pipeline Phase 0.1+ blocked, требует PC для walk-forward (Phase a+).

## 1. Объект и геометрия

| Концепт | Определение |
|---------|-------------|
| **maxV zone** | диапазон `[zone_lo, zone_hi]` с Gaussian-силой в центре |
| **L (level)** | `mb_close` = close LTF-бара с **АБСОЛЮТНЫМ** max-volume (canon Pine ViC ASVK, любое направление) |
| **mlt** | Pine ViC LTF multiplier = **45** (структурный гиперпараметр) |
| **LTF for D** | 32m (`ceil(1440/45)`, D-chart integer rule) |
| **zone_width** | `α × R_parent`, α=**0.30** |
| **clip** | `zone_lo = max(parent_L, L − α·R/2)`, `zone_hi = min(parent_H, L + α·R/2)` |
| **R эффективный** | `max(L − zone_lo, zone_hi − L)` |
| **σ Gaussian** | `R × σ_coeff`, σ_coeff = **0.5** |

Зона — **объект работы** (touch / breakout / heatmap). L — **параметр** (центр Gaussian, mit-trigger).

## 2. Состояния зоны

| State | Trigger | Effect |
|-------|---------|--------|
| **virgin** | формирование на close parent | W_v = K_V = 3.0 |
| **mit** | `bar.low ≤ L ≤ bar.high` (касание **уровня**, НЕ зоны) | W_v начинает decay |
| **broken-defense** | C2-pattern (см. ниже) | W_broken = 1.8 |

⚠️ **mit = level touch**, не zone overlap. Зона = распределение силы; уровень = state-change trigger.

## 3. AMP формула

```
AMP = W_pos × W_age × W_v × W_broken × W_vol
```

### Условие 1 — W_pos (position в parent candle)

```
W_pos = 1.5  if pos ∈ {lower_wick, upper_wick}
        0.7  if pos ∈ {body_top, body_bottom}
```

### Условие 2 — W_age (возраст)

```
W_age = 1 + 0.3 × ln(1 + days_since_formed / 30)
```

| Age | W_age | Note |
|---|---|---|
| 1d | 1.01 | |
| 30d | 1.21 | |
| 90d | 1.42 | |
| 365d | 1.77 | |
| 1825d (5y) | 2.24 | без cap (open question) |

### Условие 3 — W_v (virgin / mitigated decay)

```
virgin:        W_v = K_V = 3.0
mitigated:     W_v = 1 + (K_V − 1) × exp(−days_since_touch / TAU)
                   = 1 + 2 × exp(−t / 7)
```

| t | W_v |
|---|---|
| 0 (just touched) | ≈ 3.0 |
| 7d (TAU) | ≈ 1.74 |
| 14d | ≈ 1.27 |
| ∞ | → 1.0 |

### Условие 4 — W_broken (broken defense pattern)

**Pattern:**
```
lower_wick C1:  C2.high > L  AND  C2.close < C1.low
upper_wick C1:  C2.low  < L  AND  C2.close > C1.high
```

```
W_broken = 1.8  if pattern detected
           1.0  otherwise
```

**Crossover broken vs intact virgin** (с учётом W_v decay):

| t after break | broken (W_broken × W_v) | intact virgin (W_v) | winner |
|---|---|---|---|
| 0 | 1.8 × 3.0 = 5.4 | 3.0 | broken |
| 7d | 1.8 × 1.74 = 3.13 | 3.0 | broken (slight) |
| 14d | 1.8 × 1.27 = 2.29 | 3.0 | **intact virgin** |
| 30d+ | 1.8 × ~1.05 = 1.89 | 3.0 | **intact virgin** |

Crossover ~10-12d.

### Условие 5 — W_vol (объёмная концентрация)

```
W_vol = clip( (V_parent / median_V_20) / (R_parent / ATR_20),  0.5,  2.0 )
```

Логика:
- tight bar + heavy V (consolidation absorption) → boost (numerator >> denominator)
- wide bar + average V (directional move) → penalty
- median bar + median V → 1.0

## 4. Reaction label (ML target, заменил TBM)

```python
# LONG-side zone (lower_wick / body_bottom), approach сверху:
def label_long(D, zone_lo, zone_hi):
    touched = D.low <= zone_hi
    if not touched: return None        # нет test event
    return "R" if D.close >= zone_lo else "B"

# SHORT-side zone (upper_wick / body_top) — зеркально:
def label_short(D, zone_lo, zone_hi):
    touched = D.high >= zone_lo
    if not touched: return None
    return "R" if D.close <= zone_hi else "B"
```

**Population:** 1 zone → N test events (каждое касание = новое event).

**Эквивалентность с user canon:** «(b) видимый отбой (фитиль в зону / close на стороне подхода)» автоматически следует из (a) `not closed beyond` + touched. См. `[[feedback-maxv-reaction-definition]]`.

## 5. Параметры (полный список)

### Структурные гиперпараметры (меняют сигнал, дорогой regen)

| Param | Значение | Что меняет |
|-------|----------|-----------|
| `mlt` | 45 | LTF aggregation (D → 32m) — Pine canon |
| `ATR_N` | 20 | rolling ATR window (для W_vol) |
| `α` | 0.30 | ширина зоны как % R_parent |
| `σ_coeff` | 0.5 | σ = R × σ_coeff (Gaussian) |

### AMP-веса (скаляры в формуле)

| Param | Значение | Условие |
|-------|----------|---------|
| `W_pos_wick` | 1.5 | C1 |
| `W_pos_body` | 0.7 | C1 |
| `K_age` | 0.3 | C2 |
| `D_age` | 30 | C2 |
| `K_V` | 3.0 | C3 |
| `TAU` | 7 | C3 |
| `W_broken_val` | 1.8 | C4 |
| `W_vol_clip_lo` | 0.5 | C5 |
| `W_vol_clip_hi` | 2.0 | C5 |

**Итого: 4 структурных + 9 AMP-весов = 13 базовых.**

### Опциональные (открытые)

| Param | Если введём |
|-------|-------------|
| `W_age_cap` | `min(W_age, 2.0)` |
| `TAU_brk` | decay `W_broken = 1 + 0.8·exp(-t/TAU_brk)` |
| `medV_N` | отдельно от ATR_N |
| `drift_threshold` | если введём drift-класс |

## 6. Pipeline canon

| Phase | Содержание | Hardware | Status |
|-------|-----------|----------|--------|
| 0.1 | Fix `maxv_master_dataset_6m.py` zone formula | Mac | **TODO** |
| 0.2 | `phase0_reaction_regen.py` (new) — labels R/B | Mac | **TODO** |
| a | Meta-labeling (heuristic AMP primary + LR/RF secondary), chrono 80/20 + embargo=12D | Mac (6 мес) | TODO |
| a+ | Purged K-Fold (n=5), Walk-Forward Anchored monthly retrain, calibrate 13 params | **PC** (6 лет) | TODO |
| b | CPCV (N=24, k=4) + PSR/DSR + PBO | **PC** | TODO |
| c | Multi-TF расширение + heatmap confluence meta-feature | **PC** | TODO |

## 7. Скрипты и их состояние

| Файл | Zone canon | Mit canon | Label | Status |
|------|-----------|-----------|-------|--------|
| `~/smc-lib/scripts/maxv_amplified_chart_single.py` | ✅ 30%×R clip | ✅ level | viz only | **canon Phase 1** |
| `~/smc-lib/scripts/maxv_master_dataset_6m.py` | ❌ mb_l/mb_h | n/a | n/a | needs Phase 0.1 |
| `~/smc-lib/scripts/maxv_phase0_d_regen.py` | ❌ из master | ✅ level | ❌ TBM | deprecated, нужен reaction-regen |
| `~/smc-lib/indicators/vic_asvk.py` | n/a | n/a | ❌ maxV = dominant group | bug |

## 8. Литература (источники priors)

| Книга | Применение |
|-------|-----------|
| **Williams — Master the Markets** | VSA: wick rejection >> body continuation; volume concentration matters |
| **Nison — Japanese Candlestick** | pin bar reversal at extremes; confluence with старые S/R |
| **Lopez de Prado — Advances in Financial ML** | TBM (Ch 3.4, заменили на reaction), sample weights (Ch 4), Purged K-Fold (Ch 7), CPCV (Ch 12), PSR/DSR (Ch 14), meta-labeling (Ch 3.6) |

См. `~/smc-lib/literature/notes_lopez_de_prado.md`.

## 9. Strategy spec — ">5% reversal" (черновик, не валидирован)

**Setup (long):**
1. D-свеча тестирует maxV zone (lower_wick / body_bottom)
2. AMP ≥ AMP_threshold (top quartile, эмпирически после Phase a)
3. Confluence: ≥1 другая maxV zone того же направления в ±1% от entry
4. W_v ≥ 2.0 (virgin или recently-broken-defense)

**Execution:**
- Entry: next bar open после D-close теста (variant A, no within-bar lookahead)
- Stop: D close beyond zone OR −1.5 × ATR(20) hard
- Target PT1: +5% (50% size out), PT2 = trailing к next maxV zone same dir
- t1 vertical: 10 D bars

**Risk:** Kelly half / fixed 0.5% equity per trade.

**Short — зеркально.**

**Status:** dry spec, требует Phase a-b валидации. **НЕ деплоить без backtest.**

## 10. Открытые вопросы

1. W_age cap (log без cap → 2.24 на 5y)
2. W_broken decay (сейчас константа 1.8, crossover ~12d)
3. N test events per zone (first only или все subsequent re-tests)
4. Drift class (D close внутри zone — R по формуле, но возможно отдельный)
5. α=0.30 → эмпирически после Phase a
6. >5% target validity для всех regime'ов (bull/bear/range)

## Related memory

- `[[maxv-force-model-5-conditions]]` — snapshot (mirror этого doc)
- `[[feedback-maxv-zone-30pct-parent-range]]`
- `[[feedback-maxv-mitigation-is-level-touch]]`
- `[[feedback-maxv-reaction-definition]]`
- `[[feedback-vic-maxv-absolute-not-sided]]`
- `[[feedback-pine-ltf-d-chart-integer-rule]]`
- `[[feedback-vic-maxv-chart-style]]`
- `[[feedback-untraded-area-is-magnet]]`
- `[[feedback-heavy-compute-on-pc]]`
