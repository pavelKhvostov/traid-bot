# i-FVG (Inverse FVG)

Композитное событие: **FVG-B противоположного направления первой касается остатка FVG-A после её шринкования** → роль зоны A инвертирует (support → resistance или resistance → support).

Canon источник: `~/traid-bot/vault/knowledge/smc/inverse-fvg-definition.md` (2026-05-13).

> **Canon v2 (2026-06-15) — FINAL.** Старый канон v1 («A untouched between») deprecated — был слишком строг, отсекал большинство реальных i-FVG (например, BTC 12h 2026-06-03 пара $67,516-$67,732, который v1 не находил, а ручная разметка пользователя видела).

> **Не путать с**:
> - `fvg` — одиночная 3-свечная зона (примитив, на котором строится i-FVG)
> - `i_rdrb_fvg` — другой композит (RDRB + FVG того же направления), не имеет отношения к инверсии

## Структура

Две FVG противоположного направления (примитив см. `elements/fvg/definition.md`):

- **FVG-A** — исходная, формируется первой. Между `A.c3` и `B.c1` свечи **могут** касаться A.zone wick'ами — A.zone **шринкается** через wick-fill mitigation (Правило 2 Модель 1).
- **FVG-B** — обратная по направлению, формируется позже. Её свечи (`B.c1, B.c2, B.c3`) wick'ом касаются **shrunk_A** (остатка A после шринкования). Это inversion trigger.

Свечи: `A.c1, A.c2, A.c3, …, B.c1, B.c2, B.c3` (между `A.c3` и `B.c1` — произвольное число свечей, могут шринкать A).

## Условия (canon v2)

1. **FVG-A валидна** (детектор `detect_fvg` возвращает не-None).
2. **FVG-B валидна** и `B.direction != A.direction`.
3. **B сформирована позже A**: индекс `B.c1 > A.c3`.
4. **A не consumed между**: применяем `apply_wick_fill_mitigation(A.zone, A.direction, between_bars)`. Если `state.is_consumed` — i-FVG **не формируется**.
5. **shrunk_A** = `state.active_zone` после wick-fill mit через between.
6. **B касается shrunk_A**: хотя бы одна свеча из `(B.c1, B.c2, B.c3)` — wick в shrunk_A.
7. **shrunk_A ∩ B.zone имеет ширину > 0**.

## Направление i-FVG

Определяется направлением FVG-B:

| FVG-A (initial role) | FVG-B | A после инверсии | i-FVG direction |
|---|---|---|---|
| bullish (support) | bearish | resistance | **SHORT** |
| bearish (resistance) | bullish | support | **LONG** |

## Зоны интереса

| Зона | Что это |
|---|---|
| **A.zone** | Исходная зона FVG-A до шринкования |
| **a_shrunk** | A.zone после wick-fill mit через between bars |
| **B.zone** | Зона новой FVG-B (сам i-FVG как FVG) |
| **overlap** | `[max(a_shrunk.lo, B.zone.lo), min(a_shrunk.hi, B.zone.hi)]` — **основная зона i-FVG-события (ZoI)** |

По умолчанию **«зона интереса i-FVG» = overlap** — область пересечения остатка A с новой B.

## Эталонный пример из BTC 12h (2026-06-15 verified)

**FVG-A** (LONG) — 2026-04-05 03:00 МСК → 2026-04-06 03:00 МСК:
- A.c1: O=67300 H=67307 L=66612 C=66999
- A.c2: O=66999 H=69136 L=66681 C=69034 (displacement up)
- A.c3: O=69034 H=70283 L=68777 C=69615
- A.zone initial = `[67307, 68777]` (w=$1,469)

**Шринкование через between**:
- 2026-04-06 15:00 МСК: bar.low=68,300 → A=[67307, 68300]
- 2026-04-07 03:00 МСК: bar.low=68,072 → A=[67307, 68072]
- 2026-04-07 15:00 МСК: bar.low=67,732 → A=[67307, 67732] (далее не касается ≈ 56 дней)

**FVG-B** (SHORT) — 2026-06-02 03:00 МСК → 2026-06-03 03:00 МСК:
- B.c1: O=71409 H=71409 L=69325 C=69462
- B.c2: O=69462 H=69548 L=66193 C=66761 (displacement down, B.c2 wick касается shrunk_A)
- B.c3: O=66761 H=67516 L=65426 C=67067
- B.zone = `[67516, 69325]`

**i-FVG ZoI** = `overlap(shrunk_A, B.zone)` = `[67516, 67732]` (w=$216) → SHORT

## Mitigation после armed

После formation (B.c3 close) применяется wick-fill mit на `overlap` zone, direction = `i-FVG.direction`:
- SHORT i-FVG: bar.high тестирует overlap снизу-вверх; consumed когда bar.high ≥ overlap.hi
- LONG i-FVG: bar.low тестирует overlap сверху-вниз; consumed когда bar.low ≤ overlap.lo

## Изменения канона

- **v1 (2026-05-13)**: «A untouched between» — DEPRECATED. Слишком строг, отсекал валидные кейсы где между фазами цена многократно тестировала A.
- **v2 (2026-06-15)**: **CURRENT**. A шринкается через wick-fill, ZoI = overlap(shrunk_A, B.zone).

## Связанные элементы

- `fvg` — примитив, на котором строится i-FVG (используется дважды для A и B)
- `_mitigation.apply_wick_fill_mitigation` — функция шринкования A.zone
- `i_rdrb_fvg` — другой композит с FVG (не путать)
