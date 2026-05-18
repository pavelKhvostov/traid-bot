---
tags: [indicator, score, hull, mh, rsi, asvk, floating-tp]
date: 2026-05-15
---

# 4-indicator momentum score (Hull + MH + RSI + ASVK)

Композитный score ∈ [−1, +1] для floating TP в стратегиях с низким
baseline WR (1.1.1, 1.1.2). Каждый из 4 индикаторов даёт нормализованный
скалярный сигнал; среднее = composite.

## Формула

```
score(t) = mean(s_hull, s_mh, s_rsi, s_asvk)   ∈ [−1, +1]
```

Все 4 индикатора равноправны. Никаких подобранных весов.

## Компоненты

### 1. Hull MA (1h, length=78)

```python
s_hull = +1 if close[t] > hull[t-2] else -1
```

Использует Hull от 2 бар назад → lookahead-safe. См. [[asvk-trend-line-hull]].

### 2. MH bw2 (WaveTrend) цвет

```
bw2 = double EMA(CCI(hlc3), 9, 12), затем .rolling(4).mean()
sma14 = bw2.rolling(14).mean()

s_mh = маппинг:
  green       (bw2>0 AND bw2>=sma14) → +1.0
  grey_from_green (bw2>0 AND bw2<sma14) → +0.5
  na                                    →  0.0
  grey_from_red   (bw2<0 AND bw2>sma14) → −0.5
  red         (bw2<0 AND bw2<=sma14) → −1.0
```

См. [[money-hands-asvk]].

### 3. RSI Wilder (14)

```python
rsi = rsi_wilder(close, 14)
s_rsi = clip((rsi - 50) / 50, -1, +1)
```

Линейная норма относительно 50.

### 4. ASVK ema_3 zone (direction-aware)

```python
ema_3 = asvk_adjusted_rsi(close)  # См. [[asvk-custom-rsi]]
above, below = asvk_dynamic_levels(ema_3, lookback=200)
zone = "red" if ema_3 > above else ("green" if ema_3 < below else "neutral")

# LONG: red=+1 (overbought = continuation), green=-1 (oversold = reverse)
# SHORT: zеркально (направленный)
s_asvk = +1 / 0 / −1
```

## Применение: floating TP

```
LONG position:
  hold while score(t) > threshold
  exit when score(t) <= threshold для confirm баров подряд
  exit price = close 1h бара подтверждения

SHORT: зеркально (score >= -threshold для exit)
```

Параметры per-strategy:

| Strategy / Symbol | R_cap | threshold | confirm |
|---|---:|---:|---:|
| 1.1.1 BTC/ETH | 4.5 | −0.25 | 2 |
| 1.1.1 SOL | 3.5 | 0.00 | 1 |
| 1.1.2 BTC/ETH/SOL | 4.5 | 0.00 | 2 |

## Lookahead safety

Все индикаторы строго используют только данные ДО момента решения:
- Hull: лаг 2 бара (close[t] vs hull[t-2])
- MH bw2: EWM/rolling на 0..t
- RSI: Wilder EWM на delta 0..t
- ASVK: rolling lookback 200 баров до t

Score lookup в simulation: `searchsorted(checkpoint, side="right") - 1`
= последний ЗАКРЫТЫЙ бар до checkpoint.

## Когда работает

- **Низкий baseline WR стратегии** (1.1.1 при 45%, 1.1.2 при 42%)
- **Score catches momentum reversal до hard SL** → WR +6-10pp, медиана R становится положительной
- **Конвертирует потенциальные losses в early-exit at small gain**

## Когда НЕ работает

- **Высокий baseline WR (≥ 60%)** — например 1.1.4 BFJK
- Score-exit вынужденно режет trades которые статистически достигают fixed TP
- См. [[floating-tp-only-helps-low-wr-strategies]]

## Реализация

`research/elements_study/etap_103_floating_tp.py:build_score_series()`:

```python
def build_score_series(df_1h):
    s_hull = hull_signal(df_1h["close"])
    s_mh = mh_signal(df_1h)
    s_rsi = rsi_signal(df_1h["close"])
    s_asvk = asvk_signal_direction_aware(df_1h["close"])
    s_long  = (s_hull + s_mh + s_rsi + s_asvk) / 4.0
    s_short = -(s_hull + s_mh + s_rsi + s_asvk) / 4.0
    return s_long, s_short
```

## Связи

- [[asvk-custom-rsi]]
- [[money-hands-asvk]]
- [[asvk-trend-line-hull]]
- [[floating-tp-only-helps-low-wr-strategies]]
- [[strategy-1-1-1-floating-tp-final]]
- [[strategy-1-1-2-floating-tp-final]]
