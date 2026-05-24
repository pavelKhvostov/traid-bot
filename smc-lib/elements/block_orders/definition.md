# Блок ордеров

Композитный паттерн произвольной длины из 3+ свечей: **preceding** свеча, далее **initial run** N₁ ≥ 1 свечей одной направленности, далее **counter run** N₂ ≥ 1 свечей противоположной направленности. Counter завершается на ПЕРВОЙ свече с close-crossing `block.open`. Конфигурация `(N₁, N₂) = (1, 1)` запрещена — это canon-OB.

Формирует **HTF OB**-уровень — институциональный блок ордеров, в который цена возвращается за реакцией.

> **Не путать**:
> - с canon-OB / `ob_liq` (2-свечная пара prev/cur — фактически это (1,1) case, см. ниже);
> - с `rdrb.block` (под-зоной RDRB).

## Свечи и роли

| Роль | Количество | Направление |
|---|---|---|
| **preceding** | 1 | противоположное initial |
| **initial run** | N₁ ≥ 1 | одна направленность подряд |
| **counter run** | N₂ ≥ 1 | противоположное initial; STOP на first close-cross |

Минимум 3 свечи в слайсе (1 preceding + N₁ + N₂, где N₁ + N₂ ≥ 2 и (N₁, N₂) ≠ (1, 1)).

## Условия LONG block

1. **Preceding bull**: `preceding.is_bull` (close > open).
2. **Initial bear run**: N₁ ≥ 1 подряд медвежьих свечей сразу после preceding.
3. **Counter bull run**:
   - последовательные бычьи свечи сразу после initial;
   - завершается на ПЕРВОЙ свече, чьё `close > block.open` (first cross);
   - **если counter прервался** сменой направления / doji ДО first cross → блок не сформирован.
4. **(N₁, N₂) ≠ (1, 1)** — иначе это canon-OB.

## Условия SHORT block — зеркально

1. **Preceding bear**.
2. **Initial bull run** N₁ ≥ 1.
3. **Counter bear run** до first cross `close < block.open`.
4. **(N₁, N₂) ≠ (1, 1)**.

## Геометрия

```
block.open  = candles[0].open         # open первой initial-свечи (= initial #1)
block.close = candles[-1].close       # close ПОСЛЕДНЕЙ counter-свечи (= той, что first-crossed)
block.high  = max(c.high for c in candles)   # = pattern.high
block.low   = min(c.low  for c in candles)   # = pattern.low
```

Направление body блока (breaker-block sub-zone):
- LONG → bullish (close > open) — recovery вверх
- SHORT → bearish (close < open) — recovery вниз

## Зона интереса

Полная зона возврата — от экстремума отвергнутого движения до закрытия counter-run:

| Направление | **Зона интереса** | Состоит из |
|---|---|---|
| **LONG** | `[block.low, block.close]` | breaker block `[block.open, block.close]` сверху + drop area `[block.low, block.open]` снизу |
| **SHORT** | `[block.close, block.high]` | breaker block `[block.close, block.open]` снизу + rally area `[block.open, block.high]` сверху |

**Breaker block** = body синтетической свечи `[min(open, close), max(open, close)]` — **подзона** внутри зоны интереса (не сама зона). Это область, где бывшая сторона была «сломана» (broken side).

**Drop / rally area** = расширение зоны до экстремума паттерна (lowest low для LONG, highest high для SHORT) — отвергнутое движение, которое cancelled counter-run'ом.

## Допустимые (N₁, N₂)

| N₁ \ N₂ | 1 | 2 | 3 | 4+ |
|---|---|---|---|---|
| **1** | ❌ canon-OB | ✓ | ✓ | ✓ |
| **2** | ✓ | ✓ | ✓ | ✓ |
| **3** | ✓ | ✓ | ✓ | ✓ |
| **4+** | ✓ | ✓ | ✓ | ✓ |

## Эталонный пример — LONG block (BTC 1h, 2026-05-05 MSK)

| Свеча | Время MSK | O | H | L | C | Тип / роль |
|---|---|---|---|---|---|---|
| preceding | 2026-05-05 00:00 | 79936.70 | 80383.15 | 79936.70 | 80259.17 | bull |
| #1 (initial) | 01:00 | 80259.18 | 80397.19 | 80042.84 | 80067.23 | bear |
| #2 (initial) | 02:00 | 80067.22 | 80067.22 | 79744.91 | 79861.01 | bear |
| #3 (counter) | 03:00 | 79861.01 | 80183.33 | 79808.72 | 80170.66 | bull — close 80170.66 < 80259.18, no cross |
| #4 (counter, cross) | 04:00 | 80170.66 | 80385.06 | 80080.76 | **80352.00** | bull — close 80352.00 > 80259.18, **first cross → STOP** |

- preceding (bull) opposite к initial (bear) ✓
- N₁ = 2, N₂ = 2, (2, 2) ≠ (1, 1) ✓
- first cross @ counter #2 (80352 > 80259.18) ✓

**Геометрия**:
- `open = 80259.18`, `close = 80352.00`
- `high = 80397.19`, `low = 79744.91`
- **Зона интереса = [79744.91, 80352.00]** (h=607.09)
  - breaker block (подзона): [80259.18, 80352.00] (h=92.82) — сверху
  - drop area (подзона): [79744.91, 80259.18] (h=514.27) — снизу

## Связанные элементы

- `ob_liq` / canon-OB — 2-свечный (prev, cur) паттерн = (N₁, N₂) = (1, 1), отдельный primitive
- `rdrb` — 3-свечный паттерн со своей геометрией POI/block/liq (не путать)
