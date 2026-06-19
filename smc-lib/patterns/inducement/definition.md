# Inducement (IDM)

> ⚠ **Это не фиксированный candle-паттерн, а структурная закономерность.** Inducement — композитная зона интереса, формируемая последовательностью из 8 структурных шагов. Описывается через состояние других элементов (OB, FVG, CHoCH, Fractal), не имеет собственной геометрии «N свечей подряд».

## Что такое Inducement

**Inducement — композитная зона интереса:**

| Подзона | Что это | Семантика |
|---|---|---|
| **FVG (остаточный)** | оставшаяся непокрытая часть FVG после **частичного** касания на корректирующем bounce | непроторгованная inefficiency, магнит для возврата |
| **OB (не митингованный)** | OB-зона на топе/дне исходного импульса, **ни разу не протестированная** ценой после своего формирования | institutional execution zone, ждёт первого касания |

**Inducement = FVG_residual ∪ OB_unmitigated.** Обе подзоны лежат в одной HTF-области (premium для Bearish setup / discount для Bullish). Их union формирует «ловушку» — финальную entry-зону, в которую цена возвращается после серии структурных событий.

**Жизненный цикл зоны:**

| Фаза | Когда | Состояние |
|---|---|---|
| **Pending** | до #7 | подзоны существуют, но композит ещё не подтверждён (нет BOS-continuation) |
| **Armed** | **после формирования #7** (BOS continuation) | inducement zone валидна и ждёт возврата цены |
| **Triggered** | на #8 (sweep IDM-фрактала #6 + касание зоны) | entry в направлении исходного CHoCH |
| **Consumed** | после wick-fill подзон по Правилу 2 | зона больше не actionable |

**Зона активируется именно после #7** (BOS-continuation), не раньше: пока #7 не сформирован, корректирующий bounce #5 может быть началом разворота вверх, а не inducement-trap'ом.

## Структурная последовательность (Bearish setup)

Канон-визуал: `refs/ict_schematic_premium_discount.jpg` (ICT schematic, где **MSS = CHoCH**) и `refs/user_numbered_sequence_btc_4h.png` (BTC 4h, шаги 1–8 пронумерованы пользователем).

| # | Элемент | Условие | Роль в Inducement |
|---|---|---|---|
| **1** | **OB** (SHORT) | формируется на топе bull-импульса; prev bull + cur bear, `cur.close < prev.open` | будущая **подзона A** inducement (= `OB.zone` = rally area) |
| **2** | **FVG** (bearish) | bearish FVG внутри или сразу после OB; `c1.low > c3.high` | будущая **подзона B** inducement (полностью неотработанная пока) |
| **3** | **CHoCH** (bearish) | `close < lower_fractal.value`, `os_prev ∈ {0, +1}` → bearish CHoCH; slом uptrend (= MSS на ICT-схеме) | **gate** последовательности: без CHoCH inducement не формируется |
| **4** | **Fractal Low** | Williams strict FL, формирует новый LL после CHoCH | подтверждение нового bearish-направления |
| **5** | **Частичное перекрытие FVG** | корректирующий bounce касается FVG, заполняя её лишь частично (wick-fill model) | оставляет **FVG_residual** (= подзона B inducement) |
| **6** | **Fractal High = IDM-маркер** | Williams strict FH на топе корректирующего bounce; mini-LH ниже LH до CHoCH | **liquidity marker**: стопы шортов сидят над ним; sweep активирует ловушку. *Сам фрактал — отдельный элемент, не inducement*. |
| **7** | **Fractal Low (continuation)** | новый FL ниже #4; BOS bearish (continuation, не CHoCH) | подтверждение продолжения bearish-тренда |
| **8** | **Возврат в Inducement (sweep + entry)** | цена возвращается вверх, `high(j) > fractal_6.value` (sweep IDM), `low(j+k) ∈ Inducement_zone` (вход в композит) | **trigger**: sweep #6 + касание Inducement_zone → SHORT entry |

После #8 — финальный bearish leg (обычно сильное движение к downside target).

## Структурная последовательность (Bullish setup — зеркально)

| # | Элемент | Условие |
|---|---|---|
| 1 | **OB** (LONG) | prev bear + cur bull, `cur.close > prev.open`; на дне bear-импульса |
| 2 | **FVG** (bullish) | `c1.high < c3.low` |
| 3 | **CHoCH** (bullish) | `close > upper_fractal.value`, `os_prev ∈ {0, -1}`; slом downtrend |
| 4 | Fractal High | Williams strict FH, новый HH после CHoCH |
| 5 | Частичное перекрытие FVG (bullish) | корректирующий pullback частично заполняет FVG |
| 6 | **Fractal Low = IDM-маркер** | mini-HL над HL до CHoCH; стопы лонгов сидят под ним |
| 7 | Fractal High (continuation) | новый HH выше #4; BOS bullish |
| 8 | **Возврат в Inducement** | `low(j) < fractal_6.value` (sweep IDM) + `high(j+k) ∈ Inducement_zone` → LONG entry |

## Геометрия композитной зоны

