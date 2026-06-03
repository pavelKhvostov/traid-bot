# OB с имбалансом

Композитный элемент: **HTF OB**, валидированный наличием **сонаправленного LTF FVG**, частично пересекающим зону интереса OB.

> ⚠ **Критичное условие:** LTF FVG **обязательно сонаправлен** HTF OB (`fvg.direction == ob.direction`). Противонаправленный FVG в зоне OB → это **НЕ** `ob_vc`, это другая структура (потенциально `i_fvg`-like sequence). Несовпадение направлений автоматически дисквалифицирует кандидата на ранней стадии детекции.

Canon зафиксирован 2026-05-29.

## Класс зоны (по [[Правило 8]])

| Подзона | Класс |
|---|---|
| **zone** (OB-часть, range `[lo, hi]`) | 🎯 блок |
| **fvg** (LTF FVG-имбаланс, отдельная подзона внутри/частично пересекая zone) | 🧲 inefficiency |

Полный композит: **🎯 блок (zone) + 🧲 inefficiency (fvg)**.

## Условия детекции

**Required (порядок важности):**

1. **Сонаправленность ⚠** — `ob.direction == fvg.direction`. Это **первый и обязательный фильтр**. LONG OB → ищем LONG FVG; SHORT OB → SHORT FVG. Противонаправленные пары исключены полностью.
2. **HTF OB** существует на одном из разрешённых HTF (см. таблицу ниже). Канон OB — `~/smc-lib/elements/ob/definition.md`.
3. **LTF FVG** существует на одном из соответствующих LTF (по таблице). Канон FVG — `~/smc-lib/elements/fvg/definition.md`.
4. **Spatial overlap с drop/rally area (уточнено 2026-05-29):** FVG.zone должен иметь хотя бы частичное пересечение с **drop area** (LONG) или **rally area** (SHORT). **Запрещено:** FVG.zone полностью вне drop/rally area.

   Формально:
   - **LONG OB:** `fvg.zone ∩ ob.drop_area ≠ ∅`, где `drop_area = [min(prev.low, cur.low), prev.open]`
   - **SHORT OB:** `fvg.zone ∩ ob.rally_area ≠ ∅`, где `rally_area = [prev.open, max(prev.high, cur.high)]`

   **Почему именно drop/rally:** это зона **bearish/bullish активности prev candle**, где институционал ловил retail-движение и исполнял противоположные ордера. LTF FVG в этой зоне — прямое доказательство displacement против retail-направления.

5. **Spatial range — между low_ob_vc и первым LTF-фракталом вне drop/rally area:**
   FVG.zone должен **целиком лежать** в ценовом диапазоне между нижней границей drop area (LONG) / верхней границей rally area (SHORT) и **первым** LTF Williams N=2 фракталом, чей экстремум **за границей** drop/rally area.

   Формально для LONG:
   - `low_ob_vc = min(prev.low, cur.low)` (нижняя граница drop area)
   - `first_FH` = **первый Williams N=2 FH** на LTF с центром-баром **после открытия OB cur bar**, чей `center.high > prev.open` (high выше верхней границы drop area)
   - **Требование:** `fvg.zone ⊆ [low_ob_vc, first_FH.high]`

   Формально для SHORT (зеркально):
   - `high_ob_vc = max(prev.high, cur.high)`
   - `first_FL` = **первый Williams N=2 FL** на LTF после открытия OB cur, чей `center.low < prev.open`
   - **Требование:** `fvg.zone ⊆ [first_FL.low, high_ob_vc]`

   **Время формирования FVG не имеет значения** — это чисто пространственный фильтр (FVG.zone lies in price range bounded by drop area floor/rally area ceiling and первый «выход» цены за зону через противоположный LTF-фрактал).

   Раньше канон требовал strict close-time causality (`fvg.close ≥ ob.close`) — **отменено**: FVG может формироваться внутри OB cur bar.
6. **Actionable:** OB должен оставаться actionable (не consumed wick-fill) на момент детекции `ob_vc`. Прошлые consumed-зоны не возрождаются добавлением новых FVG.

7. **Temporal lower-bound — FVG не из прошлого (уточнено 2026-05-29):** `fvg.c1.open_time ≥ ob.cur.open_time`. FVG должна **зарождаться** не раньше открытия OB cur (одновременно — допустимо). Запрещены FVG из прошлого, которые лишь случайно пересекаются с rally/drop area текущего OB.

   **Почему `c1.open_time`, а не `c3`:** FVG-паттерн начинается с c1 (первая свеча displacement). Если c1 = open OB cur — это означает, что displacement начался в момент формирования OB. Это валидный совместный сетап. Если c1 раньше OB cur — FVG относится к более раннему институциональному движению.

