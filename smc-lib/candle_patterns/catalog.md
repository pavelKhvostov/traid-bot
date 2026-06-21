# Каталог свечных паттернов (Japanese Candlesticks)

> **Источники.** Стив Нисон «Японские свечи. Графический анализ финансовых рынков» (1991); Thomas Bulkowski «Encyclopedia of Candlestick Charts»; классические TA-источники.

Структурирован по числу свечей и типу (reversal / continuation / indecision). Каждый паттерн помечен:
- 🟢 bullish / 🔴 bearish / ⚪ neutral
- **R** — reversal | **C** — continuation | **I** — indecision

---

## 1️⃣ Single-candle patterns

### Indecision / нейтральные
| Паттерн | Тип | Описание |
|---|---|---|
| **Doji** (длинноногий) | ⚪ I | open ≈ close, длинные тени с обеих сторон — равновесие |
| **Gravestone Doji** | ⚪ I (bearish bias) | open=close=low, длинная верхняя тень — отвержение вверху |
| **Dragonfly Doji** | ⚪ I (bullish bias) | open=close=high, длинная нижняя тень — отвержение внизу |
| **Four Price Doji** | ⚪ I | OHLC все равны — крайнее равновесие (низкая liquidity) |
| **Spinning Top** | ⚪ I | малое тело, обе тени длиннее тела — слабая нерешительность |
| **High Wave Candle** | ⚪ I | очень длинные тени с обеих сторон, малое тело — высокая волатильность |

### Reversal-сигналы
| Паттерн | Тип | Описание |
|---|---|---|
| **Hammer** (молот) | 🟢 R | малое тело сверху, длинная нижняя тень ≥ 2× body, появляется в downtrend |
| **Hanging Man** (повешенный) | 🔴 R | геометрия hammer, но в uptrend |
| **Inverted Hammer** (перевернутый молот) | 🟢 R | малое тело снизу, длинная верхняя тень ≥ 2× body, в downtrend |
| **Shooting Star** (падающая звезда) | 🔴 R | геометрия inverted hammer, в uptrend |
| **Takuri Line** | 🟢 R | усиленный hammer — нижняя тень ≥ 3× body |
| **Belt Hold (Bullish)** = Yorikiri | 🟢 R | bull marubozu в downtrend: open=low, без нижней тени |
| **Belt Hold (Bearish)** | 🔴 R | bear marubozu в uptrend: open=high, без верхней тени |

### Trend confirmation
| Паттерн | Тип | Описание |
|---|---|---|
| **White Marubozu** | 🟢 C | open=low, close=high (нет теней) — сильный буллиш |
| **Black Marubozu** | 🔴 C | open=high, close=low (нет теней) — сильный медвежий |
| **Opening Marubozu (Bullish)** | 🟢 C | open=low, есть верхняя тень |
| **Closing Marubozu (Bullish)** | 🟢 C | close=high, есть нижняя тень |
| **Long White Candle** | 🟢 C | большое белое тело, малые тени |
| **Long Black Candle** | 🔴 C | большое чёрное тело, малые тени |

> ℹ️ Marubozu в `smc-lib` живёт в [`elements/marubozu/`](../elements/marubozu/) (имеет zone = тело).
> Rejection Block (RB) в [`elements/rb/`](../elements/rb/) — близкий родственник pin bar / hammer-style свечи с зоной.

---

## 2️⃣ Two-candle patterns

### Reversal
| Паттерн | Тип | Описание |
|---|---|---|
| **Bullish Engulfing** (поглощение) | 🟢 R | bear c1, bull c2; body c2 целиком покрывает body c1 |
| **Bearish Engulfing** | 🔴 R | bull c1, bear c2; body c2 покрывает body c1 |
| **Bullish Harami** (внутри) | 🟢 R | bear c1, bull c2; body c2 целиком внутри body c1 |
| **Bearish Harami** | 🔴 R | bull c1, bear c2; body c2 внутри body c1 |
| **Harami Cross** | ⚪/🟢/🔴 R | c2 = doji внутри body c1 — усиленный сигнал |
| **Piercing Pattern** (просвет в облаках) | 🟢 R | bear c1, bull c2; close c2 в верхней половине body c1 (но не покрывает) |
| **Dark-Cloud Cover** (завеса из тёмных облаков) | 🔴 R | bull c1, bear c2; c2 open > c1 high (гэп), close c2 в нижней половине body c1 |
| **Tweezer Top** (пинцет сверху) | 🔴 R | два соседних bar'а имеют идентичный high |
| **Tweezer Bottom** | 🟢 R | два bar'а имеют идентичный low |
| **Bullish Kicker (Kicking)** | 🟢 R | bear c1 → bull marubozu c2 с гэпом вверх |
| **Bearish Kicker** | 🔴 R | bull c1 → bear marubozu c2 с гэпом вниз |
| **Matching Low** | 🟢 R | два bear c подряд, close обоих равны |
| **Matching High** | 🔴 R | два bull c подряд, close равны |
| **Meeting Lines (Bullish)** | 🟢 R | bear c1, bull c2; close c2 ≈ close c1 |
| **Meeting Lines (Bearish)** | 🔴 R | bull c1, bear c2; close c2 ≈ close c1 |

