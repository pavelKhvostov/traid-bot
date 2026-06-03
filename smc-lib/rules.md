# Правила — справочник по элементам

> **Назначение.** Общие правила, характеризующие особые условия и закономерности рынка. Применимы ко всем SMC-элементам и паттернам (не специфичны для конкретного элемента).

---

## Правило 1 — Закрепление цены за уровнем

**Определение.** Закрепление цены — ситуация, при которой котировки пробивают важный уровень (поддержки или сопротивления) и остаются за его пределами.

**Условия закрепления:**

- **Пробойная свеча** — должна пробить уровень и уверенно закрыться за его пределами. Желательно с большим телом, а не длинной тенью (тень = отвергнутый пробой).
- **Подтверждающая свеча** — как минимум одна следующая свеча, которая также закрывается за пробитым уровнем. Доказывает, что цена не вернулась обратно (т. е. пробой не ложный).

**Минимум для закрепления** = 2 последовательные свечи с закрытием за уровнем (пробойная + подтверждающая).

---

## Правило 2 — Заполнение зоны интереса (mitigation)

**Определение.** Заполнение (mitigation) зоны интереса — изменение её актуального состояния при взаимодействии с ценой: частичное сжатие, полное потребление или одноразовая отработка точечного уровня. Конкретная модель зависит от типа зоны.

### Модель 1 — Wick-fill (постепенное сжатие)

При каждом касании wick'ом зона сжимается до точки максимального проникновения. Кумулятивно — каждое последующее касание сжимает ещё больше.

- **LONG zone** `[zone_lo, zone_hi]` (support снизу): при `low ≤ zone_hi`
  - `low > zone_lo` → зона сжимается до `[zone_lo, low]`
  - `low ≤ zone_lo` → **CONSUMED**
- **SHORT zone** `[zone_lo, zone_hi]` (resistance сверху): при `high ≥ zone_lo`
  - `high < zone_hi` → зона сжимается до `[high, zone_hi]`
  - `high ≥ zone_hi` → **CONSUMED**

**Семантика.** Institutional zones (OB / FVG / RDRB / block_orders) могут тестироваться многократно — каждое касание потребляет часть untraded liquidity.

### Модель 2 — First-touch (одноразовое потребление)

Первое касание wick'ом любого уровня зоны → зона полностью **CONSUMED** (без постепенного сжатия).

**Семантика.** Одноразовые rejection-маркеры (RB, liquidity-marker ob_liq) — функция «отработана» при первом контакте, далее зона не actionable.

### Модель 3 — Sweep (касание точечного level)

Wick касается или проходит за level → **CONSUMED**.

- **Fractal:** FH swept = `high > level`; FL swept = `low < level`.
- **Marubozu (open level):** bull (`open == low`) — `low ≤ open`; bear (`open == high`) — `high ≥ open`.
- **VWAP (anchored):** SHORT (от FH) — `high(t) > VWAP(t)`; LONG (от FL) — `low(t) < VWAP(t)`. Уровень `VWAP(t)` time-varying (дрейфует с накоплением volume).

**Семантика.** Точечная liquidity (fractal stops) или imbalance-target (marubozu open) или equilibrium-line (anchored VWAP) — однократный stop hunt / тест уровня.

### Привязка моделей к элементам

| Группа | Модель |
|---|---|
| OB, block_orders, FVG, i-FVG, RDRB POI, i-RDRB POI | wick-fill |
| RB, ob_liq | first-touch |
| Fractal (level), Marubozu (open), **VWAP (anchored)** | sweep |

Полная сводная таблица и геометрия зон — [`zone_of_interest.md`](./zone_of_interest.md), раздел «Mitigation».

---

## Правило 3 — VC (Volume Confirmation)

**Принцип.** HTF-зона (canonically OB) считается «подтверждённой» (volume-confirmed), если её направлению **сопутствует displacement** (FVG того же направления). Displacement может быть выражен двумя способами: **spatial** (FVG внутри HTF OB) или **temporal** (FVG сразу после OB на том же TF).

> ⚠️ **VC — предикат, не зона.** Сама зона остаётся за HTF-элементом. VC лишь сигнализирует, что HTF-зона валидирована displacement'ом.
>
> ⚠️ **Vestigial name.** Объём не используется напрямую — расчёт чисто геометрический (FVG = displacement-signature).

Canon-код: `vc/definition.md`, `vc/code.py` (API: `has_vc(ob, fvg) → bool`).

> **Зональная реализация** этой концепции — элемент `ob_vc` (см. `elements/ob_vc/definition.md`). `vc/` = предикат (bool), `ob_vc/` = зона как самостоятельный элемент библиотеки с расширенной HTF/LTF-таблицей (3D/2D ↔ 12h, D/12h ↔ 4h/6h, 4h/6h ↔ 1h/90m/2h, 1h/2h ↔ 15m/20m) и **partial overlap** условием вместо строгого containment.

### Три канонических варианта

| Variant | HTF (OB) | LTF (FVG) | Геометрия | Direction |
|---|---|---|---|---|
| **1** *(spatial)* | 1h, 2h | 15m, 20m | `FVG.zone ⊆ OB.zone` (containment) | aligned |
| **2** *(spatial)* | 4h, 6h | 1h, 90m, 2h | `FVG.zone ⊆ OB.zone` (containment) | aligned |
| **3** *(temporal)* | 1h, 2h | **same TF as OB** (1h, 2h) | `FVG.c1 = OB.cur+1` (sequential, **НЕ** требует containment) | aligned |

**Direction**: во всех вариантах — **aligned** (`OB.direction == FVG.direction`).

### Семантика

- **Variants 1, 2 (spatial containment)** — внутри HTF OB лежит LTF FVG того же направления. Институциональная зона подтверждена displacement'ом «изнутри».
- **Variant 3 (temporal sequence)** — OB сформировалась, на следующей же свече начинается FVG того же направления (FVG обычно ВНЕ OB.zone — displacement выводит цену из зоны). OB сработала как launchpad → импульс → gap.

### Что VC даёт

- Boolean predicate над HTF-зоной (актуально для всех вариантов).
- Усиливает приоритет HTF OB в ranking / выборе entry (см. [[Правило 4]]).
- Используется в [[Правило 5]] как ключевое подтверждение в основной стратегии ASVK.

### Mitigation

