---
tags: [strategy, i-rdrb, fvg, mitigation, btc, eth]
date: 2026-05-21
status: cross-asset-validated
related: [[что такое rdrb]], [[2026-05-19-rdrb-v2-babai-fractal-prediction]]
---

# i-RDRB + FVG с митигацией зоны (1h, BTC + ETH)

Cross-asset in-sample edge 2020-05-15 → 2026-05-20 (6 лет): **+269.2R за 6 лет** =
+44.9R/год портфельно. BTC: +150.8R (+25.1/год), ETH: +118.4R (+19.7/год).
Параметры универсальные для всех ассетов: entry=0.9, SL=0.2, RR=1.4.

**2026-05-21:** 2h-ТФ исключён из финала — под break-even (WR 39.9% vs BE 41.67%),
ΣR=−8.4R/3.4y. 90m исключён ещё раньше (entry-PnL отрицательный
несмотря на лучшую pivot-precision). Финал — **только 1h**.

**Cross-asset RR-проверка:** для BTC оптимум RR=1.4 (пик +150.8R), для ETH оптимум
смещён к RR=2.8 (пик +131.4R). Универсальный RR=1.4 даёт ETH 90% от своего пика;
per-asset подгонка (BTC=1.4, ETH=2.8) даёт всего +5% к портфелю — отвергнута как
overfit-risk.

## Сетап (5 свечей того же ТФ)

Индексация: `k` = trigger V1 RDRB.

1. **V1 RDRB** на тройке `(k-2, k-1, k)` — canon `[[что такое rdrb]]`:
   - LONG V1: `close(k-1) > high(k-2)` ∧ `low(k) < high(k-2)` ∧ `close(k) > max(open(k-2), close(k-2))`
   - SHORT V1: зеркально вокруг `low(k-2)`
   - Zone V1 = intersection фитилей anchor+trigger (узкая зона V1, не V2)

2. **Инверсия V1 на свече k+1** (4-я свеча):
   - V1 LONG пробит вниз  → **i-RDRB SHORT** (close(k+1) < zone_V1.bottom)
   - V1 SHORT пробит вверх → **i-RDRB LONG** (close(k+1) > zone_V1.top)

3. **FVG того же направления что i-RDRB** на свече k+2 (5-я свеча),
   тройка `(k, k+1, k+2)`:
   - LONG FVG: `high(k) < low(k+2)`
   - SHORT FVG: `low(k) > high(k+2)`

Termин «i-RDRB» из memory пользователя: «зона RDRB V1, пробитая 1h-close и
инвертированная (4-свечной элемент)». Здесь добавлен FVG-фильтр на 5-й свече
для отсева ложных инверсий.

## Зона интереса

Геометрия между крайним sweep-фитилём setup'а и low/high FVG-c2:

