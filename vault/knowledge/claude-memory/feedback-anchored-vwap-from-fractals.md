---
name: feedback-anchored-vwap-from-fractals
description: "Validated recipe for \"VWAP от фракталов\" — anchored VWAP from confirmed pivot fractals, with display/color conventions"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: c2a93cd3-276b-4637-ad17-ca05219a1dfa
---

Когда пользователь просит "VWAP от фракталов" на ТФ X, применять следующий рецепт:

1. **Фрактал**: pivot с N_FRACTAL=2 свечами по бокам (на ТФ X). FH = локальный high, FL = локальный low.
2. **Подтверждение**: фрактал считается валидным только после `(N_FRACTAL + 1) * TF` мс с момента pivot-свечи — иначе он ещё может быть переписан.
3. **VWAP**: anchored, считается от 1m данных (`~/traid-bot/data/`), `pv = Σ close*volume`, `vol = Σ volume`. Якорь — timestamp pivot-свечи.

> ⚠️ **Каноническое правило построения VWAP (2026-05-26, для D-фракталов)**: см. Правило 6 в `~/smc-lib/rules.md`. Anchor — динамический в диапазоне свечи i+1, шаг 15m, переоценка на каждой новой свече по max composite. Cascade: 1h, 2h, 4h, 6h, 8h, 12h. Этот пункт перекрывает базовый recipe для D-фракталов.
4. **Дисплей-ТФ**: на один-два шага ниже ТФ фракталов (D-фракталы → рисовать на 4h свечах, 4h → на 15m). Так линии VWAP читаемы и пересечения видны.
5. **Цвета**: FH — градиент Reds (тёмный = свежий, светлый = старый), FL — градиент Greens. Маркеры якорей: ▼ для FH, ▲ для FL.
6. **Файлы**: PNG в [[charts-output-location]] (`~/Desktop/i-rdrb-charts/`), скрипты в `~/smc-lib/scripts/plot_*.py`.
7. **Время**: оси и логи в MSK ([[display-time-in-utc-plus-3]]), данные CSV — UTC.
8. **Текстовый вывод**: таблица якорь / VWAP_now / Δ от текущего close + краткий комментарий о support/resistance кластерах.

**Why:** Пользователь подтвердил рабочим этот формат на задаче "VWAP от 10 крайних D-фракталов" (2026-05-24). Шаблон-источник: `~/smc-lib/scripts/plot_fhfl_vwap_4h_2026_05_23.py`.

**How to apply:** При любой задаче вида "построй VWAP от <N> фракталов <TF>" / "VWAP от фрактала <дата>" — использовать этот рецепт без переспроса. Если пользователь не указывает количество — спрашивать.