VC сам не mitigated — это предикат. Mitigated может быть HTF-зона (по [[Правило 2]]) или LTF FVG обеспечивающая VC (wick-fill); после consumption LTF FVG предикат снимается (если нет других обеспечивающих FVG).

---

## Правило 4 — LTF FVG усиливает значимость HTF OB — *в разработке*

Принцип: присутствие LTF FVG поднимает HTF OB в приоритете. Отношение к Правилу 3 (является ли консеквентом VC или более широким принципом) — открыто.

---

## Правило 5 — Основная стратегия ASVK (VC внутри HTF-зоны интереса)

**Принцип.** Ждать возврата цены в HTF-зону интереса → получить там подтверждение объёма (VC, см. [[Правило 3]]) того же направления, что HTF-движение → войти в направлении HTF-движения.

**Общая логика (на примере LONG, симметрично для SHORT):**

1. HTF-движение **LONG** сформировало HTF-зону интереса (OB / block_orders / RDRB POI / …).
2. Цена **спустилась** обратно в эту зону.
3. Внутри зоны на LTF появилось **LONG-подтверждение объёма** (VC: LTF LONG FVG ⊆ HTF LONG ZoI, см. [[Правило 3]]).
4. **Entry LONG** по VC-формации.
5. Continuation: цена движется LONG → отрабатываем LONG-сделку.

| Направление | HTF-движение | HTF-зона интереса | LTF VC | Entry |
|---|---|---|---|---|
| **LONG** | HTF-восходящее | LONG ZoI (e.g. LONG OB) | LONG FVG ⊆ ZoI | LONG |
| **SHORT** | HTF-нисходящее | SHORT ZoI (e.g. SHORT OB) | SHORT FVG ⊆ ZoI | SHORT |

**Композиция правил.** Правило 5 опирается на:
- [[Правило 2]] — возврат цены в зону = частичная mitigation (wick-fill / first-touch). До CONSUMED — зона actionable.
- [[Правило 3]] — VC даёт подтверждение, что зона валидирована LTF-displacement'ом.
- [[Правило 4]] — VC-наличие усиливает приоритет HTF-зоны → выбор именно этой ZoI для entry.

### Пример: стратегия 1.1.1

Стратегия **1.1.1** — одна из инстанциаций Правила 5 (по классификации ASVK). Содержит общую логику выше для LONG-сценария.

Подробности конкретных инстанциаций (1.1.1, 1.1.2, ...) — в стратегических заметках, не в этом справочнике.

---

## Правило 6 — Построение VWAPs ASVK (anchored, dynamic от D-фрактала)

**Принцип.** Anchored VWAP от D-фрактала строится с **динамическим** anchor'ом в окне свечи `i+1` (бар, следующий за пивотом). Anchor пересчитывается с шагом **15m**, при появлении каждой новой свечи выбирается позиция, дающая лучший результат.

### Параметры

| Параметр | Значение |
|---|---|
| **Базовый объект** | Подтверждённый D-фрактал (Williams N=2) |
| **Диапазон anchor** | Внутри D-свечи `i+1` (бар сразу после пивота). Размер = 24h |
| **Шаг сетки** | 15m → **96 candidate positions** (0h, +0:15, +0:30, …, +23:45) |
| **Re-evaluation cadence** | На закрытии **каждой новой свечи** (LTF cascade или 15m baseline) |
| **Критерий «лучше»** | **Max composite effectiveness** (см. `~/smc-lib/indicators/vwap_effectiveness.py`) |
| **Anchor drift** | Anchor может перемещаться в пределах окна `i+1` от bar к bar, **сохраняя только финальный выбор для текущего момента** |

### Алгоритм

```
для D-фрактала f:
  anchor_window = [f.pivot_close, f.pivot_close + 24h]
  candidates = [anchor_window.start + k * 15m  for k in 0..95]   # 96 anchor-кандидатов

  на закрытии каждой новой свечи (любого TF cascade):
    for c in candidates (только те, у которых c ≤ now):
      compute composite_c = composite_effectiveness(c, LTF cascade)
    current_anchor = argmax_c (composite_c)
    use VWAP(current_anchor) как актуальный уровень
```

### Семантика

- **Раннее время фрактала** (мало новых баров после `i+1`): кандидаты совпадают, выбор почти произвольный — может прыгать.
- **Через 1-3 дня** после `i+1`: cascade накапливает interactions → composite дифференцируется → выбор стабилизируется.
- **Долгосрочно**: anchor «фиксируется» в определённой 15m-позиции, дающей максимум respect.

Это **forward-adaptive** методология: индикатор не lookahead-биасный (для t = текущий момент использует только данные ≤ t), но сам anchor выбирается оптимально под наблюдаемую историю.

### Расхождение с Method 1 (close pivot)

| Метрика | M1 (close pivot, фикс.) | Правило 6 (динамический) |
|---|---|---|
| Среднее composite на 100 D-фракталах | 0.528 | до 0.552 (M2_best ex-post) |
| Детерминизм | да | нет (anchor drift) |
| Простота расчёта | один anchor | 96 кандидатов, переоценка |
| Применимость | сразу | требует bar-by-bar recalc |

Правило 6 — **canonical способ** построения VWAPs ASVK. M1 — упрощённая baseline.

### Cascade для composite

Default: **1h, 2h, 4h, 6h, 8h, 12h** (6 LTF, все ниже D anchor TF).

### Артефакты

- Code: `~/smc-lib/indicators/vwap_anchored.py` (statika, базовая формула)
- Effectiveness scoring: `~/smc-lib/indicators/vwap_effectiveness.py`
- Test scripts: `~/smc-lib/scripts/vwap_strategy_d_50_anchors.py`, `vwap_compare_methods_d_100.py`
- Реализация dynamic-anchor: **TBD** (расширение vwap_anchored.py для bar-by-bar selection из 96 кандидатов)

---

## Правило 7 — TrendLine ASVK: канонические length 78 и 200

**Принцип.** При использовании TrendLine ASVK (Hull MA) везде в библиотеке/проектах **по умолчанию применяются две длины: 78 и 200**. Любые другие значения требуют явного обоснования.

### Параметры

| Параметр | Значение | Применение |
|---|---|---|
| **Mode** | `Hma` (Hull MA) | default; `Ehma`/`Thma` — только если явно указано |
| **Length 1** | **78** | основной TrendLine (= 49 × 1.6 в Pine-нотации) |
| **Length 2** | **200** | медленный TrendLine |
| **Source** | `close` | default |
| **Value semantics** | **LIVE** (с close предыдущего бара) | strict-causal: HMA[i] = значение, отображаемое на чарте в момент формирования бара i до его close |
| **Таймфреймы (типовые)** | 12h, D | other TF допустимы, но эталон — эти |

