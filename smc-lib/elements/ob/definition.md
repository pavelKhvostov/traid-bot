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

OB — частный случай `block_orders` с `(N₁, N₂) = (1, 1)`. Геометрия зоны зависит от того, был ли **полный структурный пробой** prev candle:

### Условие существования Breaker Block

**Breaker block существует только при полном пробое prev структуры:**

| Направление | Условие наличия breaker |
|---|---|
| **LONG OB** | `cur.close > prev.high` (закрытие cur ВЫШЕ всего prev) |
| **SHORT OB** | `cur.close < prev.low` (закрытие cur НИЖЕ всего prev) |

Если условие не выполнено (cur.close в диапазоне prev), **breaker отсутствует** — есть только drop/rally area.

### Геометрия зон

| Направление | Drop/Rally area (всегда) | Breaker (если cur.close > prev.high для LONG / cur.close < prev.low для SHORT) | **Full ZoI** |
|---|---|---|---|
| **LONG OB**, без breaker | `[min(prev.low, cur.low), prev.open]` | — | **= drop area** |
| **LONG OB**, с breaker | `[min(prev.low, cur.low), prev.open]` | `[prev.open, cur.close]` | `[min(prev.low, cur.low), cur.close]` (drop + breaker) |
| **SHORT OB**, без breaker | `[prev.open, max(prev.high, cur.high)]` | — | **= rally area** |
| **SHORT OB**, с breaker | `[prev.open, max(prev.high, cur.high)]` | `[cur.close, prev.open]` | `[cur.close, max(prev.high, cur.high)]` (rally + breaker) |

**Breaker block** = body синтетической свечи `[min(prev.open, cur.close), max(prev.open, cur.close)]` — где бывшая сторона ордеров была «сломана» структурным пробоем. Институциональный анкор уровня.

**Drop area** (LONG) / **Rally area** (SHORT) = всегда существует. Это отвергнутое движение `prev`, которое cancelled реакцией `cur`. Институциональная зона исполнения — где крупный игрок исполнил ордера ПРОТИВ retail-движения.

> ⚠ Раньше canon фиксировал breaker всегда. С 2026-05-29 уточнено: breaker требует **полный пробой prev** (`cur.close > prev.high` для LONG). Без полного пробоя — ZoI = только drop/rally area.

### Альтернативные варианты (не дефолт)

| Вариант | Формула LONG | Формула SHORT | Когда уместен |
|---|---|---|---|
| **breaker-only** | `[prev.open, cur.close]` | `[cur.close, prev.open]` | если хотим только тело синтетической свечи (без отвергнутого экстремума) |
| **body-only prev** | `[prev.close, prev.open]` | `[prev.open, prev.close]` | если хотим максимально узкую зону (только тело prev) |
| **single-candle** | `[prev.low, prev.open]` | `[prev.open, prev.high]` | если не хотим расширять зону за счёт `cur` |
| **full prev** | `[prev.low, prev.high]` | `[prev.low, prev.high]` | если включаем оба фитиля prev |

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

**Зона интереса** = `[min(95, 94), 104]` = **`[94, 104]`** (высота 10)
- breaker block (подзона): `[100, 104]` (h=4) — сверху
- drop area (подзона): `[94, 100]` (h=6) — снизу

### SHORT OB — синтетический

| Свеча | O | H | L | C | Тип |
|---|---|---|---|---|---|
| `prev` | 100 | 105 | 98 | 104 | bull |
| `cur` | 104 | 106 | 95 | 96 | bear |

- `prev.close (104) > prev.open (100)` ✓ prev bull
- `cur.close (96) < cur.open (104)` ✓ cur bear
- `cur.close (96) < prev.open (100)` ✓ реакция вниз

**Зона интереса** = `[96, max(105, 106)]` = **`[96, 106]`** (высота 10)
- breaker block (подзона): `[96, 100]` (h=4) — снизу
- rally area (подзона): `[100, 106]` (h=6) — сверху

## Правила

Общие правила, характеризующие особые условия и закономерности рынка, применимые ко всем SMC-элементам и паттернам (не специфичные для OB). См. общий справочник [`rules.md`](../../rules.md).

## Связанные элементы

- `ob_liq` — `ob` + Williams 5-bar маркер (использует `ob` как основу)
- `block_orders` — N+M композит, `ob` = его частный случай (N₁=1, N₂=1, `prev` = preceding, `cur` = первая counter с close-crossing)
