# Зона интереса — справочник по элементам

> **Назначение.** Когда пользователь говорит «зона интереса» применительно к элементу, эта таблица фиксирует **точную геометрию зоны**. Только определение зон, без entry/SL/TP/стратегий — те живут в стратегических заметках, не здесь.

---

## 1) OB (Order Block) — canon-pair

Canon: `elements/ob/definition.md` + [[универсальные определения OB и FVG]] (vault, locked 2026-04-28). Геометрия совпадает с `(N₁, N₂) = (1, 1)` случаем `block_orders` (синхронизировано 2026-05-24).

| Направление | Условие | **Зона интереса** | Состоит из |
|---|---|---|---|
| **LONG OB** | `prev` bear, `cur` bull, `cur.close > prev.open` | `[min(prev.low, cur.low), cur.close]` | breaker block `[prev.open, cur.close]` сверху + drop area `[min(prev.low, cur.low), prev.open]` снизу |
| **SHORT OB** | `prev` bull, `cur` bear, `cur.close < prev.open` | `[cur.close, max(prev.high, cur.high)]` | breaker block `[cur.close, prev.open]` снизу + rally area `[prev.open, max(prev.high, cur.high)]` сверху |

**Breaker block** = body синтетической свечи `[min(prev.open, cur.close), max(prev.open, cur.close)]` — подзона внутри зоны интереса (broken side).

Альтернативные варианты зон (breaker-only, body-only prev, single-candle, full prev) — см. `elements/ob/definition.md`.

---

## 2) Блок ордеров

Canon: `elements/block_orders/definition.md` (зафиксирован 2026-05-24).

Композит `[preceding] + [N₁ initial] + [N₂ counter]`:
- **preceding** — 1 свеча противоположной направленности к initial
- **initial run** — N₁ ≥ 1 свечей одной направленности подряд
- **counter run** — N₂ ≥ 1 свечей противоположной направленности подряд, STOP на ПЕРВОЙ свече с close-crossing `block.open`
- **(N₁, N₂) ≠ (1, 1)** — иначе canon-OB

| Направление | preceding | initial | counter |
|---|---|---|---|
| **LONG** | bull | 1+ bear | 1+ bull, last close > block.open |
| **SHORT** | bear | 1+ bull | 1+ bear, last close < block.open |

| Направление | **Зона интереса** |
|---|---|
| **LONG** | `[block.low, block.close]` |
| **SHORT** | `[block.close, block.high]` |

Где:
- `block.open` = open первой initial-свечи
- `block.close` = close ПОСЛЕДНЕЙ counter-свечи (той, что first-crossed)
- `block.low` / `block.high` = min/max по всем initial + counter (= pattern.low / pattern.high)

**Breaker block** = body `[min(open, close), max(open, close)]` — это **подзона** внутри зоны интереса, не сама зона. Зона интереса расширяется до pattern.low (LONG) / pattern.high (SHORT).

**Не путать** с `ob/` (canon-OB pair = (1,1) case) и с `rdrb.block` (под-зоной RDRB).

---

## 3) RB (Rejection Block)

Canon: `elements/rb/definition.md` (зафиксирован 2026-05-24).

Одиночная свеча с доминирующим фитилём:
- **TOP RB**: `upper_wick ≥ 2 × lower_wick` AND `upper_wick ≥ 3 × body`
- **BOTTOM RB**: `lower_wick ≥ 2 × upper_wick` AND `lower_wick ≥ 3 × body`

Цвет тела не важен. `body > 0` и второй фитиль `> 0` обязательны (doji и марузу-с-фитилём исключены).

| Направление | **Зона интереса** |
|---|---|
| **TOP RB** | `[max(open, close), high]` |
| **BOTTOM RB** | `[low, min(open, close)]` |

---

## 4) OB с явно выраженным уровнем ликвидности

Canon: `elements/ob_liq/definition.md`.

Composite: canon-OB (пара `prev`/`cur`) + Williams 5-bar маркер (фитиль ≥ 3×, фитиль > тела, prev = HH/LL пятисвечного фрактала).

| Зона | LONG | SHORT |
|---|---|---|
| **Зона интереса (ob_liq)** | `[min(prev.low, cur.low), prev.open]` | `[prev.open, max(prev.high, cur.high)]` |
| **liq_zone** (маркер) | `[prev.low, cur.low]` | `[cur.high, prev.high]` |

⚠️ Зона `ob_liq` **намеренно уже** зоны `ob` — это только drop/rally area без breaker block. Логика входа `ob_liq` опирается на отвергнутый фитиль `prev`, а не на тело синтетической свечи. Не выравнивать с `ob` (зафиксировано 2026-05-24).

Маркер ликвидности — отдельная зона, **не часть** зоны интереса.

---

## 5) Marubozu

Canon: `elements/marubozu/definition.md` (зафиксирован 2026-05-24, Pine WICK.ED).

Одиночная свеча без фитиля **со стороны открытия**. Заменяет deprecated-канон "body / range ≥ 0.95".