### Семантика LIVE

> Значение индикатора на pivot bar `i` = значение, вычисленное при close предыдущего бара (i-1). Это то значение, которое отображается на чарте во время формирования бара `i`, до его close. Strict-causal — нет lookahead-биаса.

### Триггеры взаимодействия

| Событие | Условие | Direction |
|---|---|---|
| **Sweep level** | wick(bar) пересекает HMA(i) И close(bar) обратно за уровень | FH ↔ SHORT wick сверху; FL ↔ LONG wick снизу |
| **Cross** | close меняет сторону HMA относительно предыдущего бара | direction = новая сторона |

### Происхождение

Эти параметры приняты в проекте **Pred-12h** (см. [`projects/pred12h-fractal-three-candles.md`](./projects/pred12h-fractal-three-candles.md)):
- **С5** = sweep HMA-78 на (12h ∪ D), LIVE → P(W) **67.0%**, 5 imp
- **С6** = sweep HMA-200 на D, LIVE → P(W) **81.6%**, 1 imp

### Артефакты

- Code: `~/smc-lib/indicators/trend_line_asvk.py`
  - `trend_line_hma_78(closes)` — helper для length=78
  - `trend_line_hma_200(closes)` — helper для length=200
- Pine reference: `~/traid-bot/research/asvk_trend_line/plot_asvk_trend_line.py`

### Прочее

При появлении нового кандидата длины (например 100 или 50) сначала проверяем edge vs canon 78/200 на baseline; принимается только при существенном lift и не как замена, а как дополнительный slot.

---

## Правило 8 — Движение цены

**Принцип.** Цена движется как **магнит между двумя классами зон** — скоплениями ликвидности и ценовыми неэффективностями. Крупный капитал использует эти зоны для исполнения заявок, формируя базовую механику движения любого финансового рынка.

### Два класса притяжения

| Класс | Метафора | Что это | Канон-элементы |
|---|---|---|---|
| **Ликвидность** | ⛽ Топливо | Скопления ордеров (стопы розницы, лимитки) — крупный игрок «собирает» их для набора позиции | `fractal`, `rb`, `ob_liq.liq_zone` |
| **Неэффективность** | 🧲 Магнит | Дисбаланс buyers/sellers — резкое импульсное движение, рынок не успел сформировать справедливую цену | `fvg`, `i_fvg`, `marubozu` (тело) |

> Третий класс — **блок** (OB, RDRB, block_orders, ob_liq.zone) — это **точки исполнения** institutional orders («наторгованный блок»), а не магниты. См. [[memory:zone-class-liquidity-inefficiency-block|таксономия классов]].

> ⚠ Историческое название этого класса — **efficiency** (до 2026-05-29). Переименован в **«блок»** для согласованности с пользовательским термином «блок наторгованный» (maxV ASVK).

### Цикл движения цены (3 фазы)

```
Phase 1: Сбор ликвидности
  ↓ цена идёт к liquidity-зоне (стопам/лимиткам)
  ↓ wick-импульс снимает ордера
  ↓ крупный игрок набирает позицию против розницы

Phase 2: Заполнение неэффективности
  ↓ после snap-back цена возвращается к ближайшему inefficiency-магниту
  ↓ FVG/i-FVG/marubozu заполняется → справедливая цена восстановлена
  ↓ имбаланс закрыт

Phase 3: Поход к новой цели
  ↓ после mitigation отбрасывается от блок-зоны (OB/RDRB/block_orders)
  ↓ direction: к следующей liquidity-цели (FH/FL противоположной стороны)
  ↓ цикл повторяется на новом уровне
```

### Семантика для зон (как использовать в анализе)

| Тип взаимодействия | Что значит |
|---|---|
| **Sweep liquidity** (Phase 1) | Wick через fractal/rb/ob_liq.liq_zone — крупный игрок «съел» стопы. После sweep — потенциальный reversal |
| **Fill inefficiency** (Phase 2) | Wick-fill FVG/i-FVG или sweep marubozu open — закрытие имбаланса. Логичный intermediate-target |
| **React on блок** (Phase 3) | Touch OB/RDRB/block_orders с continuation — institutional order сработал, отскок в направлении HTF-тренда |

### Применение

1. **Идентифицируй классы**: на каждой зоне near price — это liquidity / inefficiency / блок?
2. **Найди ближайшую liquidity** (магнит для Phase 1) — куда цена «пойдёт за стопами»
3. **Найди ближайшую inefficiency** (магнит для Phase 2) — куда возвратится после sweep
4. **Найди блок-уровень** — где institutional орден будет исполнен, точка реакции
5. **Цикл прогноз**: liquidity → inefficiency → блок → next liquidity

### Композиция с другими правилами

| Правило | Связь |
|---|---|
| [[Правило 1]] (закрепление) | Phase 3 завершается closing-confirmation за блок-уровнем |
| [[Правило 2]] (mitigation) | Inefficiency-зоны mitigated через wick-fill; liquidity — first-touch / sweep |
| [[Правило 5]] (стратегия ASVK) | Phase 3 (reaction на блок-зоне) + VC = entry-сигнал |
| [[Правило 6]] (VWAPs) | Inefficiency-уровень часто совпадает с эффективным VWAP — confluence-магнит |
| [[Правило 7]] (TrendLine) | HMA-cross определяет direction Phase 3 (к какой следующей liquidity-цели) |

### Связи (memories)

- [[memory:feedback-untraded-area-is-magnet]] — fundamental SMC принцип: непроторгованная область притягивает цену
- [[memory:zone-class-liquidity-inefficiency-block]] — таксономия трёх классов
- [[memory:feedback-fractal-liquidity-strength-and-sweep]] — сила liquidity = TF × возраст × cluster; HTF sweep «проглатывает» LTF

### Practical-чек для каждой зоны

При анализе зоны спрашивай:
1. К какому классу относится? (liquidity / inefficiency / блок)
2. Mitigated или actionable? (Правило 2)
3. На каком TF? (HTF доминирует)
4. Расположена `above` / `inside` / `below` относительно цены?
5. Если liquidity или inefficiency → это **магнит**
6. Если блок → это **точка реакции**, не магнит

