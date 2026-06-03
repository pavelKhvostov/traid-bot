# Williams — Master the Markets / Volume Spread Analysis (VSA)

Tom Williams, 1993 (original "The Undeclared Secrets That Drive the Stock Market"),
revised 2000, Spanish edition 2019 (Gavin Holmes new chapters).

333 pages. Volume Spread Analysis (VSA) — методология чтения "smart money footprints"
через анализ соотношения **price spread (range) + volume**.

## Структура (Spanish edition)

| Sección | Title | Что внутри |
|---|---|---|
| Preámbulo | VSA y TradeGuider | VSA = Volume Spread Analysis, software автоматизирующий анализ |
| Introducción | El negocio más grande del mundo | Stock market = manipulated by professionals |
| Sec 1 | Conceptos básicos del mercado | Supply, demand, professional vs amateur |
| Sec 2 | **Tendencias y análisis del rango del volumen** ⭐ | Core VSA принципы |
| Sec 3 | **Anatomía de los mercados alcistas y bajistas** ⭐ | Phases: accumulation, distribution, mark-up, mark-down |
| Sec 4 | Convertirse en un trader o en un inversor | Practical |
| Apéndice | Glosario | VSA термины |

---

## Основные принципы

### 1. Supply / Demand доминируют

- Price движется по closure of supply/demand imbalance
- **Smart money** (institutions) знает direction, **dumb money** (retail) против
- VSA = читать когда smart money active

### 2. Volume Spread Analysis paradigm

Каждый bar анализируется через 3 признака:
- **Spread (range)** = high - low: wide vs narrow
- **Volume:** high / normal / low
- **Close position** в range: top / middle / bottom

**Принцип:** mismatch между effort (volume) и result (price movement) указывает на manipulation:
- Big volume + small range = high effort, low result → reversal coming
- Small volume + big range = low effort, big result → easy continuation

### 3. Background для каждого бара

VSA не рассматривает bar в изоляции:
- Trend (up/down/sideways) before bar
- Previous bars structure
- Где находимся в Wyckoff phase (accumulation → mark-up → distribution → mark-down)

---

## Каталог VSA-паттернов (релевантно для SMC)

### No Demand Bar (NDB)
- **Условие:** Up-bar (close > open), low volume, narrow range
- **Семантика:** Цена идёт вверх, но professionals не покупают → bearish hint
- **Применение:** filter для long-входов после rally

### No Supply Bar (NSB)
- **Условие:** Down-bar (close < open), low volume, narrow range
- **Семантика:** Цена идёт вниз, professionals не продают → bullish hint

### Stopping Volume
- **Условие:** Down-bar with EXTREME volume, close in upper third of range
- **Семантика:** Smart money аккумулирует на падении ("absorbing supply")
- **Применение:** raw entry signal для long

### Climactic Action (Selling Climax / Buying Climax)
- **Условие:** Wide range bar с extreme volume, close opposite to bar direction
- **Selling climax:** wide DOWN bar + extreme volume + close near HIGH → bottom signal
- **Buying climax:** wide UP bar + extreme volume + close near LOW → top signal
- **Применение:** reversal pivot signal

### Test Bar
- **Условие:** Down-bar low volume после bullish action
- **Семантика:** smart money тестирует supply, мало продавцов = bullish
- **Применение:** confirm bullish bias

### Effort vs Result
- **Mismatch:** big volume + small range = high effort, low result → reversal
- **Match:** small volume + big range = continuation legit

### Up-thrust
- **Условие:** Up-bar, wide range, close in lower third, high volume
- **Семантика:** Цена прокола вверх (sweep), но close внизу → distribution
- **Применение:** **SMC параллель — это наш fractal sweep с close в opposite end!**

### Spring (= наш SMC sweep)
- **Условие:** Down-bar wicks below support, closes back above
- **Семантика:** liquidity grab below support, reversal up

---

## Wyckoff Phases (применимо к force-model)

```
Accumulation → Mark-up → Distribution → Mark-down → Re-accumulation
   (boring        (trend          (boring          (trend
   sideways      up move)         sideways         down move)
   bottom)                        top)
```

В каждой фазе разные VSA-сигналы valid:
- **Accumulation:** tests, no supply bars, stopping volumes
- **Mark-up:** strength bars, no demand на retracements signals end
- **Distribution:** up-thrusts, weakness on rallies
- **Mark-down:** down-bars wide range, climax marks bottom

---

## Применение к `~/smc-lib/`

### Новые primitives для `elements/` или `candle_patterns/`

1. **`no_demand_bar`**: up-bar + volume < N-day low + range < ATR(14) × 0.7
2. **`no_supply_bar`**: down-bar + volume < N-day low + range < ATR(14) × 0.7
3. **`stopping_volume`**: down-bar + volume > N-day high (top 5%) + close > (lo + 0.66*range)
4. **`upthrust`**: up-bar + range > ATR(14) × 1.5 + close < (lo + 0.33*range) + volume > N-day median
5. **`selling_climax`**: down-bar + range > ATR(14) × 1.5 + close > (lo + 0.66*range) + volume > N-day high

### Расширение `vc/` (Volume Confirmation)

Текущий VC = простой volume threshold. VSA даёт **rich semantic taxonomy:**
- VC может быть not single condition но **dispatch table** по VSA-pattern:
  - if no_demand_bar в зоне → VC = "weak demand" (bearish bias even at bullish zone)
  - if stopping_volume в зоне → VC = "absorption" (strong bullish bias)
  - if upthrust в зоне → VC = "distribution" (bearish bias even at bullish zone)

### Features для force-model

1. `vsa_bar_type` (categorical: normal / no_demand / no_supply / stopping / upthrust / climax)
2. `effort_result_ratio` = volume / range_atr — high когда mismatch
3. `volume_pct_of_avg` = current vol / 20-day avg
4. `close_position_in_range` = (close - lo) / (hi - lo) ∈ [0, 1]
5. `wyckoff_phase` (categorical) — accumulation / mark-up / distribution / mark-down

---

## Главные действия

1. Implement VSA detectors в `~/smc-lib/elements/vsa_*.py` (no_demand, no_supply, stopping_volume, upthrust)
2. Add VSA features в force-model v4 dataset
3. Cross-reference VSA upthrust + наш fractal sweep — это **один и тот же паттерн**
4. Wyckoff phase classifier — отдельный задача, может быть HMM или rule-based

## Связи

- `~/smc-lib/vc/` — наш VC, расширить через VSA-taxonomy
- `[[force-model-v3-architecture]]` — добавить vsa_bar_type как feature
- `[[zone-class-liquidity-inefficiency-block]]` — VSA дополняет: какие типы liquidity-events
- Wyckoff Spring = SMC liquidity sweep below support — те же концепции, разная терминология
