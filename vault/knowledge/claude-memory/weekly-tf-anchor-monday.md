---
name: weekly-tf-anchor-monday
description: "Weekly timeframe in traid-bot uses Monday 00:00 UTC anchor (TV-standard), not epoch."
metadata: 
  node_type: memory
  type: feedback
  originSessionId: bd69e36f-0485-4922-92c1-f1eee5815475
---

В проекте traid-bot **W (weekly) ТФ всегда считается с понедельника** —
TV-стандарт. Свеча W: пн 00:00 UTC → след. пн 00:00 UTC (в UTC+3 это
пн 03:00 → пн 03:00).

**Why:** проектный canon для 2d/3d использует `origin='epoch'` (1970-01-01,
четверг), но для W пользователь требует совмещения с TV (пн-пн). Подтверждено
2026-05-20 после моей ошибки при первой попытке compose W как 7D с
epoch-anchor (получились чт-чт свечи, не совпадающие с TV).

**How to apply:**
- При composeе W из LTF использовать `origin=pd.Timestamp("1970-01-05",
  tz="UTC")` (понедельник) — не `'epoch'`.
- В скриптах `research/`: добавить ветку — если freq=="7D"/"W", origin=Monday;
  иначе epoch.
- При показе пользователю time-of-close W-свечи всегда конвертировать в
  UTC+3 (см. [[display-time-in-utc-plus-3]]).
- Для 2d/3d по-прежнему `origin='epoch'` (там сетка совпадает с TV в UTC).
