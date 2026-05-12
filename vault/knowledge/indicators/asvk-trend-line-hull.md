---
tags: [indicators, hull-ma, trend, asvk]
date: 2026-05-08
source: Pine Script (TradingView), переведён в `research/asvk_trend_line/plot_asvk_trend_line.py`
---

# ASVK Trend Line — Hull MA вариант

Авторский Pine-индикатор юзера. Реализован 1:1 в Python:
[plot_asvk_trend_line.py](../../../research/asvk_trend_line/plot_asvk_trend_line.py).

## Что это

**Hull Moving Average в 3 модификациях** (HMA / EHMA / THMA) с двумя
визуальными слоями: текущий HULL и тот же HULL, сдвинутый на 2 бара
назад. Полоса между ними + цвет по `close vs HULL[2]` — это и есть весь
сигнал.

**Не путать с RSI/Money Hands** — это **trend-following** индикатор, а не
осциллятор. Его задача — определить направление и обозначить «коридор» для
floating S/R или swing-entry.

## Из чего состоит — математика

### Hull MA (Alan Hull, 2005) — `Hma` mode (default)

```
HMA(src, n) = WMA(2·WMA(src, n/2) − WMA(src, n), round(√n))
```

Идея: `2·WMA(n/2) − WMA(n)` усиливает реактивность относительно стандартной
WMA(n) (антилаг через разность). Финальный WMA(√n) сглаживает шум этой
разности. Результат — **меньше lag чем у EMA(n) при сравнимом сглаживании**.

С default `length=49 · lengthMult=1.6 = 78`:
- Внутренний WMA(39) и WMA(78), разность.
- Финальный WMA(round(√78)) = WMA(9).

### `Ehma` mode

Те же формулы, но EMA вместо WMA. Pine WMA даёт линейные веса
(1, 2, ..., n), Pine EMA — экспоненциальные (`alpha = 2/(n+1)`,
`adjust=False`). EHMA реактивнее на резких движениях, но больше lag в
boring price action.

### `Thma` mode (нестандартный — авторский)

```
THMA(src, n) = WMA(3·WMA(src, n/3) − WMA(src, n/2) − WMA(src, n), n)
```

Тройная антилаг-комбинация на трёх длинах. Финальный WMA на полной длине
сглаживает.

⚠ **Pine-нюанс:** в `Mode("Thma", src, len)` передаётся `THMA(src, len/2)`,
то есть эффективно используется половинная длина. С default 78/2 = 39 —
THMA внутри использует WMA(13), WMA(19), WMA(39), финальный WMA(39).
Гладче чем HMA при том же `length`.

### MHULL / SHULL и полоса

```
MHULL = HULL          # текущая Hull MA
SHULL = HULL[2]       # та же Hull MA, 2 бара назад
upper = max(MHULL, SHULL)
lower = min(MHULL, SHULL)
band  = fill(upper, lower, color)
```

Полоса работает как «след» — её толщина = насколько сильно Hull сдвинулся
за 2 бара. На flat'е полоса схлопывается в линию, на тренде — расходится.

### Цвет

```
hullColor = close > SHULL ? GREEN : RED
```

Не `close > HULL`, а **`close > HULL[2]`** — то есть сравнивается с прошлой
Hull, не текущей. Это даёт более стабильный сигнал (текущая Hull всегда
близко к close, флаг бы дёргался; Hull[2] — уже устаканился).

## useHtf режим

Опциональный флаг `useHtf=true`:
- `request.security(syminfo.tickerid, htf, _hull)` — индикатор считается
  на старшем ТФ и mapping'ится на текущий чарт.
- Pine non-repaint режим (default) — значение появляется в момент
  закрытия HTF бара.
- В Python требует `resample` + `ffill` + `.shift(1)` чтобы не получить
  look-ahead на live-баре. Реализовано в `resample_htf()`.

## Параметры — что менять

| Параметр | Default | Назначение |
|---|---|---|
| `length` | 49 | базовая длина |
| `lengthMult` | 1.6 | множитель → effective `78` |
| `mode` | "Hma" | / "Ehma" / "Thma" |
| `useHtf` | false | расчёт на HTF |

**Авторские рекомендации (из тулипа):**
- **160-200** — floating S/R на свинговом ТФ (1d-3d)
- **50-80** — swing entry (4h-12h)

С default-настройкой effective_len=78 = граница «swing-entry» режима.

На 1h за 1500 баров (~62 дня) — **99 trend flips** (1 flip / 15 баров).
Слишком много для подтверждения сетапов. На 4h/6h ожидаем 3-5× меньше.

## Как использовать в стратегиях (гипотезы)

