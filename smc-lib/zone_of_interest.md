# Зона интереса — справочник по элементам

> **Назначение.** Когда пользователь говорит «зона интереса» применительно к элементу, эта таблица фиксирует **точную геометрию зоны**. Только определение зон, без entry/SL/TP/стратегий — те живут в стратегических заметках, не здесь.

---

## 1) OB (Order Block) — canon-pair

Canon: `elements/ob/definition.md` + [[универсальные определения OB и FVG]] (vault, locked 2026-04-28). Геометрия совпадает с `(N₁, N₂) = (1, 1)` случаем `block_orders` (синхронизировано 2026-05-24).

### Условия детекции

| Направление | Условие OB |
|---|---|
| **LONG OB** | `prev` bear, `cur` bull, `cur.close > prev.open` |
| **SHORT OB** | `prev` bull, `cur` bear, `cur.close < prev.open` |

### Breaker block — существует только при полном пробое prev (уточнено 2026-05-29)

**Breaker block ⇔ структурный пробой prev:**

| Направление | Условие наличия breaker |
|---|---|
| **LONG OB** | `cur.close > prev.high` |
| **SHORT OB** | `cur.close < prev.low` |

Без полного пробоя — **breaker отсутствует**, есть только drop/rally area.

### Зоны (с учётом условности breaker)

| Направление | Drop / Rally area (всегда) | Breaker (условно) | **Full Zone of Interest** |
|---|---|---|---|
| **LONG**, без breaker | `[min(prev.low, cur.low), prev.open]` | — | **= drop area** |
| **LONG**, с breaker | `[min(prev.low, cur.low), prev.open]` | `[prev.open, cur.close]` | `[min(prev.low, cur.low), cur.close]` |
| **SHORT**, без breaker | `[prev.open, max(prev.high, cur.high)]` | — | **= rally area** |
| **SHORT**, с breaker | `[prev.open, max(prev.high, cur.high)]` | `[cur.close, prev.open]` | `[cur.close, max(prev.high, cur.high)]` |

**Drop / Rally area** = всегда определена для существующего OB; отвергнутое движение `prev`, cancelled реакцией `cur`. **Институциональная зона исполнения** — где крупный игрок исполнил ордера против retail.

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

Composite: canon-OB (пара `prev`/`cur`) + 2-условный маркер ликвидности на `prev` (фитиль ≥ 3× фитиля `cur` AND фитиль > тела `prev`).

> ⚠️ **Обновлено 2026-05-27**: Williams 5-bar фрактальность УБРАНА из канона. Маркер ликвидности стал 2-условным. **Понятие «фрактальность» к ob_liq не применяется.** 2-свечный паттерн `(prev, cur)`.

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

## 7a) VWAP (anchored, ASVK)

Canon: `~/smc-lib/indicators/vwap_anchored.py` + Правило 6 в `rules.md` (построение от D-фрактала).

