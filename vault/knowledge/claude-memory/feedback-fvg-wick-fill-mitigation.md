---
name: feedback-zone-mitigation-rules
description: "Canonical mitigation для зон интереса. Wick-fill: OB/FVG/iFVG/RDRB POI/block_orders/iRDRB POI. First-touch: RB/ob_liq/marubozu. Sweep: fractal."
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 92a19f52-96e8-4b59-9766-f29ae6786cff
---

# Canonical mitigation rules для зон интереса

Три модели mitigation в зависимости от типа зоны. Записано в smc-lib: `~/smc-lib/zone_of_interest.md` (раздел "Mitigation").

## Модель 1: Wick-fill (постепенное сжатие)

При каждом касании цены wick'ом зона сжимается на величину проникновения. Кумулятивно — каждое последующее касание сжимает ещё больше.

**LONG zone** (`[zone_lo, zone_hi]`, support снизу):
```
low ≤ zone_hi:
  low > zone_lo  → zone → [zone_lo, low]
  low ≤ zone_lo  → ZONE CONSUMED
```

**SHORT zone** (`[zone_lo, zone_hi]`, resistance сверху):
```
high ≥ zone_lo:
  high < zone_hi → zone → [high, zone_hi]
  high ≥ zone_hi → ZONE CONSUMED
```

**Применимо к:** OB, block_orders, FVG, **i-FVG**, RDRB POI, i-RDRB POI.

## Модель 2: First-touch (одноразовое consumption)

Первое касание зоны wick'ом → зона полностью consumed (без постепенного сжатия).

```
Касание wick'ом любого уровня зоны → ZONE CONSUMED
```

**Применимо к:** **RB, ob_liq**.

Семантика:
- **RB** = одиночная rejection-свеча. Зона = wick rejection. Первое касание отрабатывает зону полностью.
- **ob_liq** = OB + liquidity marker (одноразовый sweep prev wick). После first touch остаётся только canon-OB (с wick-fill на оставшуюся часть, если есть).

## Модель 3: Sweep (касание точечного level)

```
Wick касается / проходит за level → CONSUMED
```

**Применимо к:** **fractal, marubozu (open level)**.

**Fractal:**
- FH swept: `high > level`
- FL swept: `low < level`

**Marubozu (sweep открытия):**
- Bull marubozu (open == low): consumed когда `low ≤ open` (тест открытия снизу wick'ом)
- Bear marubozu (open == high): consumed когда `high ≥ open` (тест открытия сверху wick'ом)

Семантика marubozu: body = imbalance area, target = open level (точечный магнит). Body как actionable zone актуальна пока open не sweep'нут. После sweep — marubozu полностью отработан. См. [[feedback-marubozu-is-imbalance-not-support]].

## Сводная таблица

| Элемент | Модель | Заметки |
|---|---|---|
| OB | **wick-fill** | подтверждено D OB 04-20 → 05-23 |
| block_orders | **wick-fill** | |
| FVG | **wick-fill** | подтверждено D FVG 04-30 → 05-18 |
| i-FVG | **wick-fill** | так же как FVG (на overlap zone) |
| RDRB POI | **wick-fill** | |
| i-RDRB POI | **wick-fill** | наследует от RDRB |
| **RB** | **first-touch** | одноразовая |
| **ob_liq** | **first-touch** | после consumption → canon OB с wick-fill |
| **marubozu (body)** | **sweep open** | mitigation = касание open level (bull: low≤open / bear: high≥open) |
| fractal (точка) | sweep | wick за level |

## Пример FVG (wick-fill, D 2026-04-30)

```
Original zone:    [76 669.1 ............... 78 040.0]    1370.9$

05-16 low=77 640 → wick-fill:
After 05-16:      [76 669.1 ........ 77 640.0]            970.9$

05-17 low=76 735 → wick-fill:
After 05-17:      [76 669.1 ... 76 735.0]                  66.1$

05-18 low=76 051 < zone_lo → CONSUMED
```

## Пример OB (wick-fill, D 2026-04-19/04-20)

```
Original:         [73 724.3, 75 841.0]    2116.7$

04-21 low=74 821.6 → wick-fill:
After 04-21:      [73 724.3, 74 821.6]    1097.3$

05-23 low=74 289.6 → wick-fill:
After 05-23:      [73 724.3, 74 289.6]     565.3$
```

## Why

Каждая модель отражает природу зоны:
- **wick-fill** = institutional zones (OB/FVG/RDRB) могут тестироваться многократно, каждый touch потребляет часть untraded liquidity
- **first-touch** = одноразовые маркеры (RB/ob_liq/marubozu) — их функция "отработана" при первом контакте, дальше зона не actionable
- **sweep** = точечная liquidity (fractal stops) — однократный stop hunt

## Применение в Pred-12h F4

F4 должен использовать соответствующую модель для каждого типа зоны:
- OB/FVG/iFVG/RDRB POI/block_orders/iRDRB POI → wick-fill
- RB/ob_liq/marubozu → first-touch
- fractal → sweep

В текущей реализации `~/smc-lib/scripts/pred12h_F4_wick_fill.py` всё применялось через wick-fill — нужно скорректировать на разные модели по типу.

## Related

- [[zone-class-liquidity-inefficiency-block]] — таксономия зон
- [[feedback-untraded-area-is-magnet]] — fundamental SMC principle (untraded area pulls)
- [[feedback-marubozu-is-imbalance-not-support]] — marubozu open level (отдельный канон)
- [[feedback-ob-vs-ob-liq-zones-differ]] — ob_liq отличается от ob
- [[12h-fractal-filter-F1-F2]] — F4 должен использовать правильные mitigation rules
