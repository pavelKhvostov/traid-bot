# ob_sweep_liq_4candles

Снятие ликвидности Williams-фрактала свечой Y, которая открывается «по другую сторону» от фрактала, своим фитилём пересекает уровень фрактала, и закрывается за close фрактал-бара.

> ⚠️ **Имя элемента** (с `_4candles`) — историческое. После рефакторинга 2026-05-27 канон **не привязан к строго 4-свечному окну**. Reference = Williams FH/FL анкер любой давности.

Эталон: BTC 6h SHORT, anchor = 2026-05-25 15:00 MSK (Williams FH at 77 906), sweep Y = 2026-05-26 15:00 MSK.

## Условия

### SHORT (anchor = Williams FH, обычно bull)

```
1. anchor — Williams 5-bar FH (валидация на стороне caller'a)
2. y.open  < anchor.high     ← открытие ниже FH (приход снизу)
3. y.high  > anchor.high     ← wick свечи Y делает sweep FH
4. y.close < anchor.open     ← close ниже зоны OB (= тела bull cur, anchor.open = bottom of body)
```

### LONG (anchor = Williams FL, обычно bear) — зеркально

```
1. anchor — Williams 5-bar FL
2. y.open  > anchor.low
3. y.low   < anchor.low      ← wick sweep FL снизу
4. y.close > anchor.open     ← close выше зоны OB (= тела bear cur, anchor.open = top of body)
```

**Уточнение 2026-05-27**: условие 4 укрепляется с «close < anchor.close» до «close < anchor.open» (= ниже всей зоны интереса OB-бара, не просто ниже close). Подтверждено на 2 кейсах разных TF.

## Зона интереса

| Направление | **liq_zone** (область снятой ликвидности) |
|---|---|
| **SHORT** | `[anchor.high, y.high]` |
| **LONG** | `[y.low, anchor.low]` |

## Семантика

Цена приходит с противоположной стороны от FH/FL, выносит уровень за фитиль (= triggers stop-orders за фракталом), но **закрывает свечу за close фрактал-бара** → false breakout / rejection / sweep.

Это **снятие ликвидности с подтверждением разворота** (close beyond, не просто wick).

## Между anchor и Y

**Нет ограничений по gap'у** — Y может быть любой следующей свечой (даже сразу после FH, или через много баров). Главное — geometric conditions выше.

## Эталон расчёта (BTC 6h SHORT, anchor = 2026-05-25 15:00 MSK)

```
anchor = Candle(open=77358, high=77906, low=77286, close=77564)   # 05-25 15:00 BULL
  — Williams 5-bar FH (high 77906 выше 2 соседей слева 77498, 77700; 2 справа 77658, 77345)

y      = Candle(open=77184, high=78080, low=75850, close=75935)   # 05-26 15:00 BEAR

Проверка:
  y.open  (77184) < anchor.high  (77906) ✓
  y.high  (78080) > anchor.high  (77906) ✓ sweep FH
  y.close (75935) < anchor.close (77564) ✓

liq_zone = [77906, 78080]
```

## Применение

| Контекст | Использование |
|---|---|
| Standalone signal | Sweep FH с rejection → SHORT entry candidate |
| OR-basket condition | Кандидат для 12h фрактал-prediction (особенно для missed imp) |
| Confluence | sweep + close-back = strong reversal signal; multi-TF FH/FL anchors дают confluence |

## API

```python
from elements.ob_sweep_liq_4candles.code import detect_ob_sweep_liq_4candles
result = detect_ob_sweep_liq_4candles(anchor_bar, y_bar, direction="short")
```

Caller сам валидирует что `anchor_bar` — Williams 5-bar FH/FL (можно через `elements.fractal.code.detect_fractal`).

### Пример полного pipeline

```python
from elements.fractal.code import detect_fractal
from elements.ob_sweep_liq_4candles.code import detect_ob_sweep_liq_4candles

# Найти все Williams FH на TF, потом для каждого искать Y с sweep
for i in range(2, len(bars) - 2):
    f = detect_fractal(bars[i-2:i+3], n=2)
    if f is None: continue
    anchor = bars[i]
    direction = "short" if f.direction == "high" else "long"
    for j in range(i+3, len(bars)):
        y = bars[j]
        r = detect_ob_sweep_liq_4candles(anchor, y, direction)
        if r is not None:
            print(f"Pattern at bar {j}, anchor {i}, direction={r.direction}")
```

## История

- **2026-05-27** — первоначальная версия с условием «cur.high > max(4 ahead highs)» (5-свечная подпись).
- **2026-05-27 (поздно)** — рефакторинг на семантику «sweep Williams FH/FL с close back». Аргументы упрощены до `(anchor, y, direction)`. Привязка к строго «4 ahead» убрана.
