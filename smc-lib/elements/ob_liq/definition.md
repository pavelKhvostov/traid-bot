# OB с явно выраженным уровнем ликвидности

Canon-OB (пара `prev`/`cur`), на который наложен **маркер ликвидности** — два обязательных условия про фитиль `prev`.

> ⚠️ **Обновлено 2026-05-27**: Williams 5-bar фрактальность УБРАНА из канона. Раньше требовалось 3-е условие (prev = 5-bar HH/LL). Теперь только 2 wick-условия. Понятие «фрактальность» для `ob_liq` НЕ применяется.

Canon из vault: `~/traid-bot/vault/knowledge/smc/что такое OB с явно выраженной зоной ликвидности.md` (изначально 2026-05-19, обновлён 2026-05-27).

## Свечи

`prev, cur` — две последовательные свечи. OB строится на паре `(prev, cur)`. Дополнительных свечей не требуется.

## Направление

| Направление | `prev` | `cur` | Реакция |
|---|---|---|---|
| **LONG OB** | bear | bull | `cur.close > prev.open` |
| **SHORT OB** | bull | bear | `cur.close < prev.open` |

## Условия маркера (оба обязательны)

### LONG OB

1. **Выраженность 3×** — нижний фитиль `prev` более чем в 3 раза длиннее нижнего фитиля `cur`:
   ```
   (min(prev.O, prev.C) - prev.low) > 3 * (min(cur.O, cur.C) - cur.low)
   ```
2. **Фитиль > тело prev**:
   ```
   (min(prev.O, prev.C) - prev.low) > |prev.O - prev.C|
   ```

### SHORT OB — зеркально

1. Верхний фитиль `prev` > 3 × верхний фитиль `cur`.
2. Верхний фитиль `prev` > тела `prev`.

## Зоны

| Зона | LONG | SHORT |
|---|---|---|
| **ZoI ob_liq (LIQ marker, narrow)** ★ | `[prev.low, cur.low]` | `[cur.high, prev.high]` |
| **Trade entry zone (canon-OB drop/rally, wide)** | `[min(prev.low, cur.low), prev.open]` | `[prev.open, max(prev.high, cur.high)]` |

**Канон 2026-06-16:** **ZoI ob_liq = LIQ marker (узкая)**. Это zone of interest, которая отличает ob_liq от обычного canon-OB. Узкая = высокая precision как уровень.

В коде: `OBLiq.zone` = LIQ marker (ZoI), `OBLiq.entry_zone` = canon-OB drop/rally (информационное).

## Mitigation canon (2026-06-16 FINAL)

**first_touch с `consume_at_fraction=1.0` (outer edge = top для LONG / bottom для SHORT)** на LIQ marker — **rigid**: ЛЮБАЯ последующая свеча зашедшая в LIQ marker → ob_liq deactivated.

| Направление | Trigger deactivation |
|---|---|
| **LONG ob_liq** | `bar.low ≤ cur.low` (LIQ_HI) |
| **SHORT ob_liq** | `bar.high ≥ cur.high` (LIQ_LO) |

**Канон НЕТ partial fill** — ob_liq живёт по принципу «всё или ничего» на LIQ marker.

## Эволюция после deactivation (2026-06-16)

Когда LIQ marker tested (выше rigid trigger), ob_liq **deactivated AS ob_liq**, но базовый OB продолжает существовать (детектируется параллельно через `elements/ob/`).

| Этап | Element | ZoI | Mitigation |
|---|---|---|---|
| До LIQ test | **ob_liq** (active) | LIQ marker (narrow) | first_touch fraction=1.0 (rigid, outer edge) |
| После LIQ test | **ob_liq retired** + параллельный **ob** продолжает | canon-OB drop/rally (wide) | wick_fill canon (partial → full) |

Это семантически = «ob_liq перевоплощается в OB с остаточной ZoI». В pipeline реализовано через **независимые** detector'ы: `scan_ob` ловит wide canon-OB pair, `scan_ob_liq` ловит ту же pair с дополнительным LIQ marker. После retire ob_liq — wide OB остаётся active.

## Чем НЕ является

- НЕ новая зона входа (зона входа остаётся canon-OB).
- НЕ primitive — это **composite**: OB-pair + marker. Используется как confluence.
- НЕ `SWEPT` из Strategy 1.1.1 — здесь соотношение фитилей внутри `(prev, cur)`, не снятие предыдущего свинга.
- НЕ привязан к фрактальности (Williams) — это убрано из канона 2026-05-27.

## API

```python
from elements.ob_liq.code import detect_ob_liq, OBLiq
result: OBLiq | None = detect_ob_liq(prev, cur)
```

## История

- 2026-05-19 — первоначальный canon с 3 условиями (включая Williams 5-bar HH/LL).
- **2026-05-27** — Williams-условие убрано. Канон стал 2-свечным с 2 wick-условиями.