> **Главное**: цена не двигается «случайно», и не только «по трендам/уровням». Она **охотится за топливом** (liquidity) и **заполняет пустоты** (inefficiency). Блок-зоны — это места, где institutional капитал ставит/исполняет ордера.

---

## Правило 9 — Сложные вычисления выносятся на отдельный PC

**Принцип.** Интерактивное общение и lightweight-вычисления выполняются на MacBook Air M5 (текущая рабочая машина). **Сложные / тяжёлые / GPU-нагруженные вычислительные процессы** упаковываются в архив и переносятся на отдельный PC для исполнения. Результаты возвращаются обратно для анализа.

### Hardware

| Машина | Назначение | Спецификация |
|---|---|---|
| **MacBook Air M5** | Интерактив, разработка кода, lightweight inference, plots, экспертные заключения | M5 SoC, mac OS |
| **PC1 (Windows)** | Heavy compute, GPU-ML (топовая GPU), large dataset processing | Ryzen 7 7700 OEM (8C/16T), RAM 32 GB, **GPU RTX 5070 Ti**, Windows 11 |
| **PC2 (Windows)** | Heavy compute, parallel CPU (больше потоков), walk-forward suites, grid-search | **i5-14600KF (14C/20T)**, RAM 32 GB DDR5, GPU RTX 4070, Windows 11 |

### Выбор PC под задачу

| Задача | Лучше на | Почему |
|---|---|---|
| **GPU-heavy ML** (LSTM/Transformer/deep RL) | **PC1** (RTX 5070 Ti) | Топовая GPU 5000-серии |
| **Grid-search / hyperparameter sweep** | **PC2** (20 threads) | На 4 потока больше |
| **Walk-forward suites** (multiprocessing) | **PC2** | 14 cores vs 8 у PC1 |
| **Generic ML training** (LightGBM, XGBoost) | Любой | Похожая производительность |

При формировании архива указывать в README **на каком PC рекомендуется запускать** (или допустимы оба).

### Что выносить на PC

| Категория | Примеры | Обоснование |
|---|---|---|
| **GPU-ML** | LSTM/Transformer на 1m OHLCV, deep sequence models, image-based pattern recognition | RTX 5070 Ti — основная GPU-мощность |
| **Heavy training** | LightGBM/XGBoost на >1M строк × десятки фичей, hyperparameter sweep, NGBoost | 32 GB RAM + Ryzen 8C/16T параллелизация |
| **Walk-forward suites** | Любой `walk_forward(...)` на годах данных с несколькими cadence/window | На M5 один прогон cadence = ~11 мин, suite из 10+ конфигов = часы |
| **Symbol-scale processing** | Полный 1m re-labelling, generation `btc_full.csv`-аналогов для других assets, multi-symbol sweeps | RAM + CPU-параллелизация |
| **Backtests** | Полный бэктест стратегии за 6 лет с зонами, экзекуцией, slippage | Параллелизуется по cut-off |

### Что НЕ выносить на PC (остаётся на Mac)

- Экспертные заключения (`zones_opinion.py`, `expert/opinion.py`, `expert/chart.py`) — секунды на M5
- Plot-скрипты для одиночных графиков
- Inference на одной точке времени (cli.py)
- Любая интерактивная работа

### ⚡ Параллелизм и hardware utilization (КРИТИЧНО, добавлено 2026-05-29)

**Цель:** **CPU usage 80-90%** на PC во время вычислений. Если <30% — компьютер недогружен, нужно перенастроить параллелизм. Принцип: «PC должен дымиться» во время heavy compute.

#### Базовые требования к коду для PC

Каждый PC-скрипт ДОЛЖЕН использовать all available threads через сочетание:

| Уровень параллелизма | Механизм | Применение |
|---|---|---|
| **Inner (intra-model)** | библиотечный `n_jobs` | LightGBM, XGBoost — built-in parallel training |
| **Outer (independent tasks)** | `joblib.Parallel` (backend=threading или loky) | Параллельные retrains / horizons / cut-offs / hyperparam configs |
| **Vectorization** | numpy/pandas вместо Python loops | Feature engineering |

#### Threading config по PC (default рекомендации)

| PC | Total threads | Outer n_jobs × Inner n_jobs | Sum | % loading target |
|---|---|---|---|---|
| **PC1** (Ryzen 7 7700, 16T) | 16 | 4 × 4 = 16 (или 8 × 2 = 16) | 16 | 90-100% |
| **PC2** (i5-14600KF, 20T) | 20 | 6 × 3 = 18 (или 4 × 5 = 20) | 18-20 | 90% |

Outer × Inner НЕ должно превышать total threads (oversubscription = context switching = замедление).

#### Выбор библиотек по параллелизму

| Библиотека | Параллелизм | Использовать когда |
|---|---|---|
| **LightGBM** (`n_jobs=-1`) | ✅ excellent, OpenMP, all cores | **Default** для tabular ML |
| **XGBoost** (`n_jobs=-1`) | ✅ good, OpenMP | Альтернатива LightGBM |
| **sklearn `HistGradientBoostingRegressor`** | ⚠ ограниченный OpenMP, реально использует <50% cores | Только если нет LightGBM (Mac без libomp) |
| **sklearn `RandomForestClassifier`** (`n_jobs=-1`) | ✅ embarrassingly parallel | Хорошо параллелится |
| **PyTorch** | GPU родной, CPU через `torch.set_num_threads()` | GPU-heavy |
| Чистый Python loops | ❌ single-thread | НЕ использовать для heavy compute |

#### Workflow self-check перед отправкой архива

Перед `zip` финального архива убедиться:

- [ ] **Inner n_jobs** настроен в библиотечных моделях (не дефолт `n_jobs=1`)
- [ ] **Outer parallelism** через `joblib.Parallel` для независимых задач (retrains × horizons, cut-offs, configs)
- [ ] **Total threads** = Outer × Inner ≈ target_PC_threads (см. таблицу выше)
- [ ] **Backend joblib** = `threading` если задачи делят numpy arrays (LightGBM/XGBoost releaseGIL), `loky` если нужны отдельные процессы
- [ ] **README** упоминает ожидаемую загрузку (например «CPU 85-95% на PC2»)
- [ ] **GPU задействован** если задача GPU-friendly и есть GPU pipeline

#### Pitfalls (горел сегодня 2026-05-29)

