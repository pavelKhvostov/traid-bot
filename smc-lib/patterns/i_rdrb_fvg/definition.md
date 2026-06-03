# i-RDRB с последующим FVG

5-свечный композитный паттерн: [[i-RDRB]] (C1-C4) + [[FVG]] (C3-C4-C5) **той же направленности**, что и i-RDRB.

Это **основной паттерн** баклога стратегий проекта (см. forensic 1h baseline на 780 закрытых сделок, RR=2.2). FVG после displacement-свечи C4 — обязательное усиление reversal.

## Свечи

C1, C2, C3, C4, C5 — пять последовательных свечей.

| Под-паттерн | Свечи в i-RDRB+FVG | Свечи в под-элементе |
|---|---|---|
| i-RDRB | C1, C2, C3, C4 | C1, C2, C3, C4 |
| FVG    | C3, C4, C5      | FVG.c1, FVG.c2 (displacement), FVG.c3 |

Маппинг для FVG: `FVG.c1 = C3, FVG.c2 = C4, FVG.c3 = C5`.

## Условия

1. **i-RDRB на (C1, C2, C3, C4)** — см. `elements/i_rdrb/definition.md`. Направление i-RDRB всегда **противоположно** направлению подлежащего RDRB.
2. **FVG на (C3, C4, C5)** — см. `elements/fvg/definition.md`.
3. **Направления совпадают**: `fvg.direction == i_rdrb.direction`.

C4 одновременно играет роль displacement-свечи для i-RDRB (reversal) и для FVG (gap-leaving).

## Направление

| RDRB (C1-C3) | i-RDRB | FVG требуется | i-RDRB+FVG |
|---|---|---|---|
| SHORT (C2 bear) | LONG (C4 bull, close > block.top) | LONG (C3.high < C5.low) | **LONG** |
| LONG (C2 bull) | SHORT (C4 bear, close < block.bottom) | SHORT (C3.low > C5.high) | **SHORT** |

## Зоны

Все зоны наследуются от под-элементов без модификации:

- **i-RDRB.rdrb.block / poi / liq** — зоны входа / интереса / ликвидности из подлежащего RDRB.
- **FVG.zone** — зона неэффективности после displacement (C4).

Для бэктестов baseline используются:
- `entry = (block.bottom + block.top) / 2` (середина block)
- `SL = min(C1..C5 lows)` для LONG / `max(C1..C5 highs)` для SHORT
- `TP = entry ± RR × R_unit`, RR ∈ [1.0, 3.0]

## Эталонный пример — SHORT i-RDRB+FVG

BTCUSDT 4h, 2026-05-20 23:00 → 2026-05-21 15:00 MSK (UTC+3):

| Свеча | Время MSK | O | H | L | C |
|---|---|---|---|---|---|
| C1 | 2026-05-20 23:00 | 77667.49 | 77766.60 | 77226.61 | 77552.23 |
| C2 | 2026-05-21 03:00 | 77552.24 | 78173.15 | 77525.00 | 78078.72 |
| C3 | 2026-05-21 07:00 | 78078.72 | 78180.01 | 77521.00 | 77889.01 |
| C4 | 2026-05-21 11:00 | 77889.01 | 78200.00 | 77147.15 | 77189.10 |
| C5 | 2026-05-21 15:00 | 77189.10 | 77402.12 | 76719.47 | 77259.46 |

**Под-RDRB (C1-C3)**: LONG (C2 bull).
**i-RDRB (C1-C4)**: SHORT (C4 bear, close 77189.10 < block.bottom).
**FVG (C3, C4, C5)**: SHORT, `C3.low (77521.00) > C5.high (77402.12)`, zone = `[77402.12, 77521.00]`.
**Совпадение направления**: SHORT == SHORT ✓ → **SHORT i-RDRB+FVG**.

## Связанные элементы

- `rdrb` — подлежащая 3-свечная структура
- `i_rdrb` — 4-свечный reversal
- `fvg` — 3-свечный gap

## Forensic baseline (для справки)

На BTC 1h за 6 лет: ~780-808 закрытых сделок при entry=mid-block, SL=pattern_extreme, RR=2.2 → WR ~36.67%, ΣR +135. Используется как baseline для всех фильтров (F1 HTF OB, F2 HTF RDRB, EVoT, R/ATR sweet spot и др.).
