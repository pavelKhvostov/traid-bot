# Решение: lowercase частоты в `tf_to_pandas_rule`

**Дата:** 2026-04-22
**Фаза:** Phase 0, Wave 2
**Статус:** Принято

## Контекст

`src/core/data_loader.py::tf_to_pandas_rule` мигрирован из `reference/obxxx.py:133-148`.
В исходнике функция возвращает uppercase частоты для `pandas.DataFrame.resample`:

```python
# reference/obxxx.py (оригинал)
def tf_to_pandas_rule(tf: str) -> str:
    # ...
    return "3H"  # или "2D", "1H" и т.п.
```

В проекте установлена **pandas 3.0.2**. Попытка вызвать `df.resample("3H", origin="epoch")`
падает с:

```
ValueError: Invalid frequency: 3H
```

## Причина

Pandas начал deprecation цикла для uppercase суффиксов частот с версии **2.2**:

- pandas 2.2.0 (2024-01) — `FutureWarning` на `"H"`/`"D"`/`"M"`/etc.
- pandas 3.0.0 — uppercase удалены, только lowercase: `"h"`, `"d"`, `"min"`, `"s"`, `"ms"`.

Источники:
- pandas 2.2 changelog: https://pandas.pydata.org/docs/whatsnew/v2.2.0.html#deprecations
- Конкретный PR удаления: pandas-dev/pandas#55877

Таблица замен (из pandas docs):

| Старая (deprecated) | Новая (pandas 2.2+) |
|---|---|
| `"H"` | `"h"` |
| `"D"` | `"d"` |
| `"T"` / `"min"` | `"min"` |
| `"S"` | `"s"` |
| `"M"` (month-end) | `"ME"` — особый случай |

## Решение

`tf_to_pandas_rule` возвращает **lowercase**:

```python
# src/core/data_loader.py (Wave 2)
def tf_to_pandas_rule(tf: str) -> str:
    # ...
    return "3h"  # или "2d", "1h" и т.п.
```

- Логика агрегации (`origin="epoch"`, OHLCV rules, `bar_count` filter) идентична исходнику.
- Результат `resample` pandas не различает по регистру внутри себя — только парсер строки частоты.
- Тесты `test_compose_3h_from_1h_with_full_3_bars` и `test_compose_3h_drops_incomplete_bar`
  проходят на pandas 3.0.2.

## Последствия

- **Минимальная версия pandas в `pyproject.toml`:** `pandas>=2.2`. При обновлении
  зависимостей не откатываться ниже — функция сломается.
- **Обратная совместимость с pandas 1.x / 2.0 / 2.1 потеряна** (там lowercase `"3h"` был
  `FutureWarning` → может работать, но с предупреждением). Проект таргетит только 2.2+.
- **Если понадобится сравнить с оригинальным `obxxx.py` на pandas 1.x** — оригинал сработает
  с uppercase, наш код — нет. Это осознанно: мы не поддерживаем pandas 1.x.

## Связанные TODO

`pd.Timestamp.utcnow()` в `data_loader.py:125` тоже deprecated в pandas 4.
Отложено до Phase 4 — см. комментарий в коде:
`# DEPRECATED pd.Timestamp.utcnow(): fix in Phase 4 per decision 2026-04-22`.

Когда будем чистить — заменить на `pd.Timestamp.now("UTC")` и убрать костыль в `_now_utc`.