8. **Temporal upper-bound — FVG в bounce-фазе (уточнено 2026-05-29):** FVG должна **полностью сформироваться** до подтверждения первого LTF Williams N=2 фрактала вне drop/rally area. Формально:
   - `fvg.c3.close_time ≤ first_FH.confirmation_time` (LONG)
   - `fvg.c3.close_time ≤ first_FL.confirmation_time` (SHORT)
   - где `confirmation_time = center.open_time + (N+1) * LTF_duration` (= момент закрытия N-го бара после центра — момент когда Williams N=2 фрактал становится подтверждённым)

   **Почему:** First FH/FL вне drop area знаменует **завершение bounce-фазы** OB. После него цена «сделала свой ход» из зоны — повторные visits представляют другие сетапы (re-entries, mitigation tests), не валидируют исходный OB. ob_vc — это **активная фаза displacement-валидации**, ограниченная временем bounce.

   Условия #7 и #8 вместе определяют временное окно: `[ob.cur.open_time, first_opposite_fractal.confirmation_time]`. FVG должна **зарождаться** в нижней границе окна и **подтверждаться** в верхней.

9. **FVG actionable к моменту FH confirmation (добавлено 2026-05-29):** К моменту подтверждения first opposite fractal FVG **не должна быть полностью consumed** (по wick-fill mitigation, см. Правило 2). Если FVG потеряла актуальность (полное заполнение), ob_vc **переквалифицируется в OB** — компонент VC утрачен.

   Формально (LONG):
   - Окно проверки: `[fvg.c3.close_time, first_FH.confirmation_time]`
   - На 1m данных в окне: если `min(low) ≤ fvg.zone_lo` (= `c1.high`) → FVG **полностью consumed** → ob_vc невалиден
   - Если `min(low) ∈ (fvg.zone_lo, fvg.zone_hi]` → частичное mitigation, всё ещё валиден
   - Если `min(low) > fvg.zone_hi` → не задета вовсе, валиден

   Зеркально для SHORT через `max(high)` и `fvg.zone_hi` (= `c1.low`).

   **Почему:** Заполненная FVG — это уже **потреблённый** imbalance, displacement-сигнал отработан. ob_vc как «активный composite» теряет VC-компонент. Если все FVG-компоненты consumed → ob_vc → OB.

   **Реализация:** требует доступа к 1m данным в детекторе. Без 1m условие #9 не проверяется (детектор возвращает результат, основанный только на #1-#8). Production-канон требует #9.

### Почему сонаправленность критична

`ob_vc` — это **усиление** HTF OB через подтверждение displacement-сигналом (LTF FVG). Подтверждение работает только если LTF импульс **идёт в ту же сторону**, что и предполагаемая реакция от HTF OB:

- LONG OB ожидает upward reaction → LONG FVG = доказательство upward displacement → confluence
- LONG OB + SHORT FVG = противоречие: HTF говорит «отскок вверх», LTF говорит «sell-side displacement» → это совсем другой сетап (потенциально inverse-FVG-like sequence, не VC)

См. также [[Правило 3]] — там же direction = aligned в каноне VC.

## HTF → LTF mapping (канонические пары)

| HTF (для OB) | Допустимые LTF (для FVG) |
|---|---|
| **3D, 2D** | 12h |
| **D, 12h** | 4h, 6h |
| **4h, 6h** | 1h, 90m, 2h |
| **1h, 2h** | 15m, 20m |

LTF выбирается из пар на одной строке — любая. Если на HTF OB есть FVG на нескольких LTF одновременно — `ob_vc` детектится один раз, в массиве `fvg_components` хранятся все валидирующие FVG (для clustering / strength scoring).

## Зона интереса

**Зона интереса `ob_vc` = `ob.zone`** (полная Full ZoI наследуется от OB, см. `ob/definition.md` — зависит от наличия breaker).