### Continuation
| Паттерн | Тип | Описание |
|---|---|---|
| **On-Neck Line** (на горловине) | 🔴 C | в downtrend: bear c1, bull c2; close c2 ≈ low c1 |
| **In-Neck Line** (под горловиной) | 🔴 C | bear c1, bull c2; close c2 чуть выше close c1 |
| **Thrusting Pattern** (вонзающая) | 🔴 C / weak R | bear c1, bull c2; close c2 в нижней половине body c1 (но > центра) |
| **Separating Lines (Bullish)** | 🟢 C | bear c1, bull c2 с тем же open — продолжение восходящего тренда |
| **Separating Lines (Bearish)** | 🔴 C | bull c1, bear c2 с тем же open |

### Bar structures
| Паттерн | Тип | Описание |
|---|---|---|
| **Inside Bar** | ⚪ I | range c2 целиком внутри range c1 (high+low) |
| **Outside Bar** | ⚪ I | range c2 покрывает range c1 (≈ Engulfing по range, не по body) |
| **NR4 / NR7** | ⚪ I | narrowest range за последние 4/7 bars — compression перед движением |

---

## 3️⃣ Three-candle patterns

### Major reversals
| Паттерн | Тип | Описание |
|---|---|---|
| **Morning Star** (утренняя звезда) | 🟢 R | bear c1 (long), малое тело c2 (любой цвет, gap вниз), bull c3 (long, close в верхней половине body c1) |
| **Evening Star** (вечерняя звезда) | 🔴 R | bull c1, малое c2 (gap вверх), bear c3 (close в нижней половине body c1) |
| **Morning Doji Star** | 🟢 R | как morning star, но c2 = doji (сильнее) |
| **Evening Doji Star** | 🔴 R | как evening star, но c2 = doji (сильнее) |
| **Abandoned Baby (Bullish)** | 🟢 R | morning doji star с **гэпами с обеих сторон** c2 (doji полностью isolated) — очень редкий, сильный |
| **Abandoned Baby (Bearish)** | 🔴 R | mirror — evening doji star с гэпами |
| **Three White Soldiers** (три белых солдата) | 🟢 R | три long bull подряд, каждый открывается внутри body предыдущего, закрывается выше |
| **Three Black Crows** (три чёрных вороны) | 🔴 R | три long bear подряд, каждый открывается внутри body предыдущего, закрывается ниже |
| **Three Inside Up** | 🟢 R | bullish harami + 3-я bull свеча с close > c1 close |
| **Three Inside Down** | 🔴 R | bearish harami + 3-я bear с close < c1 close |
| **Three Outside Up** | 🟢 R | bullish engulfing + 3-я bull с close > c2 close |
| **Three Outside Down** | 🔴 R | bearish engulfing + 3-я bear с close < c2 close |
| **Unique Three River Bottom** | 🟢 R | редкий: bear c1, bear c2 (молот-подобный с new low), малая bull c3 |
| **Three Stars in the South** | 🟢 R | три bear подряд с уменьшающимися low и body |
| **Stick Sandwich** | 🟢 R | bear c1, bull c2, bear c3 с close c3 = close c1 |
| **Identical Three Crows** | 🔴 R | three black crows где c2/c3 открываются на close предыдущего (без gap) |
| **Advance Block** | 🔴 R | three white soldiers, но c2/c3 с уменьшающимся body и длинными верхними тенями (ослабление) |
| **Deliberation Block** | 🔴 R | two white candles + 3-я star (малая) — потеря momentum |

### Continuation
| Паттерн | Тип | Описание |
|---|---|---|
| **Side-by-Side White Lines (Bullish)** | 🟢 C | в uptrend: gap up + два white candles с одинаковым open |
| **Side-by-Side White Lines (Bearish)** | 🔴 C | в downtrend: gap down + два white candles |
| **Upside Gap Tasuki** | 🟢 C | в uptrend: gap up bull c2, bear c3 заполняющий gap |
| **Downside Gap Tasuki** | 🔴 C | в downtrend: gap down bear c2, bull c3 заполняющий gap |
| **Three Line Strike (Bullish)** | 🟢 C / R | three white soldiers + 4-я bear, полностью покрывающая все три |
| **Three Line Strike (Bearish)** | 🔴 C / R | three black crows + 4-я bull, полностью покрывающая |

---

## 4️⃣ Multi-candle (4+) patterns

