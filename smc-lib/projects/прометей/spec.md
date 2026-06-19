# Прометей — spec (Phase 0 draft)

**Status:** Phase 0 draft, 2026-06-14
**Lineage:** Continuation of [[project-пример-анализа-рынка]] session-01 learnings

## 1. Цель

ML на BTC 1h cadence, предсказывает на каждом snapshot:
- **Q1: Strong level of day** — какой из active SMC zones будет «тот самый» уровень дня
- **Q2: Direction after touch** — вверх / вниз / no reaction
- **Q3 (опц.):** magnitude of move from level

## 2. Feature inputs — ТОЛЬКО SMC

Никаких MA/EMA/HMA, Lopez, macro, divergences, sessions в primary feature set.

### Group A: SMC Element Panel (canon-aware)

Per (TF × element_type) — **16 элементов × 8 TF = 128 токенов**. Per token:

**Active state:**
- `n_active_long` — number of active LONG zones of this type
- `n_active_short` — number of active SHORT zones
- `nearest_long_dist_pct` — distance % to nearest active LONG (signed: -if below price, + if above)
- `nearest_short_dist_pct` — то же для SHORT
- `nearest_long_age_bars` — bars с момента formation
- `nearest_short_age_bars`
- `nearest_long_mit_count` — n_real_mitigations (canon wear-down)
- `nearest_short_mit_count`

**Breaker state (role inverted):**
- `n_breakers_above` — count of LONG-OB→Breaker (now SHORT resistance) above price
- `n_breakers_below` — count of SHORT-OB→Breaker (now LONG support) below
- `nearest_breaker_above_dist_pct`
- `nearest_breaker_below_dist_pct`
- `nearest_breaker_age` — recency

**Consumed (context only, not actionable):**
- `n_consumed_long_5pct_below` — sense of "demand exhaustion"
- `n_consumed_short_5pct_above` — sense of "supply exhaustion"

Per token: ~14-16 фич × 128 tokens = ~1800-2050 фич just for Group A.

### Group B: Williams sweep tracker (separate element type)

8 TF × per-TF:
- `dist_to_nearest_unswept_FH_pct` (BSL)
- `dist_to_nearest_unswept_FL_pct` (SSL)
- `age_of_nearest_FH` / `_FL`
- `n_unswept_FH_within_10pct` / `_FL`
- `n_swept_FH_24h` / `_FL`

~6 фич × 8 TF = 48 features.

### Group C: Confluence (cross-element)

- `n_zones_overlapping_at_price` — сколько разных element-instances overlap at current price (any TF)
- `n_long_zones_within_2pct_above`
- `n_short_zones_within_2pct_below`
- `confluence_score` — weighted by TF (W > D > 12h > ...)
- `n_consecutive_breakers_above` — supply consolidation count
- `n_consecutive_breakers_below` — demand consolidation
- `is_inside_active_long_zone` (bool, any TF)
- `is_inside_active_short_zone`
- `is_inside_active_breaker_above` (would-act as resistance)
- `is_inside_active_breaker_below`

~15-20 фич.

### Group D: Structural state

- Last CHoCH direction + age
- Inducement state (within X bars)
- Mitigation Block active state
- Current trend label (HH+HL / LL+LH / chop) — derived from Williams chain

~10-15 фич.

**Total Primary SMC features ≈ 1900-2150.**

## 3. Targets

### Q1: Strong level of day (per-snapshot)

Per snapshot, output **ranked list of active zones with probability**:
- Input: list of all active zones (passed per snapshot from SMC element panel)
- Output: P(zone X = strong level today)
- Training: историческое определение, какая зона реально была «strong level»

**Definition of «strong level» (need to lock):**
- Option A: ближайшее зона, где price реально отреагировала (rejection or major react)
- Option B: zone where price spent most time during the day
- Option C: zone где формировалось daily high or daily low
- Option D: zone with max institutional volume (если есть данные)

**Open question for user.** Predлагаю Option A initially.

### Q2: Direction after touch

Given «strong level X identified», predict:
- P(reversal — opposite direction after touch)
- P(continuation — same direction after touch)
- P(no clear reaction)

Binary head per direction (rejection up vs down).

### Q3: Magnitude (opt)

Quantile regression на |move| within 24h after touch.

## 4. Architecture (proposal)

**2-stage:**
- **Stage A (Strong-level scorer):** input = snapshot features + per-level meta; output = ranked level list. LightGBM ranker or pairwise scoring.
- **Stage B (Reaction predictor):** input = stage A top-1 level + features; output = direction probability. Binary LightGBM.

Alternative: **single multi-output model** — output binary flag per zone + direction conditional. Use single architecture с adversarial loss.

Lock в Phase 1 после baseline test.

## 5. Validation methodology (Lopez canon — обязателен)

- Train: 2020-2024
- Holdout: 2025-2026.05
- Purged K-Fold (5 fold) + embargo=24 (1h cadence)
- Time-decay sample weights (новые сэмплы важнее)
- Per-regime calibration

## 6. Goals quantified

- Q1 top-1 precision ≥ 70% (если top-ranked level — actual reaction zone)
- Q2 AUC ≥ 0.75 (direction prediction)
- Holdout-CV consistency: |Δ| < 0.05

## 7. Phase plan

| Phase | Goal | Срок |
|---|---|---|
| **0** | Spec lock, decisions | ✅ done |
| **1** | Detector pipeline: на 1h cadence, для каждого snapshot — список active SMC instances со mitigation state | 3-5d |
| **2** | Feature engineering (Groups A-D, ~2000 фич) | 5d |
| **3** | Target definition lock (Q1, Q2) + label generation | 3d |
| **4** | Baseline train: Stage A (ranker) + Stage B (direction) | 5d |
| **5** | Walk-forward + ablation per group | 4d |
| **6** | Refinement / production output | 3d |

**Total: ~3-4 weeks** на PC1.

## 8. Decisions locked

| # | Решение | Источник |
|---|---|---|
| 1 | SMC = primary, никаких других feature groups в Phase 1 | User 2026-06-14: «SMC = самое ценное, я делаю WR без других» |
| 2 | Canon-aware mitigation tracking обязательно (apply_mitigation) | learnings session-01 |
| 3 | Все 16 SMC элементов + Williams + breakers + mit blocks | per [[feedback-smc-canon-checklist]] |
| 4 | BTC only, 1h cadence | per [[project-vc-daily-forecast]] decisions |
| 5 | Walk-forward Lopez canon (Purged K-Fold + embargo + time-decay) | mandatory |

## 9. Open questions для user

1. **Strong level definition (Q1 target):**
   - (A) Ближайшая zone где реально отбоились
   - (B) Zone where price spent most time
   - (C) Daily extremes zones
   - (D) Custom rule
2. **Direction definition (Q2):**
   - Binary (LONG reaction vs SHORT)
   - Ternary (LONG / SHORT / no react)
   - Magnitude-weighted
3. **Architecture preference:**
   - 2-stage (рекомендую начать)
   - Multi-head single model
4. **Confluence weight:** TF-based (W > D > 12h) — какие weights?

## 10. Related memory

- [[feedback-smc-canon-checklist]] — must-read перед каждым action
- [[feedback-fvg-c2-intrusion-rule]] — FVG consumption canon
- [[project-vc-daily-forecast]] — broader sibling project
- [[project-пример-анализа-рынка]] — analysis sessions where canon learnings происходили
- [[reference-andrey-12h-branch]] — NOT applicable (mixed-feature approach)
