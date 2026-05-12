---
tags: [debugging, lookahead, strategy-1-1-4, 2026-05-11]
date: 2026-05-11
---

# L3 не фильтровался против L1 invalidation — каскад продолжался на мёртвом макро

Критический баг в детекторе `detect_with_funnel` (etap_69) и `detect_4stage`
(etap_66). Найден при forensic-аудите портфеля B+F+J+K стратегии 1.1.4
(см. [[2026-05-11-strategy-114-bfjk-portfolio-bug-audit]]).

## Что было

В мульти-каскадной стратегии 1.1.4 макрозона FVG-d/12h **инвалидируется**,
если на её таймфрейме появится свеча, пробивающая FVG.top (для SHORT) или
FVG.bottom (для LONG). После инвалидации каскад должен прекращаться.

В коде проверка `l2_close > L1_active_end` была реализована **только для L2**
(OB-4h/6h). L3 (OB-1h/2h) и L4 (FVG-15m/20m) **не проверялись** против
инвалидации — могли формироваться уже после смерти макрозоны.

```python
# Старая версия (etap_69, etap_66):
for l2 in l2_zones:
    ...
    if l2_close > L1_active_end: continue   # ✓ проверка для L2

    l3_search_end = l3_search_start + l3_life  # ← НЕТ clamp по L1_active_end!
    for oj in range(j0, j1):
        l3 = l3_sorted[oj]
        ...
        # ← НЕТ проверки L3_close > L1_active_end!
        for ek in range(k0, len(fvgs_entry_sorted)):
            f_entry = fvgs_entry_sorted[ek]
            ...
            # ← НЕТ проверки L4 c2_close > L1_active_end!
```

## Симптом

При forensic-аудите portfolio B+F+J+K @ allow_multi=5:
- **24 из 186 raw-сетапов (~13%)** имели L3.close после L1 invalidation.
- На этих сетапах: **WR 21.1%, total -7R, avg -0.37R/trade** — то есть
  систематически проигрывают, как и должно быть в мёртвом контексте.
- Подмешивались в общий результат и **скрывали реальное качество стратегии**.

Конкретные примеры (chain B):
- 2022-01-13 16:00 SHORT, L1_dead=2022-01-13 12:00, L3 после смерти на 4ч
- 2023-05-31 01:00 LONG, L1_dead=2023-05-31 00:00, L3 после смерти на 1ч
- 2024-01-10 18:00 LONG, L1_dead=2024-01-10 12:00, L3 после смерти на 6ч

## Причина

Логика инвалидации применялась только к L2 потому, что L2 — единственный
уровень, у которого время поиска совпадало с временем жизни L1. L3 ищется
в окне `[L2_close, L2_close + l3_life]`. Если `l3_life > (L1_active_end -
L2_close)`, окно поиска L3 простирается **за пределы жизни L1**.

Дополнительный фактор: `allow_multi=5` (повторные каскады на одну L1).
Когда первый каскад уже сработал, поиск продолжался, ища ещё 4 сетапа.
В этом «продолжении» нередко попадались L3 за пределами L1.

## Фикс

`research/elements_study/etap_74_114_fixed_BFJK.py`:

```python
# Новая версия:
l3_search_end = min(l3_search_start + l3_life, L1_active_end)

for oj in range(j0, j1):
    l3 = l3_sorted[oj]
    ...
    if L3_close > L1_active_end: continue  # FIX

    for ek in range(k0, len(fvgs_entry_sorted)):
        f_entry = fvgs_entry_sorted[ek]
        ...
        if (f_entry["time"] + entry_td) > L1_active_end: continue  # FIX
```

Три точки проверки:
1. Clamp `l3_search_end` сверху по `L1_active_end` — поиск не идёт за пределы.
2. Явная проверка `L3_close > L1_active_end` на каждом L3-кандидате.
3. Проверка `f_entry c2_close > L1_active_end` на L4-кандидате (на всякий случай,
   хотя из логики `L4_c2_close <= L3_close` следует автоматически).

## Эффект на портфель B+F+J+K

| Метрика | До фикса | После фикса | Δ |
|---|---|---|---|
| closed | 167 | 115 | -52 |
| WR | 59.9% | **64.3%** | **+4.4%** |
| Total R | +133 | +107 | -26 |
| **avg R/trade** | +0.80 | **+0.93** | **+0.13** |
| 2024 WR | 67.5% | 77.8% | +10.3% |

**Total R упал, но качество выросло.** Total R снизился потому, что фикс
ограничил allow_multi=5 квоту — раньше она добивалась мёртвыми сетапами,
теперь часть L1-зон даёт <5 валидных сетапов.

## Правило избегания

**При любом многоуровневом каскаде с TTL/инвалидацией родительской зоны:
проверка валидности должна применяться на КАЖДОМ уровне, не только на L2.**

Шаблон:
```python
for fvg_top in fvgs_top:
    L1_active_end = compute_invalidation(fvg_top, df_top)

    for l2 in l2_zones:
        if l2_close > L1_active_end: continue   # уровень 2

        for l3 in l3_zones:
            if l3_close > L1_active_end: continue   # ← уровень 3 — НЕ забыть
            ...
            for l4 in l4_zones:
                if l4_c2_close > L1_active_end: continue   # ← уровень 4
                ...
```

**Дополнительно для multi-bar шаблонов:** scope валидности — это close
последнего бара формации, не open. Для FVG (3-bar) — `c2_time + tf_duration`.
Для OB (2-bar) — `cur_time + tf_duration`.

## Связи

- [[2026-05-11-strategy-114-bfjk-portfolio-bug-audit]] — родительская сессия
- [[strategy-1-1-4-bfjk-portfolio]] — финальная стратегия
- [[lookahead-anchor-confirm-окно-cur_open-cur_close]] — родственная грабля
  (тот же класс: не проверяется закрытость HTF при работе с LTF)
- [[universal формулы OB и FVG|универсальные определения OB и FVG]] — canon
- [[known-pitfalls]]
