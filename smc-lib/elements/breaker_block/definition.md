# Breaker Block

**Самостоятельный элемент со своей зоной интереса** (canon 2026-06-14). Breaker = **проткнутый фитиль prev** OB-candle. Активируется через close-confirmation в окне ограниченной длины. После активации zone armed как **flip-zone** с противоположным bias и трекается через wick-fill mitigation.

> ⚠ **Canon v4 (2026-06-15) — FINAL.** Старые версии (v2 immediate-activation, v3 BOS+return) **deprecated**. Текущая семантика — close-window activation + wick-fill mitigation с момента после activator. Подтверждена реальной диагностикой на BTC 12h (46 active в pin 2026-06-15, 4 в ±$15K).

## Геометрия зоны интереса

| Тип | Зона | Семантика | Действие |
|---|---|---|---|
| **Bullish Breaker** (LONG OB pair, flip) | `[prev.open, prev.high]` | верхний фитиль bear-prev | SHORT-вход на возврате цены в зону **сверху-вниз** |
| **Bearish Breaker** (SHORT OB pair, flip) | `[prev.low, prev.open]` | нижний фитиль bull-prev | LONG-вход на возврате цены в зону **снизу-вверх** |

## Канон v4 (2026-06-15)

### Шаг 1. OB-pair формирование

OB детектируется канонически (см. `elements/ob/definition.md`):
- **LONG OB**: prev bear, cur bull, `cur.close > prev.open` → potential **Bullish Breaker**
- **SHORT OB**: prev bull, cur bear, `cur.close < prev.open` → potential **Bearish Breaker**

### Шаг 2. Активация через close-confirmation в окне bar 3-6

После OB-pair (bars 1-2) сканируется окно из 4 свечей — **bar 3, 4, 5, 6** (post_bars[0..3]):

| Тип OB | Условие активации в окне | Что происходит |
|---|---|---|
| LONG | первый бар k где `bar_k.close > prev.high` | Bullish Breaker ARMED → SHORT resist |
| SHORT | первый бар k где `bar_k.close < prev.low` | Bearish Breaker ARMED → LONG support |

**Если в окне 4 свечей activator не нашёлся — breaker НЕ формируется** (return None).

### Шаг 3. Wick-fill mitigation от свечи ПОСЛЕ activator

После активации breaker zone armed. Wick-fill mitigation (Правило 2 Модель 1) применяется **с следующей свечи** после activator:

**Bullish Breaker** (SHORT resist) — тестируется `bar.low` (price returns from above):
```
bar.low > zone_hi           → no interaction
bar.low ∈ (zone_lo, zone_hi]  → partial shrink: zone_hi := bar.low
bar.low ≤ zone_lo            → CONSUMED (zone wiped out)
```

**Bearish Breaker** (LONG support) — тестируется `bar.high` (price returns from below):
```
bar.high < zone_lo           → no interaction
bar.high ∈ [zone_lo, zone_hi)  → partial shrink: zone_lo := bar.high
bar.high ≥ zone_hi            → CONSUMED
```

Note semantic: при activation цена уже **за зоной** (выше для Bullish, ниже для Bearish). Возврат в зону — это ретест с противоположной стороны от исходного OB. Поэтому wick-fill semantically обратен OB-mitigation (zone тестируется wick'ом со стороны returner'a).

## Параметры детекции

| Параметр | Значение | Описание |
|---|---|---|
| `ACTIVATION_WINDOW_BARS` | 4 | окно поиска activator = bar 3-6 от prev = post_bars[0..3] |

Wick-fill tracking — без лимита по count или времени; продолжается до CONSUMED или конца серии.

## Эталонный test cases

### Активация + CONSUMED через 2 свечи (диагностический пример 2026-06-15)

```
bar 1 (prev): O=110 H=120 L=99  C=100   bear
bar 2 (cur):  O=100 H=112 L=99  C=111   bull → LONG OB ✓ (close > prev.open)
bar 3:        O=111 H=113 L=109 C=110   close 110 < 120, no activation
bar 4:        O=110 H=115 L=108 C=113   close 113 < 120, no activation
bar 5:        O=113 H=122 L=112 C=121   close 121 > 120 ✓ ★ ARMED
                                        Bullish Breaker zone [110, 120]
bar 6:        O=121 H=125 L=117 C=118   bar.low=117 ∈ (110, 120)
                                        → shrink to [110, 117]
bar 7:        O=118 H=119 L=110 C=112   bar.low=110 ≤ zone_lo=110
                                        → CONSUMED
```

### Bullish без активации в окне → не формируется

```
bar 3-6 все close ≤ 120 → activation не сработала → return None
```

## Связанные элементы

- **`ob`** — каноничный 2-свечный OB; breaker = «второе дыхание» после close-cross в окне 4 свечей
- **`mitigation_block`** — родственный, но другой механизм: полный пробой OB + Rule 1 закрепление 4 свечи; ZoI = полная drop/rally area, mitigation = wick-fill first-touch
- **`i_rdrb`** — путают с breaker, но i-RDRB требует explicit body close beyond block boundary на C4 свече, а breaker — passive close-cross в окне без специфической формы свечи

## Изменения канона

- **2026-06-14**: вынесен из OB ZoI в самостоятельный элемент, zone = проткнутый фитиль prev (был — drop/rally area)
- **2026-06-15 v2**: immediate activation + wick-fill — DEPRECATED
- **2026-06-15 v3**: BOS+return механизм с invalidation от wick-fill — DEPRECATED
- **2026-06-15 v4**: close-window activation (bar 3-6) + post-activator wick-fill — **CURRENT CANON**

Канон pavel-notes: `~/smc-lib/literature/pavel-notes/ict-source/SMC-обзор-OB-breaker-BOS-choch-vs-price-action.md`.
