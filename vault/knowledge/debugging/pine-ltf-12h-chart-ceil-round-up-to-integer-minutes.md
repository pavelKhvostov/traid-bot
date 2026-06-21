---
tags: [debugging, pine, vic, ltf, indicator]
date: 2026-05-21
related: [[vic-maxv-расходился-с-pine-индикатором-из-за-1m-вместо-15m]], [[vic-asvk-indicator-python]]
---

# Pine LTF на 12h-chart — ceil round-up до integer-minute, не closest valid

Pine `timeframe.from_seconds(seconds)` на **12h-chart** (и других не-D
chart-ах с нестандартным результирующим LTF) использует **ceil-up до
ближайшей целой минуты**, а не closest valid TF из стандартного набора.

## Что было

ViC ASVK (`research/vic_vadim/`) на 12h-chart с auto=true, mlt=100:
- `tfC = 43 200s` (12h)
- `rs = max(60, 43200/100) = 432s = 7.2 min`
- `res = timeframe.from_seconds(min(43200, 432)) = ?`

Ожидалось: closest valid из {5m, 10m} — теоретически 5m (Δ132 < Δ168).

**Фактически Pine возвращает "8" (8-минутный non-standard TF)**: ceil(432/60).

## Сверка с индикатором

Сверено 2026-05-21 на 6 свечах BTC 14-17 мая 2026. **LTF=8m даёт расхождение
≤6 USD** на всех 6 свечах (суммарная ошибка 12 USD). Остальные LTF (1m, 5m,
7m, 10m, 15m) дают большие расхождения (десятки/сотни USD).

| LTF | Σ |Δ| на 6 свечах |
|-----|-------------------|
| 8m  | **12 USD** ★ |
| 9m  | 267 USD |
| 11m | 603 USD |
| 10m | 719 USD |

## Универсальное правило для не-D chart

```python
import math

# На любом chart-TF tfC (seconds) с заданным mlt:
rs = max(60, tfC / mlt)  # non-premium clamp
ltf_minutes = math.ceil(rs / 60)
```

## Примеры на 12h-chart

| mlt | rs(s) | LTF (Pine) |
|-----|-------|------------|
| 30  | 1440  | 24m |
| 45  | 960   | 16m |
| 50  | 864   | 15m |
| 55  | 785   | 14m |
| 80  | 540   | 9m |
| 100 | 432   | **8m** |
| 145 | 298   | 5m |
| 200 | 216   | 4m |

## Где можно нарваться

- При репликации **любого Pine ASVK ViC**, AlphaTrend, custom volume или
  liquidity-indicator на чартах ≠ D.
- Особенно critically для **12h, 6h, 3h** chart-ов, где rs/60 редко
  совпадает с целым числом минут.

## Правило избегания

1. При репликации Pine на не-D chart: использовать `ceil(rs/60)` для LTF.
2. Просить у пользователя 2-3 контрольных значения из TV для сверки на
   первой свече до прогона на всём окне.
3. Для **D-chart** правило **уточнено 2026-06-04**:
   - `rs/60` IS integer → exact `rs/60`m custom TF (как 12h-chart rule)
   - `rs/60` NOT integer → closest valid из {1,3,5,10,15,30,45,60,...}m
   - Пример integer: mlt=45 + D → rs=1920, rs/60=32 → **LTF=32m** (НЕ 30m!)
   - Пример non-integer: mlt=100 + D → rs=864, rs/60=14.4 → LTF=15m closest
   См. [[vic-maxv-расходился-с-pine-индикатором-из-за-1m-вместо-15m]] (non-integer case).

## Связи

- [[vic-maxv-расходился-с-pine-индикатором-из-за-1m-вместо-15m]] —
  родственный pitfall для D-chart (closest valid → 15m).
- [[vic-asvk-indicator-python]] — Python-портов индикатора.
- [[стратегия ViC Vadim 12h вариант 1]] — стратегия, где это правило
  критично (LTF=16m для оптимума mlt=45).
