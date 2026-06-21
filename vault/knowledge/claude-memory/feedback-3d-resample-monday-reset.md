---
name: feedback-3d-resample-monday-reset
description: "3D resample использует Unix epoch (1970-01-01 Thu) как anchor (Sat/Tue/Fri/Mon/Thu/Sun/Wed continuous 72h), НЕ Monday-anchor (2017-01-02). Иначе 3D bars съезжают с TV-канона."
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 935dc13c-ff07-4b9a-8e0d-e35a63c1d0be
---

# 3D resample — Unix epoch anchor (TV-канон)

**Правило:** Для 3D resample использовать `origin = pd.Timestamp("1970-01-01", tz="UTC")` (Unix epoch, Thursday). НЕ использовать `MONDAY_ANCHOR = 2017-01-02 (Mon)`, который применяется для остальных TFs.

**Why:**
- TV/SMC канон для 3D — continuous 72h bars анкорные к Unix epoch
- 2017-01-02 (Mon) не лежит на эпохальной 72h сетке (3346 days % 3 = 1)
- Из-за этого MONDAY_ANCHOR смещает 3D bars на 1-2 дня от TV: вместо Sun/Wed/Sat/Tue/Fri/Mon/Thu (TV-канон) получаем Mon/Thu/Sun/Wed/Sat/Tue/Fri (сдвинуто)
- 3-недельный цикл совпадает с Mon, но в промежутке bars не там где надо

**Проверка canon dates (от Unix epoch):**
```
2026-01-31 (Sat) — days 20484 % 3 = 0 ✓
2026-02-03 (Tue) — days 20487 % 3 = 0 ✓
2026-02-06 (Fri) — days 20490 % 3 = 0 ✓
2026-03-02 (Mon) — days 20514 % 3 = 0 ✓
```

**How to apply:**
- В `~/smc-lib/prediction-algo/resample.py`: 3D берёт `origin = EPOCH_ANCHOR`, остальные TFs — `MONDAY_ANCHOR`
- 3D bars регулярные 72h, поэтому `tf_to_timedelta("3d")` корректно работает (без special-case в zones.py)
- 1W остаётся на Monday-anchor (W = Mon-Mon, see [[weekly-tf-anchor-monday]])
- 2D потенциально имеет ту же проблему (48h × 7 ≠ 168h), но user не подтвердил canon — оставить как есть до запроса

**Старая ошибка (исправлено 2026-06-03):**
Изначально я предположил weekly-reset для 3D (Mon/Thu bars only с merged Sunday). Это неверно — 3D НЕ имеет weekly reset, просто continuous 72h от epoch-anchor.

**Реализация:**
- `resample.py`: `EPOCH_ANCHOR` константа; `resample_one()` выбирает origin per TF (3d → EPOCH, остальные → MONDAY)
- `zones.py`: НЕ требует special-case (3D bars регулярные)

**Влияние на прошлые анализы:**
- 3D анализы до 2026-06-03 использовали сломанный MONDAY_ANCHOR — невалидны
- 3D zones (OB / FVG / fractal / RDRB) born_ts которые не лежат на epoch-сетке (Sun/Wed/Sat/Tue/Fri/Mon/Thu от epoch) — фантомы
- Force-model v2 coefficients на 3D требуют пересчёта

**Связи:**
- [[weekly-tf-anchor-monday]] — W bars Monday-anchor (canon for 1W, не для 3D)
- [[force-model-v2-architecture]] — был построен на сломанных 3D bars; нужно перетренировать
