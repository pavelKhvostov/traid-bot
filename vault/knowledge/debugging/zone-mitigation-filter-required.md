---
tags: [debugging, pitfalls, zones, fvg, ob]
date: 2026-05-19
related: [[known-pitfalls]], [[2026-05-19-rdrb-v2-babai-fractal-prediction]]
---

# Zone-interaction фильтр без учёта mitigation покрывает почти все бары

## Что было

В HH-предикторе на D BTCUSDT (сессия 2026-05-19, скрипт `_tmp_hh_zones.py`)
попытка использовать «свеча i пересекает зону SHORT FVG / SHORT OB-liq
на D/2D/3D/W» как фильтр **без учёта того, тронута ли зона ранее**.

## Симптом

| Условие | N (свечей) | % всех | Lift над базой |
|---|--:|--:|--:|
| FVG-overlap (SHORT, D/2D/3D/W) | 2 722 | 85% | ×1.04 (+0.6 pp) |
| Sweep high D/2D/3D | 1 798 | 56% | ×1.78 (+10.5 pp) |
| OB-liq overlap (SHORT, D/2D/3D) | 1 476 | 46% | ×1.12 (+1.6 pp) |
| (a) OR (b) OR (c) | 3 009 | **94%** | ×1.06 (+0.8 pp) |

Стэк с прежним фаворитом (ss+lh = 64.6%) не сдвигается с добавлением OR-условия.

## Причина

За 8.7 лет накопилось ~553 SHORT FVG зон через 4 ТФ + 64 SHORT OB-liq.
Старые зоны не «закрываются» в простой модели — почти любая текущая свеча
геометрически пересекает какую-нибудь из множества накопленных зон.
Условие вырождается в почти-тавтологию.

## Правило избегания

При использовании zone-overlap фильтра (FVG, OB, RDRB-зона и т.п.):
**обязательно** учитывать митигацию.

**Минимум — «первый touch»**: свеча i считается, только если она первая
D-свеча после формирования зоны, чей range пересекает её. Vectorized:

```python
def first_touch_indices(zones, idx_D, h_D, l_D):
    """Для каждой зоны → индекс первой D-свечи (после formation_t),
    чей range пересекает зону, или None если ни разу не тронута."""
    touch = []
    for formation_t, zb, zt in zones:
        start_k = idx_D.searchsorted(formation_t, side="left")
        if start_k >= len(idx_D):
            touch.append(None); continue
        ov = ~((h_D[start_k:] < zb) | (l_D[start_k:] > zt))
        touch.append(start_k + int(np.argmax(ov)) if ov.any() else None)
    return touch
```

## После фикса

| Условие | N | Lift |
|---|--:|--:|
| FVG first-touch (SHORT) | 354 (11%) | ×2.20 (+16.2 pp) |
| OB-liq first-touch (SHORT) | 59 (1.8%) | ×1.38 (+5.2 pp) |
| LONG OB-liq first-touch | 65 (2.0%) | **×3.59 (+35.5 pp)** ⚡ |

Топ-стэк: ss + lh + (fvg-ft | ob-ft) SHORT → **84.6% (11/13)**, lift ×6.3.

## Альтернативные стратегии митигации (если first-touch слишком узко)

- **«Активные зоны»**: не пробитые ценой за всё время (но first-touch — стандарт SMC).
- **«Свежие зоны»**: формировались в окне последних N баров.
- **Reset после полного прохождения зоны** — после first-touch зона может «перезаряжаться».

## Источник

Сессия [[2026-05-19-rdrb-v2-babai-fractal-prediction]]. Скрипты: `_tmp_hh_zones.py`
(до фикса) → `_tmp_hh_zones_active.py` (с first-touch).
