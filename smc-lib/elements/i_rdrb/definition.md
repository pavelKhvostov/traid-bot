# i-RDRB

4-свечный **reversal-паттерн**: 3-свечный [[RDRB]] плюс свеча C4, разворачивающая движение C2 за границу RDRB block.

## Свечи

C1, C2, C3, C4 — четыре последовательные свечи.
- C1, C2, C3 образуют [[RDRB]] (см. `elements/rdrb/definition.md`).
- C4 — следующая свеча, разворачивающая направление паттерна.

## Направление

i-RDRB всегда **противоположен** направлению подлежащего RDRB:

| RDRB | i-RDRB | Условие на C4 |
|---|---|---|
| SHORT (C2 bear) | **LONG** | C4 bull AND `C4.close > rdrb.block.top` |
| LONG (C2 bull)  | **SHORT** | C4 bear AND `C4.close < rdrb.block.bottom` |

Continuation-кейсы (C4 в ту же сторону, что C2: например SHORT RDRB + C4 bear) **не образуют i-RDRB** — это просто продолжение displacement.

## Зоны

**block наследуется** из подлежащего RDRB без изменений (intersection виков C1∩C3, см. RDRB canon).

**liq в i-RDRB переопределяется** относительно RDRB — инвертируется в неотработанную зону между фитилём C3 и противоположным экстремумом C1 (canon 2026-06-14):

| i-RDRB direction | liq (canon i-RDRB) |
|---|---|
| **LONG i-RDRB** (на SHORT RDRB) | `[C3.body_top, C1.low]` — ниже block (НЕ `[block.top, C1.body_bottom]` как в SHORT RDRB) |
| **SHORT i-RDRB** (на LONG RDRB) | `[C1.high, C3.body_bottom]` — выше block (НЕ `[C1.body_top, block.bottom]` как в LONG RDRB) |

**POI** в i-RDRB = block ∪ liq (с обновлённым liq).

Семантика: liq в i-RDRB — это зона «обманутой ликвидности» в сторону разворота (где стопы шортов/лонгов в направлении C2 displacement), а не остаток фитиля C1 как в обычном RDRB.

⚠ Старый канон («все зоны наследуются») deprecated с 2026-06-14.

## Эталонный пример — LONG i-RDRB на SHORT RDRB

BTCUSDT 4h, 2026-05-18, UTC+3:

| Свеча | Время | O | H | L | C | Тип |
|---|---|---|---|---|---|---|
| C1 | 11:00 | 77073.69 | 77403.48 | 76668.58 | 77285.83 | bull |
| C2 | 15:00 | 77285.83 | 77800.00 | 76051.00 | 76409.46 | bear (displacement вниз) |
| C3 | 19:00 | 76409.46 | 76995.00 | 76144.24 | 76928.00 | bull |
| C4 | 23:00 | 76928.00 | 77222.79 | 76800.00 | 77001.87 | bull (reversal вверх) |

**RDRB (из C1-C2-C3)**:
- direction: SHORT
- POI: `[76928.00, 77073.69]`
- block: `[76928.00, 76995.00]`
- liq: `[76995.00, 77073.69]`
- variant: V1

**Проверка i-RDRB**:
- RDRB SHORT → ожидаем LONG i-RDRB
- C4.is_bull ✓
- C4.close (77001.87) > block.top (76995.00) ✓ → **LONG i-RDRB**

## Связанные элементы

- `rdrb` — подлежащая 3-свечная структура
- `fvg` — Fair Value Gap; в 5-свечной стратегии FVG строится на C3-C4-C5 в ту же сторону, что i-RDRB (усиление reversal)
