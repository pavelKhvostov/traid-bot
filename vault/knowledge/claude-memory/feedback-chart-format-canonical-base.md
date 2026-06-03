---
name: feedback-chart-format-canonical-base
description: chart_format.md база утверждена 2026-05-27. Эталон-скрипт plot_chart_format_template.py — копировать как базу для всех новых plot-скриптов
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 3af6f0d9-c3ee-48ba-ae08-4c05d8c82af3
---

База chart_format в `~/smc-lib/chart_format.md` **утверждена** 2026-05-27 как канонический шаблон прорисовки графиков. Эталон — `~/smc-lib/scripts/plot_chart_format_template.py`.

**Why:** Пользователь явно сказал «сохрани эти настройки к графику в библиотеке. Теперь это база». Все новые plot-скрипты должны наследовать эти настройки, не изобретая свои.

**How to apply:**
- При создании нового plot-скрипта (`plot_*.py`) — копировать структуру из `plot_chart_format_template.py`, не менять базовые параметры. Сверху добавлять свои индикаторы / зоны / маркеры.
- Базовые правила (свечи, ось, заголовок, текущая цена, layout) — НЕ переопределять без явного запроса пользователя.
- Полная сводка утверждённых параметров — в [[../smc-lib/chart_format.md|chart_format.md]] (раздел «Сводка утверждённых параметров»).
- Авто-докачка 1m данных через `fetch_btc_1m_missing.py` — обязательна (см. [[feedback-always-fetch-1m-before-chart]]).
- TBD-секции (индикаторы цвета, зоны, сделки, легенда) — заполняются итеративно при новых задачах рендера.
