---
tags: [session, smc, vc, rules, fractal, or-basket, asvk]
date: 2026-05-26
related: [[2026-05-26-vc-concept-canon-in-smc-lib-and-f5-search]], [[что такое VC volume confirmation]], [[12h-fractal-filter-F1-F2]]
---

# 2026-05-26 — VC: 3 варианта, rules.md (Правила 1–5), фрактальный OR-basket

Продолжение утренней сессии [[2026-05-26-vc-concept-canon-in-smc-lib-and-f5-search]]. Фокус: формализация **rules.md** в `~/smc-lib/` и переход на **OR-basket-методологию** для 12h фракталов.

## I. rules.md — добавлены Правила 2, 3, 4, 5

`~/smc-lib/rules.md` — общие рыночные правила, применимые ко всем элементам.

| # | Правило | Статус | Источник |
|---|---|---|---|
| 1 | Закрепление цены за уровнем (2 close) | canon | пред. |
| 2 | Заполнение зоны интереса (mitigation: wick-fill / first-touch / sweep) | canon | вынесено из `zone_of_interest.md` |
| 3 | **VC (Volume Confirmation)** — 3 варианта (см. §II) | canon | сегодня |
| 4 | LTF FVG усиливает HTF OB | partial (бинарно, aligned only; связь с П3 — позже) | сегодня |
| 5 | **Основная стратегия ASVK** (VC внутри HTF ZoI) | canon | сегодня |

### Правило 5 — ASVK основная стратегия

Принцип:
1. HTF-движение формирует HTF ZoI (OB / block_orders / RDRB POI)
2. Цена возвращается в ZoI (mitigation по [[Правило 2]])
3. Внутри ZoI на LTF появляется VC того же направления ([[Правило 3]])
4. Entry в направлении HTF-движения
5. Continuation

Пример (find_rule5_asvk_examples.py): BTC 2026-03-23 02:00 MSK
- 1h LONG OB [67361, 68339]
- Pullback 09:36 → 11:00
- 15m LONG FVG [68000, 68282] ⊆ OB.zone (V1 VC)
- Continuation +5.85% за 48h, drawdown ~0
- Chart: `~/Desktop/i-rdrb-charts/rule5_asvk_example.png`

Стратегия **1.1.1** — конкретная инстанциация Правила 5 для LONG.

## II. VC — 3 канонических варианта (Правило 3)

VC реализуется **тремя вариантами**. Два класса:

### Spatial containment (FVG внутри HTF OB)

| Variant | OB TF | FVG TF | Геометрия |
|---|---|---|---|
| V1 | 1h, 2h | 15m, 20m | `FVG.zone ⊆ OB.zone` |
| V2 | 4h, 6h | 1h, 90m, 2h | `FVG.zone ⊆ OB.zone` |

### Temporal sequence (FVG сразу после OB на том же TF)

| Variant | OB TF | FVG TF | Геометрия |
|---|---|---|---|
| V3 | 1h, 2h | **same TF** | `FVG.c1 = OB.cur+1` (NO containment) |

**Direction:** все варианты — aligned (`OB.dir == FVG.dir`).

**Семантика V3:** OB сработала как launchpad → следующая свеча запускает impulse → displacement → gap. FVG обычно ВНЕ OB.zone (above для LONG / below для SHORT), т.к. цена выкинута из зоны.

Пример V3 (скриншот пользователя 2026-05-26 15:27): bear OB.prev → bull OB.cur → bull FVG.c1 → huge bull FVG.c2 (displacement) → FVG.c3. FVG.zone выше OB.zone.

### Сводный предикат

```
VC(OB, FVG) := OB.dir == FVG.dir AND (
    (FVG.zone ⊆ OB.zone)                                  # V1, V2 (spatial)
    OR
    (FVG.c1 = OB.cur+1 AND OB.tf == FVG.tf AND OB.tf ∈ {1h, 2h})  # V3 (temporal)
)
```

⚠️ Код `~/smc-lib/elements/vc/code.py` пока реализует только V1/V2 (containment). V3 — нужно расширить API.

Полный canon: [[что такое VC volume confirmation]].