### A. Pro-trend filter для C2 / Strategy 1.1.5

[[strategy-c2-ob-6h-fvg-2h-pro-rr1]] уже использует EMA200(2h) для
pro-trend. Hull(78, mode=Hma) на 2h — гипотетически реактивнее EMA200 на
смене тренда. Backtest hypothesis:

```
LONG C2 only if close > SHULL on entry_tf
SHORT C2 only if close < SHULL on entry_tf
```

Сравнить с EMA200-фильтром head-to-head на 178 setups C2.

### B. Confluence-фильтр для [[s4 снятие фрактала]]

Sweep'ы (LL fractal break) лучше работают, когда Hull-trend уже идёт в
сторону sweep direction. Но это **counter-intuitive** — sweep это разворот.
Возможные варианты гипотезы:
- LONG sweep + Hull уже зелёная (hidden bull) = pro-trend reversal
- LONG sweep + Hull красная (regular bull) = counter-trend, более
  агрессивно

Сегментировать sweeps по `is_green at signal_time`.

### C. Multi-TF Hull confluence

Идея от ASVK — на разных длинах получать разную «слойность»:
- Hull(200) на 1d = macro-trend
- Hull(80) на 4h = swing-trend
- Hull(50) на 1h = entry-trend

Сетап входа = все 3 одного цвета. Аналог Triple-confluence из
`research/elements_study/etap_22` который НЕ дал прорыва на чистых OB+FVG.
Но Hull другая природа — может работать.

### D. Adaptive exit для C2

`close < SHULL` на entry_tf = exit для LONG. Аналог [[H12]] (NWE-cross
exit) для Money Hands. Сравнить с TP/SL exit.

### E. Decorative в Telegram

Добавить `🟢 Hull-up / 🔴 Hull-down` в формат сигналов 8 live-стратегий
для дискреционного контроля. Без backtest-валидации, но информативно.

## Грабли при реализации

1. **Pine `int()` truncates, не rounds** — `int(49 * 1.6) = int(78.4) = 78`.
   В Python `int()` тоже truncates → одинаково. ✅
2. **`math.round(sqrt(78)) = round(8.83) = 9`** — Pine round до int. В Python
   `int(round(...))` ✅.
3. **WMA веса** — `1, 2, ..., n` (1 = oldest, n = newest). Не `0..n-1`,
   не нормализованные. Sum = `n*(n+1)/2`. Используем
   `pd.rolling().apply(weighted_average)` — медленно для больших датасетов,
   но точно соответствует Pine.
4. **EMA `adjust=False`** — иначе разойдётся с TV. ✅
5. **`useHtf` без `.shift(1)` — look-ahead.** Pine non-repaint режим
   == после закрытия HTF бара. На live-баре не должно использоваться
   значение HTF, который ещё формируется.
6. **`SHULL = HULL[2]`** — индекс [2] в Pine = 2 бара назад. В pandas
   `hull.shift(2)`. Пропустить 2-bar offset — потерять весь смысл
   индикатора.
7. **THMA `len/2` обвёртка** — в Pine эта дополнительная половина
   спрятана внутри `Mode()` switch. Easy to miss.

## Производительность

WMA через `rolling().apply(lambda)` — `O(N·n)` ≈ 1500·78 = 117k операций
для 1h на 62 дня. Терпимо для plot. Для бэктеста 6 лет 1m данных
(3.3M баров) — нужна векторизация через FFT-convolution или `np.convolve`.

Шаблон fast-WMA для backtest:
```python
def wma_fast(arr, n):
    weights = np.arange(1, n + 1, dtype=float)
    weights /= weights.sum()
    return np.convolve(arr, weights[::-1], mode="valid")
```

## Куда двигаться дальше

1. Запустить `plot_asvk_trend_line.py` с `MODE="Hma"`, `MODE="Ehma"`,
   `MODE="Thma"` на одном окне → визуально сравнить с TV.
2. Backtest C2 + Hull pro-trend filter (length=78 на 2h).
3. Сравнить «Hull(78)/2h» vs «EMA200/2h» как pro-trend gate для C2:
   гипотеза — Hull даёт меньше скипов на разворотах рынка.

## Связи

- [[asvk-custom-rsi]] — соседний ASVK-индикатор (oscillator + adaptive levels)
- [[money-hands-asvk]] — соседний ASVK-индикатор (WaveTrend + MF + Stoch)
- [[strategy-c2-ob-6h-fvg-2h-pro-rr1]] — основной кандидат на Hull-фильтрацию
- [[7-criteria-of-good-strategy]] — критерии оценки нового фильтра