| Pitfall | Симптом | Решение |
|---|---|---|
| sklearn HGBR на дефолтных параметрах | CPU <20% на 20-thread PC, runtime ×5-10 от ожидания | Заменить на LightGBM `n_jobs=-1` |
| Sequential horizons/configs | CPU плохо нагружен даже с LightGBM | `joblib.Parallel` по независимым задачам |
| Oversubscription (Outer × Inner > total) | CPU 100% но реально медленнее | Снизить Outer×Inner ≤ total_threads |
| Default `n_jobs=1` библиотек | Один поток на всё | Явно `n_jobs=-1` или конкретное число |
| `joblib backend="loky"` с большими numpy arrays | Pickling overhead | `backend="threading"` для shared-memory задач |

#### Цикл оптимизации

```
1. Запустить PC-задачу
2. Проверить Task Manager (Windows) или htop:
   - CPU <30%       → плохо, оптимизировать параллелизм
   - CPU 30-70%    → недогрузка, добавить joblib parallel
   - CPU 70-95%    → ✅ оптимально
   - CPU 100%      → проверить нет ли oversubscription (медленнее реально)
3. Если плохо нагружено: Ctrl+C, обновить архив, перезапустить
4. Не «терпеть» долгие runtime — лучше потратить 30 мин на оптимизацию параллелизма и сэкономить часы
```

#### Cancellation strategy

Если PC явно недогружен и runtime растягивается — **отменить и перезапустить с оптимизированной версией** ВЫГОДНЕЕ чем ждать. Например, сегодня:
- HGBR sequential на 3 064 features = 10-18 часов
- LightGBM parallel n_jobs=3 × 6 horizons = ~1-2 часа
- Решение перезапустить экономит **8-16 часов** против дожидания.

### Workflow

```
[Mac] → Claude формирует архив-задачу:
  1. Код (Python-скрипт + зависимости)
  2. Данные (или ссылка на ~/Desktop/btc_full.csv эквивалент)
  3. requirements.txt (зафиксированные версии)
  4. README с шагами запуска и ожидаемым output
  5. Имя архива: ~/Desktop/compute-YYYY-MM-DD-task-name.zip

[Mac → PC] Пользователь переносит архив

[PC (Windows 11)] Пользователь:
  1. Распаковывает
  2. Запускает по README
  3. Получает output (CSV/JSON/PNG)

[PC → Mac] Пользователь возвращает output на Mac

[Mac] Claude анализирует результаты, формирует выводы
```

### Что включать в архив (чек-лист)

**Code & deps:**
- ✅ Python-скрипт(ы) с absolute или relative paths корректно настроенными под Windows
- ✅ `requirements.txt` (pinned versions для production; `>=,<` ranges для гибкости с wheels)
- ✅ Данные если требуются (или явная инструкция «скопировать `btc_full.csv` в папку `data/`»)
- ✅ README.md с командой запуска (`python script.py`) и описанием expected output + **ожидаемая CPU loading %**
- ✅ Заранее заданная папка для output (`./output/`)

**Параллелизм (см. секцию выше):**
- ✅ **Inner n_jobs** настроен (LightGBM/XGBoost: `n_jobs=-1` или explicit число потоков)
- ✅ **Outer parallelism** через `joblib.Parallel` для независимых задач
- ✅ Total threads (Outer × Inner) соответствует target PC (~16 для PC1, ~20 для PC2)
- ✅ README указывает **ожидаемую CPU loading** (например «85-95% на PC2»)

**Windows pitfalls:**
- ⚠️ **CP1251 console на Windows** — не использовать unicode-symbols (Δ, ★, 🔥) в `print()`; заменять ASCII (`delta`, `***`). Или добавить `chcp 65001 >nul` в `run.bat`
- ⚠️ Path separator — использовать `pathlib.Path` или `os.path.join`, не hardcoded `/`
- ⚠️ Если GPU-задача — явно `torch.cuda.is_available()` check и `device = "cuda"` (на PC будет CUDA, не MPS)
- ⚠️ **CRLF line endings** в `.bat` файлах (Mac пишет LF — Windows cmd может не парсить → молчаливое закрытие)
- ⚠️ Cyrillic username path → `pip install --only-binary=:all:` для wheels-only, избегаем компиляции из source

### Триггеры для применения Правила 9

| Сигнал | Действие |
|---|---|
| Walk-forward suite на 5+ лет с >1 cadence | → архив на PC |
| Тренировка LightGBM/XGBoost на 1M+ строк | → архив на PC |
| Любое GPU-ML (PyTorch/TensorFlow обучение) | → архив на PC |
| Multi-symbol processing (BTC + ETH + SOL) полный rebuild | → архив на PC |
| Estimated runtime > 30 мин на M5 | → архив на PC |
| Estimated peak RAM > 8 GB | → архив на PC |
| Iterative dev/debug сессия | → остаётся на Mac (даже если медленнее) |

### Артефакты

- Папка для архивов: `~/Desktop/compute-archives/` (создаётся при первом использовании)
- Шаблон README — TBD (формируется ad-hoc для каждой задачи)
- Naming convention: `compute-YYYY-MM-DD-{task-slug}.zip`

---

## Правило 10 — Канонический формат вывода «элементов библиотеки»

**Принцип.** При запросе пользователя показать «**элементы библиотеки**» (или «покажи элементы», «какие элементы», «что в `elements/`») использовать **строго фиксированный 4-секционный формат**. Не упрощать, не пропускать секции, не менять порядок колонок.

### Триггеры применения

| Фраза пользователя | Действие |
|---|---|
| «**элементы библиотеки**» | → формат Правило 10 |
| «покажи элементы» / «какие элементы» / «что в elements/» | → формат Правило 10 |
| «список элементов» / «инвентарь зон» | → формат Правило 10 |

### Источник истины

- Слаги: `ls ~/smc-lib/elements/*/`
- Заголовки: первая строка `definition.md` каждой папки
- Сигнатуры детекторов: `grep "^def " ~/smc-lib/elements/*/code.py`
- Класс зоны: [[Правило 8]] + [[memory:zone-class-liquidity-inefficiency-block]]
- Mitigation: [[Правило 2]]
- Активные в prediction-algo: `~/smc-lib/prediction-algo/zones.py` константа `ALL_TYPES`

### Исключения (НЕ показывать в перечне)

Папки в `elements/`, которые **не отображаются** при выводе по триггерам Правила 10:

| Слаг | Почему исключён |
|---|---|
| `ob_sweep_liq_4candles` | Retrospective event/marker — фиксирует уже свершившийся sweep. Не forward-looking zone, используется как feature в детекции/labelling других элементов, но не как самостоятельная зона интереса. Зафиксировано 2026-05-29 |
| `rb` | Исключён из перечня по решению пользователя 2026-05-29. Папка остаётся на диске, детектор работает. В `ALL_TYPES` для prediction-algo остаётся (если иное не указано) |

Эти папки остаются на диске (полезны как feature/context), но в Rule 10 output для них нет строки. Если потребуется отдельный перечень «retrospective markers» — он формируется по другому триггеру.

### Формат вывода (4 секции, именно в этом порядке)

#### Секция 1 — Главная таблица «Элементы»

**Порядок строк — строго по классу зоны** (по циклу Правила 8: liquidity → inefficiency → блок → composite). Внутри класса — по сложности (от простого к составному) или по алфавиту слага. Между группами — заголовочная строка с emoji класса для визуального разделения.

**Колонки (унифицированы 2026-05-29):**
- `Слаг` — snake_case как имя папки
- `Заголовок` — из definition.md
- `Свечей` — минимум для детекции
- `Mitigation` — wick-fill / first-touch / sweep
- `Геометрия` — **range** (диапазон `[lo, hi]`) или **level** (точечный уровень-значение). Это **главная различающая ось** — фрактал и марубозу выступают как уровень (значение), потому что за диапазоном точно не знаем где разворот; все остальные имеют чёткий диапазон.
- `Направление` — **всегда `long / short`** (трейдинговое ожидание после взаимодействия). Внутренние code-метки исторически разные (high/low у фрактала, top/bottom у RB) → mapping см. ниже.

Колонка `Класс` НЕ нужна внутри таблицы — класс задан заголовком группы.

### Mapping внутренних code-меток → отображаемое направление

В коде `direction` field у `ActiveZone` использует исторические значения. Display всегда сводит к `long/short`:

| Элемент | Internal `direction` | Display `Направление` | Семантика |
|---|---|---|---|
| OB, block_orders, FVG, i_fvg, RDRB, i_rdrb, ob_liq, marubozu, ob_vc | `long` / `short` | long / short | без изменений |
| **RB** | `bottom` / `top` | **long / short** | bottom = support (long), top = resistance (short) |
| **fractal** | `low` / `high` | **long / short** | FL sweep → long setup, FH sweep → short setup |

Шаблон:

```
### ⛽ Liquidity (топливо — Phase 1 в Правиле 8)
| Слаг | Заголовок | Свечей | Mitigation | Геометрия | Направление |
|---|---|---|---|---|---|
| rb | RB (Rejection Block) | 1 | first-touch | range | long / short |
| fractal | Fractal (Williams) | 2N+1 (def 5) | sweep | **level** | long / short |

### 🧲 Inefficiency (магнит — Phase 2)
| Слаг | Заголовок | Свечей | Mitigation | Геометрия | Направление |
|---|---|---|---|---|---|
| fvg | FVG (Fair Value Gap) | 3 | wick-fill | range | long / short |
| i_fvg | i-FVG (Inverse FVG) | 6+ | wick-fill (overlap) | range | long / short |

### 🎯 Блок (точка реакции — Phase 3)
| Слаг | Заголовок | Свечей | Mitigation | Геометрия | Направление |
|---|---|---|---|---|---|
| ob | OB (Order Block) | 2 | wick-fill | range | long / short |
| block_orders | Блок ордеров | 3+ (N₁+N₂+1) | wick-fill | range | long / short |
| rdrb | RDRB | 3 | wick-fill (POI) | range | long / short |
| i_rdrb | i-RDRB | 4 | wick-fill (наследует RDRB) | range | long / short |

### Composite (multi-class)
| Слаг | Заголовок | Свечей | Mitigation | Геометрия | Направление | Композит классов |
|---|---|---|---|---|---|---|
| ob_liq | OB с уровнем ликвидности | 2 | first-touch | range | long / short | 🎯 блок (zone) + ⛽ liquidity (liq_zone) |
| marubozu | Marubozu | 1 | sweep (open) | **level** | long / short | 🧲 inefficiency (body) + ⛽ liquidity (open level) |
```

В composite-группе добавляется седьмая колонка «Композит классов».

#### Секция 2 — Структура каждого элемента

Code block с layout папки + что лежит:

```
~/smc-lib/elements/<slug>/
├── definition.md   — canon: что это, геометрия зоны, условия, mitigation
└── code.py         — детектор detect_<slug>(...) → <Element> | None
```

#### Секция 3 — Сигнатуры детекторов

Таблица: `Элемент | Сигнатура | Возврат` по каждому элементу.

#### Секция 4 — Что используется в prediction-algo

Цитата константы `ALL_TYPES` из `zones.py` + пояснение что исключено и почему. Обязательно указать причину исключения `ob_sweep_liq_4candles` (retrospective event).

#### Секция 5 — Не-элементы (рядом с `elements/`)

Краткая ссылка на:
- `~/smc-lib/patterns/` — полные setup-паттерны (i_rdrb_fvg, run_3candles_sweep)
- `~/smc-lib/vc/` — Volume Confirmation (предикат, не зона; см. [[Правило 3]])
- `~/smc-lib/indicators/` — VWAP, HMA TrendLine, MoneyHands и др.

### Что НЕ включать

- Историю изменений каждого элемента (это в session-notes)
- Подробную геометрию зон (это в `zone_of_interest.md`, ссылаться)
- Trading strategy / entry / SL — это уровень патернов, не элементов
- Тестовое покрытие построчно (можно одной строкой «test-файлов нет» — это статус-факт)

### Почему именно так

Пользователь хочет **быстро восстановить инвентарь** при работе с библиотекой. Структура «таблица → структура → API → активность → соседи» отвечает на 4 типичных вопроса в одном выводе:
1. Что у нас есть? → секция 1
2. Где это лежит? → секция 2
3. Как этим пользоваться? → секция 3
4. Что реально работает в production? → секция 4
5. Что рядом, но не элементы? → секция 5

Зафиксировано 2026-05-29 после успешного презентационного формата в сессии reverification + roadmap.

---

## Правило 11 — Компрессия (эффективное ценообразование) — *в разработке*

