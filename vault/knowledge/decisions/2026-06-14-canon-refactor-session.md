# 2026-06-14 — Session: Canon refactor (OB / Breaker / Mitigation / CHoCH-BOS / Rules cleanup)

> **Тип:** architectural decisions  
> **Скоуп:** `~/smc-lib/` — массовый рефактор канона элементов, правил, реструктуризация elements/ vs patterns/  
> **Длительность:** одна большая сессия 2026-06-14  
> **Статус:** ✅ все изменения зафиксированы в коде + .md канон + 150/150 tests PASSED + memory обновлён

---

## TL;DR — что изменилось

1. **OB canon (2026-06-14)** — `OB.zone = drop/rally area` всегда. Breaker block вынесен в самостоятельный элемент.
2. **Breaker Block** — отдельный элемент со своей ZoI = проткнутый фитиль prev `[prev.open, prev.high]` (LONG) / `[prev.low, prev.open]` (SHORT). Заменяет старый канон body синтетической свечи.
3. **Mitigation Block** — переопределён: полностью пробитый OB + закрепление по Правилу 1. ZoI = бывшая OB drop/rally area, роль flip.
4. **Правило 1 «закрепление»** — переписано: пробойная + **3 подтверждающие** с **open И close** за уровнем (раньше было 1 + 1 close).
5. **CHoCH/BOS** — папка `elements/choch/` → `elements/choch_bos/`, переписан под LuxAlgo Pine v5 canon. CHoCH и BOS остаются разными элементами downstream.
6. **i-RDRB liq инвертирован** — `[c3.body_top, c1.low]` (LONG) / `[c1.high, c3.body_bottom]` (SHORT), не наследуется из RDRB.
7. **Inducement** — composite ZoI (OB_unmitigated ∪ FVG_residual) после CHoCH, 8-шаговая закономерность. Перенесён `elements/` → `patterns/`.
8. **Перенос в patterns/** — `inducement`, `rdrbx`, `ob_sweep_liq_4candles`.
9. **Правила 3, 4, 5, 11, 12 архивированы** → `~/smc-lib/projects/_корзина/`. Активны: 1, 2, 6, 7, 8, 9, 10, 13.
10. **Memory обновлён** — 5 feedback-memory файлов + MEMORY.md индекс.

---

## 1. OB canon — drop/rally area only

### Было

`OB.zone` включала **breaker subzone** при полном пробое prev (cur.close > prev.high для LONG). Поле `OB.breaker_block: Interval | None` в dataclass.

### Стало

`OB.zone = drop/rally area` **всегда**, регардлесс полного пробоя:
- LONG: `[min(prev.low, cur.low), prev.open]`
- SHORT: `[prev.open, max(prev.high, cur.high)]`

Поле `OB.breaker_block` удалено. Добавлен helper `is_full_break(ob) -> bool` для триггера формирования отдельного Breaker Block.

### Файлы

- `elements/ob/definition.md` — переписан раздел «Зона интереса»
- `elements/ob/code.py` — `OB` dataclass упрощён, `detect_ob` возвращает drop/rally area
- `elements/ob/tests/test_ob.py` — 13 тестов обновлены
- `elements/zone_of_interest.md` §1 — синхронизирован

### Канонические PNG (`~/Desktop/i-rdrb-charts/`)

- `ob_zone_of_interest_canon.png` — LONG + SHORT
- `ob_zone_of_interest_no_breaker.png` — пример без full break
- `wick_fill_mitigation_example.png` — wick-fill cumulative shrink

---

## 2. Breaker Block — standalone element

### Геометрия (canon 2026-06-14)

| Тип | prev | ZoI = проткнутый фитиль prev |
|---|---|---|
| **Bullish Breaker** | bear OB-candle | `[prev.open, prev.high]` (верхний фитиль) |
| **Bearish Breaker** | bull OB-candle | `[prev.low, prev.open]` (нижний фитиль) |

Семантика: institutional flip-zone — отвергнутый ранее wick prev, проткнутый реакцией cur. При возврате цены → bias flip.

### Файлы

- `elements/breaker_block/definition.md` — переписан
- `elements/breaker_block/code.py` — `BreakerBlock` dataclass с полем `zone`; `detect_breaker` использует pierced wick формулу
- `elements/breaker_block/tests/test_breaker_block.py` — 7 тестов

### Старый канон (deprecated)

- body синтетической свечи `[prev.open, cur.close]` — больше не используется
- Drop/rally area как breaker zone (из старого `breaker_block/definition.md`) — deprecated

### PNG

- `breaker_block_zone_of_interest.png`
- `ob_vs_breaker_separate_zones.png` (наглядное разделение OB и Breaker)

---

## 3. Mitigation Block — redefined

### Новый canon

Mitigation Block формируется когда:
1. Существует OB (LONG/SHORT)
2. Полный пробой OB.zone в обратную сторону (close за противоположной границей)
3. **Закрепление по Правилу 1**: пробойная + 3 подтверждающих с open И close за пробитым уровнем

После закрепления — **OB.zone становится Mitigation Block**, роль инвертирована (LONG OB support → Bearish MB resistance).

### Геометрия

| Тип | ZoI | Действие на возврате |
|---|---|---|
| **Bearish MB** (LONG OB пробит вниз) | бывшая drop area | SHORT |
| **Bullish MB** (SHORT OB пробит вверх) | бывшая rally area | LONG |

Mitigation: wick-fill (наследуется от OB).

### Файлы

- `elements/mitigation_block/definition.md` — старый ABC/MSS canon **остался в файле** (TODO — переписать), но **memory зафиксировал новый canon**
- `elements/mitigation_block/code.py` — старый ABC detector остаётся; **нет implementation под новый canon** (TODO)
- PNG: `mitigation_block_zone_of_interest.png`

### TODO

- [ ] Переписать `mitigation_block/definition.md` под новый canon
- [ ] Заменить ABC-based `detect_mitigation_at` на новый «broken OB + Rule 1» detector

---

## 4. Правило 1 — Закрепление

### Было

Пробойная + 1 подтверждающая с close за уровнем = минимум 2 свечи.

### Стало

Пробойная + **3 подтверждающие** свечи, у каждой **И open, И close** за пробитым уровнем = минимум **4 свечи**.

### Файлы

- `rules.md:7-16` — переписан
- `README.md:63` — обновлено описание

### Применение

- Mitigation Block формирование (см. п.3)
- Inducement opt. trigger на #8
- Expert Phase 3 closing-confirmation

---

## 5. CHoCH/BOS — LuxAlgo canon

### Изменения

- Папка `elements/choch/` → **`elements/choch_bos/`**
- Алгоритм переписан под **LuxAlgo Pine v5** «Market Structure CHoCH/BOS (Fractal)» canon (CC BY-NC-SA)
- State machine `os ∈ {0, ±1}`; trigger = одно close-cross
- Williams strict N=2, `length=5` default

### Семантика

- **CHoCH** = reversal (`os` flip)
- **BOS** = continuation (`os` same/initial)
- Оба элемента **разные** в downstream (`ALL_TYPES`, ML, strategies)
- Общий код в одной папке только из-за shared state machine

### Файлы

- `elements/choch_bos/definition.md` — LuxAlgo canon
- `elements/choch_bos/code.py` — `MarketStructureEvent` dataclass; `scan_market_structure()`, `detect_choch()`, `detect_bos()`
- `elements/choch_bos/tests/test_choch_bos.py` — 9 тестов
- `elements/choch_bos/refs/luxalgo_market_structure_fractal.{pine,rtf}` — canon источник
- `elements/zone_of_interest.md` §11 — обновлён

### Семантический mapping

- **MSS** в ICT-схемах = наш **CHoCH** (терминологический синоним)

---

## 6. i-RDRB — liq инвертирован

### Было (canon до 2026-06-14)

«Все зоны (POI, block, liq) наследуются из подлежащего RDRB без изменений.»

### Стало (canon 2026-06-14)

`block` наследуется из RDRB. **`liq` переопределяется** — инвертируется в сторону разворота:

| i-RDRB | liq (новый canon) | Условие V1 |
|---|---|---|
| **LONG i-RDRB** (на SHORT RDRB) | `[c3.body_top, c1.low]` (ниже block) | `c3.body_top < c1.low` |
| **SHORT i-RDRB** (на LONG RDRB) | `[c1.high, c3.body_bottom]` (выше block) | `c1.high < c3.body_bottom` |

POI = block ∪ liq. V2 если liq пустой.

### Семантика

«Зона обманутой ликвидности» в сторону разворота — стопы участников, поверивших в C2 displacement и оказавшихся в ловушке после C4 reversal.

### Файлы

- `elements/i_rdrb/definition.md` — раздел «Зоны» переписан
- `elements/i_rdrb/code.py` — `IRDRB` dataclass: добавлены `variant`, `poi`, `block`, `liq`
- `elements/i_rdrb/tests/fixtures.json` — i_rdrb_poi/block/liq добавлены
- `elements/i_rdrb/tests/test_i_rdrb.py` — 9 тестов

---

## 7. Inducement — composite ZoI (post-CHoCH)

### Новый canon

Не паттерн фиксированного числа свечей — **структурная закономерность из 8 шагов**:

1. OB
2. FVG (aligned)
3. **CHoCH** (gate-условие)
4. Fractal Low (подтверждение направления)
5. Частичное перекрытие FVG (residual)
6. Fractal High = **IDM** (mini-LH)
7. Fractal Low (BOS continuation) — **zone armed после этого шага**
8. Возврат + sweep IDM = trigger entry

**Inducement ZoI = OB (unmitigated) ∪ FVG (residual after #5)** — composite zone.

### Жизненный цикл

| Фаза | Когда |
|---|---|
| Pending | до #7 |
| **Armed** | после #7 (BOS continuation) |
| Triggered | на #8 (sweep IDM + касание composite) |
| Consumed | wick-fill (Правило 2) |

### Перенос

`elements/inducement/` → **`patterns/inducement/`** (многоэлементная закономерность, не atomic primitive).

В `patterns/inducement/refs/` сохранены canon-картинки:
- `ict_schematic_premium_discount.jpg`
- `user_numbered_sequence_btc_4h.png`

### Старый canon (deprecated)

Pro-trend continuation sweep mini-HL/LH в активном тренде — больше не canon.

### TODO

- code.py + tests всё ещё реализуют старый canon (требуется переписать под composite ZoI detector с OB + FVG + CHoCH + fractal chain)

---

## 8. Перенос elements/ → patterns/

| Элемент | Куда | Причина |
|---|---|---|
| `inducement` | `patterns/` | многоэлементная structural sequence |
| `rdrbx` | `patterns/` | extended RDRB с delayed Cn (только canon doc) |
| `ob_sweep_liq_4candles` | `patterns/` | retrospective marker, не forward-looking zone |

Обновлены: `patterns/README.md`, `elements/zone_of_interest.md`, импорты в тестах.

---

## 9. Архивация правил

### Перенесены в `~/smc-lib/projects/_корзина/`

| Правило | Файл архива |
|---|---|
| **3** (VC predicate) | `rule_3_vc_volume_confirmation.md` |
| **4** (LTF FVG усиливает HTF OB, был в разработке) | `rule_4_ltf_fvg_strengthens_htf_ob.md` |
| **5** (Стратегия ASVK 1.1.1) | `rule_5_asvk_strategy_vc_in_htf_zone.md` |
| **11** (Компрессия, был в разработке) | `rule_11_compression_efficient_pricing.md` |
| **12** (Macro TOTALES + USDT.D) | `rule_12_macro_totales_usdtd.md` |

### Stub'ы оставлены в rules.md

Каждое правило заменено заглушкой со ссылкой на архив. **Нумерация сохранена** для устойчивости backlinks. Backlinks `[[Правило N]]` помечены `[[Правило N (ARCHIVED)]]`.

### Активные правила (8 из 13)

1, 2, 6, 7, 8, 9, 10, 13.

---

## 10. Memory обновления

Добавлены 5 feedback-memory файлов:
- `feedback-rule-1-zakrepleniye-updated.md`
- `feedback-ob-breaker-canon-separate.md`
- `feedback-mitigation-block-canon.md`
- `feedback-choch-bos-luxalgo-canon.md`
- `feedback-inducement-composite-zoi-patterns.md`

Все добавлены в `~/.claude/projects/-Users-vadim/memory/MEMORY.md` индекс с cross-references `[[name]]`.

---

## 11. Текущий счёт элементов

| Слой | Count | Список |
|---|---|---|
| `elements/` | **14** атомарных | ob, fvg, fractal, marubozu, block_orders, rdrb, i_rdrb, i_fvg, ob_liq, ob_vc, rb, breaker_block, mitigation_block, choch_bos |
| `patterns/` | **5** | run_3candles_sweep, i_rdrb_fvg, inducement, rdrbx, ob_sweep_liq_4candles |

`ALL_TYPES` (prediction-algo) — без изменений:
```python
("OB", "FVG", "fractal", "marubozu", "block_orders", "RDRB", "iRDRB", "iFVG", "ob_liq", "ob_vc")
```

---

## 12. PNG artifacts (`~/Desktop/i-rdrb-charts/`)

Канонические визуализации, отрисованные в сессии:

| Файл | Что |
|---|---|
| `ob_zone_of_interest_canon.png` | OB LONG + SHORT (canon 2026-06-14) |
| `ob_zone_of_interest_no_breaker.png` | OB без full break |
| `ob_vs_breaker_separate_zones.png` | OB + Breaker как отдельные зоны |
| `breaker_block_zone_of_interest.png` | Standalone Breaker Block |
| `mitigation_block_zone_of_interest.png` | LONG/SHORT MB после Rule 1 закрепления |
| `wick_fill_mitigation_example.png` | Cumulative wick-fill на LONG OB |
| `fvg_wick_fill_mitigation.png` | Bullish FVG wick-fill |
| `fractal_zone_of_interest.png` | FH/FL (Williams N=2) |
| `marubozu_zone_of_interest.png` | LONG/SHORT marubozu + sweep open |
| `block_orders_zone_of_interest.png` | LONG/SHORT block_orders (N₁=3, N₂=2) |
| `rdrb_zone_of_interest.png` | LONG/SHORT RDRB V1 |
| `i_rdrb_zone_of_interest.png` | LONG/SHORT i-RDRB V1 (новый liq canon) |
| `rdrb_irdrb_v2_variants.png` | 4 V2 кейса |
| `i_fvg_zone_of_interest.png` | Bullish/Bearish i-FVG |
| `ob_liq_zone_of_interest.png` | LONG/SHORT ob_liq (без Williams) |
| `ob_vc_zone_of_interest.png` | LONG/SHORT ob_vc (partial overlap drop/rally) |
| `rb_zone_of_interest.png` | TOP/BOTTOM RB + first-touch |

---

## 13. Тесты

**150/150 PASSED** в `elements/` + `patterns/` после всех изменений.

Основные изменения:
- 13 тестов OB
- 7 тестов Breaker Block
- 9 тестов CHoCH/BOS (новый файл)
- 9 тестов i-RDRB (расширены под новый liq canon)
- 5 тестов inducement (мигрировали с импортом из patterns/)

---

## Связанные документы vault

- `~/traid-bot/vault/knowledge/smc/универсальные определения OB и FVG.md` — old canon source, частично deprecated
- `~/traid-bot/vault/knowledge/smc/что такое VC volume confirmation.md` — старая VC docs (Rule 3 archived)
- `~/traid-bot/vault/knowledge/smc/три класса зон ликвидность эффективность неэффективность.md` — taxonomy (актуально)

## Открытые задачи (TODO для следующих сессий)

- [ ] `elements/mitigation_block/definition.md` + `code.py` — переписать под новый canon (broken OB + Rule 1) вместо старого ABC/MSS
- [ ] `patterns/inducement/code.py` + tests — реализовать composite-ZoI detector (OB + FVG + CHoCH chain) вместо старого pro-trend
- [ ] `elements/block_orders/definition.md` — проверить нужно ли обновлять canon под NEW OB-style drop/rally area (для согласованности с #3 из user's TV markup analysis)
- [ ] Update memory `zone-class-liquidity-inefficiency-block` если добавится новый класс или таксономия пересмотрена