## III. OR-basket методология для 12h Pred-фракталов

### Архитектурный сдвиг (утверждён сегодня)

Раньше: AND-cascade (F1∩F2∩F3∩F4∩F5...) — терял important pivots при каждом доп. фильтре.

Сейчас: **OR-basket** поверх baseline F1∩F2∩F3:

```
in_basket := pivot ∈ F1∩F2∩F3  AND  (C1 OR C2 OR C3 OR ...)
```

Каждое условие — **независимое** на полном baseline 1266. Цель: recall **18/18** imp через union условий.

### Baseline (зафиксирован сегодня)

| | n | conf | not conf | P(W) | imp |
|---|---:|---:|---:|---:|---:|
| F1∩F2∩F3 | 1 266 | 619 | 647 | 48.9% | 18/18 |

### Условие 1 = sweep maxV(i-1) на 1m

| keep | conf | not | P(W) | Δ | imp |
|---:|---:|---:|---:|---:|---:|
| 356 | 268 | 88 | **75.3%** | +26.4 | 5/18 |

### Условие 2 = union P11_count {8,12,16,24}×15m direction-matched

P11_count = доля 15m свечей за окно, направленных ПРОТИВ pivot (FH → bearish closes; FL → bullish).

| Компонент | keep | conf | not | P(W) | imp |
|---|---:|---:|---:|---:|---:|
| P11_8×15m ≥ 0.65 (2h) | 143 | 107 | 36 | 74.8% | 5 |
| P11_12×15m ≥ 0.75 (3h) | 62 | 46 | 16 | 74.2% | 2 |
| P11_16×15m ≥ 0.65 (4h) | 86 | 60 | 26 | 69.8% | 3 |
| P11_24×15m ≥ 0.65 (6h) | 60 | 44 | 16 | 73.3% | 1 |
| **Union (Условие 2)** | **193** | **141** | **52** | **73.1%** | **5/18** |

### Корзина после Условий 1 + 2

| | n | P(W) | imp |
|---|---:|---:|---:|
| Basket = (C1 ∪ C2) | **463** | 71.9% | **8/18** |
| Остаток (в работе) | 803 | 35.6% | **10/18** |

### 10 непойманных imp (требуют новых условий с WR≥70%)

| # | MSK | dir | dist_ema200 |
|---|---|---|---:|
| 3 | 2026-02-08 15:00 | high | −22.84% |
| 10 | 2026-02-25 15:00 | high | −19.41% |
| 11 | 2026-02-28 03:00 | low | −23.55% |
| 14 | 2026-03-04 15:00 | high | −11.51% |
| 15 | 2026-03-08 15:00 | low | −18.71% |
| 23 | 2026-03-22 15:00 | low | −13.70% |
| 26 | 2026-03-25 03:00 | high | −8.36% |
| 29 | 2026-03-29 15:00 | low | −14.66% |
| 47 | 2026-04-29 15:00 | low | +0.19% |
| 48 | 2026-05-06 03:00 | high | +8.62% |

