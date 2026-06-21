# OB (Order Block)

Канонический 2-свечный паттерн: последняя противоположная свеча (`prev`) перед импульсной реакцией (`cur`), которая закрывается за `prev.open`. Институциональная «зона ордеров», в которую цена возвращается за реакцией.

Canon из vault: `~/traid-bot/vault/knowledge/smc/универсальные определения OB и FVG.md` (locked 2026-04-28).

> **Отличается от:**
> - `rdrb` — 3-свечный паттерн с собственной геометрией POI/block/liq
> - `ob_liq` — `ob` + Williams 5-bar маркер ликвидности (composite поверх `ob`)
> - `block_orders` — N+M композит (`ob` = частный случай N₁=1, N₂=1)

## Свечи

`prev`, `cur` — две последовательные свечи. `prev` — старшая (по времени), `cur` — младшая (реакция).

## Направление и условия

### LONG OB

- `prev.close < prev.open` (prev bear)
- `cur.close > cur.open` (cur bull)
- `cur.close > prev.open` (реакция закрывается ВЫШЕ open prev)

### SHORT OB

- `prev.close > prev.open` (prev bull)
- `cur.close < cur.open` (cur bear)
- `cur.close < prev.open` (реакция закрывается НИЖЕ open prev)

## Зона интереса

OB — частный случай `block_orders` с `(N₁, N₂) = (1, 1)`. **Зона интереса OB = drop/rally area, ВСЕГДА, без breaker block.** Breaker block — самостоятельный элемент со своей зоной (см. `elements/breaker_block/definition.md`).

### Геометрия

| Направление | **Зона интереса OB** |
|---|---|
| **LONG OB** | `[min(prev.low, cur.low), prev.open]` (drop area) |
| **SHORT OB** | `[prev.open, max(prev.high, cur.high)]` (rally area) |

**Drop area** (LONG) / **Rally area** (SHORT) — отвергнутое движение `prev`, cancelled реакцией `cur`. **Институциональная зона исполнения** — где крупный игрок исполнил ордера ПРОТИВ retail-движения.

### Полный пробой prev и breaker

Если `cur.close > prev.high` (LONG) или `cur.close < prev.low` (SHORT) — выполняется условие полного структурного пробоя prev. **Это триггер формирования отдельного элемента `breaker_block`** (зона = проткнутый фитиль prev). Сам OB ZoI от этого не меняется.

| Условие полного пробоя | Что формируется |
|---|---|
| `cur.close > prev.high` (LONG) | OB (ZoI = drop area) + Breaker Block (ZoI = верхний фитиль prev = `[prev.open, prev.high]`) |
| `cur.close < prev.low` (SHORT) | OB (ZoI = rally area) + Breaker Block (ZoI = нижний фитиль prev = `[prev.low, prev.open]`) |

См. `elements/breaker_block/definition.md` для канонической геометрии breaker zone и mitigation-модели.

> ⚠ **2026-05-29**: формализовано условие полного пробоя prev (`cur.close > prev.high` / `cur.close < prev.low`).
> ⚠ **2026-06-14 (первая правка)**: breaker block — это проткнутый фитиль prev, не body синтетической свечи (deprecated).
> ⚠ **2026-06-14 (вторая правка)**: breaker block **вынесен из OB ZoI** в самостоятельный элемент со своей зоной интереса. OB ZoI теперь = drop/rally area, всегда, регардлесс от полного пробоя.

### Альтернативные варианты (не дефолт)

| Вариант | Формула LONG | Формула SHORT | Когда уместен |
|---|---|---|---|
| **body-only prev** | `[prev.close, prev.open]` | `[prev.open, prev.close]` | если хотим максимально узкую зону (только тело prev) |
| **single-candle** | `[prev.low, prev.open]` | `[prev.open, prev.high]` | если не хотим расширять зону за счёт `cur` |
| **full prev** | `[prev.low, prev.high]` | `[prev.low, prev.high]` | если включаем оба фитиля prev |

> Старый «breaker-only» и «synthetic-body» — больше НЕ варианты OB ZoI; breaker block теперь самостоятельный элемент. См. `elements/breaker_block/definition.md`.

Дефолт справочника — **полная зона** (первая таблица).

## Эталонные примеры

### LONG OB — синтетический

| Свеча | O | H | L | C | Тип |
|---|---|---|---|---|---|
| `prev` | 100 | 102 | 95 | 96 | bear |
| `cur` | 96 | 105 | 94 | 104 | bull |

- `prev.close (96) < prev.open (100)` ✓ prev bear
- `cur.close (104) > cur.open (96)` ✓ cur bull
- `cur.close (104) > prev.open (100)` ✓ реакция вверх

**Зона интереса OB** = drop area = `[min(95, 94), 100]` = **`[94, 100]`** (h=6).

Также формируется отдельный элемент **Breaker Block** (т.к. cur.close=104 > prev.high=102):
- Breaker Block ZoI = верхний фитиль prev = **`[100, 102]`** (h=2). См. `elements/breaker_block/definition.md`.

### SHORT OB — синтетический

| Свеча | O | H | L | C | Тип |
|---|---|---|---|---|---|
| `prev` | 100 | 105 | 98 | 104 | bull |
| `cur` | 104 | 106 | 95 | 96 | bear |

- `prev.close (104) > prev.open (100)` ✓ prev bull
- `cur.close (96) < cur.open (104)` ✓ cur bear
- `cur.close (96) < prev.open (100)` ✓ реакция вниз

**Зона интереса OB** = rally area = `[100, max(105, 106)]` = **`[100, 106]`** (h=6).

Также формируется отдельный элемент **Breaker Block** (т.к. cur.close=96 < prev.low=98):
- Breaker Block ZoI = нижний фитиль prev = **`[98, 100]`** (h=2). См. `elements/breaker_block/definition.md`.

## Правила

Общие правила, характеризующие особые условия и закономерности рынка, применимые ко всем SMC-элементам и паттернам (не специфичные для OB). См. общий справочник [`rules.md`](../../rules.md).

## Связанные элементы

- `ob_liq` — `ob` + Williams 5-bar маркер (использует `ob` как основу)
- `block_orders` — N+M композит, `ob` = его частный случай (N₁=1, N₂=1, `prev` = preceding, `cur` = первая counter с close-crossing)
