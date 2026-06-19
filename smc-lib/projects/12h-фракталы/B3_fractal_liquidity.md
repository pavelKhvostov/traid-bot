# B3 — Fractal Liquidity

Третья основная зона интереса по таксономии user'а ([[zone-class-liquidity-inefficiency-block]]):
- **liquidity** ← этот блок (фракталы, equal highs/lows, объёмные ликвидные уровни)
- **inefficiency** — FVG (см. B1)
- **блок (OB)** — Order Block + ob_liq (см. B2)

С 2026-06-06 объединяет sub-условия по ликвидности; первое реализованное — снятие maxV-уровня (объём-проксированная ликвидность).

## Sub-conditions

### B3C1 — maxV sweep (i-1)

Был **C1** в старом каноне → B2 → **B7 → B3C1** (2026-06-06 переосмыслен как fractal liquidity sub).

```
maxV_level(i-1) — close LTF-бара с абсолютным max-vol внутри 12h-бара i-1
                  (per memory [[feedback-vic-maxv-absolute-not-sided]])

B3C1 fires при pivot i, если:
  FH:  high[i] ≥ maxV_level(i-1)
  FL:  low[i]  ≤ maxV_level(i-1)
```

**Causality:** ✅ maxV computed on bar i-1 (past), check on bar i (current).

**Цифры (на A4-baseline 1356, canonical 2026-06-06):**
n = 375 · conf = 282 · **WR 75.20%** · Δ +26.60 pp

**Обоснование как «fractal liquidity»:** maxV-level — это точечный уровень с максимальной объёмной активностью на родительском баре. По smart-money трактовке это **точка концентрации ликвидности** на микро-структуре (хотя формально не фрактал Уильямса). Объёмный аналог классической fractal liquidity.

## Канон / код
- Канон maxV: [[maxv-force-model-5-conditions]], [[feedback-maxv-zone-30pct-parent-range]]
- LTF detection: [[feedback-pine-ltf-d-chart-integer-rule]]
- Detector: `~/smc-lib/elements/maxv/` (если есть) или `vic_asvk.py`
- Basket scoring: `~/smc-lib/scripts/pred12h_basket_c1c2c3.py`

## TODO
- Пересчитать B3C1 на A4-baseline 1356 (окно 2020-01-01 → now)
- Causality-аудит ([[feedback-b-series-strict-causal-i]])
- Возможные B3Cx (классическая «чистая» fractal liquidity):
  - **B3C2** — sweep Williams n=2 фрактала (раннее снятие)
  - **B3C3** — equal highs / equal lows sweep (EQH/EQL liquidity pool)
  - **B3C4** — swing pivot sweep (HTF major fractal)
  - **B3C5** — sweep с volume confirmation (объёмная подпитка ликвидности)
  - **B3C6** — sweep с iFVG mitigation (fractal + inefficiency confluence)

## Связанные memories
- [[zone-class-liquidity-inefficiency-block]] — таксономия зон
- [[feedback-fractal-liquidity-strength-and-sweep]] — сила и sweep фрактальной ликвидности (TF × age × cluster)
- [[maxv-force-model-5-conditions]] — maxV-модель
- [[feedback-b-series-strict-causal-i]] — strict causality для B-серии
