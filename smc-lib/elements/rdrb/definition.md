# RDRB

3-свечный паттерн смещения с зоной возврата.

## Свечи

C1, C2, C3 — три последовательные свечи слева направо.

## Направление

Задаётся направлением C2:
- **C2 bear** → **SHORT RDRB** (смещение вниз)
- **C2 bull** → **LONG RDRB** (смещение вверх)
- **C2 doji** → не RDRB

## Варианты: V1 vs V2

RDRB бывает двух видов в зависимости от наличия зоны `liq`:

- **V1** — `liq` непустой (block не доходит до тела C1 в направлении паттерна).
- **V2** — `liq` пустой (`block == POI`). Вик C3 заходит как минимум до тела C1:
  - short: `C3.high ≥ C1.body_bottom`
  - long:  `C3.low ≤ C1.body_top`

## Условия (SHORT)

1. `C2.is_bear`
2. `C2.close < C1.low` — C2 закрывается ниже всего диапазона C1 (включая нижний вик)
3. `C3.upper_wick ∩ C1.lower_wick ≠ ∅` — верхний вик C3 и нижний вик C1 имеют общий ценовой диапазон
4. `C1.body_bottom > C3.body_top` — тела C1 и C3 не перекрываются

## Структура зон (SHORT)

```
block = C1.lower_wick ∩ C3.upper_wick
      = [max(C1.low, C3.body_top), min(C1.body_bottom, C3.high)]

poi   = [block.bottom, C1.body_bottom]
      = [max(C1.low, C3.body_top), C1.body_bottom]

liq   = [block.top, C1.body_bottom]   если block.top < C1.body_bottom
      = ∅                              иначе
```

Геометрически: block примыкает к **нижней** границе POI, liq — сверху от block до тела C1.

## Условия (LONG) — зеркально

1. `C2.is_bull`
2. `C2.close > C1.high`
3. `C3.lower_wick ∩ C1.upper_wick ≠ ∅`
4. `C3.body_bottom > C1.body_top`

## Структура зон (LONG)

```
block = C1.upper_wick ∩ C3.lower_wick
      = [max(C1.body_top, C3.low), min(C1.high, C3.body_bottom)]

poi   = [C1.body_top, block.top]
      = [C1.body_top, min(C1.high, C3.body_bottom)]

liq   = [C1.body_top, block.bottom]   если block.bottom > C1.body_top
      = ∅                              иначе
```

Block примыкает к **верхней** границе POI, liq — снизу от тела C1 до block.

## Эталонные примеры

### SHORT V1 — BTCUSDT 1h, 2026-05-22, UTC+3

| Свеча | Время | O | H | L | C | Тип |
|---|---|---|---|---|---|---|
| C1 | 10:00 | 77423.41 | 77543.38 | 77288.77 | 77408.06 | bear |
| C2 | 11:00 | 77408.07 | 77535.00 | 77216.00 | 77267.38 | bear (displacement вниз) |
| C3 | 12:00 | 77267.39 | 77360.00 | 77200.00 | 77307.11 | bull |

**Проверка условий**:
- C2.is_bear ✓
- C2.close (77267.38) < C1.low (77288.77) ✓ → SHORT
- C3.upper_wick [77307.11, 77360.00] ∩ C1.lower_wick [77288.77, 77408.06] = [77307.11, 77360.00] ≠ ∅ ✓
- C1.body_bottom (77408.06) > C3.body_top (77307.11) ✓

**Зоны**:
- POI: `[77307.11, 77408.06]` (высота 100.95)
- block: `[77307.11, 77360.00]` (высота 52.89; примыкает к низу POI)
- liq: `[77360.00, 77408.06]` (один интервал сверху, высота 48.06)
- variant: V1

### SHORT V1 — BTCUSDT 15m, 2026-05-23 09:30, UTC+3

| Свеча | Время | O | H | L | C | Тип |
|---|---|---|---|---|---|---|
| C1 | 09:30 | 75458.41 | 75491.31 | 75419.72 | 75452.45 | bear |
| C2 | 09:45 | 75452.44 | 75452.45 | 75394.54 | 75398.33 | bear |
| C3 | 10:00 | 75398.33 | 75443.44 | 75266.74 | 75363.40 | bear |

**Зоны**:
- POI: `[75419.72, 75452.45]` — нижняя граница = C1.low (т.к. C1.low > C3.body_top)
- block: `[75419.72, 75443.44]`
- liq: `[75443.44, 75452.45]`
- variant: V1

## Связанные элементы

- `i_rdrb` (планируется) — 4-свечный паттерн: RDRB + displacement-свеча C4
- `fvg` (планируется) — Fair Value Gap, часто используется совместно с RDRB
