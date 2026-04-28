---
tags: [session, strategy, backtest, vic-evot, vic-bos, strategy-1-1-1]
date: 2026-04-28
related: [[vic_evot]], [[vic_bos]], [[strategy_1_1_1]], [[универсальные определения OB и FVG]]
---

# Сессия 2026-04-28: Strategy 1.1.1, VIC BOS, итеративный backtest

## Что сделано

### 1. VIC_EVOT — серия правок и фиксов

**Изменения в `strategies/vic_evot.py`:**
- Расширил окно фрактала до 4 позиций (FRACTAL_WINDOW=4) → потом убрал, заменил
  на структурную инвалидацию: «между фракталом и FVG не должно быть противоходного фрактала».
- Убрал FVG-vs-vic constraint (FVG не обязан быть выше/ниже уровня).
- Entry с close(i+2) → 80% FVG (limit-вход):
  - LONG: `entry = high(i)*0.2 + low(i+2)*0.8`
  - SHORT: `entry = low(i)*0.2 + high(i+2)*0.8`
- OB-15m фильтр variant B (хотя бы одна свеча противоположного цвета в окне) —
  на 3y BTC ухудшил результат на −27R (отсекал 7% сигналов, которые в среднем были лучше).
  Реально не работает.

**Изменения в `backtest_vic_evot.py`:**
- CLOSE_EOD = False (без EOD-cutoff — самообман). Симулируем до фактического SL/TP.
- Добавил SL_BUFFER_MULT=1.1 (увеличение SL на 10%) — на 3y RR=1 ухудшил
  результат с −41R до −68R (буфер не помогает на BTC).
- Multi-RR runs: одновременно RR=1.0 и RR=2.2 в раздельные CSV.
- Корректный учёт PnL: `wins*rr - losses*sl_buffer` (раньше было `wins - losses`).
- **Fix lookahead bug:** scan начинался с `signal_time = open(i+2)`, теперь с
  `signal_time + 15min = close(i+2)`. До фикса было «магическое» 60%+ WR на
  e=0.0 sl=0.8 (+184R), после фикса всё развалилось до реальных 49-51%.

**Grid search оптимальных параметров:**
- Лучший конфиг (true 1:1 RR): `entry_pct=1.0, sl_buffer=0.8`. На 3y BTC: WR 51.0% / +13R.
- Все другие комбинации e × sl на 3y дают WR в диапазоне 47-51%.
- 90-дневные пики WR 60-76% — все были артефактом lookahead. Реальный edge
  стратегии на BTC очень слабый.

**Production VIC_EVOT (e=0.8 sl=1.1) на 3 года:**
- RR=1.0: 683 closed, WR 49.5%, **PnL −41.5R**
- RR=2.2: 683 closed, WR 30.6%, **PnL −61.6R**
- LONG-only: 50.4% / +3R (≈ break-even)
- SHORT: 45.0% / −32R (стабильно убыточен)
- **Стратегия в текущем виде не имеет edge на 3-летнем out-of-sample.**

### 2. VIC BOS (новая стратегия) — backtest_vic_bos.py

Новая стратегия в отдельном файле (по запросу пользователя — не модифицировать VIC_EVOT).

**Логика:**
1. Закрытие 1d → maxV(D-1) и направление по close(D-1) vs maxV.
2. В day D на 1m — первое касание vic.
3. После cross на 3m — break of structure (BOS).
4. Различные варианты BOS опробованы.

**Варианты BOS (на 3 года BTC, RR=1):**

| Вариант | n | WR | PnL |
|---|---|---|---|
| Swing (3-step pattern) | 555 | 50.3% | +3R |
| **Fractal (closest unbroken)** | **726** | **50.7%** | **+10R** |
| Triple H-L-H (3 fractals) | 557 | 46.5% | −39R ❌ |
| **Quadruple H-L-H-L (LH+LL)** | **511** | **53.6%** | **+37R** ✓ |
| BOS B (locked target, тройка) | 728 | 51.5% | +22R |
| **«Первый+предыдущий фрактал»** | **347** | **52.4%** | **+17R** |

**Найденные паттерны на BOS B:**
- LONG: WR 51.8%, +3R (близко к break-even)
- SHORT: WR 45%, −32R (катастрофа все 3 года)
- Q4 положителен в 3 из 4 лет (Nov+Dec лучшие)
- Сезонные фильтры дают +49R на 3y (см. session note).

### 3. Strategy 1.1.1 — multi-TF nested OB+FVG

Создана с нуля по запросу пользователя — отдельная стратегия в `strategies/strategy_1_1_1.py`
+ `backtest_strategy_1_1_1.py`.

**Концепт:**
- OB-D (день) + FVG-4h в его time range и зоне → определяет «макро-зону».
- В этой макро-зоне ждём OB-1h + FVG-15m (аналог на низших ТФ).
- Entry = середина FVG-15m. SL = край OB-D zone. RR=1.0.

