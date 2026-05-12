---
tags: [indicators, money-hands, wavetrend, asvk]
date: 2026-05-06
source: Pine Script (TradingView), переведён в `research/money_hands/plot_money_hands.py`
---

# Money Hands — ASVK · детальный разбор

Авторский Pine-индикатор. Реализован как WaveTrend (LazyBear) + Heikin Ashi
Money Flow + двойной Stochastic + дивергенции на bw2.

⚠️ **Допущение:** `lib.blueWaves(src, n1, n2)` из закрытой библиотеки
`raf_mak/libpublic` интерпретирована как WaveTrend LazyBear. Если
визуально не совпадает с TV — нужен код библиотеки.

## Из чего состоит

### bw2 — главный осциллятор (WaveTrend wt2)

```
ap   = hlc3
esa  = EMA(ap, 9)
d    = EMA(|ap-esa|, 9)
ci   = (ap - esa) / (0.015 * d)
wt1  = EMA(ci, 12)
wt2  = SMA(wt1, 4)
bw2  = wt2
```

Симметричный относительно нуля, обычно ±100. Цикл ~12-15 баров на 1h.
Сглаженный → есть лаг, но дивергенции и пивоты надёжнее.

### Цветовая state machine `bw2 vs SMA(14)` — **главная фишка**

| bw2 | vs SMA | цвет | смысл |
|---|---|---|---|
| > 0 | ≥ SMA | 🟢 | бычий импульс УСИЛИВАЕТСЯ |
| > 0 | < SMA | ⚪ | бычий импульс СЛАБЕЕТ |
| < 0 | ≤ SMA | 🔴 | медвежий импульс УСИЛИВАЕТСЯ |
| < 0 | > SMA | ⚪ | медвежий импульс СЛАБЕЕТ |

**Серые столбики = «начало конца» текущего импульса.**
Это уникальное свойство — фаза импульса, а не просто направление.

### Триггеры ±75 / OB-OS ±60

Фиксированные. ±60 — «зоны экстремума», ±75 — жёсткие триггеры.
Не адаптивные — в сильном тренде дают фальшивые сигналы.

### Money Flow по Heikin Ashi

```
HA: open/high/low/close по правилам HA (сглаженные свечи)
raw = ((HA_close - HA_open) / (HA_high - HA_low)) * 200
MF = SMA(raw, 60) - 2.25
```

`(HA_close-HA_open)/(HA_high-HA_low)` ∈ [-1, +1] — доминирование
свечи в свою сторону. HA убирает шум хвостов. SMA(60) ≈ 2.5 дня на 1h.

MF > 0 = деньги в покупки, < 0 = в продажи. Медленный, но устойчивый.

### Двойной Stochastic

```
rsiMod    = SMA(Stoch(close, high, low, 40), 2)   # ~1.5 дня
stcRsiMod = SMA(Stoch(close, high, low, 81), 2)   # ~3.5 дня
```

Cross rsiMod ↑ stcRsiMod = краткосрочный momentum обогнал среднесрочный
→ bull. Аналог классики stoch RSI, но на ценах.

### Дивергенции на bw2

Параметры: lbL=2, lbR=2, range **5-60** баров (короче ASVK RSI 4-100).
Лучше для intraday. 4 типа: regular bull/bear, hidden bull/bear.

## Money Hands vs ASVK Custom RSI

| ASVK RSI | Money Hands |
|---|---|
| Adjusted RSI (accelerator) | bw2 (сглаженный WaveTrend) |
| Adaptive OB/OS | Fixed ±60/±75 |
| NWE-канал (стат-границы) | Цветовая state machine (4 фазы) |
| Дивергенции range 4-100 | Дивергенции range 5-60 |
| Структурные ▲/▼ (EMA50 локальных) | Money Flow по HA (60-бар) |
| 1 осциллятор | 4 осциллятора |
| – | Heikin Ashi сглаживание |

**Уникально для MH:**
- Фаза импульса через цвет (растёт/слабеет, а не только направление)
- Двойной Stoch — встроенный multi-TF взгляд
- Heikin Ashi MF — малошумный
- Короткие дивергенции — intraday-моменты, которые ASVK пропускает

## Гипотезы интеграции с [[strategy_3_2]]

