---
tags: [session, pred12h, c9, force, andrey, ml, magnitude]
date: 2026-06-05
strategy: pred12h-fractal-prediction
status: c9-approved-magnitude-integrated
---

# C9 утверждён + Andrey ML magnitude интегрирован в basket

Продолжение basket development. Сессия посвящена двум темам:
1. **Cumulative force investigation** → утверждение C9 = reverse force divergence (WR 84.2%)
2. **Andrey ML magnitude integration** → каждое basket event получает предсказание % движения цены

## Часть 1: Cumulative Force Investigation

### Hypothesis

Force per single bar = noisy. Может cumulative sum за 2-3 свечи дает чище сигнал?

```
net_w1 = net(i)
net_w2 = net(i) + net(i-1)
net_w3 = net(i) + net(i-1) + net(i-2)

где net = Σ(buyer - seller) across {1h, 2h, 4h, 6h, 8h, 12h, 1d, 2d, 3d}
```

### Direction-matched (canon: FH→sellers, FL→buyers)

Все 4 missed (#14, #15, #48, NEW) имеют direction-matched cumulative force:
- #14: net_w3 = -5649 (sellers dom) — top-1 FH cumulative за 4 мес окно
- #15: net_w3 = +3800 (buyers dom)
- #48: net_w3 = -5932 (sellers dom) — top-3 FH
- NEW: net_w3 = -2400 (sellers dom)

**Но WR direction-matched за 6 лет — низкий:**
| Window | Best WR | catches |
|-------:|--------:|---------|
| w1 | 37% | all 4 missed |
| w2 | 46% | all 4 |
| w3 | 47% | all 4 |

**Trend-continuation bars** имеют такую же direction-matched cumulative force → невозможно различить reversal vs continuation через cumulative force alone.

### Reverse direction (force ПРОТИВ ожидаемого = exhaustion)

Открыты три 80%+ WR конфигурации:

| Filter | Window | n | WR | Семантика |
|--------|-------:|--:|---:|-----------|
| FL net ≤ -1000 | w1 (1 свеча) | 12 | **100%** | seller capitulation at bottom |
| FH net ≥ +500 | w1 (1 свеча) | 39 | **82%** | buyer distribution at top |
| FL net_w2 ≤ -2000 | w2 (2 свечи) | 14 | **86%** | extended seller capitulation |

**Window w3 (3 свечи) reverse → max 57-59%** (не 80%+).

### C9 утверждено = union 3 reverse-force filters

```python
C9 = C9a ∪ C9b ∪ C9c
  C9a: (direction=FL) AND (net ≤ -1000)
  C9b: (direction=FH) AND (net ≥ +500)
  C9c: (direction=FL) AND (net_w2 ≤ -2000)
```

**Метрики:**
| | n | conf | WR | imp/18 |
|---|---:|---:|---:|---:|
| C9 standalone | 57 | 48 | **84.2%** | 0 |
| C9 unique (вне C1-C7 + C8) | 6 | 5 | **83.3%** | 0 |
| C1-C7 ∪ C8 ∪ C9 (full basket) | **676** | 449 | 66.4% | 15/18 |

C9 — узкий, high-precision add-on. **Не ловит 4 missed** (они имеют canonical direction-matched force, не reverse).

## Часть 2: Andrey ML Magnitude Integration

### Идея

basket = «здесь будет фрактал». Andrey ML = «вероятность что цена дойдёт ±3/4/5%».
Объединение → «где разворот + насколько сильный».

### Что у Andrey есть

6 ML моделей etap_173:
- y_low_strong_3/4/5 — для FL: вероятность движения ≥3/4/5% вверх за 7 дней
- y_high_strong_3/4/5 — для FH: ≥3/4/5% вниз за 7 дней
- Per bar: p_3, p_4, p_5 (path-free MAX move probability)

### E_pct (interpolated expected magnitude)

```
E_pct = 3 × p_3 + 1 × p_4 + 1 × p_5
```

Range 0% → 5%+ per bar.

### Cross-join: 181 basket events × Andrey predictions

Из 676 наших basket events:
- **181 в Andrey OOS window** (2025-01-05 → 2026-05-21, 1.37 года) → have Andrey predictions
- 495 в train period (2020-2024) → predictions не сохранены (нужно walk-forward)

### Distribution на 181

| Метрика | Confirmed (mean) | Not (mean) | Δ |
|---------|----------------:|----------:|--:|
| p_3 | 0.54 | 0.33 | +0.20 |
| p_4 | 0.51 | 0.32 | +0.19 |
| p_5 | 0.48 | 0.30 | +0.18 |
| E_pct | 2.59% | 1.63% | +0.97% |

### 🎯 Calibration — E_pct → WR (monotonic!)

| E_pct bucket | n | WR |
|--------------|--:|---:|
| [0, 1) | 33 | 27% |
| [1, 2) | 52 | 58% |
| [2, 3) | 42 | 79% |
| **[3, 4)** | 37 | **81%** ★ |
| **[4, 5)** | 17 | **82%** ★ |

**Чёткая монотонность** — Andrey magnitude prediction корректно calibrates confirmation rate.

### Intersection basket-181 с Andrey ML signals (305 в signals_caught.csv)

| | n | % |
|---|--:|--:|
| Basket-181 | 181 | 100% |
| **∩ ML (p_main ≥ 0.3)** | **124** | **68.5%** |
| Basket БЕЗ ML | 57 | 31.5% |

Top tier breakdown (A+B+C = p ≥ 0.6): **56 events** — двойная confluence.

### Применения

| Подход | Эффект |
|--------|--------|
| Filter E_pct ≥ 3% | 54 events с WR **81.5%** |
| Filter E_pct ≥ 4% | 17 events с WR 82.4% |
| Filter p_3 ≥ 0.6 | 56 events с WR 82.4% |
| Basket ∩ ML p ≥ 0.3 | 124 events confluence |

**Magnitude prediction добавляет +15pp WR при filter E≥3%** (basket alone 64% → 81% combined).

## Графики

### `~/Desktop/basket_e_pct_3plus_oos.png`
12h BTC за OOS window 2025-01 → 2026-05. 54 events с E_pct ≥ 3% (44 confirmed = 81.5% WR). Каждый маркер с label E_pct%.

### `~/Desktop/basket_ml_intersection_2026.png`
12h BTC за 2026 год. 34 events где basket + Andrey ML согласны (p_main ≥ 0.3). 28/34 = 82.4% WR. Labels: p_main, E_pct, tier letter.

## Лимитации Andrey magnitude

- **Path-free predictions** (max move за 7d, не path-dependent)
- Realized trading WR с SL может быть ниже (видели 2× drop в TBM audit для signals_caught)
- Для ranking magnitude — работает отлично (calibration monotonic)
- Покрытие **только 1.37 года OOS** — 495 train events без predictions

## Что осталось

- **Покрыть 495 train basket events** — нужно walk-forward на PC или re-split Mac (10 мин)
- **4 missed (#14, #15, #48, NEW)** — открыто; не ловятся ни C9 ни magnitude
- **TBM-style honest backtest** для basket + magnitude — pending

## Артефакты

### Скрипты (новые)
- `~/smc-lib/scripts/missed_force_cumulative.py` — initial force grid
- `~/smc-lib/scripts/c8_cluster_only_grid.py` — pure cluster (B option for C8)
- `~/smc-lib/scripts/basket_andrey_magnitude.py` — cross-join basket × Andrey
- `~/smc-lib/scripts/plot_basket_e_pct_3plus.py` — E_pct ≥ 3% chart
- `~/smc-lib/scripts/plot_basket_ml_intersection_2026.py` — intersection 2026 chart

### Data
- `~/Desktop/basket_andrey_magnitude.csv` — 181 events × {ts, direction, confirmed, p_3, p_4, p_5, E_pct}
- `~/Desktop/basket_e_pct_3plus_oos.png` — chart за OOS
- `~/Desktop/basket_ml_intersection_2026.png` — chart за 2026

## Текущий full basket после C9

```
Baseline F1∩F2∩F3 = 1275 / P(W)=48.6% / 18/18 imp / 22 targets
↓
C1∪…∪C7 (canon) = 657 / 66.7% / 15/18 imp / 18/22 targets
+ C8 (≥2 W-aligned swept VWAPs) = +13 unique → 670 / 66.3% / 15/18
+ C9 (reverse force divergence) = +6 unique → 676 / 66.4% / 15/18

Coverage 22 targets: 18/22 = 81.8%
Missed: #14, #15, #48, NEW 2026-05-10
```

## Связано

- [[2026-06-04-pred12h-c8-vwap-w-aligned-canon]] — C8 предыдущая сессия
- [[feedback-12h-fractal-c9-reverse-force]] — C9 memory
- [[2026-06-03-bulkowski-12-reversal-detectors-etap-172]] — Andrey Bulkowski (для контекста ML)
- `~/smc-lib/projects/pred12h-fractal-three-candles.md` — canon basket с C8+C9
- `~/smc-lib/projects/andrey-12h.md` — Andrey project mirror
- `~/smc-lib/prediction-algo/force_opinion.py` — Phase 4 force framework
