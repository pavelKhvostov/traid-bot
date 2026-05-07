---
tags: [indicators, rsi, asvk]
date: 2026-05-06
source: Pine Script (TradingView), переведён в `research/asvk_rsi/plot_asvk_rsi.py`
---

# ASVK Custom RSI — что это, фишки, идеи интеграции

Авторский Pine-индикатор юзера. Реализован 1:1 в Python:
[plot_asvk_rsi.py](../../../research/asvk_rsi/plot_asvk_rsi.py).

## Не путать

Это **не overbought-индикатор**. Это **детектор импульса + адаптивные
уровни + Гауссов канал + 4 типа дивергенций** в одном.

## Из чего состоит — математика

### Adjusted RSI (синяя линия `ema_3`)

```
coef = 1.2 if rsi > 50 else 0.8
adjusted = rsi² * coef / ema5(rsi)
ema_3 = ema5(adjusted)
```

Квадратичная амплификация отклонения от своей короткой EMA, с асимметричным
trend-bias (бычий импульс усиливается сильнее). Может выходить за [0; 100].

**Фишка:** sharp-move'ы видны быстрее raw RSI. Дивергенции на нём острее.

### Адаптивные уровни OB/OS

Считаются на rolling 200 баров. После упрощения:

```
above = (z + 200) / 4              # z = count(ema_3 > 50)
below = 100 - 49*(z + 200) / 200   # z = count(ema_3 < 50)
```

| z | above | below |
|---|---|---|
| 200 (полностью bullish) | 100 | 2 |
| 100 (50/50) | 75 | 26.5 |
| 50 | 62.5 | 38.75 |

**Фишка:** в сильном тренде классические 70/30 дают ложные сигналы
«перекупленности в тренде». Здесь пороги уезжают на края — OB достигается
только при реальном extension.

### NWE Гауссов канал

```
weights[j] = exp(-j² / (2·bw²)),  bw=8, bar=499
output[i]  = Σ ema_3[i-j] · weights[j] / Σ weights
band       = ±2 · SMA(|ema_3 - output|, 499)
```

bar=499 формальный — веса падают до 1% за ~25 баров (3·bw),
**эффективный lookback ≈ 24-32 бара**. Канал не repaint'ится
(`repainting_mode=false` в коде).

**Фишка:** пробой канала = ema_3 ушёл от своего сглаженного тренда
сильнее обычного. Stat-z-score-аналог.

### Дивергенции

Считаются на `ema_3`, не на raw RSI. Pivot lbL=3, lbR=2, range [4, 100] bars.
4 типа: regular bull/bear, hidden bull/bear.

**Фишка:** на amplified-осцилляторе дивергенции острее.

### Структурные ▲▼

```
findLocalExtrema(ema_3) → isMin/isMax при src[2] strict extremum vs [0,1,3,4]
emaL/emaH = ta.ema(localExtrema, 50), обновляется только при non-na.
```

Треугольник рисуется при смене `emaL/emaH`. **Фишка:** медленный structural-trend
RSI; маркеры HL/HH или LL/LH в RSI-пространстве.

### Заливки

- Yellow между NWE-band и dynamic-level = «канал дотянулся, ema_3 ещё нет»
- Red/Green = «ema_3 пробил уровень»

Двухуровневая визуализация: приближение → достижение.

## Идеи интеграции с нашими стратегиями

### [[s4 снятие фрактала]] / Strategy 1.1.5 — sweep+OB

- **Confluence-фильтр** в момент `signal_time`: проверять, в какой
  ASVK-зоне находится 1h ema_3. Гипотеза: SHORT 1.1.5 лучше работают,
  когда ema_3 в red-зоне (extension вверх). LONG — в green.
- **Контр-фильтр дивергенций:** SHORT, но в окне
  `[sweep_time-24h, signal_time]` есть bull/h_bull на 1h ema_3 → скип.
- **Идеальный паттерн:** sweep + bear/h_bear div одновременно.

### [[strategy_1_1_1]] — multi-TF OB+FVG

- **Адаптивные уровни как режим-фильтр:** делить сигналы по `z_above`
  на момент сетапа. В сильном тренде (above>80) поведение лонгов может
  отличаться от флэта (above≈75). Backtest hypothesis.

### Live FRACTAL / VIC_EVOT

- Добавить в Telegram **ASVK-контекст** (декоративно, без логики):
  «🟢 OS / bear-div 1h» — для дискреционного контроля.

### [[s3 rdrb + ob1h]]

- RDRB = ложный пробой с возвратом. ASVK дивергенция на той же свече
  = сильнейшая конфирмация (RDRB сам — сигнал разворота).

### [[vic_bos]]

- Структурные ▲▼ ASVK на 3m как доп. подтверждение к ценовому BOS.

## Граблики при реализации

- Pine `if rsi > 50: coef:=1.2`, `if rsi < 50: coef:=0.8` — при `rsi == 50`
  coef сохраняет прошлое значение (`var float coef = na`). В Python
  принято `>= 50 → 1.2, < 50 → 0.8`. Несимметричность ≤ 1 бар.
- `current_value_below` асимметричен `current_value_above`:
  `coeff_2 = 1/y` (а не `0/y`). Похоже на опечатку автора Pine, но
  воспроизводим 1:1.
- NWE-режим в Pine — `repainting_mode = false` (default), non-causal
  ветка `barstate.islast` не выполняется. Реализуем только causal
  свёртку с историей.
- Wilder smoothing для RSI = `ewm(alpha=1/period, adjust=False)`,
  не `span=period`. Ошибиться легко, и значения разойдутся с TV.

## Куда двигаться дальше

Конкретный backtest-эксперимент: для каждой строки `signals/strategy_1_1_5_3y_K3.csv`
добить колонки `asvk_zone_at_signal_time` (red/yellow_OB / neutral / yellow_OS / green)
и `asvk_div_in_window` (bool). Сегментировать сигналы и смотреть,
есть ли разница в распределении исходов после введения SL/TP формулы.
