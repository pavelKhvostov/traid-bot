# Nison — Japanese Candlestick Charting Techniques (1991)

Steve Nison, New York Institute of Finance. 330 pages.

Основная книга по japanese candlestick — оригинал techniques которые мы используем в SMC.

## Структура

Книга — каталог candlestick patterns + indicators. Также интегрирует Western analysis:
- Volume + open interest (chapter by John Murphy)
- Market Profile (Pete Gramza)
- Elliott Wave (John Gambino)
- Options и hedging (Jeff Korzenik, Sanfilippo, Ganes)
- Oscillators (Charles LeBeau)

## Sakata's Five Rules

Pre-1700s японские правила (San-zan / San-zenpyo):

| Правило | Что значит |
|---|---|
| San-zan (Three Mountains) | Triple top reversal |
| San-sen (Three Rivers) | Triple bottom reversal |
| San-kawa (Three Gaps) | After 3 gaps in one direction → exhaustion |
| San-pei (Three Soldiers) | Three white soldiers → bullish continuation |
| San-poh (Three Methods) | Rising/falling three methods (continuation patterns) |

## Single-candle patterns (применимо к `~/smc-lib/elements/`)

| Pattern | Описание | У нас |
|---|---|---|
| **Marubozu** | Свеча без фитиля со стороны open | ✓ `elements/marubozu` |
| **Doji** | Open ≈ close, длинные wicks | ✗ |
| **Spinning Top** | Small body, wicks обе стороны | ✗ |
| **Hammer / Hanging Man** | Длинный нижний wick, body вверху | ✗ — потенциальный RB extension |
| **Inverted Hammer / Shooting Star** | Длинный верхний wick, body внизу | ✗ |
| **Long Legged Doji** | Doji с очень длинными wicks (indecision) | ✗ |
| **Gravestone Doji** | Doji on high, no lower wick (bearish reversal) | ✗ |
| **Dragonfly Doji** | Doji on low, no upper wick (bullish reversal) | ✗ |

## Multi-candle patterns

### Reversal patterns

| Pattern | Свечи | Семантика | У нас |
|---|---|---|---|
| **Engulfing (Bullish/Bearish)** | 2 | Second body engulfs first | ✗ |
| **Harami (Bullish/Bearish)** | 2 | Second body INSIDE first (inside-bar) | ✗ |
| **Harami Cross** | 2 | Doji inside first body | ✗ |
| **Tweezer Top/Bottom** | 2 | Two bars same extreme | ✗ |
| **Morning Star / Evening Star** | 3 | Reversal sandwich (long body + small + opposite long) | ✗ |
| **Three Black Crows / White Soldiers** | 3 | Three same-direction bodies | ✗ |
| **Abandoned Baby** | 3 | Gapped doji (rare strong reversal) | ✗ |

### Continuation patterns

| Pattern | Свечи | Семантика |
|---|---|---|
| **Rising/Falling Three Methods** | 5 | Long body + 3 small opposite + long same |
| **Tasuki Gap** | 3 | Gap + reversal bar (continuation) |
| **Side-by-side White Lines** | 3 | Two similar long bodies separated by gap |
| **On-neck / In-neck / Thrusting Line** | 2 | Bear bar followed by partial recovery |

## Volume + Open Interest (Murphy chapter)

Western analysis комплементарно candlesticks:
- **Volume confirms trend** — rising prices + rising volume = healthy
- **Volume divergence** — rising prices + falling volume = weakness
- **OBV (On Balance Volume)** = cumulative volume direction
- **Volume Climax** — extreme volume → reversal coming (тот же концепт что Williams VSA climactic action)

## Market Profile (Gramza chapter)

Прицип:
- Каждая цена за day получает TPO (time-price opportunity) count
- **POC** (Point of Control) — наиболее frequent price
- **VAH/VAL** (Value Area High/Low) — 70% TPOs
- "Initial Balance" — first hour high/low
- **Auction failure** — return to value area после excursion

Релевантно нам: концепция "value area" аналогична OB drop/rally area.

## Применение к `~/smc-lib/`

### Pattern detectors которые НЕ ЕСТЬ в нашем `elements/`

Кандидаты для новых primitives:

1. **`doji`** — `abs(open - close) < range × 0.1`
2. **`hammer`** — body in upper 33%, lower wick > 2× body, no upper wick
3. **`shooting_star`** — body in lower 33%, upper wick > 2× body, no lower wick
4. **`engulfing_bull`** — prev bear + cur bull + cur.body engulfs prev.body
5. **`engulfing_bear`** — prev bull + cur bear + engulfs
6. **`harami_bull`** — prev bear large + cur bull small inside body
7. **`morning_star`** — bear + doji/small + bull (3-candle reversal)
8. **`evening_star`** — bull + doji/small + bear

Многие из них дублируют **RB** (rejection block — наш long-wick single bar). Hammer ≈ bottom RB, shooting star ≈ top RB.

### Pattern detectors которые ЕСТЬ как часть других elements

| Nison | Наш аналог |
|---|---|
| Marubozu | `elements/marubozu` ✓ |
| Hammer | подобно `elements/rb` (bottom variant) |
| Shooting Star | подобно `elements/rb` (top variant) |
| Engulfing bull | можно derive from OB-pair pattern |
| Harami | inside bar — special case of consolidation |

### Volume integration (Murphy)

Все candlestick patterns Nison считает **более significant** когда подтверждены volume:
- Hammer + high volume = stronger reversal
- Engulfing + high volume = stronger signal

Это согласуется с Williams VSA principle. Можно сделать **comprehensive VSA + Candlestick scoring:**
- VSA bar classification (no_demand, stopping, etc.)
- Candlestick pattern (hammer, doji, etc.)
- Combined into one bar feature

## Главные действия

1. **Doji detector** — простой; добавить в `elements/doji/` или `candle_patterns/`
2. **Hammer/Shooting Star** — расширить `elements/rb` или новые
3. **Engulfing pair** — можно derive из OB, но явный detector полезен
4. **Morning/Evening Star** — 3-bar reversal, потенциально мощный signal
5. **Market Profile** ideas — POC/VAH/VAL может быть extension к force-model v4

## Связи

- `~/smc-lib/elements/marubozu` — основа из Nison
- `~/smc-lib/elements/rb` — hammer / shooting star родственники
- `[[force-model-v3-architecture]]` — candlestick patterns как feature
- Williams VSA + Nison patterns — комплементарно (volume + form)
