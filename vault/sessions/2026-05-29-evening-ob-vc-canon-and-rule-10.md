---
tags: [session, smc-lib, ob-vc, rule-10, taxonomy-rename, prediction-algo, zones-opinion]
date: 2026-05-29
related: [[2026-05-29-prediction-algo-verification-and-roadmap]], [[2026-05-28-evening-expert-section-candle-patterns-rule8-prediction-algo]]
---

# 2026-05-29 (evening) — ob_vc canon (9 условий), Правило 10, переименование efficiency→блок, A′ селектор

Продолжение [[2026-05-29-prediction-algo-verification-and-roadmap]]. Главное достижение — построен **новый канонический элемент `ob_vc`** с 9-условным каноном, реализован детектор, протестирован на реальных данных. Параллельно сделан большой канон-рефакторинг библиотеки.

## I. Задача #6 — tradeable target (filter близких зон)

В `zones_opinion.py` добавлен параметр `min_target_dist_pct=0.30` (CLI `--min-target-dist-pct`). Кластеры с distance < threshold отображаются на карте, но **не выбираются** как `base_target` / FIRST-TARGET. Пропущенные близкие зоны показаны отдельной строкой «(пропущены как незначительные)».

**Тестирование на 0.5%:** при пороге 0.5% маржинальная `P_first` схлопывается до ≈0 у обеих сторон (margin шум), потому что `first_hit_above` физически почти не срабатывает на дальней дистанции. Сделано открытие: для дальних целей нужна другая метрика.

## II. Модель A → A′ (важный урок)

### Попытка A: Conditional P_first

Реализовал в `model.py`: новый conditional rate `cond_first_above|below = mean(first_hit_above | hit_D=True)`. Гипотеза: декомпозиция `P_first = P_hit_D × P_cond_first` обойдёт схлопывание на дальней дистанции.

**Результат**: алгебраически идентично маржинальной `P_first` (потому что `first_hit=True ⇒ hit_D=True`). Численная проверка показала разницу только в Laplace smoothing (0.01). **Откатил полностью**.

### Принят A′: P_hit_D как универсальный селектор

Заменил селектор для `base_target` / FIRST-TARGET с `max_p_first` на `max_p_d`. P_hit_D работает на любой дистанции и сопоставим между сторонами. `P_first` остался как информация в выводе + новая строка «Race на ближайших» для близких зон обоих сторон.

**Результат на BTC 73 568:** margin +0.38 (уверенный ВВЕРХ), target [73 868, 74 244] на +486$/0.66% — tradeable. Раньше с P_first было +0.17.

**Урок зафиксирован в session:** прежде чем строить ML-расширение, проверить, не решается ли проблема корректным использованием существующих метрик.

## III. Roadmap из 5 задач → 5+1+1+1...

Постановка после A′:
- 5 исходных задач roadmap (траектория, корреляции, отскок/пробой, max range, sequence)
- #6 — close target filter (tradeable output) ✅ сделано
- Что ещё (max-excursion модель на PC) отложено для отдельной сессии

## IV. Переименование класса `efficiency` → `блок`

По пользовательскому решению (термин «блок наторгованный» = maxV ASVK уже использовался). Переименование:

**Канон (smc-lib):**
- `rules.md` → Правило 8 — таксономия, фазы, чеклисты (4 правки)
- `zone_of_interest.md` → принципы именования + примеч.
- `expert/opinion.md` → Шаг 4 + 2 cross-ref
- `expert/README.md` → описание классификации
- `elements/fractal/definition.md` → ссылка на memory
- `projects/prediction-algo.md` → колонка «Категория» в таблице

**Memory:**
- Создан `zone-class-liquidity-inefficiency-block.md` (с историей переименования + расширенной таксономией)
- Удалён `zone-class-liquidity-inefficiency-efficiency.md`
- Обновлены 7 cross-ref в других memory + MEMORY.md index

### ⚠ Сбой при миграции — потеря prediction-algo.md

При замене через `sed -i.bak` на macOS BSD файл `~/smc-lib/projects/prediction-algo.md` обнулился (unicode multi-byte issue). Восстановил только таблицу типов зон из контекста + warning-блок об инциденте. **Урок:** больше не использовать sed для unicode-замен — только Edit-tool или Python.

## V. Правило 10 — формат вывода «элементов библиотеки»

Зафиксирован канонический 5-секционный формат:

1. **Главная таблица** — сгруппирована по классу в порядке цикла Правила 8 (`⛽ Liquidity → 🧲 Inefficiency → 🎯 Блок → Composite`). Колонки: Слаг | Заголовок | Свечей | Mitigation | Геометрия | Направление
2. **Структура папки** — code block с definition.md + code.py
3. **Сигнатуры детекторов** — таблица Элемент | Сигнатура | Возврат
4. **Что в prediction-algo** — цитата `ALL_TYPES` + исключения
5. **Не-элементы** — patterns/, vc/, indicators/

**Триггеры:** «элементы библиотеки», «покажи элементы», «список элементов», «инвентарь зон».

**Ключевые две оси:**
- `Геометрия` — `range` или `level`. Фрактал + марубозу = level, остальные = range.
- `Направление` — всегда `long/short`. Internal-метки (`high/low`, `top/bottom`) маппятся в display.

Записано в memory `feedback-elements-library-output-format.md`.

`ob_sweep_liq_4candles` исключён из перечня — retrospective marker, не forward-looking зона.

## VI. Новый элемент `ob_vc` — OB с имбалансом

Создан с нуля по детальному канону пользователя:

### Геометрия
- **Композит:** 🎯 блок (zone) + 🧲 inefficiency (fvg)
- **Zone = OB.zone** (full ZoI, может включать breaker block)
- **Target для FVG = drop area (LONG) / rally area (SHORT)** — не full ZoI

### Канон OB рефакторинг (важно)
Breaker block теперь существует **только при полном пробое prev** (cur.close > prev.high для LONG / < prev.low для SHORT). Раньше существовал безусловно. Соответственно ZoI зависит от наличия breaker:
- С breaker: drop area + breaker
- Без breaker: только drop area

Обновлены `~/smc-lib/elements/ob/definition.md` и `zone_of_interest.md` секция OB.

### Канон ob_vc — 9 условий (финал)

