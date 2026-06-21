# 2026-06-04 — ViC maxV Force Model (5 условий) + Phase 0 ML pipeline

> **Цель сессии:** построить data-driven формулу силы maxV для использования как expert/signal. Перешли от эвристической AMP к подготовке ML pipeline по Lopez de Prado.

---

## 1. Финальная архитектура AMP формулы (5 условий)

```
AMP(maxV) = W_pos × W_age × W_virgin × W_broken × W_vol
                                                    +
                          Gaussian spread σ = R/2 (R = max(L−zone_lo, zone_hi−L))
```

### Условия и параметры (на сейчас — эвристика, нужна калибровка)

| # | Условие | Вопрос которое отвечает | Параметры |
|---|---|---|---|
| 1 | **W_pos** | «Где внутри свечи был max V — фитиль или тело?» | wick=1.5, body=0.7 |
| 2 | **W_age** | «Сколько maxV существует на карте?» | 1 + 0.3·ln(1+d/30) |
| 3 | **W_virgin** | «Цена возвращалась к уровню? Как давно?» | K=3, τ=7d, decay `1+(K−1)·exp(−t/τ)` |
| 4 | **W_broken** | «Был ли уровень сломан со strong follow-through на C2?» | 1.8 |
| 5 | **W_vol** | «Концентрированный объём или размазан?» | `(V/median_V_20) / (range/ATR_20)`, clip [0.5, 2.0] |
| σ | **Gaussian** | «Ширина зоны влияния вокруг LEVEL» | σ = R/2 (2σ-правило) |

Всего **9 калибруемых параметров** (без σ_factor=0.5 как канон).

---

## 2. Pattern: Broken Defense (Condition #4)

Найден и подтверждён на двух группах:

```
Group 1: 30-01 + 31-01 (failed defense @ 82k) → 3 мес → реакция 06-05 upper_wick @ 81,768
Group 2: 04-02 + 05-02 (failed defense @ 72k) → 3 дня → реакция 08-02 upper_wick @ 70,566
```

**Детектор:**
```python
def detect_broken_defense(C1, C2):
    if C1.maxV.position == "lower_wick":
        return C2.high > C1.maxV.level AND C2.close < C1.low
    if C1.maxV.position == "upper_wick":
        return C2.low < C1.maxV.level AND C2.close > C1.high
```

C1.maxV становится **broken defense POI** → ×1.8 boost.

На 6-месячном датасете BTC: **11/91 D-events** имеют этот паттерн.

---

## 3. Phase 0 — Регенерация D-only dataset (ВЫПОЛНЕНО)

### Исправленные баги старого master dataset

| Баг | Где | Фикс |
|---|---|---|
| **Lookahead 326/2457 touches** | старый touches anchor = LTF_close (внутри parent) | new anchor = `formed_ts + parent_TF_ms` (parent close) |
| **3D epoch anchor → phantom bars** | `anchor=0` для 3D | Должен быть `MON_ANCHOR` (Mon/Thu only). Для D epoch=midnight UTC корректен |
| **Triangular force бинарный** | Q10=0.59, Q30+=1.0 | Заменён на Gaussian σ=R/2: median 0.99, min 0.006, max 1.0 |
| **Нет TBM exit info** | только `label`, нет barrier hits | Добавлены `exit_ts`, `exit_price`, `holding_min` |
| **Нет concurrent labels** | sample_weight отсутствует | Lopez de Prado Ch 4: `1/n_concurrent`, median weight = 0.106 |

### Output: `~/Desktop/maxv_touches_D_clean.parquet`

```
172 touches из 183 D events (11 virgins без touch за окно)
P(+1) = 27.3%  P(-1) = 59.9%  P(0) = 12.8%
Median holding = 86h (3.5 дня)  
Concurrent labels median = 10 (high overlap)
TBM params: PT=1.5×ATR(20), SL=1.0×ATR(20), t1=12 D-bars
```

### Главный инсайт

**maxV touches чаще ПРОБИВАЮТ чем дают реакцию.** Под random walk было бы P(+1) = 40% (= SL/(PT+SL)). Получаем 27% → market against reaction. → Heuristic AMP должен работать как primary filter.

---

## 4. Текущий вопрос: maxV = точка или направленный диапазон?

### Сейчас (гибрид)
- LEVEL — точка (maxV.close)
- Zone — диапазон [zone_lo, zone_hi] = LTF bar OHLC
- Force — Gaussian peak на LEVEL, fade к границам
- Touch — точечное `low ≤ LEVEL ≤ high`
- Direction — inferred from position

### Вариант D (предлагается)
Directional touch detection:
```python
if side == "long":   # lower_wick support
    return prev_close > level AND current_low <= level   # approach сверху
else:                # upper_wick resistance
    return prev_close < level AND current_high >= level  # approach снизу
```

Преимущества:
- Отсечём «сквозные проходы» (price went through without reacting)
- Каждый touch имеет defined direction
- P(+1) ожидаемо вырастет с 27% до 35-40%

**Решение пользователя:** обсуждается, возможно Phase 0b.

---

## 5. ML Pipeline (Lopez de Prado canon)

### Pilot (Phase a) на 6-месячном датасете

```
Train: 80% chronological (~145 events, Dec 2025 - end Mar 2026)
Test:  20% holdout      (~37 events, Apr - May 2026)
Embargo: 12 D bars между train_end_label и test_start
```

### Production (после regenerate 6y → PC)

**Walk-Forward Anchored с monthly retrain:**