### A. Прямые фильтры на signal_time

**MH1.** Цвет bw2 в момент signal:
- LONG + 🟢 = pro-trend
- LONG + ⚪-после-🔴 = идеальный bottom-fade
- LONG + 🔴 = counter-trend (опасно)
- Сегментировать 245 сделок по 4 цветам и сравнить WR.

**MH2.** bw2 в OB/OS зоне на touch_time:
- LONG + bw2 ≤ -60 (или ≤ -75) = вход с экстремумом
- SHORT + bw2 ≥ 60.

**MH3.** Money Flow знак в момент signal:
- LONG + MF > 0 = деньги в покупки = confluence.
- Простой бинарный фильтр.

**MH4.** bw1/bw2 cross в окне до signal:
- Bullish cross (bw1 ↑ bw2) в [touch-24h, signal] = разворот импульса.
- Аналог зелёного кружка в Money Cipher B.

### B. Дивергенции (расширение [[H1]])

**MH5.** Двойная divергенция (ASVK + bw2):
- На H1-сегменте (62.7% WR) добавим: на bw2 ТАКЖЕ aligned div.
- Гипотеза: WR > 70%.

**MH6.** bw2-only дивергенция (без ASVK):
- На сегменте «без ASVK div» (192 сделки, WR 53.1%) — есть ли сделки с bw2-div?
- Если на non-ASVK bw2-div даёт edge — это независимый источник.

### C. Multi-Stoch фильтры

**MH7.** rsiMod/stcRsiMod alignment:
- LONG + rsiMod < 20 И stcRsiMod < 30 = двойной OS.
- Жёстко, мало сделок, но сильно.

**MH8.** rsiMod cross stcRsiMod в окне:
- Bullish cross в [touch-12h, signal] = momentum-shift.

### D. Money Flow direction-фильтр

**MH9.** MF тренд (delta MF):
- MF растёт последние 12 баров = деньги в покупки.
- Confluence для LONG.

**MH10.** MF amplitude:
- |MF| в top 30% по absolute value = сильное направленное движение.
- Гипотеза: pro-trend сетапы в strong movements работают лучше.

### E. Composite-индексы

**MH11.** Money Hands score (4 флага по аналогии с [[H15]]):
- bw2 цвет правильный
- bw2 в OB/OS на touch
- MF знак правильный
- bw1/bw2 cross или дивергенция в окне
- Score 0-4 → размер 1.0+0.5×score.

**MH12.** Combined ASVK + MH score (8 флагов, max sizing 3.0×).
Гипотеза: совместный сетап = best of both worlds.

### F. Adaptive exit (расширение [[H12]])

**MH13.** bw2 cross zero как exit для LONG:
- Аналог H12 (NWE-cross), но через bw2.
- Возможно работает и на SHORT (где NWE не работал).

**MH14.** bw2 цвет смена как exit:
- LONG: пока 🟢 — держим. Переход на ⚪ (bw2 < SMA14) — выход.
- Натурально, pro-trend trail.

## Приоритет реализации

1. **MH1** (цвет bw2) — самая дешёвая и информативная сегментация
2. **MH5** (двойная дивергенция) — расширение топ-1 H1
3. **MH13/14** (bw2 exit) — попытка спасти SHORT-сегмент H12
4. **MH11/12** (composite score) — для sizing

## Грабли при реализации

- WaveTrend требует тщательной реализации EMA с `adjust=False` (как в Pine).
- Heikin Ashi: HA_open итеративный, нельзя векторизовать через shift.
- Pine `ta.stoch(source, high, low, length)` — `100·(close-ll)/(hh-ll)`, НЕ
  `(source-ll)/(hh-ll)`. Аккуратно с тем, что source — это close.
- Дивергенции на bw2 имеют другой range (5-60 vs 4-100 у ASVK) — пивоты
  чаще, но и шумнее.
- `lib.blueWaves` неизвестна — допущение WaveTrend LazyBear. Проверять
  визуально с TV перед production-использованием.

## Что не использовать

- **Триггеры ±75 как фильтр входа** — слишком часто срабатывают в тренде.
- **rsiMod/stcRsiMod cross без других флагов** — слишком быстрый, шумный.
- **MF без HA** — обычная формула шумная, не даёт edge.
