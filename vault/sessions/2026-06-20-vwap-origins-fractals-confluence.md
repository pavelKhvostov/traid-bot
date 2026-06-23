---
date: 2026-06-20
tags: [session, vwap, vwap-effective, fractal, anchored-vwap, confluence, multi-tf, project]
projects: [vwap-effective-anchors]
related: [[2026-06-19-vwap-effective-anchors-12h-fractals]]
---

# 2026-06-20 — VWAP origins → fractals → multi-TF confluence

## TL;DR
Продолжение проекта **vwap-effective-anchors**. Главное открытие: **VWAP origins для qualifying anchors совпадают с Williams N=2 fractals** на 4h/12h/1D/1W. 38% origins — multi-TF aligned. **Сильный VWAP = fractal на 3+ TFs одновременно** + сильное body (≥0.45) + volume burst (×1.5+).

## 🎯 Логика проекта (напоминание)

Anchor = 12h Williams N=2 fractal center, цена = 0.5 wick midpoint.
Qualifying anchor = forward 5% LONG/SHORT раньше чем invalidation (пробой wick extreme).
764 qualifying на BTC за 6.5 лет (2020-2026).

## 🔍 Phase 1 — VWAP origins (откуда «пришёл» VWAP к anchor)

### Метод
Для каждого qualifying anchor: найти T' в прошлом такое что VWAP(T' → anchor_ts) пришёл в anchor_price.

```
f(T) = sum_pv[T] - anchor_price * sum_v[T]
Решение: f(T') = f(anchor_ts) → точка где VWAP equals anchor_price
```

### Результаты
- 604/764 (79%) anchors имеют ≥1 origin
- 160/764 (21%) не имеют — VWAP с любой точки не доходит до anchor_price
- **Median latest origin distance**: 15 дней назад
- **Median earliest origin distance**: 117 дней назад

## 🧪 Phase 2 — Fib hypothesis (отвергнута)

Проверили: сидят ли anchors на Fibonacci уровнях от origins?

| Group | Match rate (Fib ±1.5%) | Baseline |
|---|---|---|
| FH latest | 6.2% | ~15% |
| FH earliest | 4.4% | ~15% |
| FL latest | 7.1% | ~15% |
| FL earliest | 10.3% | ~15% |

**Большинство origins имеют близкое (0-15%) retracement к anchor**. Fib hypothesis НЕ подтверждена статистически.

> Наш случай 03-04 с 23.51% (близкое к Fib 23.6%) оказался coincidence.

## 🎯 Phase 3 — Структурный анализ origins

### Откуда «приходит» VWAP — на каких структурных точках?

| Feature | % origins |
|---|---|
| **4h Williams fractal** | **35.4%** ⚡ |
| **12h Williams fractal** | 33.1% |
| **1D Williams fractal** | 32.6% |
| **1W Williams fractal** | 27.0% |
| Near local high (±72h) | 1.2% |
| Near local low (±72h) | 0.7% |
| NY open (13-14 UTC) | 11.3% |
| London open (07-08 UTC) | 8.9% |
| Asia open (00-01 UTC) | 7.0% |
| Volume > 2× prev 24h avg | 23.9% |

### Главный вывод
**Combined «origin совпадает с fractal хотя бы на одном TF»: ~70-80%**.

→ **VWAP origins = чаще всего Williams N=2 fractals** на каком-то TF.

## 🏆 Phase 4 — Какие фракталы формируют СИЛЬНЫЕ VWAPs

### Multi-TF confluence distribution

| TFs aligned | Count | % |
|---|---|---|
| 0 (не fractal) | 372 | 30.8% |
| 1 TF | 372 | 30.8% |
| **2 TF** | 253 | 20.9% |
| **3 TF** | **175** | **14.5%** |
| **4 TF** | **36** | **3.0%** |

**38% origins на multi-TF aligned fractals (2+ TFs)**.

### Топ комбинации

| Combo | n | % |
|---|---|---|
| ⚡ **4h + 12h + 1D** | 101 | 8.4% |
| 4h | 127 | 10.5% |
| 1W | 110 | 9.1% |
| 12h + 1D | 69 | 5.7% |
| 4h + 12h | 61 | 5.0% |
| **12h + 1D + 1W** | 42 | 3.5% (HTF stacked) |

### Свойства strong fractal-баров

