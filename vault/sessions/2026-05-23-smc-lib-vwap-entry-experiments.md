---
tags: [session, smc-lib, i-rdrb, fvg, vwap, asvk, vwap-entry]
date: 2026-05-23
status: done
related: [[i-rdrb fvg митигация зоны 1h btc eth]], [[что такое rdrb]], [[vadim 12 confluens asvk]]
---

# 2026-05-23 — smc-lib + VWAPs ASVK как entry/TP-фильтр

Сессия с нуля: построение независимой канонической библиотеки SMC-элементов
`~/smc-lib/` (вне traid-bot) + большой блок экспериментов по использованию
индикатора `VWAPs ASVK` (anchored VWAP) поверх стратегии i-RDRB+FVG.

## 1. ~/smc-lib — новая каноническая библиотека SMC

Создана независимая Python-библиотека для эталонных определений и кода SMC-элементов.

### Структура

```
~/smc-lib/
  README.md, candle.py (Candle dataclass + intervals_overlap), conftest.py
  elements/
    rdrb/      — 3-свечный RDRB
    i_rdrb/    — 4-свечный i-RDRB (reversal-only)
    fvg/       — Fair Value Gap (3 свечи)
  scripts/     — сканеры, бэктесты, генераторы графиков
```

Каждый элемент = папка `definition.md` + `code.py` + `tests/`. **23 теста проходят** (9 RDRB + 9 i-RDRB + 5 FVG).

Цель: формальные `detect_*(c1, c2, c3, ...)` функции, импортируемые отдельно от traid-bot. Будущие сессии должны проверять `~/smc-lib/elements/<name>/definition.md` как первый источник правды.

### Зафиксированная таксономия RDRB

После нескольких итераций согласована с пользователем:

**Направление паттерна определяется C2:**
- C2 bear → **SHORT** RDRB
- C2 bull → **LONG** RDRB
- C2 doji → не RDRB

**Зоны (для SHORT):**
- `POI = [max(C1.low, C3.body_top), C1.body_bottom]` — zone of interest
- `block = C1.lower_wick ∩ C3.upper_wick = [max(C1.low, C3.body_top), min(C1.body_bottom, C3.high)]`
- `liq = [block.top, C1.body_bottom]` если block.top < C1.body_bottom, иначе `∅`

Для LONG — зеркально вокруг C1.body_top.

**Варианты V1/V2:**
- V1 — `liq ≠ ∅` (block не покрывает POI целиком)
- V2 — `liq = ∅` (block == POI; вик C3 заходит до тела C1)

### Зафиксированный i-RDRB — reversal-only

i-RDRB ВСЕГДА разворачивает направление RDRB:
- SHORT RDRB + C4 bull AND `C4.close > block.top` → **LONG i-RDRB**
- LONG RDRB + C4 bear AND `C4.close < block.bottom` → **SHORT i-RDRB**
- Continuation-кейсы (C4 в ту же сторону что C2) — НЕ i-RDRB.

Эта правка была критична: первая версия принимала continuation как i-RDRB, что давало ложные сетапы. Пользователь поправил: "У нас получится должен long i-RDRB" для SHORT RDRB → i-RDRB всегда reversal.

### Эталоны

- RDRB SHORT V1: BTC 1h 2026-05-22 10:00-12:00 MSK (POI [77307.11, 77408.06])
- RDRB SHORT V1 (C1.low > C3.body_top): BTC 15m 2026-05-23 09:30-10:00 MSK
- i-RDRB LONG на SHORT RDRB: BTC 4h 2026-05-18 11:00-23:00 MSK
- SHORT FVG: BTC 4h 2026-05-21 07:00-15:00 MSK

## 2. Статистика паттернов BTC за 6 лет

Локальные 1m CSV `~/traid-bot/data/BTCUSDT_1m_vic_vadim.csv` догнан с Binance до 2026-05-23 18:25 UTC (скрипт `~/smc-lib/scripts/update_btc_1m_csv.py`).

### i-RDRB на 1h

| | Count |
|---|---:|
| LONG i-RDRB | 1274 |
| SHORT i-RDRB | 1273 |
| **Всего** | **2547** |

Распределение по подлежащим RDRB вариантам: V1 1151 / V2 1396 (V2 чаще). Симметрия long/short почти идеальная.

### i-RDRB + FVG-same на разных ТФ

| ТФ | Свечей | i-RDRB | i-RDRB+FVG | % FVG | LONG | SHORT |
|---|---:|---:|---:|---:|---:|---:|
| 1h | 53 105 | 2547 | **808** | 31.4% | 406 | 402 |
| 2h | 26 274 | 1222 | 376 | 30.8% | 188 | 188 |
| 4h | 13 141 | 571 | 203 | 35.6% | 101 | 102 |
| 6h | 8 761 | 336 | 117 | 34.8% | 53 | 64 |
| 8h | 6 571 | 303 | 93 | 30.7% | 49 | 44 |
| 12h | 4 381 | 177 | 76 | 42.9% | 38 | 38 |