| Параметр | Значение | Обоснование |
|---|---|---|
| Warm-up | 24 мес (2020-2021) | Минимум для статистической стабильности |
| Test window | 1 мес forward | Realistic для live |
| Retrain frequency | Monthly | Не overfit, не drift |
| Embargo (purge) | 12 D bars = t1 | Lopez de Prado Ch 7 |
| Train mode | Anchored (растёт), не rolling | Сохраняем full history через bull/bear regime |
| Total folds | ~48 (2022-2026) | Достаточная mean+std оценка |

### Compute estimate

| Шаг | Где | Время |
|---|---|---:|
| Phase 0 (D-only regen 6 мес) | Mac | ✅ ~3 мин — DONE |
| Phase b (univariate audit) | Mac | ~3-5 мин |
| Phase a (pilot GBM + SHAP) | Mac | ~10 мин |
| Phase 0+ (regen 6y) | Mac | ~60 мин |
| Phase walkfwd (60 retrains) | **PC** (Rule 9) | ~3-6 ч |

---

## 6. Визуальные артефакты

### Canon style ViC heatmap (утверждено)

Сохранено в [[feedback-vic-maxv-chart-style]]. Параметры:

```python
blue_cmap = LinearSegmentedColormap.from_list(
    "force_blue",
    [(0.690, 0.847, 1.0, 0.0),          # transparent light azure
     (0.0,   0.690, 1.0, 0.25),         # vivid azure #00b0ff @ alpha 0.25
     (0.098, 0.463, 0.824, 0.45)]       # cobalt #1976d2 @ alpha 0.45
)

ax.imshow(img, aspect="auto", cmap=blue_cmap, vmin=0, vmax=1,
          origin="upper", interpolation="bilinear", zorder=1)
```

+ LEVEL line: `color="#5a5a5a", lw=0.5, alpha=0.25`
+ Canon base: chart_format.md (Bull #01a648 / Bear #131b1b, Y right, no grid, Mondays X-ticks)

### Финальная визуализация

`~/Desktop/maxv_cluster_feb.png` — heatmap 91 D maxV на BTC Feb 5 → May 6 2026:
- Яркость ∝ AMP (все 5 условий)
- Topmost: 02-24 lower_wick virgin (W_vol boost 1.48) AMP=9.12
- 11 broken-defense events контурируют bull-trend continuation zones

---

## 7. 10 virgin maxV identified (период Feb 5 - May 6, 2026)

| Date | LEVEL | Position | Age (от 04-06) |
|---|---:|---|---:|
| 02-06 | 61,734 | lower_wick | 90d |
| 02-24 | 62,966 | lower_wick | 72d |
| 02-28 | 63,264 | lower_wick | 68d |
| 03-29 | 65,688 | lower_wick | 39d |
| 04-13 | 73,000 | body_top | 24d |
| 04-16 | 73,512 | lower_wick | 21d |
| 04-29 | 75,324 | lower_wick | 8d |
| 04-30 | 76,317 | body_top | 7d |
| 05-04 | 78,936 | body_bottom | 3d |
| 05-06 | 81,768 | upper_wick | 1d |

**Текущая цена 81,447.** Только 05-06 над ценой как resistance. Под ценой — поддерживающая лестница 78,936 → 76,317 → ... → 61,734.

---

## 8. Скрипты

| Файл | Назначение |
|---|---|
| `~/smc-lib/scripts/maxv_amplified_chart_single.py` | Canon heatmap, 5 условий, blue gradient |
| `~/smc-lib/scripts/maxv_master_dataset_6m.py` | Старый master (есть bug 3D anchor, lookahead в touches) |
| `~/smc-lib/scripts/maxv_phase0_d_regen.py` | **NEW:** D-only regen без lookahead + Gaussian + TBM exit |
| `~/smc-lib/scripts/maxv_phase_c_tbm_check.py` | Phase (c) sanity check старого dataset |
| `~/smc-lib/scripts/maxv_two_groups_compare.py` | Анализ двух групп 30-01/31-01/06-05 vs 04-02/05-02/08-02 |

---

## 9. Открытые задачи

| Task ID | Subject | Status |
|---|---|---|
| #17 | Phase (c): TBM labeling check | ✅ completed |
| #20 | Phase 0: Regenerate D-only touches | ✅ completed |
| #18 | Phase (b): Univariate feature audit | blocked by #20 (готов запускать) |
| #19 | Phase (a): Pilot GBM + SHAP | blocked by #18 |

**Решение по directional touch (Variant D)** перед Phase b — обсуждается.

---

## 10. Связи с canon

- [[feedback-vic-maxv-absolute-not-sided]] — maxV = close абсолютной max-vol LTF (не sided)
- [[feedback-pine-ltf-d-chart-integer-rule]] — D+mlt=45 → LTF=32m (CEIL rule)
- [[feedback-vic-maxv-chart-style]] — canon blue gradient визуализация
- [[feedback-untraded-area-is-magnet]] — основа condition #3 (W_virgin)
- [[feedback-3d-resample-monday-reset]] — баг старого master, для D неактуально
- [[feedback-heavy-compute-on-pc]] — walk-forward на 6y → PC
- [[feedback-key-findings-from-reading-format]] — формат вывода (Правило 13)
- [[feedback-display-time-in-utc-plus-3]] — времена в чате MSK

## История параметров (для контекста)

| Условие | Изначально (head) | После итераций сессии | Будет после ML calibration |
|---|---|---|---|
| W_pos | 1.5/0.7 | 1.5/0.7 (не менялось) | TBD (OLS coef) |
| W_age | 1+0.3·ln(1+d/30) | same | TBD (curve fit) |
| W_virgin (K) | 4.0 binary | 3.0 + decay τ=7d | TBD (exp fit на P(react) vs days_since_touch) |
| W_broken | — | 1.8 | TBD (P_broken / P_baseline) |
| W_vol | — | (V/medV) / (R/ATR), clip [0.5, 2.0] | TBD (best clip bounds + AUC) |