| Направление | Условие | **Зона интереса** |
|---|---|---|
| **LONG marubozu** | `open == low` AND `close > open` | `[open, close]` (= `[low, close]`) |
| **SHORT marubozu** | `open == high` AND `close < open` | `[close, open]` (= `[close, high]`) |

В обоих случаях зона = тело свечи. Фитиль с противоположной от open стороны допускается **произвольной** длины (это и есть отличие от старого 95 %-канона).

---

## 6) FVG (Fair Value Gap)

Canon: `elements/fvg/definition.md` + [[универсальные определения OB и FVG]].

| Направление | Условие | **Зона интереса** |
|---|---|---|
| **LONG FVG** (bullish) | `c1.high < c3.low` | `[c1.high, c3.low]` |
| **SHORT FVG** (bearish) | `c1.low > c3.high` | `[c3.high, c1.low]` |

---

## 6a) i-FVG (Inverse FVG)

Canon: `elements/i_fvg/definition.md` (зафиксирован 2026-05-24) + [[inverse-fvg-definition]] (vault).

Композит: **FVG-B противоположного направления** первой касается ранее untouched **FVG-A** → роль зоны A инвертирует (support ↔ resistance).

**Условия**:
1. FVG-A валидна, FVG-B валидна, `B.direction != A.direction`
2. A осталась untouched между `A.c3` и `B.c1` (никакая свеча в окне не входит в A.zone)
3. Хотя бы одна свеча из (B.c1, B.c2, B.c3) касается A.zone (first touch внутри B)
4. `A.zone ∩ B.zone ≠ ∅`

**Зоны**:

| Зона | Что это |
|---|---|
| **A.zone** | Исходная FVG-A (геометрия неизменна, **меняет роль**: support → resistance или наоборот) |
| **B.zone** | Новая FVG-B (сам i-FVG как FVG) |
| **overlap** | `[max(A.bot, B.bot), min(A.top, B.top)]` — пересечение, **зона интереса i-FVG-события** |

| Сценарий | Роль A до | Роль A после | i-FVG direction |
|---|---|---|---|
| A bull → B bear | support | resistance | SHORT |
| A bear → B bull | resistance | support | LONG |

По умолчанию **«зона интереса i-FVG» = overlap** (двойная значимость).

---

## 7) Fractal (Williams)

Canon: `elements/fractal/definition.md` (зафиксирован 2026-05-24, N=2 Williams BW 5-bar default; параметр N настраиваемый).

- **FH (Fractal High)** — `high` центральной свечи **строго** выше `high` 2N соседей (default N=2 → 5-bar окно).
- **FL (Fractal Low)** — `low` центральной свечи **строго** ниже `low` 2N соседей.
- Подтверждается через `(N+1) * tf` после `open_time` центральной свечи.

| Направление | **Зона интереса** | Геометрия |
|---|---|---|
| **FH** | `center.high` | **точка / уровень** (одно число) |
| **FL** | `center.low` | **точка / уровень** |

Это единственный primitive в smc-lib с **точечной** зоной (не интервалом). Класс зоны — **liquidity** (collected stops за уровнем).

LuxAlgo "Liquidity Swings" — **measurement layer** над FH/FL (touch count + volume пока зона uncrossed, отрисовка как интервал фитиля). Не часть primitive; может навешиваться отдельным слоем при необходимости.

---

## 8) RDRB

Canon: `elements/rdrb/definition.md`.

3-свечный паттерн с тремя зонами:

| Зона | Что это |
|---|---|
| **POI** | Полная зона интереса (block ∪ liq) |
| **block** | Пересечение виков C1 и C3, ⊆ POI |
| **liq** | POI \ block (опциональная, только V1) |

| Направление | POI | block | liq |
|---|---|---|---|
| **LONG RDRB** | `[C1.body_top, block.top]` | `[max(C1.body_top, C3.low), min(C1.high, C3.body_bottom)]` (верх POI) | `[C1.body_top, block.bottom]` если непуст |
| **SHORT RDRB** | `[block.bottom, C1.body_bottom]` | `[max(C1.low, C3.body_top), min(C1.body_bottom, C3.high)]` (низ POI) | `[block.top, C1.body_bottom]` если непуст |

**V1 vs V2**: V1 — liq непустой, V2 — `block == POI` (liq пустой).

По умолчанию **«зона интереса RDRB» = POI**.

---

## Композитные элементы

### i-RDRB
Все зоны наследуются от подлежащего RDRB (POI / block / liq не меняются). C4 только подтверждает разворот.

### i-RDRB + FVG
- **Зона интереса 1 (RDRB-часть)** — POI (см. RDRB выше)
- **Зона интереса 2 (FVG-часть)** — gap-зона FVG

---

## Принципы именования

- «**Зона интереса**» (POI / Point of Interest) — зона, где ждать реакцию. Геометрическое понятие.
- «**Зона ликвидности**» — место скопления стопов / лимиток (FH / FL, liq-под-зоны RDRB, маркер ob_liq).
- «**Зона неэффективности**» — FVG.
- «**Зона эффективности**» — RDRB block, maxV (см. [[три класса зон ликвидность эффективность неэффективность]]).
