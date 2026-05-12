---
tags: [debugging, look-ahead, strategy_1_1_6]
date: 2026-05-06
status: resolved
related: [[strategy-1-1-1-look-ahead-15min-vs-tf_duration]], [[strategy_1_1_6]]
---

# Strategy 1.1.6: htf-FVG поиск стартовал до закрытия cur macro-OB

## Симптом

Первый прогон 1.1.6 на 3y BTC дал WR 27.3% / −10R на 22 closed
(135 raw → 115 deduped). Числа не RED FLAG (WR < 60%), но
пользователь сверил конкретный сигнал на TV и нашёл аномалию.

Сигнал 2026-02-14 LONG (CSV строка 108):
- top: FVG-12h, c2_time=2026-02-14 03:00 → c2_close=2026-02-14 15:00
- macro: OB-6h, cur_time=**2026-02-16 21:00** → **cur_close=2026-02-17 03:00**
- htf: FVG-1h, c2_time=**2026-02-17 00:00** ← за 3 часа ДО cur_close 6h

То есть htf-реакция формировалась **до того**, как cur-свеча
macro-OB вообще закрылась. В реальном времени на 02-17 00:00 мы
ещё не знаем, какой close у 6h-свечи 21:00-03:00 — она ещё
формируется. Использовать её как «структурный анкер» = lookahead.

## Причина

`find_first_fvg_htf_in_zone` в [strategies/strategy_1_1_6.py](../../../strategies/strategy_1_1_6.py):

```python
# БЫЛО:
htf_hours = 1 if htf_label == "1h" else 2
htf_start = ob_macro.cur_time + pd.Timedelta(hours=htf_hours)
```

Длительность бара выводилась из **ТФ поиска** (1h/2h), а должна
из **ТФ candidate-структуры** (4h/6h). На 6h-macro+1h-htf:
- БАГ: htf_start = 21:00 + 1h = 22:00 (искал htf-FVG с 22:00)
- ПРАВДА: htf_start = 21:00 + 6h = 03:00 следующего дня

Конкретно для 14 февраля кейс попал в окно 22:00 — 03:00, где
htf-FVG нашлась в 00:00 — 3 часа лишнего lookahead.

## Идентичность с уже-известным bug'ом

Это **тот же класс ошибки**, что
[[strategy-1-1-1-look-ahead-15min-vs-tf_duration]]: длительность
бара хардкодилась/выводилась из неправильного контекста.

| Bug | 1.1.1 | 1.1.6 |
|---|---|---|
| Где | `simulate_outcome` fill-scan | `find_first_fvg_htf_in_zone` |
| Что использовалось | `+15min` хардкод (для 20m FVG нужно `+20min`) | `+htf_hours` (1 или 2) |
| Что должно использоваться | `tf_minutes` из `sig["fvg_tf"]` | `macro_hours` (4 или 6) |
| Источник правды | Метаданные сигнала | Параметр функции (макро-ТФ) |

## Фикс (2026-05-06)

```python
# СТАЛО:
def find_first_fvg_htf_in_zone(
    df_htf, fvg_top, ob_macro, search_start,
    macro_hours: int,    # ← добавлен параметр
    htf_label,
):
    htf_start = ob_macro.cur_time + pd.Timedelta(hours=macro_hours)
```

В вызывающем коде в `_scan_top` после выбора macro:
```python
macro_hours = 4 if macro_tf == "4h" else 6
htf_1h = find_first_fvg_htf_in_zone(df_1h, fvg_top, ob_macro, search_start,
                                     macro_hours, htf_label="1h")
```

## Эффект

| | До fix | После fix |
|---|---|---|
| Raw | 141 | 135 |
| Deduped | 115 | 111 |
| Closed | 22 | 15 |
| NO_ENTRY | 93 | 96 |
| WR | 27.3% | 33.3% |
| PnL | −10R | −5R |
| R/trade | −0.455 | −0.333 |

7 «магических» сигналов вычистились. Из них, видимо, большинство
было убыточными (поскольку PnL улучшился на +5R при потере 7
сделок — это в среднем −0.71R/удалённая сделка, что хуже общего
R/trade −0.455). То есть lookahead **не давал ложного edge'а**, но
давал лишний шум, который размазывал статистику.

После fix'а стратегия всё равно отрицательная (-5R, WR 33%),
но числа теперь честные.

## Тесты сначала упали

После применения fix'а 4 из 6 unit-тестов упали:
- test_happy_path_long_via_1d_4h_1h: 0 == 1 (нет сигнала)
- test_happy_path_short_via_1d_4h_1h: то же
- test_earliest_wins_macro_by_cur_close_not_cur_time: то же
- test_rr_equals_one_exact_equality: то же

Фикстуры строились на ошибочной логике (`cur_time + 1h`).
По правилу «не подгонять фикстуру, разобраться где правда» —
вижу что фикстуры были неправильные, **сдвинул htf-FVG свечи**:
для 4h-macro с 09-11 на 12-14, для 6h-macro с 07-09 на 12-14.

После исправления фикстур все 6 тестов зелёные. Это правильный
сигнал что fix корректен — старые тесты были «зелёные ложно».

## Правило избегания (для всех multi-TF cascades)

**Длительность бара candidate-структуры → smещение search_start.**
Не ТФ поиска, не ТФ родителя в дереве — именно **той структуры**,
которая должна быть полностью сформирована до начала поиска
реакции на неё.

Pattern для будущего:
```python
# Любой переход из ТФ-уровня A в ТФ-уровень B (где B быстрее A):
search_start_for_B = candidate_A.cur_time + Timedelta(hours=A_hours)
                                              # ^^^^^^^
                                              # длительность A, не B
```

В 1.1.1 это сделано правильно:
- top → macro: `ob_top.cur_time + top_tf_hours` (24 для 1d, 12 для 12h) ✓
- macro → htf: `cur_top.cur_time + (top_tf_hours - htf_hours)` ✓

В 1.1.6 нужно было: `ob_macro.cur_time + macro_hours`. **Теперь сделано.**

## Источник

Замечен пользователем при ручной TV-сверке сигнала 2026-02-14
после первого прогона. Подтверждение того, что **визуальная
сверка с TV — критический шаг** при появлении новой стратегии,
автоматические тесты не покрывают такой класс ошибок (они проверяют
конкретные числа на синтетических фикстурах, которые тоже могут
скрывать ту же грабли).

## Связи

- [[strategy_1_1_6]] — обновлённый spec
- [[strategy-1-1-1-look-ahead-15min-vs-tf_duration]] — родственный bug
- [[known-pitfalls]] — добавлен 10-й pitfall
- [[2026-05-06-strategy-1-1-6-первый-прогон]] — session note
