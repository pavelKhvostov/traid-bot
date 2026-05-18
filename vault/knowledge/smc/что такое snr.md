---
tags: [smc, ict, snr, support-resistance, primitive]
date: 2026-05-18
related: [[что такое order block]], [[что такое rdrb]], [[что такое fvg]]
---

# Что такое SnR

## TL;DR

**SnR (Support aNd Resistance)** — классический price-action концепт. **В книге
ICT отдельного «SNR block» НЕ существует**. ICT переименовывает S/R в
**«liquidity pools»** и конкретизирует через OB / Breaker / Mitigation /
Rejection блоки.

## Определение SnR-зоны (классическое)

Горизонтальная область, где цена многократно тестировала уровень и
отказывалась его пробить:

1. **≥2 swing-точек** (HH или LL) в узком ценовом диапазоне (±0.3% на LTF,
   ±1% на HTF от среднего уровня кластера)
2. **Свинги — фрактальные** (5-bar fractal: HH/LL в i относительно i±1, i±2)
3. **Между касаниями есть отскок** (цена реально уходила от уровня)
4. **Zone width** = диапазон touch-цен + небольшой ATR-буфер
5. **Валидна пока 2 closes не пробили зону** (close > top для resistance,
   close < bottom для support)

## SnR vs ICT-блоки

| Концепт | Школа | Геометрия зоны | Кол-во событий |
|---------|-------|----------------|----------------|
| **SnR** | Classical TA | Горизонталь между swing-highs/lows | **≥2 касания** |
| **OB** | ICT | Тело свечи перед impulse | 1 свеча |
| **Breaker** | ICT | OB, пробитый и retest как flip-zone | 1 OB + flip |
| **Mitigation** | ICT | OB без забоя противоположного swing | 1 OB + retest |
| **Rejection block** | ICT | Фитильная зона отказа | 1 фитиль |
| **RDRB** | Custom 3-bar | Sweep + rejection (см. [[что такое rdrb]]) | 3 свечи |
| **Supply/Demand** | Sam Seiden | Drop-Base-Rally / Rally-Base-Drop | base зона |

Все они describing the same phenomenon (зона где сидит liquidity), но с
разной геометрией и разной точностью определения зоны.

**Ключевое отличие SnR от ICT-блоков**: SnR требует **множественные касания**
(социальное доказательство), ICT-блоки строятся на **одном-двух событиях**
(импульс + retest).

## Где есть SnR-логика в нашем коде

В проекте `traid-bot` SnR как **самостоятельная стратегия НЕ реализована**.
Близкие реализации:

- [[s3 rdrb + ob1h]] / `strategies/strategy_rdrb.py` — 3-bar pattern
  (концептуально близок: уровень + sweep + rejection, но требует только 1
  касание trigger-свечой, не множественные)
- [[что такое order block]] — ICT OB (последняя свеча перед impulse)
- [[strategy-1-1-7-ifvg-continuation]] — iFVG (flip-зона)

Если когда-то делать SnR-стратегию явно, базовая логика:

```python
def find_snr_zones(df, zone_pct=0.003, min_touches=2, fractal_n=2):
    # 1. Найти 5-bar fractals (HH and LL)
    hi_idx, lo_idx = find_fractals(df, n=fractal_n)
    # 2. Кластеризовать свинги по близости цены
    res_clusters = cluster_swings(hi_idx, df["high"], zone_pct)
    sup_clusters = cluster_swings(lo_idx, df["low"], zone_pct)
    # 3. Фильтр: >= min_touches
    res = [c for c in res_clusters if len(c) >= min_touches]
    sup = [c for c in sup_clusters if len(c) >= min_touches]
    # 4. Validation: zone валидна пока 2 closes не пробили
    return [validate_zone(c, df) for c in res + sup]
```

Полная имплементация в `research/elements_study/etap_154_find_last_snr_btc_2h.py`.

## Пример SnR на BTC (2026-05-18)

На 1d window 2 года: **active RESISTANCE [81,638 - 83,264]** — 3 daily touches
6, 10, 14 May 2026. Текущая цена $77,457 (6% ниже).

На 2h window 125 дней: **active RESISTANCE [80,877 - 81,446]** — 5 2h-touches
5-13 May. 2h-зона полностью внутри 1d-зоны = **multi-TF confluence**.

## SnR как фильтр на наши cascades

Гипотетическое применение к [[strategy-wicked-fractal-ob-d-btc-only]]:

> Wicked OB-D LONG setup игнорируется, если entry попадает прямо под активный
> SnR-resistance (zone_bottom > entry > resistance_zone). SHORT — наоборот,
> игнор над активным support.

Это могло бы быть Variant I — TBD test.

## Альтернативное значение SNR

**Signal-to-Noise Ratio** — статистическая метрика качества тренда:
`|price_change_N| / avg_volatility_N`. Используется как trend-following filter.
**НЕ относится к SnR-блокам** — другая концепция, omonim.

## Связи

- [[что такое order block]]
- [[что такое rdrb]] — 3-bar version of S/R with sweep
- [[что такое fvg]]
- [[strategy-wicked-fractal-ob-d-btc-only]] — wick-based S/R concept
- [[strategy-1-1-7-ifvg-continuation]] — flip-zone concept
