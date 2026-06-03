# Bulkowski — Encyclopedia of Chart Patterns (3rd ed, 2021)

Thomas Bulkowski, Wiley. ~1000+ pages в full edition. **У нас только 30-страничный preview.**

## Что это

Самый цитируемый каталог chart patterns с **статистикой** для каждого:
- Filter rules (что qualifies)
- Breakout success rate
- Failure rate / throwback rate
- Average performance (move size)
- Performance rank (1-50)

## Преимущество над Nison

Nison — описательный (что pattern значит). Bulkowski — **empirical** (что pattern даёт на data over decades).

Для каждого pattern:
- ~10,000+ instances анализированы
- Statistics на bull market vs bear market separately
- Volume confirmation impact
- Throwback / pullback rates
- Stop-loss optimal placement

## Категории patterns

Полная книга содержит ~100+ pattern types:
- **Chart patterns** (визуальные): head-and-shoulders, double tops, triangles, rectangles, wedges, flags, etc.
- **Candlestick patterns** (Nison subset)
- **Event patterns** (earnings, splits)
- **Bullish/bearish:** parallel sections

## Preview content (30 pages)

Из 30 доступных страниц видны:
- Cover, copyright, dedication
- Introduction теаsing
- Sample chapter (вероятно)

## Применение к `~/smc-lib/`

Без full edition — невозможно use statistics. Однако концептуально:

### Полезные паттерны (если добавлять detectors)

| Pattern | Что значит | SMC параллель |
|---|---|---|
| **Head and Shoulders** | 3 peaks, middle highest | Triple-top distribution |
| **Inverse H&S** | Mirror, bullish | Triple-bottom accumulation |
| **Double Top/Bottom** | 2 peaks/troughs same level | Liquidity sweep (EQH/EQL) |
| **Triangle (Asc/Desc/Sym)** | Converging lines | Compression before move |
| **Rectangle (Range)** | Horizontal consolidation | Accumulation / distribution |
| **Wedge (Rising/Falling)** | Sloping convergence | Trend exhaustion |
| **Flag / Pennant** | Counter-trend consolidation | Continuation pattern |
| **Cup with Handle** | U-shape + small pullback | Bullish continuation |

### Statistics applications (если найдём full edition)

Например для **Head and Shoulders** Bulkowski обычно даёт:
- Bull market success rate ~75%
- Average move post-breakout ~22%
- Throwback rate ~50%

Эти числа можно использовать как **baseline** для наших ML models — если force-model даёт 60% и Bulkowski H&S 75%, простой rule-based лучше.

## Action items

1. **Get full edition** Encyclopedia of Chart Patterns (3rd ed) если потребуется pattern statistics
2. Тем временем — preview достаточно как reference что book exists
3. Использовать **обычные chart patterns** (H&S, triangles, rectangles) как complementary detectors к SMC zones

## Связи

- `[[force-model-v3-architecture]]` — добавить chart pattern features
- Nison candlestick patterns — Bulkowski покрывает subset, но glaubliche statistics
- VSA / Williams — Bulkowski на patterns, Williams на bars