### Continuation
| Паттерн | Тип | Описание |
|---|---|---|
| **Rising Three Methods** | 🟢 C | bull c1 (long) + 3 малых bear подряд внутри range c1 + bull c5 (close > c1 close) |
| **Falling Three Methods** | 🔴 C | bear c1 + 3 малых bull внутри range c1 + bear c5 (close < c1 close) |
| **Mat Hold (Bullish)** | 🟢 C | bull c1 + gap up + 3 bear within body c1 + bull c5 breakout |
| **Concealing Baby Swallow** | 🟢 R | редкий 4-bar: bear, bear, bear, bull — четвёртая bull полностью поглощает третью |
| **Ladder Bottom** | 🟢 R | редкий 5-bar: три bear, малая bull, длинная bull |
| **Breakaway (Bullish)** | 🟢 R | 5-bar: bear c1, gap down bear c2, два малых bear, bull c5 → reversal к началу |
| **Breakaway (Bearish)** | 🔴 R | mirror |

### Streaks
| Паттерн | Тип | Описание |
|---|---|---|
| **Eight New Price Lines** | 🟢/🔴 weak R | 8+ свечей с последовательно новыми high/low — exhaustion |
| **Ten New Price Lines** | 🟢/🔴 R | усиленная версия |

---

## Сводка по группам

| Группа | Reversal | Continuation | Indecision | Всего |
|---|---:|---:|---:|---:|
| Single | 9 | 5 | 6 | 20 |
| Two-bar | 14 | 5 | 3 | 22 |
| Three-bar | 18 | 6 | 0 | 24 |
| Multi (4+) | 5 | 4 | 0 | 9 |
| **Итого** | **46** | **20** | **9** | **~75** |

---

## Что уже есть в `smc-lib` (близкие родственники)

| Свечной паттерн | Где в библиотеке | Семантика в smc-lib |
|---|---|---|
| White/Black Marubozu | `elements/marubozu/` | Тело = imbalance zone (магнит), open = sweep level |
| Hammer / Shooting Star / pin bar | `elements/rb/` | Rejection Block — фитиль = liquidity zone |
| Bullish/Bearish Engulfing (по body) | (нет — кандидат) | Можно добавить отдельно |
| 3 same-direction continuation | `patterns/run_3candles_sweep/` | Setup с entry/SL/TP |
| i-RDRB + FVG (5-bar) | `patterns/i_rdrb_fvg/` | Композитный setup |

---

## Кандидаты на ближайшее включение в `candle_patterns/`

Топ по utility (по мнению автора Нисона + опытных трейдеров):

| Приоритет | Паттерн | Why |
|---|---|---|
| ⭐⭐⭐ | **Bullish/Bearish Engulfing** | Один из самых надёжных 2-bar reversal сигналов |
| ⭐⭐⭐ | **Morning/Evening Star** | Классический 3-bar reversal, особенно с doji middle |
| ⭐⭐⭐ | **Inside Bar** | Compression паттерн — отлично для breakout setups |
| ⭐⭐ | **Three White Soldiers / Black Crows** | Сильное trend-initiation подтверждение |
| ⭐⭐ | **Doji (gravestone/dragonfly)** | Простые reversal-маркеры |
| ⭐⭐ | **Harami (+ Cross)** | Contraction-сигнал перед reversal |
| ⭐⭐ | **Piercing / Dark-Cloud Cover** | 2-bar reversal с гэпом |
| ⭐ | **Tweezer Top/Bottom** | Простой, но многочисленные false signals |
| ⭐ | **Rising/Falling Three Methods** | Continuation паттерн в trend |

---

## Применение в проекте

Свечные паттерны используются как:
- **Confluence trigger** внутри HTF-зоны (engulfing в OB-зоне → strong entry)
- **Reversal signal** на VWAP/HMA уровне (hammer на эффективном VWAP support)
- **OR-basket condition** в проектах прогнозирования (см. [[../projects/pred12h-fractal-three-candles.md|Pred-12h]])
- **Filter** для других setup'ов (например inside bar за HTF свечой = compression перед breakout)

**Не используются standalone** — всегда требуется multi-TF контекст ([[../expert/opinion.md]]).

---

## Источники

1. **Стив Нисон** — «Японские свечи. Графический анализ финансовых рынков» (1991, 2001) — каноническая работа
2. **Thomas Bulkowski** — «Encyclopedia of Candlestick Charts» (2008) — статистика для 100+ паттернов на S&P
3. **Greg Morris** — «Candlestick Charting Explained» — classification framework
4. **CandleScanner** / **TC2000** — современные таксономии

> Эта таксономия — стартовая. По мере реализации детекторов в `candle_patterns/<name>/code.py` каталог будет уточняться (особенно граничные условия, body/range фильтры, gap definitions).
