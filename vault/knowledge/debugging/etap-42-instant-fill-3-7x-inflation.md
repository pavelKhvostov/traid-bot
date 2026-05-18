---
tags: [debugging, simulator, instant-fill, lookahead-like, pitfall]
date: 2026-05-15
---

# etap_42 instant-fill simulator завысил PnL в 3-7×

## Что было

В etap_42 PDF (Smart Trail report от 2026-05-10) я использовала
**instant-fill execution model**: trade фейерится в момент
`signal_time + tf_min` независимо от того, дотронулась ли цена до entry.

Тогда же документировала это как «Simulation contract: instant entry @
signal_time (no no_entry filter)» — было известно что это упрощение.

## Симптом

PDF указывал "M0 Fixed RR=2.5 → +168R BTC 6.34y". В etap_100 (2026-05-15)
я взяла те же параметры (sl=0.40, MIN_SL=1%, RR=2.5) и **новые multi-shot
данные** → получила «+313R retry BTC». Пользователь обоснованно усомнился.

## Причина

`simulate_fixed_rr` в etap_42:

```python
i0 = np.searchsorted(df_1m.index.values, et64)  # = bar at signal_time + tf_min
h = df_1m["high"].values[i0:i1]
l = df_1m["low"].values[i0:i1]
# Сразу проверяем SL/TP hits без ожидания касания entry:
sl_hits = (l <= sl)
tp_hits = (h >= tp)
```

Если цена УЖЕ выше entry на момент signal close — limit-ордер в реальности
**не заполнится** (он на entry-цене ниже текущей). Но simulator делает
вид что trade открыт и считает SL/TP.

Симметрично: цена УЖЕ ниже entry — реальный limit заполняется мгновенно,
но дальнейший «выход обратно к entry» в simulator невозможен (мы уже в
trade), хотя в реальности trade был бы открыт по market если pre-fill
happened.

## Аудит на BTC 6.34y

| Execution | PnL baseline | PnL retry | Inflation factor |
|---|---:|---:|---:|
| **instant** (etap_42 model) | +276R | **+313R** | — (reference) |
| **limit** (realistic) | +73R | +84R | ÷3.7× |
| **market** (entry @ close) | +56R | +79R | ÷4.9× |

С дедупом (для очищенного instant vs limit):
- instant + dedup: +165R baseline (= etap_42 reference)
- **limit + dedup: +41R** (real expectation)
- Inflation factor: **×4.0**

## По 3 символам (instant / limit + dedup, BTC 6y / ETH 6y / SOL 5.76y)

| Symbol | Instant + dedup | Limit + dedup | Inflation |
|---|---:|---:|---:|
| BTC | +165R | +41R | ×4.0 |
| ETH | +173R | +52R | ×3.3 |
| SOL | +194R | +42R | **×4.6** |

SOL особенно подвержен — волатилен, цена чаще пробивает entry без отката.

## Правило избегания

1. **Backtest simulator должен ждать касания entry** (limit-fill model) или
   симулировать market entry at close-price (с реалистичной R пересчётом).
2. Если используется instant-fill для screening — **пометить явно в PDF/log**
   и **не сравнивать с numbers from limit-fill** напрямую.
3. **Любой WR > 60% на сотнях сделок** — first candidate для проверки
   exec model на инфляцию.
4. **Cross-validate** на 2+ execution models перед утверждением.

## Когда instant-fill всё-таки OK

- **Screening comparison** разных exit-режимов (M0, M1, M8, ...) — все
  используют ту же fictional model, relative ранжирование сохраняется
- **Maximum theoretical PnL** estimation
- НЕ для абсолютных live-trading expectations

## Источник

[[2026-05-15-floating-tp-multi-symbol-c2-trendfilter]] — etap_101 audit.

## Связи

- [[multi-shot-detector-2.3x-inflation]] — другой источник инфляции в той же сессии
- [[lookahead-bug-в-vic-evot-backtest]] — другой класс ошибок, похожий симптом