**Принцип.** **Компрессия = эффективное ценообразование.** Зона, в которой institutional accumulation/distribution прошёл аккуратно: сформирован стек OB разных ТФ, и все inefficiency (FVG) внутри стека отработаны.

### Структурное определение (зафиксировано пользователем 2026-05-29)

1. **Серия OB разных ТФ** в одной price zone (стек multi-TF институциональных уровней).
2. **Все LTF FVG 15m в зоне OB-стека заполнены ≥50%** (mitigation by wick-fill).

Если есть хотя бы одна FVG 15m с мит < 50% → **это НЕ компрессия** (есть остаточная inefficiency, рынок ещё не «дошёл» до efficient pricing).

### Класс зоны

**⛽ Liquidity** — фрактальная ликвидность (по решению пользователя). См. [[Правило 8]] таксономию.

Семантически: компрессия = «traded zone» — институционал торговался **fair** внутри стека, оставив stops розницы за границами компрессии. Sweep этих границ = Phase 1 цикла Правила 8.

### Контраст с [[memory:feedback-untraded-area-is-magnet]]

| Тип зоны | Магнит-логика |
|---|---|
| **Untraded area (FVG, marubozu body)** | Магнит — цена возвращается заполнить |
| **Traded area (компрессия)** | **НЕ магнит** — заполнение уже произошло, зона «отработана» |

### Контраст с `ob_vc` ([[Правило 3]] зональная реализация)

| Элемент | FVG-статус |
|---|---|
| **ob_vc** | OB + **активная** (не отработанная) LTF FVG = displacement validator |
| **compression** | OB-стек + **отработанные** (≥50%) LTF FVG = efficient pricing |

**Взаимоисключающие** состояния для одного OB.

### Открытые вопросы (для следующих сессий)

1. **Минимум OB в стеке** — 2? 3? больше?
2. **HTF-набор** — на каких TF собираем OB (1h, 4h, 12h, 1d)?
3. **«В одной зоне»** — overlapping zones / общий midpoint ± толеранс / bounding box?
4. **Direction OB** — same direction (LONG-only / SHORT-only стек) или mixed допустим?
5. **FVG TF set** — только 15m или включая 20m?
6. **Формула «≥50% заполнен»** — `(hi - min_wick) / (hi - lo) ≥ 0.5` для LONG FVG?
7. **Геометрия компрессии-зоны** — union / intersection / bounding box / outer edges?
8. **Mitigation модель самой компрессии** — sweep? first-touch?
9. **Direction labels компрессии** — long/short / top/bottom / neutral?

### Связи

- [[Правило 2]] — wick-fill mitigation для проверки «≥50%»
- [[Правило 3]] — VC: компрессия = антипод ob_vc для одного OB
- [[Правило 8]] — Phase 0/preparation цикла; компрессия = накопленная liquidity
- [[memory:feedback-untraded-area-is-magnet]] — антонимично: untraded = magnet, traded (компрессия) = не magnet
- [[memory:feedback-fractal-liquidity-strength-and-sweep]] — сила liquidity = TF × age × cluster

### Статус

🚧 **В разработке.** Концепция зафиксирована, точные параметры — TBD в следующих сессиях. Не реализовывать детектор и не интегрировать в `prediction-algo` до уточнения 9 открытых вопросов выше.

Подробности будущей работы — фиксировать в этом правиле, не создавать отдельный элемент `elements/compression/` до финализации канона.


## Правило 12 — Макроиндикаторы TOTALES и USDT.D

Контекст рынка для подтверждения BTC-сигналов (confluence layer над стратегиями).

### Определения

**TOTALES** — суммарная капитализация криптовалютного рынка **БЕЗ учёта стейблкоинов**.
- = total market cap (BTC + ETH + ALTS) − stablecoin caps
- TradingView ticker: `CRYPTOCAP:TOTAL2` или агрегат
- Семантика: «деньги в крипте» (риск-он капитал)
- TOTALES ↑ = capital flowing into crypto (bullish)
- TOTALES ↓ = capital выходит (bearish)

**USDT** — самый популярный стейблкоин (Tether). Привязан 1:1 к USD.

**USDT.D** (USDT Dominance) — **индекс доли USDT в общей капитализации крипторынка**.
- = USDT_market_cap / TOTAL_crypto_market_cap × 100%
- TradingView ticker: `CRYPTOCAP:USDT.D`
- Семантика: «доля кэша в крипто-портфелях»
- USDT.D ↑ = капитал перетекает в стейблы (risk-off, **bearish для BTC/altcoins**)
- USDT.D ↓ = капитал из стейблов идёт в крипту (risk-on, **bullish для BTC/altcoins**)

### Важнейшее свойство — зеркальность

USDT.D **антикоррелирован** с TOTALES (и BTC):
- TOTALES ↑ обычно ↔ USDT.D ↓ (деньги входят в крипту → доля USDT уменьшается)
- TOTALES ↓ обычно ↔ USDT.D ↑ (деньги выходят в стейблы → доля USDT растёт)

Это даёт **двойную независимую проверку** market regime.

### Confluence rule для BTC-стратегий

Для BTC trade в направлении X (LONG / SHORT):

| Indicator | Same / Mirror | Логика |
|---|---|---|
| **TOTALES** | **SAME** direction | crypto market растёт ↔ BTC LONG валиден |
| **USDT.D** | **OPPOSITE** direction (mirror) | капитал выходит из стейблов ↔ BTC LONG валиден |

**Подгруппы confluence**:
- `TOTALES match only` — только TOTALES согласен
- `USDT.D mirror only` — только USDT.D согласен (mirror)
- `Triple confluence` — оба согласны (TOTALES same + USDT.D mirror)
- `Any sync` — хотя бы один
- `No sync` — оба против → **отказать в сделке** (или signal вне макро-контекста)

### Critical lookahead guardrail

Direction TOTALES / USDT.D определять **ТОЛЬКО по закрытым свечам** (например предыдущий 1d close).

**Известный bug** (исправлен в сессии): прошлая реализация анализатора `analyze_rdrb_confluence_macro.py` использовала close **сегодняшней (незакрытой) свечи** для определения direction. Это давало lookahead ~12 часов в среднем, ~24+ часа в 17% случаев. WR Triple confluence был завышен на ~10pp.

**Канон**: для timestamp T использовать direction за период `[T - N×1d, T_prev_closed_day_close]`, где `T_prev_closed_day_close` — close последней **полностью** закрытой daily candle (не включает intra-day движение текущего дня).

