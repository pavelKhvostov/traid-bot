# OB с явно выраженным уровнем ликвидности

Canon-OB (пара `prev`/`cur`), на который наложен **маркер ликвидности** — три обязательных условия про фитиль `prev`. Маркер подтверждается на закрытии свечи `cur+1` (нужна 5-свечная окно).

Canon из vault: `~/traid-bot/vault/knowledge/smc/что такое OB с явно выраженной зоной ликвидности.md` (зафиксирован 2026-05-19).

## Свечи

`prev-2, prev-1, prev, cur, cur+1` — пять последовательных свечей. OB строится на паре `(prev, cur)`. Свечи `prev-2, prev-1, cur+1` нужны только для 5-bar Williams-фрактала.

## Направление

| Направление | `prev` | `cur` | Реакция |
|---|---|---|---|
| **LONG OB** | bear | bull | `cur.close > prev.open` |
| **SHORT OB** | bull | bear | `cur.close < prev.open` |

## Условия маркера (все три обязательны)

### LONG OB

1. **Выраженность 3×** — нижний фитиль `prev` более чем в 3 раза длиннее нижнего фитиля `cur`:
   ```
   (min(prev.O, prev.C) - prev.low) > 3 * (min(cur.O, cur.C) - cur.low)
   ```
2. **Фитиль > тело prev**:
   ```
   (min(prev.O, prev.C) - prev.low) > |prev.O - prev.C|
   ```
3. **Williams 5-bar LL по `prev`**: `prev.low` строго ниже `low` четырёх соседей:
   ```
   prev.low < low[k]   для k ∈ {prev-2, prev-1, cur, cur+1}
   ```

### SHORT OB — зеркально

1. Верхний фитиль `prev` > 3 × верхний фитиль `cur`.
2. Верхний фитиль `prev` > тела `prev`.
3. `prev.high` строго выше `high` четырёх соседей (`prev-2, prev-1, cur, cur+1`).

## Зоны

| Зона | LONG | SHORT |
|---|---|---|
| **Зона входа (canon-OB)** | `[min(prev.low, cur.low), prev.open]` | `[prev.open, max(prev.high, cur.high)]` |
| **Зона-маркер ликвидности** | `[prev.low, cur.low]` | `[cur.high, prev.high]` |

**Важно**: зона входа = canon-OB. Маркер ликвидности — отдельная зона рядом, не меняет зону входа.

## Чем НЕ является

- НЕ новая зона входа (зона входа остаётся canon-OB).
- НЕ primitive — это **composite**: OB-pair + marker. Используется как confluence (например, в стратегии **babai**, LONG-only на 12h).
- НЕ `SWEPT` из Strategy 1.1.1 — здесь соотношение фитилей внутри `(prev, cur)`, не снятие предыдущего свинга.

## Связанные элементы

- `fractal` (планируется) — Williams 5-bar BW-фрактал, основа условия №3