- **LONG i-RDRB**:
  - `zone_bottom = min(low #1..#4)` (низший экстремум первых 4 свечей setup'а)
  - `zone_top    = low(#5)` (low FVG c2 свечи)
- **SHORT i-RDRB**:
  - `zone_top    = max(high #1..#4)`
  - `zone_bottom = high(#5)`
- `width = top − bottom`

## Execution (entry/SL/TP, доли ширины зоны)

| Параметр | LONG | SHORT |
|---|---|---|
| Митигация | первое `low_1m ≤ zone_top` | первое `high_1m ≥ zone_bottom` |
| Entry | `zone_bottom + 0.9·width` | `zone_top − 0.9·width` |
| SL | `zone_bottom + 0.2·width` | `zone_top − 0.2·width` |
| Risk | `entry − SL` = `0.7·width` | `SL − entry` = `0.7·width` |
| **RR** | **1.4** | **1.4** |
| TP | `entry + 1.4·risk` | `entry − 1.4·risk` |

### Workflow

1. Setup детектируется на close FVG.c2 (свеча #5)
2. **Без таймстопа** ждём митигацию (touch zone_top для LONG / zone_bottom для SHORT)
3. После митигации активируется лимитный ордер на entry:
   - Если TP достигнут до entry → **no_entry** (cancel)
   - Иначе fill (low ≤ entry для LONG)
4. Дальше ждём первый из SL / TP (без таймстопа) → loss / win

## Параметры (фиксированы)

| Параметр | Значение |
|---|---|
| Ассеты | **BTCUSDT, ETHUSDT** |
| Период in-sample | 2020-05-15 → 2026-05-20 (6 лет) |
| ТФ | **1h только** (2h и 90m исключены) |
| RDRB zone version | V1 (intersection) |
| ENTRY_FRAC | 0.9 |
| SL_FRAC | 0.2 |
| RR | 1.4 |

## In-sample метрики (6 лет, BTC + ETH 1h)

| Ассет | Total | no_mit | no_entry | closed | WR% | ΣR | R/trade | R/год |
|---|---|---|---|---|---|---|---|---|
| BTC | 805 | 6 | 69 | 730 | **50.27%** | **+150.80R** | +0.207 | +25.1 |
| ETH | 811 | 7 | 56 | 748 | 48.26% | **+118.40R** | +0.158 | +19.7 |
| **Σ портфель** | **1616** | 13 | 125 | **1478** | **49.26%** | **+269.20R** | +0.182 | **+44.9** |

По направлениям (BTC):

| Direction | Closed | Wins | Losses | WR | ΣR | R/trade |
|---|---|---|---|---|---|---|
| LONG | 364 | 183 | 181 | 50.3% | +75.20R | +0.207 |
| SHORT | 366 | 184 | 182 | 50.3% | +75.60R | +0.207 |

По направлениям (ETH):

| Direction | Closed | Wins | Losses | WR | ΣR | R/trade |
|---|---|---|---|---|---|---|
| LONG | 381 | 176 | 205 | 46.2% | +41.40R | +0.109 |
| SHORT | 367 | 185 | 182 | **50.4%** | **+77.00R** | **+0.210** |

**Break-even WR при RR=1.4 = 41.67%.** Margin:
- BTC: **+8.60pp** (LONG/SHORT симметрично)
- ETH: **+6.59pp** (LONG слабее, SHORT сильнее — ETH-direction-bias)
- Σ портфель: **+7.59pp**

Частота: ~245 сделок/год портфельно (~123 на ассет) = ~4.7/неделю.

### Архив: почему 2h и 90m исключены (BTC 3.4y test)

| ТФ | closed | WR% | ΣR | Причина |
|---|---|---|---|---|
| 2h | 198 | 39.9% | −8.40R | Под break-even на RR=1.4 (нужен RR≈2.4 для +12.6R) |
| 90m | 246 | 43.9% | −30.00R | Парадокс: pivot-precision 73%, entry-PnL отрицательный |

Per-TF подгонка RR (1h=1.4, 2h=2.4) даёт +97.8R но отвергнута как overfit-risk.

### Архив: per-asset RR-оптимум (ETH cross-asset)

| Ассет | RR-оптимум | Пик ΣR | ΣR при RR=1.4 | Потеря от универсала |
|---|---|---|---|---|
| BTC | 1.4 | +150.80 | +150.80 | 0% |
| ETH | 2.8 | +131.40 | +118.40 | −10% (13R за 6 лет) |

Per-asset RR (BTC=1.4, ETH=2.8) даёт +282.20R vs универсальный +269.20R — прирост
всего +5%, отвергнут (две таблицы параметров = overfit-risk).

### По-TF оптимумы (для справки, НЕ используем)

Если допускать per-TF подгонку RR (отвергнуто пользователем как overfit-risk):

| ТФ | оптимум RR | ΣR (per-TF opt) |
|---|---|---|
| 1h | 1.4 | +85.20 |
| 2h | 2.4 | +12.60 |
| Σ | — | +97.80 (+28.8/год) |

Единый RR=1.4 проигрывает per-TF на ~6R/год, но устойчивее (одна таблица параметров).

## Геометрия — крайний пример (1h LONG, BTC, 2026-05-19)

5-candle window (UTC+3):

| Свеча | Время | OHLC | Роль |
|---|---|---|---|
| #1 anchor | 16:00 | O 76940 H 77049 L 76596 C 76873 | V1 SHORT якорь |
| #2 mid | 17:00 | O 76873 H 77024 L 76145 C 76392 | mid (пробитие < anchor.low) |
| #3 trigger | 18:00 | O 76392 H 76676 L 76338 C 76521 | trigger (close < anchor.low) |
| #4 inversion | 19:00 | O 76521 H 76911 L 76408 **C 76895** | close > V1 zone_top → инверсия |
| #5 FVG.c2 | 20:00 | O 76895 H 77015 L 76759 C 76857 | LONG FVG (high(#3)=76676 < low(#5)=76759) |

V1 SHORT zone = [76596.00, 76675.76] → пробитый close(#4)=76895.
i-RDRB direction = **LONG**.

Зона интереса: `[76144.71, 76759.39]` (width 614.68 USD / 0.80% цены).

Execution:
- Entry = 76697.92, SL = 76267.65, Risk = 430.27, **TP (RR=1.4) = 77300.30**
- Митигация 21:30 UTC+3 (через 30 мин после close #5)
- Цена дошла до entry → fill → продолжила вверх → пробила TP до возврата к SL → **WIN, +1.4R**

## Перспективные C2-фильтры (НЕ применены, кандидаты на потом)

### OB-4h confluence ⭐⭐⭐ (2026-05-21) — самый сильный кандидат

**Идея:** свечи setup'а #1..#5 на 1h проецируются на 1-2 соседних 4h-бара.
Если эти 4h-бары образуют **OB-pair того же направления что i-RDRB** —
это HTF-структурное подтверждение reversal'а.

```
# в окне [open(#1), close(#5) + 4h] на 4h ТФ
# найти OB-pair с direction == i_dir → confluence pass
```

**Эффект (BTC + ETH 1h, 6y):**

| | n closed | WR% | ΣR | R/trade | Δprec |
|---|---|---|---|---|---|
| Baseline | 1478 | 49.26 | +269.20 | +0.182 | — |
| **OB-4h match** ⭐ | **674** | **53.41** | +190.00 | **+0.282** | **+4.15pp** |
| no OB-4h | 804 | 45.77 (−3.49pp) | +79.20 | +0.099 | — |

**Cross-asset устойчивость рекордная** — spread BTC↔ETH всего **0.58pp** (WR
53.69% / 53.11%). Это лучший по стабильности из всех проверенных фильтров.

**Сравнение с Hull-78 1d (предыдущий лидер):**

| | Hull-78 1d direct | OB-4h match |
|---|---|---|
| n | 378 | 674 (+78%) |
| WR | 54.23% | 53.41% (−0.82pp) |
| ΣR | +114.00 | +190.00 (+67%) |
| R/trade | +0.302 | +0.282 (−7%) |

OB-4h побеждает Hull-1d по охвату и ΣR при сопоставимой precision.

**Помесячно** при применении: ~9.4 сделки/мес портфельно (2.2/неделю),
+2.64R/мес. Vs baseline 20.5/мес и +3.74R/мес: −54% trades, −29% R.

**Решение 2026-05-21:** НЕ применять пока. Возможный C2 на будущее.
Файлы: `research/vic_vadim/backtest_irdrb_fvg_ob4h_confluence.py`.

### Volume-фильтр: `rel_vol < 1.5` (2026-05-21)

**Идея:** отбрасывать setup'ы где Σvolume трёх центральных свечей (#2 mid +
#3 trigger + #4 inversion) превышает 1.5× от ожидаемого среднего по SMA20.

```
rel_vol = volume(#2) + volume(#3) + volume(#4)  /  (3 × SMA20(vol_per_1h_bar))
```

**Эффект на 6y in-sample:**

| Bucket rel_vol | n closed | WR% | ΣR | R/trade |
|---|---|---|---|---|
| <0.5 | 70 | 54.29% | +21.20 | +0.303 |
| 0.5–1.0 | 354 | 53.11% | **+97.20** | +0.275 |
| 1.0–1.5 | 184 | 49.46% | +34.40 | +0.187 |
| **>1.5** ❌ | 122 | **40.98%** | **−2.00** | −0.016 |

Чёткая **обратная монотонность**: тихие setup'ы (low rel_vol) — высокий edge;
шумные (rel_vol > 1.5) — убыточный хвост (50 wins / 72 losses на 122 сделках).

**Применение фильтра `rel_vol < 1.5`:**
- Closed: 730 → 608 (−122)
- WR: 50.27% → **51.97%** (+1.7pp)
- ΣR: +150.80 → **+152.80** (+2.0R)
- R/trade: +0.207 → **+0.251** (+21%)

**Интерпретация:** высокий объём = trend continuation / capitulation,
не reversal-setup. Тихие сетапы — структурный edge i-RDRB. По SMC-логике
sweep + reversal эффективнее в low-volume контексте (нет агрессивных
участников рынка).

**Решение 2026-05-21:** **НЕ применять пока**, сохранить как
перспективный C2. Проверить на cross-asset (ETH/SOL) и walk-forward
перед добавлением.

См. `research/vic_vadim/analyze_volume_filter.py`,
`signals/irdrb_fvg_volume_analysis.csv`.

### Отвергнутые C2 (negative results)

**HTF sweep confluence** (`backtest_irdrb_fvg_mit_c2.py`): одна из свечей
(#1, #2, #3) должна sweep FH/FL или LONG/SHORT FVG на ТФ {12h, 1d, 2d, 3d, W}
(direction-matching). Результат: 805 → 526 setup'ов (−34.7%),
WR 50.27% → 50.0%, ΣR +150.80 → +94.80, R/trade +0.207 → +0.200. **Не
улучшает edge.** Скорее всего i-RDRB сам по себе уже эмулирует sweep-логику
на 1h, HTF-confluence не добавляет нового сигнала.

**EVoT-entry 50% (BTC-specific)** (`backtest_irdrb_fvg_evot_entry.py`): новая
точка входа = 50% диапазона между EVoT maxV (3 свечи FVG #3..#5) и FVG-границей
(low(#5) для LONG, high(#5) для SHORT). На BTC: WR 52.82% (n=142), R/trade +0.268
(+29% от baseline), но ΣR упал до +38.00 (отсечено 66% bad_geometry). SHORT
особенно сильный (WR 64.44%, R/trade +0.547 на 45 trades). **На ETH провалился:**
WR 39.44% (под break-even), ΣR=−7.60, SHORT WR упал с 64.44% до 37.50%. Классический
BTC-specific overfit. Отвергнут 2026-05-21.

## Файлы

- Детектор + scan + backtest: `research/vic_vadim/`
  - `scan_ob_fvg_seq.py` — sanity-scan OB+FVG sequence (без i-RDRB-фильтра)
  - `check_fractal_after_setup.py` — pivot precision после OB+FVG offset+1
  - `check_irdrb_fvg.py` — i-RDRB+FVG предсказатель фрактала
  - `check_irdrb_mitigation.py` — % митигации зоны + распределение времени
  - `backtest_irdrb_fvg_zone.py` — entry-backtest БЕЗ ожидания митигации (v2)
  - `backtest_irdrb_fvg_mit_zone.py` — entry-backtest С ожиданием митигации (v3, текущий)
  - `backtest_irdrb_fvg_mit_rr_grid.py` — grid RR ∈ [1.0..3.0 step 0.1]
- `backtest_irdrb_fvg_mit_c2.py` — попытка HTF-sweep C2 (negative result)
- `analyze_volume_filter.py` — volume-фильтр (перспективный C2)
- Сигналы: `signals/irdrb_fvg_mit_zone_{1h,2h,90m}.csv`

## Что НЕ входит (открытые задачи на улучшение)

1. **90m ТФ исключён** — pivot-precision был лучшим (73.45%), но entry-сетап
   убыточный (−30R на 3.4y). Парадокс не разобран.
2. **Cross-asset** — только BTC. ETH/SOL не валидированы.
3. **Walk-forward / OOS** — нет. Всё in-sample на 3.4 года.
4. **HTF-контекст** — не применялся (Hull, EMA, ASVK Trend Line).
   2h находится под break-even — HTF-фильтр мог бы вытащить.
5. **Объёмный фильтр** — не применялся.
6. **2h SHORT неэффективен на любом RR ≤ 3.0** — кандидат на полное отключение
   2h SHORT (только 1h-обе + 2h LONG?).
7. **Direction-bias** — LONG WR 47.9% > SHORT 45.6%. Зеркальный bias BTC
   uptrend 2023-26. На bear-market может развернуться.

## Митигация — эмпирика (BTC 2023-26)

99% setup'ов получают митигацию рано или поздно:

| ТФ | % мит. | median | p25 | p75 | p95 | max |
|---|---|---|---|---|---|---|
| 1h | 98.8% | 1.5h | 0.3h | 8.0h | 86.9h | 2108h (88 дн) |
| 2h | 99.1% | 3.3h | 0.6h | 18.8h | 181h | 4611h (192 дн) |
| 90m | 98.6% | 2.8h | 0.5h | 10.8h | 82.6h | 2417h (101 дн) |

Median 1.5-3.3h → митигация обычно в первые 1-2 свечи того же ТФ.
В четверти случаев — моментально (та же 1m-свеча что и close #5).

## Связи

- [[что такое rdrb]] — canon RDRB V1/V2, определение зоны
- [[2026-05-19-rdrb-v2-babai-fractal-prediction]] — сессия, где появился термин i-RDRB
- [[zone-mitigation-filter-required]] — pitfall про обязательность mitigation-фильтра
- [[стратегия ViC Vadim 12h вариант 1]] — родственная стратегия (другая логика setup'а, но философия похожа)
