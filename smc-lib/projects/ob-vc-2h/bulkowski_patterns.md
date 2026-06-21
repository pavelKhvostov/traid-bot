# Bulkowski Patterns Catalog — применимость к 2h ob_vc

**Цель:** при формировании 2h ob_vc setup'а получить **decision Enter/Skip** на базе Bulkowski-патернов + ML model.

**Контекст:** baseline +407R / WR 56.3% / 3,378 trades за 6y (после A1 drop). Tier 1 (B1 fires) = WR 64.5%. Хотим поднять WR на +5-10 pp.

**Honest constraint:** прошлая попытка (Phase 4 ML на ob_vc + tabular features) дала AUC 0.510 — **хуже** Phase 3 (0.540). Tabular ML потолок ~0.55. Поэтому ожидания: marginal lift +2-5 pp, не +20.

---

## Bulkowski's core concepts

1. **Empirical stats** — каждый pattern имеет реальные исторические данные:
   - **Failure rate** — % случаев когда pattern не дал ожидаемого move
   - **Average rise/decline** — средний move после breakout
   - **Throwback/pullback rate** — % случаев когда цена откатилась к neckline после breakout
   - **Volume signature** — нужный volume профиль для confirmation

2. **Busted patterns** — failed pattern даёт сильное движение в противоположную сторону. Это часто более прибыльно чем сам pattern.

3. **Context matters** — bull market vs bear market, timeframe, breakout direction.

4. **Throwback expectation** — entry после throwback к neckline даёт лучший R/R чем чистый breakout.

---

## 15 patterns most relevant for 2h ob_vc

### REVERSAL patterns (для LONG ob_vc — нужны bullish, для SHORT — bearish)

#### 1. Double Bottom (W-pattern) — LONG ⭐⭐⭐
**Геометрия:** 2 минимума на ≈одинаковом уровне (within 3%), разделённых rally up ≥10%. Neckline = top между ними.

**Bulkowski stats (Adam & Eve DB):**
- Failure rate: 4% (one of the most reliable)
- Average rise after breakout: 38%
- Throwback rate: 64%

