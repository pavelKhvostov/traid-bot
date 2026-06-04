---
tags: [debugging, pandas, data-manager]
date: 2026-06-03
---

# `compose_from_base(...).reset_index()` теряет имя 'time'

## Симптом

```python
df_12h = compose_from_base(df_1h, '12h')
df_12h = df_12h[(df_12h.index >= start) & (df_12h.index <= end)].copy()
df_12h = df_12h.reset_index()
df_12h['time']  # KeyError: 'time'
```

## Причина

`compose_from_base` использует `pandas.resample(rule, origin='epoch').agg(...)`.
Если у входного `base_df` индекс безымянный (что бывает после первого
`load_df` + срезов), то и результат resample имеет безымянный индекс. После
`reset_index()` колонка появляется без имени → доступ по `df['time']` падает.

## Воспроизведение

```python
import pandas as pd
idx = pd.date_range('2020-01-01', periods=100, freq='1h', tz='UTC')
df = pd.DataFrame({'open':1.0,'high':1.0,'low':1.0,'close':1.0,'volume':1.0}, index=idx)
df.index.name = None  # безымянный
df12 = df.resample('12h', origin='epoch').agg({'close':'last'})
out = df12.reset_index()
print(out.columns)  # Index(['index', 'close'])  ← имя стало 'index', не 'time'
```

## Правило избегания

После `compose_from_base(...).reset_index()` всегда явно ренеймить первую
колонку:

```python
df = compose_from_base(df_1h, '12h').reset_index()
if 'time' not in df.columns:
    df = df.rename(columns={df.columns[0]: 'time'})
```

Или просто работать через индекс без reset_index — большинство кода
проекта так и делает.

## Где сейчас защищено

- `research/elements_study/etap_172_bulkowski_patterns.py` — добавлен явный rename.

## Где может ещё стрельнуть

- Любой research-скрипт, делающий `compose_from_base().reset_index()`. Особенно
  в `research/elements_study/` где много standalone скриптов.

## История

- **2026-06-03** — поймано при первом запуске etap_172
  ([[2026-06-03-bulkowski-12-reversal-detectors-etap-172]]). Пять минут на фикс.
