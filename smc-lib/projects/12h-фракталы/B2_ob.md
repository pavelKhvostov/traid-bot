# B2 — OB (Order Block)

Был **C7** = `block_orders` в старом каноне. Перенесён на позицию **B2** как вторая основная зона интереса после FVG.
С 2026-06-06 включает sub-условие на ob_liq (ранее отдельный B4).

## Идея

«Снятие OB» — первое касание/прокол ордер-блока на pivot bar (multi-TF) указывает на формирование Williams n=2 фрактала.

OB — одна из трёх канонических SMC-зон по таксономии user'а ([[zone-class-liquidity-inefficiency-block]]):
- **liquidity** — фракталы, equal highs/lows
- **inefficiency** — FVG, marubozu (см. B1)
- **блок (OB)** — этот блок

## Sub-conditions

### B2C1 — FIRST 50%-sweep OB (multi-TF)

Первое 50%-снятие OB-зоны на pivot bar.
Multi-TF: 12h ∪ D ∪ 2D ∪ 3D ∪ W.

**Causality:** ✅ событие на баре i (sweep level + close), zone создана ≤ i.

**Цифры (на A4-baseline 1356, canonical 2026-06-06):**
n = 58 · conf = 52 · **WR 89.66%** · Δ +41.06 pp ⭐

### B2C2 — FIRST 50%-sweep ob_liq (multi-TF)

Был отдельным **B4** до 2026-06-06; перенесён сюда как sub-условие OB-семейства.

Первое 50%-снятие **ob_liq** зоны (узкий 2-свечный, 2-условный маркер, БЕЗ Williams-фрактальности — см. [[feedback-ob-liq-no-fractality]]).
Multi-TF: 12h ∪ D ∪ 2D ∪ 3D ∪ W.

**ob_liq ≠ OB** ([[feedback-ob-vs-ob-liq-zones-differ]]): отдельный детектор с собственной (узкой) зоной интереса. Объединение в одном B2 — структурное (оба класса «блок»), не геометрическое.

**Causality:** ✅ событие на баре i, zone ≤ i.

**Цифры (на A4-baseline 1356, canonical 2026-06-06):**
n = 73 · conf = 50 · **WR 68.49%** · Δ +19.89 pp

### B2 union (canonical 2026-06-06)

`B2 = B2C1 ∪ B2C2`. **n = 105 · conf = 79 · WR = 75.24% · Δ +26.64 pp.**

Overlap B2C1 ∩ B2C2 = 58 + 73 − 105 = 26 событий (≈ 30% от B2C1).

## Канон / код

- OB элемент: `~/smc-lib/elements/` (искать ob / order_block)
- ob_liq элемент: `~/smc-lib/elements/ob_liq/` (2-свечный, 2-условный)
- Memory: [[zone-class-liquidity-inefficiency-block]] — таксономия зон
- Memory: [[feedback-ob-vs-ob-liq-zones-differ]] — OB ≠ ob_liq
- Memory: [[feedback-ob-liq-no-fractality]] — ob_liq БЕЗ Williams
- Basket scoring: `~/smc-lib/scripts/pred12h_basket_c1c2c3.py`

## TODO

- Пересчитать B2C1, B2C2 и union на A4-baseline 1356 (окно 2020-01-01 → now)
- Изучить overlap B2C1 ∩ B2C2 — насколько ob_liq и OB ловят одни и те же pivot'ы
- Возможные B2C3..B2C7 (по образцу B1):
  - B2C3 — OB + AGE filter
  - B2C4 — OB + WIDE filter (по ATR)
  - B2C5 — OB sweep depth grid (S70/S100)
  - B2C6 — OB retest (close inside после первого sweep)
  - B2C7 — OB vol_spike (sweep + volume z ≥ +2σ)
- Causality-аудит каждого B2Cx по правилу [[feedback-b-series-strict-causal-i]]