**Relevance for ob_vc:** если 2h ob_vc LONG формируется НА уровне второго bottom (или после breakout neckline'а) → strong confluence.

**Detection complexity:** **средняя** (ZigZag-based).

#### 2. Double Top (M-pattern) — SHORT ⭐⭐⭐
Mirror of Double Bottom.
- Failure rate: 8%
- Average decline: 21%
- Pullback rate: 69%

#### 3. Triple Bottom — LONG ⭐⭐
**Геометрия:** 3 минимума на ≈одинаковом уровне.
- Failure rate: 4%
- Average rise: 41%

**Detection:** **сложная** (нужны 3 swings).

#### 4. Triple Top — SHORT ⭐⭐
Mirror.

#### 5. Inverse Head & Shoulders — LONG ⭐⭐⭐
**Геометрия:** 3 minima: left shoulder, head (lowest), right shoulder. Neckline соединяет 2 peaks между ними.

**Bulkowski stats:**
- Failure rate: 3% (one of most reliable bullish)
- Average rise: 45%
- Throwback rate: 50%

**Relevance:** 2h ob_vc near right shoulder bottom или после neckline breakout — мощный сигнал.

**Detection:** **сложная** (3 swings + neckline geometry).

#### 6. Head & Shoulders Top — SHORT ⭐⭐⭐
Mirror.
- Failure rate: 4%
- Average decline: 22%

#### 7. Rounding Bottom (Saucer) — LONG ⭐
**Геометрия:** smooth U-shape minimum (низкая волатильность).
- Failure rate: 5%
- Average rise: 43%

**Detection:** **очень сложная** (требует smoothness check).

#### 8. Bullish Engulfing (candlestick) — LONG ⭐⭐
**Геометрия:** prev bearish candle полностью engulfed bull candle.
- Reliability: medium (context-dependent)

**Detection:** **простая** (1-2 строки кода).

**Relevance:** если предыдущая 4h или 1D bar = Bullish Engulfing → context для LONG ob_vc.

#### 9. Hammer / Inverted Hammer — LONG ⭐⭐
**Геометрия:** long lower wick, small body на top, short upper wick.
- Reliability: medium-high after downtrend

**Detection:** **простая** (wick/body ratio).

### CONTINUATION patterns (для confirmation существующего тренда)

#### 10. Ascending Triangle — LONG ⭐⭐
**Геометрия:** flat resistance + rising support (higher lows).
- Failure rate: 11%
- Average rise: 35%
- Breakout direction: up 70%

**Relevance:** 2h ob_vc LONG после breakout ascending triangle = strong confluence.

**Detection:** **средняя**.

#### 11. Descending Triangle — SHORT ⭐⭐
Mirror.

#### 12. Symmetrical Triangle — context ⭐
**Геометрия:** converging trendlines (lower highs + higher lows).
- Failure rate: 12% (breakout in expected direction)
- Bias: continuation pattern

**Use:** breakout direction unclear → wait for confirmation.

#### 13. Bull Flag / Bear Flag — context ⭐⭐
**Геометрия:** sharp move (flagpole) + consolidation parallel channel.
- Failure rate: 4-8%
- Continuation pattern

**Relevance:** 2h ob_vc после flag breakout = trend confluence.

### BUSTED patterns (Bulkowski's edge!)

#### 14. Busted Bearish Pattern → LONG ⭐⭐⭐
**Концепция:** недавний Bear Flag / Descending Triangle / Double Top **сломан** (breakout вверх вместо ожидаемого вниз).

**Bulkowski insight:** busted patterns дают **stronger move** чем сам pattern. Performance ranks высоко.

**Relevance:** 2h ob_vc LONG в зоне busted bearish pattern = **очень сильный** сетап.

**Detection:** **средняя** (нужно идентифицировать pattern + проверить busted condition).

#### 15. Busted Bullish Pattern → SHORT ⭐⭐⭐
Mirror.

---

## Priority matrix для MVP

| # | Pattern | Bulkowski reliability | Detection | MVP priority |
|---|---|---|---|---|
| 1 | Double Bottom | ⭐⭐⭐ 4% fail | средняя | **TOP** |
| 2 | Double Top | ⭐⭐⭐ 8% fail | средняя | **TOP** |
| 8 | Bullish Engulfing | ⭐⭐ context | простая | **TOP** (quick win) |
| 9 | Hammer | ⭐⭐ context | простая | **TOP** (quick win) |
| 14 | Busted Bearish | ⭐⭐⭐ strong | средняя | **TOP** (edge) |
| 15 | Busted Bullish | ⭐⭐⭐ strong | средняя | **TOP** (edge) |
| 5 | Inverse H&S | ⭐⭐⭐ 3% fail | сложная | Phase 2 |
| 6 | H&S Top | ⭐⭐⭐ 4% fail | сложная | Phase 2 |
| 10 | Ascending Triangle | ⭐⭐ 11% fail | средняя | Phase 2 |
| 11 | Descending Triangle | ⭐⭐ 11% fail | средняя | Phase 2 |
| 13 | Bull/Bear Flag | ⭐⭐ 4-8% fail | средняя | Phase 2 |
| 3,4 | Triple Top/Bot | ⭐⭐ 4% fail | сложная | Phase 3 |
| 7 | Rounding Bottom | ⭐ 5% fail | оч. сложная | Skip |
| 12 | Symmetrical Triangle | ⭐ neutral | средняя | Skip |

---

## MVP scope (today)

**Build detectors for 6 patterns:**
1. Bullish Engulfing (4h, 1D) — простая
2. Bearish Engulfing (4h, 1D) — простая
3. Hammer (4h, 1D) — простая
4. Double Bottom (1D ZigZag-based) — средняя
5. Double Top (1D ZigZag-based) — средняя
6. Busted Bear Flag → LONG / Busted Bull Flag → SHORT — средняя

**Detection window:** последние 30 дней до born_ms (Bulkowski патерны обычно formed in 1-12 weeks).

**Output per ob_vc setup:** 6 binary features + pattern age (bars since formation).

**Validation:**
- Per-pattern WR uplift (split: in/out)
- Combined model: logistic regression на 6 features + B1 + n_FVG + R%
- Walk-forward 1y train / 6m test rolling
- Compare vs B1 baseline (WR 64.5%)

---

## Risks and honest expectations

1. **Tabular ML ceiling** — AUC 0.55 limit на ob_vc context per Phase 4 result.
2. **Pattern detection noise** — ZigZag-based detection чувствительна к parameter choice (1% vs 2% vs 3%).
3. **Selection bias** — Bulkowski stats на equity markets, не на crypto/BTC.
4. **Timeframe mismatch** — большинство Bulkowski stats на daily/weekly equity bars; 2h crypto другой regime.

**Honest goal:** найти **1-2 features** которые дают +2-5 pp WR uplift, не all-in expectation +20 pp.

---

## Next steps

1. ✅ Catalog patterns (this doc)
2. ⏳ Implement 6 detectors (`bulkowski_detectors.py`)
3. ⏳ Compute features for all 3,378 setups
4. ⏳ Per-pattern WR uplift analysis
5. ⏳ Logistic regression on 6 features
6. ⏳ Walk-forward validation
7. ⏳ Decision threshold tuning
8. ⏳ If positive: production decision API

## Связи
- [[ob-vc-2h-filters-a1-b1]] — current baseline (A1+B1)
- [[bb-model-phase4-negative-result]] — prior Phase 4 failure (AUC 0.510)
- [[feedback-heavy-compute-on-pc]] — heavy ML → Windows PC
- [[ob-vc-2h-24-types-wick-ratio]] — 24-type classification