VWAP — **точечный уровень во времени** (значение `VWAP(t)` на каждом баре). Класс зоны — **liquidity / equilibrium** (точка справедливой цены по объёму с anchor'а).

- **SHORT VWAP** (anchored от FH): «resistance-line» — цена идёт снизу, тестирует уровень сверху.
- **LONG VWAP** (anchored от FL): «support-line» — цена идёт сверху, тестирует уровень снизу.

| Направление | **Зона интереса** | Геометрия |
|---|---|---|
| **SHORT VWAP** (от FH) | `VWAP(t)` | **точка / уровень во времени** (динамический) |
| **LONG VWAP** (от FL) | `VWAP(t)` | **точка / уровень во времени** (динамический) |

Аналогично fractal — **точечная** зона, но с **time-varying** значением (не статичная). По мере накопления volume `VWAP(t)` дрейфует к равновесной цене.

> **Effectiveness scoring** (`~/smc-lib/indicators/vwap_effectiveness.py`) — measurement layer: reactions (close on entry side) vs breaks (close на противоположной). Не часть primitive — навешивается отдельно как метрика качества уровня.

---

## 4a) ob_sweep_liq_4candles

Canon: `elements/ob_sweep_liq_4candles/definition.md`. ⚠️ Имя `_4candles` историческое.

Снятие ликвидности Williams 5-bar FH/FL свечой Y. Y открывается по другую сторону от фрактала, wick проходит за уровень, close за close фрактал-бара.

| Направление | Условия Y | **liq_zone** |
|---|---|---|
| **SHORT** (anchor = FH) | `y.open < anchor.high`, `y.high > anchor.high`, `y.close < anchor.close` | `[anchor.high, y.high]` |
| **LONG** (anchor = FL) | `y.open > anchor.low`, `y.low < anchor.low`, `y.close > anchor.close` | `[y.low, anchor.low]` |

Mitigation: TBD (вероятно first-touch).

---

## 7b) run_3candles_sweep

Перемещён в `patterns/` (полный setup-паттерн с entry/SL/TP). См. `patterns/run_3candles_sweep/definition.md`.

Зона интереса (sweep wick c2):
| Направление | Зона |
|---|---|
| **SHORT** | `[max(c2.o, c2.c), c2.high]` (верхний фитиль c2) |
| **LONG** | `[c2.low, min(c2.o, c2.c)]` (нижний фитиль c2) |

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

### i-RDRB + FVG (перемещён в `patterns/`)
Полный setup-паттерн с торговым контекстом — см. `patterns/i_rdrb_fvg/definition.md`.
Зоны интереса:
- **Зона 1 (RDRB-часть)** — POI (см. RDRB выше)
- **Зона 2 (FVG-часть)** — gap-зона FVG

> **VC (Volume Confirmation) НЕ является зоной интереса** — это **обобщённая концепция подтверждения** (предикат над HTF-зоной), не геометрическая зона. Канон: `vc/definition.md`. Здесь только ссылка для справки.

---

## Принципы именования

- «**Зона интереса**» (POI / Point of Interest) — зона, где ждать реакцию. Геометрическое понятие.
- «**Зона ликвидности**» — место скопления стопов / лимиток (FH / FL, liq-под-зоны RDRB, маркер ob_liq).
- «**Зона неэффективности**» — FVG, i-FVG, marubozu (тело).
- «**Блок**» — OB, RDRB POI / block, block_orders, ob_liq.zone. «Наторгованный блок» — точка институционального исполнения, не магнит. См. [[memory:zone-class-liquidity-inefficiency-block|таксономия классов]].

> ⚠ **2026-05-29:** класс «**эффективность**» переименован в «**блок**» по решению пользователя. Согласовано с уже использовавшимся термином «блок наторгованный» (maxV ASVK). Историческая ссылка на vault-файл `три класса зон ликвидность эффективность неэффективность.md` оставлена как есть (не переименован).

---

## Mitigation (изменение зоны интереса при взаимодействии с ценой)

Существует три модели mitigation в зависимости от типа зоны:

### Модель 1: **Wick-fill** (постепенное заполнение)

При каждом касании цены wick'ом зона сжимается на величину проникновения. Каждое последующее касание ещё больше сжимает оставшуюся зону (кумулятивно).

**LONG-направленная зона** (`[zone_lo, zone_hi]`, untraded область снизу/поддержка):
- Касание сверху, `low ≤ zone_hi`:
  - `low > zone_lo` → зона сжимается до **`[zone_lo, low]`**
  - `low ≤ zone_lo` → **зона полностью consumed**

**SHORT-направленная зона** (`[zone_lo, zone_hi]`, untraded область сверху/сопротивление):
- Касание снизу, `high ≥ zone_lo`:
  - `high < zone_hi` → зона сжимается до **`[high, zone_hi]`**
  - `high ≥ zone_hi` → **зона полностью consumed**

Применимо к: **OB, block_orders, FVG, i-FVG, RDRB POI, i-RDRB POI**.

### Модель 2: **First-touch** (одноразовое consumption на zone)

Первое касание зоны wick'ом → зона **полностью consumed** (без постепенного сжатия).

Применимо к: **RB, ob_liq**.

Семантика:
- **RB** = одиночная rejection-свеча с длинным wick'ом. Зона = "место отвергнутого тика". После первого касания зона "отработала".
- **ob_liq** = OB + liquidity marker (одноразовый sweep). После первого touch остаётся только canon-OB (с wick-fill на оставшуюся часть, если actionable).

### Модель 3: **Sweep** (для точечных levels)

Mitigation = wick касается/проходит за level.

Применимо к: **fractal, marubozu (open level), VWAP (anchored)**.

**Fractal:**
- FH swept: `high > level`
- FL swept: `low < level`

**Marubozu (open level = sweep открытия):**
- Bull marubozu (open == low): consumed когда `low ≤ open` (тест открытия снизу)
- Bear marubozu (open == high): consumed когда `high ≥ open` (тест открытия сверху)

Семантика marubozu: body = imbalance area, target = open level (точечный магнит, см. [[feedback-marubozu-is-imbalance-not-support]]). Body как actionable zone актуальна пока open не sweep'нут. После sweep — marubozu полностью отработан.

**VWAP (anchored, ASVK):**
- SHORT VWAP (от FH): swept когда `high(t) > VWAP(t)` (wick пересёк уровень сверху)
- LONG VWAP (от FL): swept когда `low(t) < VWAP(t)` (wick пересёк уровень снизу)
- Особенность: `VWAP(t)` **дрейфует во времени** — sweep оценивается на текущее значение. Strict-canon sweep (wick касается) = consumed; для более тонкой логики см. effectiveness scoring (`vwap_effectiveness.py` — break vs reaction).

### Сводная таблица

| Элемент | Модель | Заметки |
|---|---|---|
| OB | wick-fill | постепенное сжатие |
| block_orders | wick-fill | |
| FVG | wick-fill | |
| i-FVG | wick-fill | на overlap zone (как FVG) |
| RDRB POI | wick-fill | |
| i-RDRB POI | wick-fill | наследует от RDRB |
| **RB** | **first-touch** | одноразовое |
| **ob_liq** | **first-touch** | после → canon OB с wick-fill |
| **marubozu (body)** | **sweep open** | mitigation = касание open level |
| fractal | sweep | wick за level |
| **VWAP (anchored)** | **sweep** | wick пересёк VWAP(t) (time-varying level). См. также effectiveness scoring |

> **VC не входит в таблицу mitigation** — это предикат, не зона. Mitigation касается **HTF-зоны**, к которой VC привязан (OB / block_orders / …) по своим канонам.
