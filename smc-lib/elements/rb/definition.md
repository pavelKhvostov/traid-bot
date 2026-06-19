# RB (Rejection Block)

Одиночная свеча с **явно выраженным доминирующим фитилём**, который отвергает уровень в одну сторону. Доминирующий фитиль в 2 раза больше второго фитиля и в 3 раза больше тела свечи.

> **Не путать** с canon-OB (2-свечная пара), `ob_liq` (canon-OB + Williams-маркер) и `block_orders` (N+M композит).

## Свечи

Одна свеча с OHLC. Цвет тела (bull/bear) **не имеет значения** — определяющая геометрия — соотношение виков и тела.

## Направление и условия

| Направление | Условие |
|---|---|
| **TOP RB** (bearish rejection) | `upper_wick ≥ 2 × lower_wick` AND `upper_wick ≥ 3 × body` |
| **BOTTOM RB** (bullish rejection) | `lower_wick ≥ 2 × upper_wick` AND `lower_wick ≥ 3 × body` |

Где:
```
upper_wick = high - max(open, close)
lower_wick = min(open, close) - low
body       = |open - close|
```

Дополнительные требования:
- `body > 0` (не doji — иначе деление на ноль и теряется смысл K2-фильтра)
- `other_wick > 0` (иначе деление на ноль в K1; «другой фитиль = 0» — это вырожденная марузу-с-фитилём, не RB)

## Зона интереса

**Зона интереса = зона доминирующего фитиля.**

| Направление | Зона интереса |
|---|---|
| TOP RB | `[max(open, close), high]` |
| BOTTOM RB | `[low, min(open, close)]` |

## Mitigation canon (2026-06-15 — FINAL)

**First-touch по entry-level 0.5** (середина wick'a), а НЕ по внешнему краю зоны.

| Направление | Consume trigger |
|---|---|
| **BOTTOM RB** (LONG support) | `bar.low ≤ (low + body_bottom) / 2` (= mid wick = entry-level) |
| **TOP RB** (SHORT resist) | `bar.high ≥ (body_top + high) / 2` (= mid wick = entry-level) |

**Обоснование:** RB считается «отработанным» когда цена дала возможность взять сделку (= entry-level), а не когда просто слегка коснулась внешнего края wick'a. Согласовано с торговой моделью (см. ниже: Entry = mid wick).

⚠ Старый канон (zone-boundary, consumed на любой touch wick'ом) — DEPRECATED 2026-06-15.

## Базовая торговая модель (mean-reversion)

| Параметр | TOP RB (SHORT) | BOTTOM RB (LONG) |
|---|---|---|
| **Entry** | `(body_top + high) / 2` (мid вика = consume trigger) | `(low + body_bottom) / 2` (mid wick = consume trigger) |
| **SL** | `high` | `low` |
| **TP** | `low` | `high` |

`R = |entry - SL|`, `T = |entry - TP|`, `RR = T/R` — плавает по геометрии (обычно 1.4–3.0).

## Эталонный пример — TOP RB (BTC 12h, 2026-04-14 15:00 MSK)

| Поле | Значение |
|---|---|
| O / H / L / C | 74376.52 / 76038.00 / 73795.47 / 74131.55 |
| body | 244.97 (bear) |
| upper_wick | 1661.48 |
| lower_wick | 336.08 |
| upper / lower | 4.94× (≥ 2 ✓) |
| upper / body | 6.78× (≥ 3 ✓) |
| → | **TOP RB ✓** |

**Зона интереса**: `[74376.52, 76038.00]` (h=1661.48).

**Trade**:
- Entry = 75207.26 (mid upper wick)
- SL = 76038.00, R = 830.74
- TP = 73795.47, T = 1411.79, **RR = 1.70**
- Outcome: **WIN** (цена дошла до TP до SL)

## Baseline backtest (12h BTC, 2020-05 → 2026-05)

| Direction | n | WR | avg RR | ΣR | R/trade | в год |
|---|---|---|---|---|---|---|
| TOP RB (SHORT) | 252 | 35.27% | 1.91 | +3.2 | +0.013 | ~41 |
| BOTTOM RB (LONG) | 356 | 39.17% | 1.84 | +33.7 | +0.100 | ~58 |
| **ИТОГО** | **608** | **37.54%** | **1.87** | **+37.0** | **+0.064** | ~100 |

Break-even WR @ avgRR=1.87 = 1/(1+1.87) ≈ 34.8%. Реальный WR 37.5% — edge ~2.7pp.

## Связанные элементы

- `ob_liq` — другая форма «отвержения уровня» (2-свечная пара с маркером)
- `block_orders` — N+M композит вместо одиночной свечи
- `fractal` (планируется) — Williams 5-bar HH/LL, концептуально связан с RB как отдельная single-candle структура отвержения