**Универсальные определения OB и FVG** зафиксированы пользователем как canon
(см. [[универсальные определения OB и FVG]]).

**Финал на 3 года BTC:**
- 69 сигналов, 66 closed, 35W/31L, WR 53.0%, PnL +4R
- LONG: 26 сделок, 57.7%, +4R
- SHORT: 40 сделок, 50%, +0R
- 2026: 4/4 wins (+4R)

Детали итеративных правок:
1. OB-1h fully inside intersection → overlap
2. FVG-4h c2 в cur day OB-D (строго)
3. Все валидные FVG-4h как отдельные ситуации (не первая)
4. Stop-условия только после первого касания зоны
5. Stop = 2 close ниже bottom (LONG) / 2 close выше top (SHORT) — без wick-based full fill
6. OB-1h ↔ FVG-4h через `zones_overlap` (включая случай когда FVG-4h внутри OB-1h)

### 4. Универсальные определения OB и FVG (canon)

Пользователь явно зафиксировал формулы как универсальные:

**OB (пара prev, cur):**
- LONG OB zone = `[min(prev.low, cur.low), prev.open]`
- SHORT OB zone = `[prev.open, max(prev.high, cur.high)]`

**FVG (3-свечной i-2, i-1, i):**
- LONG FVG (high(i-2) < low(i)): zone = `[high(i-2), low(i)]`
- SHORT FVG (low(i-2) > high(i)): zone = `[high(i), low(i-2)]`

Сохранено в [[универсальные определения OB и FVG]] и в agent memory.

## Файлы

**Новые:**
- `strategies/strategy_1_1_1.py` — Strategy 1.1.1 (multi-TF OB+FVG)
- `backtest_strategy_1_1_1.py`
- `backtest_vic_bos.py` — VIC BOS strategy
- `dump_ob_d_fvg_4h.py` — список всех валидных OB-D + FVG-4h пар
- `optimize_vic_entry_sl.py` — grid search VIC_EVOT параметров
- `optimize_vic_yearly.py` — yearly breakdown оптимизированных параметров

**Изменённые:**
- `strategies/vic_evot.py` — структурная инвалидация, OB-15m, 80% FVG entry
- `backtest_vic_evot.py` — CLOSE_EOD=False, SL_BUFFER_MULT, fix lookahead, multi-RR
- `tests/test_vic_evot.py` — обновлены под новую логику

**CSV результатов:**
- `signals/vic_evot_backtest_3y_*.csv` — VIC_EVOT 3y RR=1 / RR=2.2
- `signals/vic_bos_3y_*.csv` — VIC BOS 3y
- `signals/strategy_1_1_1_3y_RR1.csv` — Strategy 1.1.1 3y
- `signals/strategy_1_1_1_ob_d_fvg_4h.csv` — все 182 пары OB-D + FVG-4h

## Главные insights

1. **Lookahead в backtest** — серьёзный класс багов. Любой scan от open
   текущей 15m свечи (вместо close+15min) может «увидеть» данные внутри неё.
   Фикс изменил «магические» 60%+ WR на реальные 49-51%.

2. **Out-of-sample проверка обязательна.** 90-дневные пики WR 70-76%
   на VIC_EVOT с фильтром k≥2 на 3 годах развалились до 46.6% / −15R.
   3-х летняя статистика — минимум для валидного edge на крипте.

3. **VIC_EVOT в текущем виде — отрицательный edge** на BTC out-of-sample.
   LONG-only ≈ break-even. SHORT катастрофически убыточен. Optimization
   через grid search даёт максимум +13R за 3 года — маргинально.

4. **VIC BOS quadruple** — самый стабильный по годам (+37R, no catastrophe years).
   Заслуживает рассмотрения как отдельная стратегия.

5. **Strategy 1.1.1** — крайне селективная (69 сигналов за 3 года = ~1.5/месяц),
   100% WR на 4 свежих сигналах 2026, но статистики на 3 годах мало для
   уверенности. Multi-TF логика красивая, но требует точного совпадения
   условий — мало кейсов проходят воронку.

6. **Сезонность реальна.** На VIC BOS Q4 положителен 3/4 лет, фильтр
   «без слабых месяцев» (Feb/Mar/Jul/Aug/Oct) даёт +49R vs +12R baseline
   на 3 годах. Но сезонность стратегия-зависимая (VIC_EVOT любит май, BOS любит ноябрь).

## Что дальше

- Strategy 1.1.1 — продолжать итерации по правилам пользователя
- Возможно — внедрить в live (vic_scanner или новый scanner)
- VIC_EVOT — рассмотреть деактивацию live (отрицательный edge)
- VIC BOS quadruple — кандидат на live версию

## Связи

- [[vic_evot]] — обновлена логикой текущей сессии
- [[универсальные определения OB и FVG]] — canon для всех стратегий
- [[lookahead-bug-в-vic-evot-backtest]] — детали фикса
