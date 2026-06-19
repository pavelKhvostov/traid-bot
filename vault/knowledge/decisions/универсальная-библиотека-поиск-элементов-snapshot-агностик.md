---
tags: [decision, architecture, smc-lib, ml]
date: 2026-06-17
---

# Универсальная библиотека «поиск-элементов» — snapshot инвариантен, baseline проект-специфичен

## Контекст

Pipeline `живой-рынок` к 2026-06-17 дозрел до версий `event_detector_v11` + `snapshot_generator_v6`. Оба скрипта универсальны: ничего проектного в них нет, они применимы к любому будущему ML-проекту на SMC элементах. Нужно зафиксировать их в библиотеке и провести чёткую границу с baseline-уровнем проектов.

## Решение

Создан раздел `~/smc-lib/поиск-элементов/` с двумя universal-скриптами и журналом ошибок их разработки. Граница ответственности:

```
~/smc-lib/поиск-элементов/        ← universal (для всех проектов)
  ├─ event_detector_v11.py        — детектор 13 элементов × 8 TFs на истории
  ├─ snapshot_generator_v6.py     — per-anchor active-zone snapshot (±20% досягаемость)
  └─ ошибки.md                    — журнал 19 ошибок процесса разработки

~/smc-lib/projects/<name>/baseline/  ← project-specific (на каждом проекте свой)
  ├─ past/                        — past trajectory features (откуда цена пришла)
  ├─ forward/                     — asymmetric forward geometry (n_above/below, free_space)
  ├─ cluster/                     — current cluster identity (dominant_tf, n_tfs, role_mix)
  └─ labels/                      — forward_labeler, multi-stage hierarchical
```

## Чем оперирует библиотечный snapshot (universal)

| Per-row | Per-anchor |
|---|---|
| zone_id, element_type, tf, direction, role | anchor_ts, current_price |
| zone_lo/hi, last_active_lo/hi | |
| level, distance_signed_pct | |
| price_in_zone, dist_to_edge_pct | |
| age_ms, mit_pct | |

Scope: **±20%** от current_price (overlap filter — диапазон, в котором цена может оказаться в обозримом будущем). Никаких context aggregates, density counts, confluence flags.

## Чем НЕ оперирует библиотека (отложено на baseline проекта)

Раньше snapshot_v5/v6 содержал `in_2pct`, `ctx_n_active_{tf}` × 8, `ctx_n_in_zone_{tf}` × 8, `ctx_n_{BLOCK/INE/LIQ}_in2pct` × 3. Это **снимок «где цена СЕЙЧАС»** — бесполезно для ML, потому что цена там по определению. Плюс ±2% радиус забивается мелкими 15m/30m зонами без структурного смысла.

Удалено из v6. Перенесено на baseline-уровень с переосмыслением:

**Past trajectory** (откуда цена пришла):
- `path_direction_{Δt}`, `path_range_{Δt}`, `path_position_in_range_{Δt}` за 1h/4h/12h/1d
- `swept_zones_{tf}_{Δt}` — какие active zones цена пробила/sweep'нула на пути
- `entered_from_side` — снизу (тестит resistance) или сверху (тестит support)
- `bars_in_current_zone` — сколько 1h цена держится в текущей кластерной зоне

**Forward geometry** (куда может пойти, асимметрично):
- `n_zones_above_{tf}` / `n_zones_below_{tf}` — не симметричные counts
- `dist_to_nearest_above_{tf}` / `_below_{tf}`
- `free_space_above` / `_below` — дистанция до первой кластерной плотности
- `cluster_strength_above` / `_below` — масса (сумма TF weights)
- `dominant_tf_above` / `_below`

**Current cluster identity** (на каком линейном уровне цена сейчас):
- `current_cluster_id` (group по overlap)
- `current_cluster_dominant_tf`
- `current_cluster_n_tfs` (confluence depth)
- `current_cluster_role_mix` (BLOCK/INE/LIQ proportions)
- `current_cluster_age_max`

## Почему такая граница

1. **Library = инвариант.** Что есть в досягаемости — факт, не выбор. Не должен зависеть от проекта.
2. **Baseline = гипотеза.** Какие features описывают «куда цена пойдёт» — это исследовательский вопрос конкретного проекта (predictor / strategy / classifier).
3. **Снапшот ≠ trajectory.** [[ml-snapshot-not-trajectory]] — общий принцип. Snapshot — статика, trajectory — динамика. Их нельзя смешивать в одном слое.
4. **Конкретный момент времени неинформативен.** «Где цена СЕЙЧАС» = там, по определению. Информативно «откуда + куда».

## Применение к будущим проектам

Любой новый ML-проект на SMC:
1. Использует `event_detector_v11.py` без модификаций (или ветку для нового элемента).
2. Использует `snapshot_generator_v6.py` без модификаций.
3. Строит **свой** baseline-слой с past/forward/cluster features под задачу.
4. Cluster-aggregator (hierarchical multi-stage, ошибка #15 из журнала) — тоже на baseline уровне.

## Связанное

- [[2026-06-17-поиск-элементов-library-section-pc-upgrade]] — сессия где это сделано
- [[2026-06-17-живой-рынок-v8-v11-cleanup]] — pipeline эволюция до v11/v6
- [[ml-snapshot-not-trajectory]] — общий принцип
- [[feedback-zone-overlap-filter-canon]] — ±20% overlap, не center distance
