# Свечные паттерны (candle_patterns)

> **Назначение.** Atomic candle-formation детекторы (1-N свечей) — классические японские свечные паттерны и их вариации. Только **сигнал** (boolean detection), без entry/SL/TP setup'а.

---

## Различие с другими разделами

| Раздел | Что это | Возвращает | Пример |
|---|---|---|---|
| `elements/` | SMC primitives с зоной интереса | объект с `zone=(lo, hi)` + mitigation | OB, FVG, RDRB, ob_liq |
| **`candle_patterns/`** | **Свечные паттерны** — классика TA | объект с `direction`, `bars` (бары паттерна) | hammer, engulfing, doji, morning_star |
| `patterns/` | Полные торговые setup'ы | объект с `entry`, `sl`, `tp` | run_3candles_sweep |
| `vc/` | Predicate (boolean) над HTF-зоной | `bool` | has_vc(ob, fvg) |
| `indicators/` | Numeric features | `list[float]` или `dict` | HMA, ATR, VWAP |

**Ключевая семантика**:
- **Элемент** = «зона интереса», к которой можно вернуться (есть price-range, mitigation)
- **Свечной паттерн** = «формация на N свечах», сигнал в моменте (нет встроенной зоны)
- **Pattern** = свечной паттерн + готовый торговый setup

Примеры границы:
- `marubozu` — в `elements/`, потому что body = зона интереса (untraded → магнит)
- `rb` (rejection block) — в `elements/`, потому что фитиль = зона
- `engulfing` — в `candle_patterns/`, чисто signal, нет встроенной зоны
- `hammer` — в `candle_patterns/`, signal (потенциальный reversal); если использовать как зона — это уже `rb`
- `run_3candles_sweep` — в `patterns/`, потому что есть Entry/SL/TP

---

## Структура папки одного паттерна

```
candle_patterns/<name>/
  definition.md       # формальное определение (условия, формулы, эталон)
  code.py             # detect_<name>(*candles) → <Name> | None
  tests/
    test_<name>.py
```

API детектора:
```python
@dataclass(frozen=True)
class <Name>:
    direction: Literal["long", "short"]
    bars: list[Candle]   # бары паттерна
    # доп-метрики (опционально): body_ratio, wick_ratio, displacement и т.п.

def detect_<name>(c1: Candle, c2: Candle, ...) -> <Name> | None:
    ...
```

---

## Кандидаты для раздела (TBD по мере добавления)

### Single-candle
- **doji** (open ≈ close, long wicks; варианты: gravestone, dragonfly, long-legged)
- **hammer** / **inverted hammer** (small body, long lower/upper wick)
- **shooting star** (small body, long upper wick at top)
- **spinning top** (small body, both wicks ~равны)
- **pin bar** (= hammer/shooting star обобщённо)

### Two-candle
- **engulfing** (bullish/bearish) — body c2 поглощает body c1
- **harami** (bullish/bearish) — body c2 внутри body c1
- **tweezer top / bottom** — два high/low подряд равны
- **piercing line** / **dark cloud cover** — close c2 пробивает середину c1
- **inside bar** — c2 целиком внутри range c1
- **outside bar** — c2 целиком охватывает range c1

### Three-candle
- **morning star** / **evening star** — c1 strong, c2 small/doji, c3 strong противоположный
- **three white soldiers** / **three black crows** — три сильные однонаправленные
- **three inside up/down** — engulfing-подобный 3-bar reversal
- **three outside up/down** — внешний reversal

### Multi-candle (>3)
- TBD

---

## Применение

| Где | Как |
|---|---|
| **Confluence-фильтр** | Pattern на entry-баре подтверждает direction (например engulfing внутри HTF OB) |
| **Reversal signal** | hammer / shooting star на ключевом уровне |
| **Trend continuation** | three soldiers / morning star после pullback |
| **OR-basket conditions** | свечной паттерн как одно из condition в проекте (Pred-12h C8?) |

Не используются как standalone strategy — только как trigger / confluence в комбинации с SMC-зонами и multi-TF контекстом ([[../expert/opinion.md|expert/opinion]]).

---

## Статус

🟡 **В разработке.** Раздел создан 2026-05-28. Паттерны добавляются по мере необходимости (например, при анализе reversal-сигналов на ключевых уровнях, или для условий в Pred-проектах).

---

## Связи

- [[../elements/marubozu/definition.md]] — marubozu (имеет zone, не candle_pattern)
- [[../elements/rb/definition.md]] — RB (имеет zone)
- [[../patterns/run_3candles_sweep/definition.md]] — 3-bar continuation с setup
- [[../candle.py]] — базовая модель Candle