| TF | Body/range | Volume ratio |
|---|---|---|
| 4h | 0.38 | 1.40× |
| **12h** | 0.39 | **1.56×** ⚡ |
| **1D** | **0.45** ⚡ | 1.41× |
| 1W | 0.44 | 1.13× |

→ **1D fractals** имеют наиболее сильное body (displacement)
→ **12h fractals** показывают наибольший volume burst

## 🎯 ВЕРДИКТ — критерии «сильного» VWAP-origin fractal

```
✅ Multi-TF aligned: fractal одновременно на 4h + 12h + 1D
✅ Body to range ≥ 0.45 (strong displacement)
✅ Volume × 1.5+ vs prev 5 bars
✅ FL для bull трендов, FH для bear (HTF direction aligned)
```

**Идеал** = **fractal совпадающий на 3+ TFs одновременно** (14.5% всех origins).

## 📐 Phase 5 — Position в fractal-баре (где origin сидит внутри)

Origin's price closest to canonical anchor:

| Position | 4h | 12h | 1D |
|---|---|---|---|
| close | 21% | 21% | 22% |
| hl_mid | 14% | 19% | 16% |
| body_mid | 13% | 14% | 17% |
| open | 18% | 11% | 15% |
| wick_mid_FH/FL | 12-14% | 12-15% | 11-13% |
| high/low | 4% | 4% | 3% |

**Time position median = 50%** через бар  
**Price position median = 50%** от low  

→ Origin сидит **в МИДДЛ бара** (time AND price). НЕТ одной канонической позиции. Origin распределён по open/close/mid/wicks.

→ Открытое исследование: **0.5 wick midpoint (наш anchor convention) ≠ доминирующая позиция origin**. Распределение почти равномерное.

## 📂 Файлы

```
~/Desktop/fractal_anchors_12h_qualifying.parquet     ← 1293 fractals + labels
~/Desktop/vwap_origins_per_anchor.parquet           ← 604 anchors with origins
~/Desktop/fib_origin_alignment.parquet              ← Fib analysis (negative)
~/Desktop/origin_structural_features.parquet        ← структурный анализ
~/Desktop/origin_position_in_fractal.parquet        ← position в баре
~/Desktop/strong_vwap_fractals.parquet              ← multi-TF confluence

~/smc-lib/projects/vwap-effective-anchors/
  scripts/fractal_anchor_demo.py
  scripts/fractal_anchor_scanner.py
  scripts/find_vwap_origins.py
  scripts/anchor_predictors_analysis.py
```

Новые скрипты сегодня (в /tmp, нужно перенести в smc-lib):
- `/tmp/fib_origin_check.py` — Fib hypothesis test
- `/tmp/origin_structure_check.py` — структурный анализ
- `/tmp/origin_position_in_fractal.py` — position в баре
- `/tmp/strong_vwap_fractals.py` — multi-TF confluence

## 🚀 Roadmap (revised)

### ✅ Phase 0 (yesterday)
- Anchor definition + qualifying filter
- Baseline 1031 → 764 qualifying

### ✅ Phase 1-5 (today)
- VWAP origins backward search
- Fib hypothesis (отвергнута)
- Структурный анализ origins → fractals
- Multi-TF confluence для strong VWAPs
- Position в fractal-баре

### ⏳ Phase 6 (next)
- **Filtered scanner**: только anchors с origin на 3+ TF aligned fractal
- WR comparison: subset vs baseline 59%
- Forward detector: при формировании 12h fractal проверять есть ли strong-VWAP confluence в прошлом

### ⏳ Phase 7
- Live detection при 12h close
- Trade execution rules
- Backtest equity curve

## 🔑 Ключевые инсайты дня

1. **VWAPs приходят от Williams fractals** — 70-80% origins на каком-то TF
2. **Multi-TF confluence = сила** — 14.5% origins на 3+ TFs одновременно
3. **1D fractals = best displacement** (body/range 0.45)
4. **12h fractals = best volume** (1.56× burst)
5. **Position в fractal-баре не доминирует** — origin distributed across open/close/mid/wicks
6. **Fib hypothesis опровергнута** — наш 03-04 кейс с 23.6% был coincidence

## Tags
#vwap #vwap-effective #fractal #12h #anchored-vwap #multi-tf #confluence #williams #counter-trend #project-update