| Setup | Inducement_zone |
|---|---|
| **Bearish** | `[OB.zone_low, OB.zone_high] ∪ [FVG_residual.low, FVG_residual.high]` — обе обычно перекрываются / соприкасаются в premium-half (62–79% Fib от move CHoCH→#7) |
| **Bullish** | то же, но в discount-half |

**FVG_residual.** Если на #5 wick зашёл в FVG на глубину `d` (от ближайшей границы), то по wick-fill model (см. `~/smc-lib/rules.md` Правило 2):
- Bullish FVG `[c1.high, c3.low]`, касание сверху wick'ом до `low_touch`: residual = `[c1.high, low_touch]`
- Bearish FVG `[c3.high, c1.low]`, касание снизу wick'ом до `high_touch`: residual = `[high_touch, c1.low]`

Если `low_touch ≤ c1.high` (для bullish) — FVG **полностью consumed**, inducement-композит вырождается в один OB.

**OB.unmitigated.** Если между #1 и #8 ни один бар не входил в `OB.zone` wick'ом — OB остаётся неотработанным; иначе условие inducement не выполнено (canon requires mitigation_status(OB) == 0 at step #8).

## Активация и триггер entry

**Армирование зоны (Armed):** после подтверждения #7 (BOS continuation) — все 7 структурных предусловий выполнены, композит OB ∪ FVG_residual известен и валиден.

**Триггер entry (Triggered):** на баре `j > #7`:

1. **Sweep IDM-фрактала #6**: `high(j) > fractal_6.high` (bearish) / `low(j) < fractal_6.low` (bullish)
2. **Вход в композит**: в том же окне касание `Inducement_zone` (тот же бар или последующий, `j ≤ k ≤ j + small_window`)
3. **Reaction-confirmation** (опционально, по Правилу 1): пробойная свеча + ≥3 подтверждающих в обратную сторону = подтверждение разворота от inducement

Без полной цепочки #1–#7 inducement не армирован → triggered невозможно.

## Зона интереса

**Inducement сама по себе и есть зона интереса** (композит FVG_residual ∪ OB_unmitigated). Mitigation — wick-fill (наследуется от FVG и OB по Правилу 2).

| Тип | Зона интереса | Trigger entry | Действие |
|---|---|---|---|
| **Bearish Inducement** | OB (SHORT, unmit) ∪ FVG_residual (bearish) | sweep fractal_6 высоко + касание зоны | SHORT |
| **Bullish Inducement** | OB (LONG, unmit) ∪ FVG_residual (bullish) | sweep fractal_6 низко + касание зоны | LONG |

## Параметры детекции

| Параметр | Default | Описание |
|---|---|---|
| `fractal_length` | 5 | Williams length (= LuxAlgo canon, см. `choch_bos`) |
| `max_bars_choch_to_idm` | 30 | максимум баров от CHoCH (#3) до формирования IDM-fractal (#6) |
| `max_bars_idm_to_continuation` | 30 | от #6 до confirmation BOS (#7) |
| `max_bars_to_return` | 50 | от #7 до возврата в зону (#8) |
| `require_fvg_partial_fill` | True | если False — FVG может оставаться нетронутой (но строгий канон требует частичного перекрытия) |
| `require_ob_unmitigated_at_return` | True | OB не должен быть митингованным до #8 |
| `min_idm_sweep_pct` | 0.0 | глубина sweep'а IDM (`high(j) - fractal_6.high` / fractal_6.high × 100); 0 = касание wick'ом |

## Отличие от других элементов

| Элемент | Что snap'ается / тестируется | Контекст |
|---|---|---|
| **Inducement** | mini-LH/HL (IDM-фрактал) + composite zone (FVG+OB) | **ПОСЛЕ** CHoCH; разворот после reversal sequence |
| **CHoCH** | major structural low/high | сама точка slома структуры |
| **BOS** | major structural low/high в текущем направлении | continuation |
| **Liquidity Sweep (4-candle)** | старый FH/FL одним движением | standalone, без CHoCH-цепочки |
| **Mitigation Block** | OB, пробитый с закреплением по Правилу 1 | flip-zone после полного пробоя OB |
| **Breaker Block** | OB, пробитый структурно (BOS opposite) | flip-zone, пробитый фитиль prev |

## Связанные элементы

- **`ob`** — подзона A inducement (OB unmitigated)
- **`fvg`** — подзона B inducement (residual после частичного fill)
- **`choch_bos`** — gate-условие #3 (требуется CHoCH bearish/bullish соответственно)
- **`fractal`** — точки #4, #6, #7 (Williams strict, length=5)

## Источники

- ICT Month01 + ICT-методология-7-концептов (pavel-notes 2026-06-10).
- `refs/ict_schematic_premium_discount.jpg` — ICT schematic с Premium/Discount Array, MSS, IDM, OTE (62-79% Fib).
- `refs/user_numbered_sequence_btc_4h.png` — реальный пример BTC 4h с пронумерованной последовательностью 1–8.

## TODO

- [ ] `code.py` — переписать под композитный детектор: OB-scan + FVG-scan + CHoCH-event + fractal-chain + zone overlap + return trigger
- [ ] `tests/` — fixtures под полную последовательность 1–8 (positive) + missing CHoCH (negative) + FVG fully consumed (negative) + OB already mitigated (negative)
- [ ] Backtest: Inducement как фильтр reversal-entry vs raw CHoCH-entry на 6y BTC
- [ ] Сравнение с OTE 62-79% Fib retracement — обычно inducement-зона совпадает с OTE