8 из 10 имеют `dist_ema200 ≤ −5%` (drawdown context). 2 outliers (#47, #48) — у/выше EMA200. Все из периода 2026-02-04 ... 2026-05-06.

### Кандидаты Условия 3 — НЕ нашли WR≥70%

Попробованы single & combo features (dist_ema200 / opp_wick / close_pos / EVoT placements P1–P12). Ни одна standalone-конфигурация WR ≥ 70% AND ловит ≥1 missed imp.

**Лучшее**: `dist_ema200 ≤ −5%` → keep=400, P=47.8%, **catches_missed=8/10** (но WR ниже baseline).

### Что отвергнуто как Условие N (полный список)

| Кандидат | Best result | Решение |
|---|---|---|
| C1 старой стратегии = sweep_FH/FL OR OB_sweep на {12h,D,2D,3D,W} | 401 / 57.1% / 6 imp | НЕ ≥70%, не добавлен |
| EVoT(rNorm) W1/W2/W3 (full pivot bar / sliding) | 145 / 75.9% / 2 imp | overlap с maxV, не вернёт imp |
| EVoT P1_post_extr | макс 53% / 18 imp | слабо |
| EVoT P2_last_Kh | 146 / 79.5% / 2 imp (last 6h ≥0.10) | overlap с maxV |
| EVoT P5_first_Kh | 46-48% | анти-сигнал |
| EVoT P6_pre_ext / P7_post_ext / P10_prev_full | ≤53% | слабо |
| EVoT P8_around_ext ±2h ≥+0.10 | 58 / 72.4% / 1 imp | мал. выборка |
| EVoT P9_prev_lastKh (на баре i-1) | ≤55% | нейтрально |
| Climax + reversal divergence (pre/post extremum) | ≤49.5% | не работает |
| dist_ema200 ≤ X% (любые пороги) | макс 49.3% (≤−7%) | WR < 70% |
| opp_wick ≤ 0.10 | 360 / 52.2% / 7 missed | WR < 70% |
| dist_ema200 ≤ −5% AND opp_wick ≤ 0.15 | 186 / 46.2% / 6 missed | WR ниже baseline |

## IV. Решения и правила архитектуры (записаны в memory)

1. **[[feedback-12h-fractal-baseline-f1f2f3]]** — статистику Pred-фракталов начинать с F1∩F2∩F3 = 1266/48.9%/18/18; не разворачивать от raw bars.
2. **[[feedback-12h-fractal-or-basket-arch]]** — после F3 условия параллельные (OR), не AND-cascade; recall 18/18 — обязательное требование.
3. Условия добавляются в корзину **только при WR≥70%** standalone на baseline (утверждено сегодня).

## V. Открытые задачи

- **Правило 4 vs Правило 3** — связь не определена (пользователь ответит позже)
- **VC v3 в коде**: расширить `~/smc-lib/elements/vc/code.py` для поддержки V3 (temporal sequence)
- **Условие 3 для 12h фракталов**: не найдено standalone WR≥70%, ловящего 10 missed imp. Возможные направления:
  - Mining оставшихся LTF/HTF sweep-варианты (LTF Williams fractal sweep, HTF iFVG sweep, LTF OB sweep) — `pred12h_cond3_mining_wr70.py` подготовлен, не запущен
  - Альтернатива: посчитать union strong-but-overlapping conditions, принять снижение WR ниже 70% для conditions, ловящих outliers (#47, #48)
- **Side-quest baseline 1.1.1** (i-RDRB+FVG anti-filter, отложено с 2026-05-25)

## Артефакты

- `~/smc-lib/rules.md` — Правила 1, 2, 3 (3 варианта), 4 (partial), 5
- `~/smc-lib/elements/vc/definition.md` — расширено V1, V2, V3
- `~/smc-lib/scripts/`:
  - `find_rule5_asvk_examples.py` + `plot_rule5_example.py` (chart)
  - `pred12h_C1_C2_orbasket.py` — старые C1/C2 на baseline
  - `pred12h_evot_condition.py` — EVoT W1/W2/W3
  - `pred12h_evot_ltf_condition.py` — EVoT placements P1–P5
  - `pred12h_evot_ltf_v2.py` — EVoT placements P6–P12 + climax
  - `pred12h_cond2_p11_union.py` — Условие 2 union
  - `pred12h_missed10_profile.py` — feature mining для 10 missed
  - `pred12h_cond3_candidates.py` — Условие 3 single + combo (нет WR≥70%)
  - `pred12h_cond3_mining_wr70.py` — широкий mining (подготовлен, не запущен)
- `~/Desktop/i-rdrb-charts/rule5_asvk_example.png`
- Скриншот VC v3 примера: `~/Desktop/Снимок экрана — 2026-05-26 в 15.27.06.png`

## Связи

- [[2026-05-26-vc-concept-canon-in-smc-lib-and-f5-search]] — утренняя сессия (VC introduction + F5 search)
- [[2026-05-25-irdrb-fvg-v2-block-orders-confluence]] — отложенная side-quest
- [[что такое VC volume confirmation]] — canon VC (обновлён сегодня)
- [[универсальные определения OB и FVG]] — базовые определения
- [[три класса зон ликвидность эффективность неэффективность]] — таксономия зон
