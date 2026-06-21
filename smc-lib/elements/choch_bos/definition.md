# CHoCH / BOS — Market Structure (Fractal)

**Два самостоятельных элемента** маркетной структуры. Реализация одного канона (LuxAlgo Pine v5 «Market Structure CHoCH/BOS (Fractal)», CC BY-NC-SA), но в вычислениях и экспериментах CHoCH и BOS — **разные элементы**.

| Элемент | Семантика |
|---|---|
| **CHoCH** (Change of Character) | Слом текущего направления структуры — закрытие против последнего структурного пробоя. Кандидат на разворот. |
| **BOS** (Break of Structure) | Продолжение текущего направления — закрытие в ту же сторону, что и последний структурный пробой. Подтверждение тренда. |

Канон-источник: LuxAlgo, Pine v5, `length=5` default.

## Каноническая логика (LuxAlgo)

### 1. Фрактал (Williams strict, length=5, N=2)

`p = int(length/2)` (default 2).

```
dh = sum(sign(high - high[1]), p)
dl = sum(sign(low  - low[1]),  p)

bullf = dh == -p and dh[p] ==  p and high[p] == ta.highest(length)
bearf = dl ==  p and dl[p] == -p and  low[p] == ta.lowest(length)
```

Эквивалент Williams BW 5-bar с N=2:
- **bullf (FH)** — на баре `n-p`: high строго выше `p` баров до и `p` баров после; high = max окна `length`.
- **bearf (FL)** — зеркально для low.

Фрактал подтверждается через `p` баров после центральной свечи.

### 2. State machine ориентации

`os ∈ {0, +1, -1}` — сторона последнего структурного пробоя.

- `os = 0` — initial (структурный пробой ещё не произошёл).
- `os = +1` — последний пробой был bullish (close cross верхнего фрактала).
- `os = -1` — последний пробой был bearish (close cross нижнего фрактала).

### 3. Классификация события на закрытии бара

Когда фиксируется bullish или bearish break:

| Сторона break'а | Условие триггера | `os_prev` | Тип события | `os_new` |
|---|---|---|---|---|
| **Bullish** | `ta.crossover(close, upper.value)` AND `not upper.iscrossed` | `+1` или `0` | **BOS** (continuation) | `+1` |
| **Bullish** | то же | `-1` | **CHoCH** (reversal) | `+1` |
| **Bearish** | `ta.crossunder(close, lower.value)` AND `not lower.iscrossed` | `-1` или `0` | **BOS** (continuation) | `-1` |
| **Bearish** | то же | `+1` | **CHoCH** (reversal) | `-1` |

После события: `upper.iscrossed := true` (или `lower.iscrossed := true`), `os := новый`.

### 4. Триггер — **ОДНО** закрытие

Триггер LuxAlgo = `ta.crossover` / `ta.crossunder`, т.е. одно закрытие за уровнем фрактала. **Закрепления по Правилу 1 (1 пробойная + 3 подтверждающих) НЕ требуется.** Это можно добавить как параметр, но канон-default = одно закрытие.

### 5. Внутренние support / resistance (опционально)

После CHoCH/BOS LuxAlgo может рисовать новый opposing S/R:
- **После bullish break** — `min low` в окне `[upper.loc, current_bar - 1]` → новый support.
- **После bearish break** — `max high` в окне `[lower.loc, current_bar - 1]` → новый resistance.

Пробой этой линии (`close < support` / `close > resistance`) → маркер «Resistance/Support Breakout».

## Параметры детекции (наши)

| Параметр | Default | Описание |
|---|---|---|
| `length` | 5 | окно Williams-фрактала (LuxAlgo canon) |
| `min_break_depth_pct` | 0.0 | минимум глубины закрытия за уровнем (% от уровня); 0 = любой close beyond |
| `use_rule_1_confirmation` | False | расширение: требовать пробойную + 3 подтверждающие (Правило 1) |

## Зона интереса

**Ни CHoCH, ни BOS сами не зоны.** Это **триггеры** — точечный уровень фрактала + бар закрытия.

| Элемент | Триггер-уровень | Бар события | Что искать после |
|---|---|---|---|
| **Bullish CHoCH** | `upper.value` (FH) | `i_break` | LONG entry в discount-half move'а после reversal |
| **Bullish BOS** | `upper.value` (FH) | `i_break` | LONG continuation, pullback в FVG/OB/Mitigation |
| **Bearish CHoCH** | `lower.value` (FL) | `i_break` | SHORT entry в premium-half |
| **Bearish BOS** | `lower.value` (FL) | `i_break` | SHORT continuation, retracement в FVG/OB/Mitigation |

## Связанные элементы

- **`fractal`** — обязательный для определения upper/lower уровней (наш Williams N=2 совпадает с LuxAlgo при `length=5`).
- **`ob`**, **`fvg`**, **`mitigation_block`**, **`breaker_block`** — entry-зоны после CHoCH/BOS.

## Семантика в downstream

> ⚠ **CHoCH и BOS — два разных элемента** в `ALL_TYPES` и любых ML/strategy-вычислениях. Объединённый код в `choch_bos/` существует только из-за общей state machine `os` (без неё их нельзя различить корректно). На выходе event имеет `type ∈ {"CHoCH", "BOS"}`, и downstream обрабатывает их раздельно.

## Источник

- **LuxAlgo Pine v5** «Market Structure CHoCH/BOS (Fractal)» (CC BY-NC-SA 4.0).
  - Полный source: [`refs/luxalgo_market_structure_fractal.pine`](refs/luxalgo_market_structure_fractal.pine) (извлечённый), [`refs/luxalgo_market_structure_fractal.rtf`](refs/luxalgo_market_structure_fractal.rtf) (оригинал с TradingView).
- pavel-notes: `~/smc-lib/literature/pavel-notes/ict-source/SMC-обзор-OB-breaker-BOS-choch-vs-price-action.md`, `ICT-2022-mentorship-пошаговый-entry-алгоритм-DOL-MSS-displacement.md`.
