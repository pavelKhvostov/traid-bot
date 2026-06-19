# ob_vc 1h — проект библиотеки

**Создан:** 2026-06-15.
**Канон:** `~/smc-lib/elements/ob_vc/definition.md` (условия #1-#9).
**HTF:** 1h. **Допустимые LTF (по canon mapping):** 15m, 20m.
**Период данных:** 2020-01-01 → 2026-06-07.

## П.1 — Количество ob_vc 1h на BTC

| Метрика | Значение |
|---|---|
| **После канона #1-#8** (без consumption filter) | **7,775** unique events |
| **После канона #1-#9** (FVG не consumed на 1m) | **5,624** unique events |
| LONG (#1-#9) | 2,889 (51.4%) |
| SHORT (#1-#9) | 2,735 (48.6%) |

**Сравнение с 2h:** 1h даёт ~5.6k events против ~5.4k на 2h (#1-#9). Сопоставимо.

**LTF preference** (как в ob-vc-2h: 15m имеет приоритет, 20m — fallback):
- 15m выбрано: 6,225 FVG-components в 1h #1-#9
- 20m fallback: 389 FVG-components (≈7%)

## Источник данных

Slice'нут из `~/smc-lib/projects/ob-vc-2h/data/ob_vc_phase1_5*.parquet` (общий generator phase1 на всех 8 HTF):
- `data/ob_vc_1h_phase1.parquet` — #1-#8
- `data/ob_vc_1h_phase1_5.parquet` — #1-#9

⚠ **Унаследованный lookahead bug**: `born_ms = max(cur_close_ms, fvg_c3_close_ms)`, **без** учёта `fract_confirm_ms` (Williams N=2 confirmation). Реальное strict timing = `max(cur.close, c3.close, fract.confirm_ms)`. Потенциально 15-60 мин lookahead на 1h HTF (меньше чем 30мин-2ч у 2h из-за более коротких LTF). Фикс — в TODO.

## Структура проекта

```
ob-vc-1h/
  README.md          — этот файл
  data/              — 1h-only slices (phase1 + phase1.5)
  scripts/           — strict-timing fix, 24-types reclassify для 1h, TBM
  charts/            — visualization (24-types taxonomy для 1h)
  sessions/          — analysis logs
```