LTF FVG — это **подзона-валидатор**, обязательно пересекающая **drop/rally area** (см. условие #4). Сама FVG-зона хранится в `fvg_components` и доступна как метаданные.

| Направление | Зона интереса (ob_vc) | Обязательная overlap-цель для FVG |
|---|---|---|
| **LONG** | `ob.zone` (drop area или drop + breaker) | **drop area** `[min(prev.low, cur.low), prev.open]` |
| **SHORT** | `ob.zone` (rally area или rally + breaker) | **rally area** `[prev.open, max(prev.high, cur.high)]` |

## Mitigation

**wick-fill** — наследуется от OB (постепенное сжатие при каждом касании). См. [[Правило 2]] Модель 1.

LTF FVG **не** mitigated независимо в рамках `ob_vc` — мы трекаем основную зону (OB). Если LTF FVG отдельно интересна — она остаётся валидным `fvg`-элементом в библиотеке параллельно.

## Свечей

**2** (`prev` + `cur` для HTF OB) + LTF FVG (3 LTF свечи отдельным каналом, не считаются в счёт HTF-элемента).

## Direction labels

`long` / `short` — наследует от OB. Display всегда `long/short` (см. Правило 10 mapping таблицу).

## Композитная природа и связь с VC

`ob_vc` — это **зональная реализация** концепции [[Правило 3]] (VC — Volume Confirmation).

| | `vc/` | `ob_vc/` |
|---|---|---|
| Что это | **Предикат** `has_vc(ob, fvg) → bool` над HTF-зоной | **Зона** `ob_vc.zone` (= OB.zone) — самостоятельный элемент библиотеки |
| Возврат детектора | bool | `OBVC` объект с zone + fvg_components |
| TF pairs | 3 канонических варианта (1h+15m, 4h+1h, temporal sequence) | Расширенная таблица: 3D/2D + 12h, D/12h + 4h/6h, **4h/6h + 90m**, 1h/2h + 15m/20m |
| Overlap requirement | varies (containment в v1/v2; temporal в v3) | **partial overlap** (relaxed) |
| Использование | predicate-фильтр при ranking зон | зона-target в `prediction-algo`, `zones_opinion` |

`ob_vc` — **более широкое определение** чем VC variants: relaxed overlap, расширенный TF range.

## Detection algorithm (псевдокод)

```python
def detect_ob_vc(
    ob: OB,
    ltf_fvgs: list[FVG],         # все LTF FVG (без temporal-фильтра)
    ltf_bars: dict[str, pd.DataFrame],  # LTF bars для каждого допустимого LTF
) -> OBVC | None:
    """
    ob: HTF OB кандидат
    ltf_fvgs: все LTF FVG на разрешённых LTF (без time-фильтра, см. условие #5)
    ltf_bars: OHLC для каждого LTF (нужны для детекции first FH/FL)
    """
    if not _is_supported_htf(ob.tf):
        return None
    allowed_ltfs = HTF_TO_LTF_MAPPING[ob.tf]

    # Drop area (LONG) / Rally area (SHORT) — обязательная overlap-цель
    if ob.direction == "long":
        drop_lo = min(ob.prev_low, ob.cur_low)
        drop_hi = ob.prev_open
        target_zone = (drop_lo, drop_hi)
        low_ob_vc = drop_lo
    else:
        rally_lo = ob.prev_open
        rally_hi = max(ob.prev_high, ob.cur_high)
        target_zone = (rally_lo, rally_hi)
        high_ob_vc = rally_hi

    # Найти первый Williams N=2 LTF фрактал ВНЕ drop/rally area
    # (для LONG — FH, чей center.high > drop_hi; для SHORT — FL с center.low < rally_lo)
    # после открытия OB cur bar
    first_extreme_level = {}  # per LTF
    for ltf in allowed_ltfs:
        bars = ltf_bars[ltf]
        bars_after_ob = bars[bars.index >= ob.cur_ts]
        if ob.direction == "long":
            first_extreme_level[ltf] = _first_williams_fh_above(bars_after_ob, threshold=drop_hi, n=2)
        else:
            first_extreme_level[ltf] = _first_williams_fl_below(bars_after_ob, threshold=rally_lo, n=2)
        if first_extreme_level[ltf] is None:
            # Нет противоположного экстремума — не можем определить верхнюю границу
            # → ob_vc не определён до его появления
            continue

    fvg_components = []
    for fvg in ltf_fvgs:
        # КРИТИЧНЫЙ фильтр — первым: сонаправленность HTF OB и LTF FVG
        if fvg.direction != ob.direction:
            continue
        if fvg.tf not in allowed_ltfs:
            continue
        # Overlap с drop/rally area (хотя бы частичный)
        if not _intervals_overlap(fvg.zone, target_zone):
            continue
        # Spatial range: FVG.zone ⊆ [low_ob_vc, first_FH.high] для LONG (зеркально для SHORT)
        extreme = first_extreme_level.get(fvg.tf)
        if extreme is None:
            continue  # нет противоположного фрактала на этом LTF
        if ob.direction == "long":
            if fvg.zone_hi > extreme:
                continue  # FVG выше первого FH — вне диапазона
        else:
            if fvg.zone_lo < extreme:
                continue
        fvg_components.append(fvg)

    if not fvg_components:
        return None

    return OBVC(
        tf=ob.tf,
        direction=ob.direction,
        zone=ob.zone,
        fvg_components=fvg_components,
        born_ts=ob.born_ts,  # OB-born; first valid FVG момент можно хранить отдельно
    )
```

## Связи

- [[Правило 3]] — VC канон (предикатная форма этой же концепции)
- [[Правило 8]] — таксономия классов
- [[Правило 2]] — wick-fill mitigation
- `~/smc-lib/elements/ob/` — базовый OB
- `~/smc-lib/elements/fvg/` — базовый FVG
- `~/smc-lib/vc/` — VC как предикат

## TODO

- [ ] `code.py` — реализовать `detect_ob_vc(...)` по псевдокоду выше
- [ ] Решить интеграцию в `prediction-algo/zones.py` `ALL_TYPES` (как отдельный type, или derived feature)
- [ ] Тесты на 5 разных HTF (3D, D, 12h, 4h, 2h) с реальными BTC-данными
- [ ] Backtest качества: даёт ли `ob_vc` lift над одиночным OB по P_hit_D?
- [ ] Решить mitigation для отдельных FVG-components: трекать или игнорировать?