Цифры близки к `[[i-rdrb-v1-fvg-f1-f2-f3-strategy-257-setups-wr72]]` baseline (~809 trades), подтверждает что новая таксономия совместима со старой по подсчёту.

## 3. Базовый бэктест RR=1 (без VWAP) — baseline

**Правила**: Entry = 0.5 RDRB block (limit, ждёт fill бессрочно).
SL = pattern_low (LONG) / pattern_high (SHORT) — экстремум всех 5 свечей C1..C5.
TP = RR 1:1 от entry. Симуляция на 1m данных.

**Результат BTC 1h 6y**:

| Side | WR | Trades | Net R |
|---|---:|---:|---:|
| LONG | 61.40% | 245W / 154L = 399 | **+91R** |
| SHORT | 52.63% | 210W / 189L = 399 | +21R |
| **TOTAL** | **57.02%** | 455W / 343L = 798 | **+112R** |

Fill rate 98.8% (798/808). Expectancy +0.140R/сделку. **Net +112R за 6 лет.**

LONG side значительно сильнее SHORT (8.77pp разница в WR) — bull-bias BTC.

## 4. VWAPs ASVK — что это

Pine-индикатор от автора ASVK (`/Users/vadim/Desktop/Без названия 3.rtf`). Рисует до 10 anchored VWAP'ов от выбранных дат.

Формула:
```
cumPV   = Σ(volume × close)  начиная с anchor
cumVol  = Σ(volume)          начиная с anchor
VWAP(t) = cumPV / cumVol
```

Реализация в Python: см. `~/smc-lib/scripts/backtest_i_rdrb_fvg_vwap_entry.py`.

## 5. Эксперимент A: "Вход по VWAP" (entry-стратегия)

**Правила**:
- Anchor VWAP: 5m свеча, содержащая pattern_low (LONG) или pattern_high (SHORT) на 1m уровне.
- Entry: первое 1m после C5 close где VWAP попадает в диапазон `[bar.low, bar.high]`.
- **Фильтр**: VWAP в момент fill не должен быть выше block.top (LONG) или ниже block.bottom (SHORT).
- SL = pattern_extreme. TP = RR 1:1 от entry.

**Эталон 2026-05-23**: pattern_low candle = 03:41 MSK 5m bucket `03:40`. VWAP entry triggered at **08:24 MSK** при VWAP=75490.48 (block.top=75500 ✓). Сделка ушла в LOSS (цена дошла до SL=75220).

**Результат на 808 паттернах**:

| Side | WR | Trades | Net R |
|---|---:|---:|---:|
| LONG | 62.50% | 20W / 12L = 32 | +8R |
| SHORT | 30.77% | 4W / 9L = 13 | −5R |
| **TOTAL** | 53.33% | 24W / 21L = 45 | **+3R** |

**Filter режет 94.4% паттернов** (763/808 отброшены). LONG WR (62.5%) ≈ baseline (61.4%) — edge не улучшен, только trades drastically reduced. SHORT провал (только 13 сделок, статистически шумно).

**Вывод**: фильтр "VWAP ≤ block.top" слишком жёсткий, не даёт значимого улучшения.

## 6. Эксперимент B: VWAP-TP (mean reversion)

Тестировали 3 варианта с фиксированным entry (0.5 block) и SL = pattern_extreme,
но динамическим TP = текущее значение VWAP:

| Variant (anchor для VWAP) | Trades | WR% | ΣR | R/tr | LONG ΣR | SHORT ΣR |
|---|---:|---:|---:|---:|---:|---:|
| **A baseline RR=1** (no VWAP) | 780 | **56.67** | **+104.0** | +0.133 | +86.0 | +18.0 |
| B vwap_same (anchor = SL extreme) | 779 | 54.94 | +61.6 | +0.079 | +35.2 | +26.4 |
| C vwap_opposite (anchor = opp extreme) | 779 | 53.15 | +80.8 | +0.104 | +50.2 | +30.6 |
| D vwap_c5 (anchor = C5 open) | 779 | 52.50 | +95.0 | +0.122 | +61.0 | **+34.0** |

**Все VWAP-TP варианты ХУЖЕ baseline по total ΣR.** Динамический TP цепляется раньше → меньше R за win, при той же доле SL hits.

**Однако SHORT-сторона ОЖИВАЕТ с VWAP-TP**: vwap_c5 даёт R-S +34R против baseline +18R (+16R = +88%). LONG ухудшается (R-L +61R vs +86R).

## 7. Эксперимент C: VWAP как фильтр входа

Baseline с RR=1, но добавлен фильтр по позиции VWAP в момент C5 close:

| Filter (anchor=pattern_low long/high short) | n | WR% | ΣR | R/tr |
|---|---:|---:|---:|---:|
| **BASELINE** (no filter) | 780 | 56.67 | **+104.0** | +0.133 |
| F1 VWAP в block | 56 | 55.36 | +6.0 | +0.107 |
| F2 VWAP выше block (long) / ниже (short) | 671 | **57.23** | +97.0 | +0.145 |
| F3 VWAP ниже block (long) / выше (short) — anti | 53 | 50.94 | +1.0 | +0.019 |
| F4 VWAP > entry (long) / < entry (short) | 710 | 57.18 | +102.0 | +0.144 |
| F5 VWAP < entry (long) / > entry (short) | 70 | 51.43 | +2.0 | +0.029 |

**F2/F4 дают маржинальный +0.5pp WR при потере 2-7R общего.** F3/F5 — слабые подмножества (anti-edge), их можно исключать → +1-2R чистого выигрыша.

Slope-filter (направление наклона VWAP за период anchor → C5) бесполезен в текущей форме: anchor на pattern_extreme гарантирует slope в сторону паттерна для 100% сетапов.

## 8. Вывод по VWAPs

**VWAP не даёт существенного edge поверх baseline i-RDRB+FVG**:
- TP-варианты — хуже на total R (фиксированный RR=1 побеждает)
- Filter-варианты — маржинальные (+0.5pp WR ценой -5R total)
- Entry-strict — экстремально режет samples, даёт ту же WR что baseline

Единственное направление, где VWAP помогает структурно: **SHORT side с TP по VWAP** (+16R vs baseline). Возможный hybrid: LONG = RR=1, SHORT = VWAP-c5 TP. Не тестировал композитно, но цифры намекают.

## 9. Где искать реальный edge

Из памяти `[[i-rdrb-v1-pattern]]` и `[[i-rdrb-v1-fvg-f1-f2-f3-strategy-257-setups-wr72]]`:
- **HTF OB match** (4h-12h) — +4.15pp WR на baseline
- **R/ATR(20) ∈ [0.55, 1.03]** — после F1∪F2 даёт **257 trades, 71.6% WR, +111R, Sharpe 3.13**
- Сильнее любого VWAP-варианта на порядок.

Дальнейшее развитие smc-lib должно идти к этим элементам, а не к VWAP:
- `elements/order_block/` — bullish/bearish OB на разных ТФ
- `elements/atr/` — ATR(N)
- Композитный детектор HTF context + i-RDRB + FVG

## 10. Артефакты

### Скрипты (`~/smc-lib/scripts/`)
- `update_btc_1m_csv.py` — догон 1m CSV с Binance
- `count_i_rdrb_btc_1h_6y.py` — счёт паттернов на 1h за 6y
- `count_i_rdrb_fvg_btc_1h_6y.py` — то же + FVG-same
- `count_i_rdrb_fvg_multi_tf.py` — сводка по ТФ {2h-12h}
- `find_i_rdrb_examples.py` / `find_i_rdrb_fvg_examples.py` — поиск свежих примеров
- `find_i_rdrb_fvg_local.py` — то же на локальном CSV (полная история)
- `show_latest_long_trades.py` — детализация последних N сделок
- `backtest_i_rdrb_fvg_rr1.py` — baseline RR=1
- `backtest_i_rdrb_fvg_vwap_entry.py` — VWAP-entry strict
- `sweep_vwap_strategies.py` — A/B/C/D TP-варианты
- `sweep_vwap_filters.py` — F1-F10 filter-варианты
- `verify_vwap_entry_2026_05_23.py` — sanity check на эталоне
- `plot_vwap_entry_examples.py` — генерация трёх графиков

### Графики (`~/Desktop/i-rdrb-charts/`)
- `vwap_entry_2026-05-23_long_loss.png` — эталон 2026-05-23 LONG (LOSS)
- `vwap_entry_2025-07-23_long_win.png` — WIN LONG из истории
- `vwap_entry_2026-03-03_short_win.png` — WIN SHORT из истории

### Memory pointers
- `[[smc-lib-location]]` — где живёт библиотека
- `[[btc-data-1m-csv]]` — локальные 1m данные
- `[[charts-output-location]]` — куда складывать PNG

## Связи

- `[[i-rdrb fvg митигация зоны 1h btc eth]]` — основная стратегия с теми же 5-свечными паттернами, но с zone-mitigation entry (другой entry-механизм, не 0.5 block)
- `[[i-rdrb-v1-fvg-f1-f2-f3-strategy-257-setups-wr72]]` — фильтрованная версия с +111R
- `[[i-rdrb-v1-fvg-f1-f2-f4-strategy-401-setups-wr71]]` — альтернатива по F4
- `[[vadim 12 confluens asvk]]` — confluence-score (parallel research)
- `[[2026-05-21-i-rdrb-confluens-asvk-research]]` — предыдущая сессия с ASVK-индикаторами
- `[[что такое rdrb]] (vault)` — другая RDRB-конвенция (для live-бота)
