# run_3candles_sweep

3-свечный паттерн liquidity grab внутри однонаправленного run. Симметричен для LONG/SHORT.

Эталон: BTC 8h, 2026-05-26 03:00 MSK (c1) → 11:00 (c2 sweep) → 19:00 (c3). См. [[2026-05-27-run_3candles_sweep-introduction]].

## Условия

Три последовательные свечи `c1, c2, c3`. Все одного направления. Средняя свеча `c2` выносит экстремум `c1` своим фитилём; этот фитиль доминирует над телом c2.

### SHORT (3 bear)

```
1. c1, c2, c3 — все bear (close < open), ни одна не doji
2. c2.high > c1.high                              ← wick c2 снял high c1
3. c2.upper_wick ≥ 2.5 × c2.body                  ← wick доминирует над телом

где:
  upper_wick = c2.high - max(c2.open, c2.close)
  body       = |c2.open - c2.close|
```

### LONG (3 bull) — зеркально

```
1. c1, c2, c3 — все bull (close > open), ни одна не doji
2. c2.low < c1.low                                ← wick c2 снял low c1
3. c2.lower_wick ≥ 2.5 × c2.body

где:
  lower_wick = min(c2.open, c2.close) - c2.low
  body       = |c2.open - c2.close|
```

## Семантика

Liquidity grab внутри однонаправленного движения: средняя свеча резко выносит стопы за c1, но в итоге группа из 3 свечей остаётся однонаправленной. **Trend continuation with sweep** — продолжение в направлении паттерна после захвата ликвидности.

## Зона интереса

Зона интереса = **полоса фитиля c2** (sweep zone):
- SHORT: `[max(c2.open, c2.close), c2.high]`
- LONG: `[c2.low, min(c2.open, c2.close)]`

Это область выноса ликвидности — туда цена потенциально возвращается перед continuation.

## Торговый сетап (continuation)

После подтверждения паттерна на close c3:

| Параметр | SHORT | LONG |
|---|---|---|
| **Direction** | SHORT (continuation) | LONG (continuation) |
| **Entry** | `max(c2.o, c2.c) + 0.3 × upper_wick` (= 30% внутрь wick от тела) | `min(c2.o, c2.c) - 0.3 × lower_wick` |
| **SL** | `c2.high` (экстремум wick) | `c2.low` |
| **TP** | `c3.low` | `c3.high` |

Entry — pullback limit order. Ждём возврата цены в wick c2 на 30% уровне, затем SHORT/LONG с SL за экстремумом c2 и TP на c3.low/c3.high.

### Эталон расчёта (BTC 8h SHORT 2026-05-26)

```
c1 = 05-26 03:00 MSK BEAR  O=77322 H=77345 L=76476 C=76731
c2 = 05-26 11:00 MSK BEAR  O=76731 H=78080 L=76273 C=76518
c3 = 05-26 19:00 MSK BEAR  O=76518 H=76710 L=75779 C=76115

c2.upper_wick = 78080 - max(76731, 76518) = 78080 - 76731 = 1349
c2.body       = |76731 - 76518| = 213
ratio         = 1349 / 213 = 6.34  ≥ 2.5 ✓
c2.high (78080) > c1.high (77345) ✓
3 bears подряд ✓

Entry SHORT = 76731 + 0.3 × 1349 = 77136
SL          = 78080
TP          = 75779

Risk   = 78080 - 77136 = 944
Reward = 77136 - 75779 = 1357
RR     = 1357 / 944    = 1.44
```

## Чем НЕ является

- Не reversal паттерн — это **continuation** (3 свечи остаются в одном направлении)
- Не sweep HTF fractal — wick сравнивается ТОЛЬКО с c1 (предыдущая bar), не со swing high
- Не OB — нет требования прот-направленного prev

## Применение

| Контекст | Использование |
|---|---|
| Standalone strategy | Entry/SL/TP даны — полный сетап |
| OR-basket condition | Можно использовать как Условие в композиции (например для 12h Pred-фрактала, если применимо) |
| Confluence | sweep wick c2 = HTF zone of interest для следующих движений |

## TF и активы

Эталон зафиксирован на BTC 8h. Универсальность по TF и активам — TBD (требует валидации).