| # | Условие |
|---|---|
| 1 | **Сонаправленность** ⚠ critical first filter: `ob.direction == fvg.direction` |
| 2 | HTF OB существует на canon-TF |
| 3 | LTF FVG существует на canon-LTF (по таблице HTF→LTF) |
| 4 | **Spatial overlap с drop/rally area** (хотя бы частично; запрещено полностью вне) |
| 5 | FVG.zone ⊆ `[low_ob_vc, first_FH/FL.extreme]` — первый Williams N=2 фрактал ВНЕ drop/rally area |
| 6 | OB actionable (caller's responsibility; в детекторе не проверяется) |
| 7 | **Temporal lower:** `fvg.c1.open_time ≥ ob.cur.open_time` (FVG не из прошлого) |
| 8 | **Temporal upper:** `fvg.c3.close_time ≤ first_fractal.confirmation_time` (FVG в bounce-фазе) |
| 9 | **FVG не consumed** на 1m в окне `[c3.close, fh.confirmation]` — иначе ob_vc → OB |

### HTF → LTF mapping

| HTF | LTF |
|---|---|
| 3D, 2D | 12h |
| D, 12h | 4h, 6h |
| **4h, 6h** | **1h, 90m, 2h** |
| 1h, 2h | 15m, 20m |

(Добавлены `20m`, `90m`, `2d` в `resample.py` `_TF_TO_FREQ`.)

> **Уточнение конца сессии 2026-05-29:** в первой версии было `4h, 6h → 90m`. Пользователь указал, что упущены пары `4h/6h × 1h/2h` (соответствует VC variant 2). Расширено до `(1h, 90m, 2h)`. Финальная таблица — **16 пар × 2 направления = 32 signed комбинации**.

### Связь с VC (Правило 3)
- `vc/` = **предикат** (bool) над HTF-зоной, 3 канонических варианта (1h+15m containment, 4h+1h containment, temporal sequence)
- `ob_vc/` = **зона** (самостоятельный элемент), partial overlap (не containment), расширенный HTF range

В Правиле 3 добавлена back-reference на ob_vc.

### Реализация

**`~/smc-lib/elements/ob_vc/`:**
- `definition.md` — полный канон (9 условий + псевдокод + связи + TODO)
- `code.py` — детектор (~200 строк):
  - `HTF_TO_LTF` mapping
  - `LTF_DURATION_MS` для temporal calc
  - `OBVC` dataclass
  - `detect_ob_vc(ob, htf, ltf_bars_after_ob, ltf_fvgs, n_fractal=2, df_1m=None)`
  - Helpers: `_has_breaker`, `_drop_or_rally_area`, `_first_williams_fh_above`, `_first_williams_fl_below`
  - Сонаправленность как первый фильтр
  - `df_1m` опционально (для условия #9 — production canon)

### Эволюция отбора (по мере добавления условий)

Тестовый запуск на BTC за 90 дней, HTF 4h/6h × LTF 90m:

| Версия | LONG | SHORT |
|---|---:|---:|
| Только #1-#4 (sonap + overlap drop area) | 115 | 106 |
| + #7 (FVG c1 ≥ OB cur) | 91 | 90 |
| + #8 (FVG до first FH confirm) | 34 | 27 |
| **+ #9 (FVG не consumed)** | **22** | **19** |

Каждое условие отсеивает ~30%. Финал — строгий, реалистичный канон.

### Проверка на 27-05 07:00 4h LONG OB

По 1-8 условиям — валидно (1 FVG-компонент `[75 739, 75 843]`). По #9 — **отвал** (1m данные показали min low 75 711 в окне между c3 close и FH confirmation; FVG.zone_lo = 75 739 → consumed). Корректное поведение: ob_vc → OB.

### Финальные топ-6 (canon #1-#9, BTC 90 дней)

**LONG** (22 всего): 23-05 6h, 20-05 6h, 14-05 6h, 05-05 4h, 05-05 6h, 04-05 4h
**SHORT** (19 всего): 18-05 4h, 18-05 6h, 17-05 4h, 17-05 6h, 13-05 6h, 28-04 4h

Все имеют ровно 1 FVG-компонент (bounce phase коротка — обычно 1 FVG на 90m).

## VII. Интеграция ob_vc в prediction-algo (сделано в конце сессии)

В `~/smc-lib/prediction-algo/zones.py` добавлено:
- Импорт `detect_ob_vc, HTF_TO_LTF as OB_VC_HTF_TO_LTF`
- `"ob_vc"` добавлен в `ZoneType` literal и `ALL_TYPES` tuple (теперь **11 типов** в production)
- Новая функция `_scan_ob_vc_cross_tf(resampled, df_1m, n_fractal=2)` — cross-TF scanner:
  - Для каждого HTF из `HTF_TO_LTF` итерирует OB-пары
  - Вызывает `detect_ob_vc(...)` с canon strict (`df_1m` для условия #9)
  - Возвращает события `{type: "ob_vc", direction, lo, hi, born_idx, mit: "wick-fill"}` с zone = ob.zone
- `precompute_zone_events` обновлён: после per-TF scan вызывает cross-TF scanner для ob_vc; auto-resample недостающих LTF (90m, 15m, 20m, 6h, 4h, 2h, 1h) если их нет в исходных `tfs`

**Mitigation:** ob_vc наследует wick-fill от OB. **Born_idx:** = `ob.cur.born_idx` (HTF индекс).

**Smoke test через `zones_opinion`:** ob_vc корректно появляется в кластерах:
```
↓ [70506, 72583]  9 зон: FVG/OB/block_orders/fractal/iFVG/ob_vc на 12h/1d/1h/4h
→ [74380, 75275]  5 зон: OB/RDRB/block_orders/marubozu/ob_vc на 1h
```

## VIII. Доработка канона: +4 пары HTF 4h/6h × LTF 1h/2h

После полного сканирования и презентации статистики пользователь указал, что упущены 4 пары:
- `4h × 1h`, `4h × 2h`, `6h × 1h`, `6h × 2h`

Это соответствует **VC variant 2** (Правило 3). Канон расширен:
- `HTF_TO_LTF["4h"]` = `("1h", "90m", "2h")` (было `("90m",)`)
- `HTF_TO_LTF["6h"]` = `("1h", "90m", "2h")` (было `("90m",)`)

Финал: **16 канонических пар × 2 направления = 32 signed комбинации**.

## IX. Полный скан ob_vc по 16 парам (BTC 90 дней)

Скрипт `/tmp/scan_all_12_pairs.py` (название историческое, переименовать при следующей сессии). Время сканирования: **2.9 сек** на Mac M5.

### Результаты по тиерам

| Тиер | Pairs | LONG | SHORT | Total |
|---|---|---:|---:|---:|
| **Макро** (3D/2D × 12h) | 2 | 0 | 0 | **0** |
| **HTF** (D/12h × 4h/6h) | 4 | 14 | 7 | **21** |
| **Средний** (4h/6h × 1h/90m/2h) | 6 | 64 | 62 | **126** |
| **LTF** (1h/2h × 15m/20m) | 4 | 257 | 237 | **494** |
| **TOTAL** | **16** | **335** | **306** | **641** |

### Топ-3 пар по conversion rate (OB → ob_vc)

| # | Pair | Conv. |
|---|---|---:|
| 1 | 2h × 15m | 49% (132 ob_vc) |
| 2 | 2h × 20m | 39% (106) |
| 3 | D × 4h | 35% (8) |

### Топ-3 по абсолютному количеству

| # | Pair | Total |
|---|---|---:|
| 1 | 1h × 15m | 148 |
| 2 | 2h × 15m | 132 |
| 3 | 1h × 20m | 108 |

### Наблюдения

1. **89% всех ob_vc** — в LTF-тиере (494/641). Это intraday-сетапы.
2. **2h × 15m доминирует по conversion** (49%) — почти каждая вторая 2h OB подтверждается 15m FVG.
3. **12h × 4h/6h неожиданно мало** (8% conversion) — bounce-фаза на 12h длинная, FVG чаще consumed по #9.
4. **Макро-тиер пуст за 90 дней** — для статистики нужны годы данных (на 6 лет: оценочно 50-200 ob_vc).
5. **+85 ob_vc** добавили 4 новые пары (4h/6h × 1h/2h) — 15% всех найденных.

## X. Что НЕ сделано (TODO для следующих сессий)

- **Регенерация `btc_full.csv` с ob_vc-событиями** — для обучения lookup-модели на новом типе. **PC-задача** по Правилу 9 (~30 000 событий за 6 лет).
- **Backtest ob_vc** — lift над одиночным OB по P_hit_D на 6-летнем датасете.
- **Unit-тесты** в `~/smc-lib/elements/ob_vc/` — нет тестов сейчас, нужен test-suite.
- **Memory `feedback-ob-vc-canon.md`** — добавить 9 условий для быстрого reference в будущих сессиях
- **Reclass ob_vc → OB** — формализовать «degradation flow» когда все FVG-components consumed.

## VIII. Артефакты сессии

### Новые/изменённые файлы

**smc-lib/elements/ob_vc/** (новая папка):
- `definition.md` — канон ob_vc (9 условий, ~200 строк)
- `code.py` — детектор (~200 строк)

**smc-lib/elements/ob/**:
- `definition.md` — рефактор breaker block (теперь conditional)

**smc-lib/**:
- `rules.md` — Правило 10 (новое), обновление Правила 8 (block rename), back-ref на ob_vc в Правиле 3 (с 16-парой таблицей)
- `zone_of_interest.md` — OB section refactor, принципы именования
- `expert/opinion.md`, `expert/README.md` — class rename
- `elements/fractal/definition.md` — memory link rename
- `projects/prediction-algo.md` — частично восстановлен после sed-сбоя
- `prediction-algo/resample.py` — добавлены `20m, 90m, 2d` TF
- `prediction-algo/zones_opinion.py` — A′ селектор (P_hit_D), min_target_dist_pct=0.30 default
- `prediction-algo/zones.py` — `ob_vc` добавлен в `ALL_TYPES`, новый `_scan_ob_vc_cross_tf`, обновлён `precompute_zone_events`

**Memory:**
- Новые: `feedback-elements-library-output-format.md`, `zone-class-liquidity-inefficiency-block.md`
- Удалён: `zone-class-liquidity-inefficiency-efficiency.md`
- Обновлены ссылки: 7 cross-ref в memory-файлах + MEMORY.md index

### Tmp-скрипты (exploratory)

- `/tmp/find_ob_vc_examples.py` — поиск ob_vc на 6h
- `/tmp/find_ob_vc_long_examples.py` — поиск 3 LONG примеров
- `/tmp/verify_ob_vc_23_05.py` — verification на 23-05 OB
- `/tmp/recent_ob_vc_4h_6h.py` — топ-6 LONG + SHORT
- `/tmp/detail_26_05_short.py` — детальный разбор 18 FVG (старый canon)
- `/tmp/scan_all_12_pairs.py` — full scan по всем 16 каноническим парам (имя историческое — изначально было 12 пар)
- `/tmp/detail_21_05_long.py` — разбор 6 FVG (показал проблему с pre-FH)
- `/tmp/verify_27_05_long.py` — пошаговая проверка 9 условий

## XI. Открытые вопросы

1. ~~**Интеграция в prediction-algo** — структура и API~~ ✅ **сделано** (см. секция VII)
2. **Backtest ob_vc** — нужно сравнить hit-rate ob_vc vs одиночный OB того же HTF/direction (отложено на PC)
3. **Re-runtime для #9** — если 1m не доступно при детекции, использовать ли legacy режим (#1-#8) с маркером, или вообще не делать детекцию?
4. **Mitigation отдельных FVG-components** — пока не трекается; нужно ли?
5. **Reclass ob_vc → OB при потере всех FVG-компонентов** — нужен формальный «degradation flow» (не просто `return None`)
