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

### Зона интереса OB — всегда drop/rally area (canon 2026-06-14)

| Направление | **Зона интереса OB** |
|---|---|
| **LONG** | `[min(prev.low, cur.low), prev.open]` (drop area) |
| **SHORT** | `[prev.open, max(prev.high, cur.high)]` (rally area) |

**Drop / Rally area** — отвергнутое движение `prev`, cancelled реакцией `cur`. **Институциональная зона исполнения** — где крупный игрок исполнил ордера против retail.

### Связка с Breaker Block

Если выполняется условие полного структурного пробоя prev (`cur.close > prev.high` для LONG / `cur.close < prev.low` для SHORT), **параллельно с OB формируется самостоятельный элемент Breaker Block** со своей зоной интереса = проткнутый фитиль prev. OB ZoI при этом не расширяется. См. §9 ниже и `elements/breaker_block/definition.md`.

> ⚠ **2026-06-14**: breaker block вынесен из OB ZoI в самостоятельный элемент. Старый канон (breaker как подзона OB c расширением Full ZoI) — deprecated.

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

Canon: `elements/i_fvg/definition.md` (**canon v2 — 2026-06-15**) + [[inverse-fvg-definition]] (vault).

Композит: **FVG-B противоположного направления** касается **остатка FVG-A после шринкования** → роль зоны A инвертирует (support ↔ resistance).

> ⚠ **Canon v2 (2026-06-15)** — старый v1 («A untouched between») DEPRECATED. A.zone теперь **шринкается** wick-fill'ом через between bars; ZoI = `overlap(shrunk_A, B.zone)`. Verified на real BTC 12h: 4 active i-FVG в ±$15K на пин 2026-06-15 совпадают с ручной разметкой пользователя.

**Условия (v2)**:
1. FVG-A валидна, FVG-B валидна, `B.direction != A.direction`
2. Между `A.c3` и `B.c1` применяется **wick-fill mitigation** к A.zone (направление = A.direction). Если A полностью consumed — i-FVG **не формируется**.
3. `shrunk_A` = остаток A.zone после mit через between (= a.zone если нет касаний)
4. Хотя бы одна свеча из `(B.c1, B.c2, B.c3)` касается `shrunk_A` (inversion trigger)
5. `shrunk_A ∩ B.zone ≠ ∅`

**Зоны**:

| Зона | Что это |
|---|---|
| **A.zone** | Исходная FVG-A (до шринкования) |
| **a_shrunk** | A.zone после wick-fill через between bars |
| **B.zone** | Новая FVG-B (сам i-FVG как FVG) |
| **overlap** | `[max(a_shrunk.lo, B.zone.lo), min(a_shrunk.hi, B.zone.hi)]` — пересечение остатка A и B = **зона интереса i-FVG-события** |

| Сценарий | Роль A до | Роль A после | i-FVG direction |
|---|---|---|---|
| A bull → B bear | support | resistance | **SHORT** |
| A bear → B bull | resistance | support | **LONG** |

По умолчанию **«зона интереса i-FVG» = overlap(shrunk_A, B.zone)** (двойная значимость).

**Эталонный real BTC кейс**: FVG-A 2026-04-05/06 (LONG, `[67307, 68777]`) шринкается через 3 wick'a в апреле до `[67307, 67732]`. FVG-B 2026-06-02/03 (SHORT, `[67516, 69325]`) формируется через 56 дней. `overlap = [67516, 67732]` = i-FVG SHORT zone w=$216.

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

Canon: `patterns/ob_sweep_liq_4candles/definition.md` (перенесён 2026-06-14 из elements/ в patterns/ как retrospective event-marker, не atomic zone). ⚠️ Имя `_4candles` историческое.

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

## 9) Breaker Block (canon 2026-06-14)

Canon: `elements/breaker_block/definition.md`. **Самостоятельный элемент** со своей зоной интереса = **проткнутый фитиль prev (OB-candle)**.

### Условие формирования

Полный структурный пробой prev. Может произойти:
- **Immediate (на формировании OB)**: `cur.close > prev.high` (LONG) / `cur.close < prev.low` (SHORT).
- **Delayed (post-OB)**: позже бар j закрывается за пределами полной OB-области; см. detect_breaker в code.py.

### Зона интереса