См. `~/traid-bot/vault/knowledge/debugging/confluence-lookahead-and-rr22-bugs.md`.

### Параметры (canonical defaults)

| Параметр | Значение | Обоснование |
|---|---|---|
| Lookback period | **3 closed daily bars** | Стабильность direction без noise |
| Direction rule | `close[T_now] > close[T_now − N]` для UP / mirror для DOWN | Net change за N дней |
| Strict timing | Только closed candles | Никакого lookahead |
| Default N | 3 (по умолчанию) | Из старой логики; можно тюнить per-стратегия |

### Data sources

| Indicator | Файл | TF | Статус |
|---|---|---|---|
| TOTALES | `~/traid-bot/data/TOTALES_{15m,1h,4h,1d}.csv` | 15m, 1h, 4h, 1d | ✓ есть |
| USDT.D | _нет локально_ | Fetch требуется | ✗ TBD |

### Применение в стратегиях

Confluence — **опциональный фильтр** или **scoring boost**, не hard filter. Опции:

| Подход | Применение |
|---|---|
| **Hard filter** | Trade ONLY если Triple confluence — selective, freq −50% |
| **Direction veto** | Skip если No sync (оба против) — мягко, freq −10-20% |
| **Sizing modifier** | Triple = 1.5× position, Any sync = 1× , No sync = 0.5× |
| **Scoring feature** | Добавить в ML head как feature, не hard rule |

Strategy 1.1.1 V2 design doc: «опционально — как ml-feature, не hard filter».

### Связи

- `[[Правило 5]]` — основная стратегия ASVK (может использовать confluence как F4 layer)
- `[[memory:feedback-1-1-1-floating-without-totales-usdtd]]` — мой 6y benchmark +196R НЕ включает TOTALES/USDT.D
- `~/traid-bot/vault/knowledge/debugging/confluence-lookahead-and-rr22-bugs.md` — lookahead bug post-mortem
- `~/traid-bot/research/rdrb/analyze/analyze_rdrb_confluence_macro.py` — existing analyzer (используется как reference, не как production code)

### Открытые вопросы

1. **Lookback N**: 1, 3, 5, 7 дней? Зависит от стратегии (intraday vs swing)
2. **TF для direction**: 1d default, но 4h для быстрых стратегий, 1w для swing?
3. **TOTAL vs TOTAL2 vs TOTAL3**: какой агрегат канонический? (TOTAL = вся капитализация включая BTC; TOTAL2 = без BTC; TOTAL3 = без BTC+ETH)
4. **Threshold** для «direction confirmed»: net change > 0%? > 0.5%? > 1%?
5. **USDT.D vs USDC.D vs USD.D combined**: смотреть только USDT или агрегат stablecoin dominance?
6. **Fetch USDT_D**: source (TradingView API? CoinGecko? Binance index?)

---

## Правило 13 — Канонический формат «Ключевые выводы из чтения»

**Принцип.** При запросе пользователя «**изучи книги**», «**ключевые выводы из чтения**», «**прочитай и сделай выводы**», «**что взять из литературы**» — использовать строго фиксированный формат **action-oriented findings** (не summary). Цель — actionable items для immediate work, не литературное резюме.

### Триггеры применения

| Фраза пользователя | Действие |
|---|---|
| «**изучи** [книги/литературу/PDFs]» | → формат Правило 13 |
| «**ключевые выводы из чтения**» / «**что взять из чтения**» | → формат Правило 13 |
| «**прочитай и сделай выводы**» / «**summary книги**» | → формат Правило 13 |
| «**что применить из** [книги]» | → формат Правило 13 |

### Формат вывода

Заголовок секции: `## Ключевые выводы из чтения`

Под каждую книгу — **одна секция** в порядке релевантности (⭐⭐⭐ → ⭐). Каждая секция:

#### 1. Заголовок секции:
```
### 🎯 <Автор / Краткое имя книги> — <направление применения>
```

Emoji выбирается по характеру книги:
- 🎯 — ML/quant/инфраструктура
- 📊 — volume/orderflow/microstructure
- 🕯 — candlestick/price action
- 📈 — chart patterns / classic TA

Стрелка `→ направление применения` указывает **куда мы это применим** в нашей кодовой базе (force-model, vc/, elements/, etc.).

#### 2. Тело секции — ТОЛЬКО ОДНА из форм:

**Форма A — Таблица (chapter / what to apply):**

```
| Глава / раздел | Что применять (action item) |
|---|---|
| Ch X — <название> | <конкретное действие в нашем коде> |
```

**Форма B — Bullet list (новые primitives / patterns):**

```
N novel <element_type> candidates:
- `slug_1` — короткое определение детектора
- `slug_2` — короткое определение
...
**<concept_name> = <our_existing_concept>** — те же концепции, разная терминология.
```

**Форма C — Краткая ссылка на полный note-файл** (если preview / частичный материал):

```
Preview only — для serious use нужна full edition. <Краткий список потенциального применения, если будет full>.
```

### Структура секции (обязательная)

Каждая секция должна включать:
1. **Заголовок** с emoji + направлением применения (1 строка)
2. **Тело** — таблица (A) ИЛИ bullet list (B) ИЛИ ссылка (C)
3. (опционально) короткий **commentary** на 1-2 предложения с insights

### Что нельзя

- ❌ Длинный summary книги (краткое summary — в `notes_<имя>.md`)
- ❌ Биография автора, история издания
- ❌ Концепции БЕЗ привязки к нашему коду
- ❌ Reading order tips (это для `README.md` библиотеки)

### Что обязательно

- ✓ Каждый action item должен указывать **конкретно** на наш файл/модуль/класс
- ✓ Приоритет ⭐ выставлен и виден
- ✓ Cross-references на наши existing modules через `~/smc-lib/...` paths

### Источник истины

- Детальные заметки по каждой книге: `~/smc-lib/literature/notes_<имя>.md`
- Каталог литературы: `~/smc-lib/literature/README.md`
- Этот формат для вывода в **чат пользователю**, не для записи в файлы

### Связи

- `[[Правило 10]]` — аналогичный канонический формат для «элементов библиотеки»
- `~/smc-lib/literature/` — раздел литература (создан 2026-06-03)
- `[[memory:feedback-elements-library-output-format]]` — родственный feedback memory для формата элементов
