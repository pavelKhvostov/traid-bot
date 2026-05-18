---
tags: [debugging, live-bot, lookahead, multi-scanner]
date: 2026-05-13
---

# Live-сканеры отправляли сигналы из предыдущих часов

## Что было

В `strategy_1_1_1_scanner.py` и `multi_strategy_scanner.py`:

```python
MAX_SIGNAL_AGE_HOURS = 2
sig_time = sig["signal_time"]  # = fvg_entry.c2_time (OPEN бара)
age = pd.Timestamp.now(tz="UTC") - sig_time
if age > pd.Timedelta(hours=MAX_SIGNAL_AGE_HOURS):
    silenced
```

## Симптом

Пользователь явно потребовал: бот должен отправлять ТОЛЬКО сигналы, образовавшиеся в текущий час.

При проверке найдено:
- **15m FVG c2_open=12:30 (c2_close=12:45)** при 1h close 14:00 имеет age=1.75h по c2_open → проходит фильтр, хотя сигнал из ПРЕДЫДУЩЕГО часа.
- **2h FVG свежий** (c2_open=12:00, c2_close=14:00) при 1h close 14:00 имеет age=2h. WS delay 100ms → age=2h+ε → silenced. **Систематически блокирует 2h FVG**.

## Причина

1. `signal_time = fvg_entry.c2_time` это OPEN бара, не CLOSE. Для 2h FVG разница 2 часа.
2. `MAX_SIGNAL_AGE_HOURS = 2` слишком вольное окно — пропускает сигналы из предыдущих часов.
3. Не привязано к 1h boundary.

## Правило избегания

При фильтрации live сигналов по "freshness":
- Использовать `c2_CLOSE = signal_time + tf_duration` для measure
- Проверять попадает ли c2_close в текущий 1h-час: `(current_hour_close - 1h, current_hour_close]`
- `current_hour_close = pd.Timestamp.now('UTC').floor('h')`
- Для разных FVG TF (15m, 20m, 1h, 2h) делать раздельный duration lookup

## Fix (2026-05-13)

```python
FVG_TF_MINUTES = {"15m": 15, "20m": 20, "1h": 60, "2h": 120}

current_hour_close = pd.Timestamp.now(tz="UTC").floor("h")
prev_hour_close = current_hour_close - pd.Timedelta(hours=1)

for sig in signals:
    sig_time = pd.Timestamp(sig["signal_time"])
    if sig_time.tz is None: sig_time = sig_time.tz_localize("UTC")
    fvg_tf = sig.get("fvg_tf", "15m")
    tf_min = FVG_TF_MINUTES.get(fvg_tf, 15)
    signal_close = sig_time + pd.Timedelta(minutes=tf_min)

    if not (prev_hour_close < signal_close <= current_hour_close):
        mark_sent(key, {"stale_outside_current_hour": True, ...})
        continue
```

Применено в `strategy_1_1_1_scanner.py` и `multi_strategy_scanner.py`.

## Источник

[[2026-05-13-live-bot-vic-ifvg-strategies-117-118]] — session note