| Тип | Зона интереса = проткнутый фитиль prev | Действие |
|---|---|---|
| **Bullish Breaker** (LONG OB candle, прев — bear) | `[prev.open, prev.high]` (верхний фитиль bear-prev) | SHORT на возврате цены В зону снизу (если post-BOS) / LONG-confluence (если immediate) |
| **Bearish Breaker** (SHORT OB candle, прев — bull) | `[prev.low, prev.open]` (нижний фитиль bull-prev) | LONG на возврате цены В зону сверху (post-BOS) / SHORT-confluence (immediate) |

Институциональный flip-уровень — отвергнутое перо prev, проткнутое реакцией. Геометрия одинакова в обоих контекстах (immediate / delayed).

> ⚠ **2026-06-14**: вынесено из OB ZoI в самостоятельный элемент. Старый канон (зона = drop/rally area бывшего OB) deprecated.

---

## 10) Mitigation Block (draft, 2026-06-13)

Canon: `elements/mitigation_block/definition.md`. ABC-логика: зона, где институционал закрывает убыточную позицию → разворот.

| Тип | A-B-C структура | Зона интереса = OB в точке A |
|---|---|---|
| **Bearish Mitigation** | A=HH, B=HH>A, C=LL<A (MSS вниз) | `[A_low, A_open]` |
| **Bullish Mitigation** | A=LL, B=LL<A, C=HH>A (MSS вверх) | `[A_open, A_high]` |

PD Array priority = **#1** (выше Breaker, FVG, OB).

---

## 11) CHoCH / BOS — Market Structure (LuxAlgo canon, 2026-06-14)

Canon: `elements/choch_bos/definition.md`. **Два разных элемента** в downstream, общий код — state machine `os` (LuxAlgo Pine v5).

| Элемент | Условие триггера (на закрытии бара) | Триггер-точка | Семантика |
|---|---|---|---|
| **Bullish BOS** | `close > upper_fractal.value` AND `os ∈ {0, +1}` | `upper.value` (FH) | continuation up |
| **Bullish CHoCH** | `close > upper_fractal.value` AND `os == -1` | `upper.value` (FH) | reversal up (slом downtrend) |
| **Bearish BOS** | `close < lower_fractal.value` AND `os ∈ {0, -1}` | `lower.value` (FL) | continuation down |
| **Bearish CHoCH** | `close < lower_fractal.value` AND `os == +1` | `lower.value` (FL) | reversal down (slом uptrend) |

Фрактал = Williams strict, `length=5` (N=2). Триггер = **одно закрытие** за уровнем (Правило 1 опционально). Ни CHoCH, ни BOS не являются зонами — это триггеры разворота / продолжения.

---

## 12) Inducement (IDM) — composite ZoI после CHoCH (canon 2026-06-14)

Canon: `patterns/inducement/definition.md` (перенесён 2026-06-14 из elements/ в patterns/ как многоэлементная структурная закономерность). Inducement сам = композитная зона интереса.

**Зона интереса = `OB (unmitigated) ∪ FVG (residual after partial fill)`** — обе подзоны в premium-half (Bearish) или discount-half (Bullish).

| Setup | Inducement_zone (geometry) | Trigger entry |
|---|---|---|
| **Bearish** | `OB.zone (SHORT, unmit)` ∪ `FVG_residual (bearish)` | sweep `fractal_6.high` высоко + касание зоны → SHORT |
| **Bullish** | `OB.zone (LONG, unmit)` ∪ `FVG_residual (bullish)` | sweep `fractal_6.low` низко + касание зоны → LONG |

**Gate-условие:** все шаги 1–7 должны быть выполнены последовательно, обязательно с CHoCH (= MSS на ICT-схеме) между OB/FVG-формированием и mini-fractal'ом IDM. Без CHoCH — не inducement.

**Жизненный цикл:** zone становится **armed** ПОСЛЕ формирования #7 (BOS continuation), не раньше; **triggered** на #8 (sweep IDM + касание composite).

Mitigation — wick-fill (наследуется от OB и FVG по Правилу 2).

> ⚠ **2026-06-14**: deprecated старый канон «pro-trend continuation sweep mini-HL/LH в активном тренде». Новый канон — post-CHoCH composite zone, ICT/LuxAlgo canon.

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
