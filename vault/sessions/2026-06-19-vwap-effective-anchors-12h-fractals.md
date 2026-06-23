# 2026-06-19 — VWAP Effective Anchors (новый проект)

## TL;DR
Запустили новый проект **vwap-effective-anchors** для детектирования эффективных VWAP-якорей на 12h Williams N=2 fractals. Цель: торговать «скользящие» с известным RR (+5% / -5%). За 6.5 лет на BTC найдено 1293 fractals → 764 qualifying (59%). Сделан baseline statistical analysis — 6 фич с p<0.05, выделена counter-trend ловушка как ключевая.

## 🎯 Цель проекта

Найти **графический паттерн** который предшествует появлению эффективного VWAP anchor, чтобы:
1. Детектировать заранее в real-time
2. Анкорить VWAP на 0.5 wick midpoint центральной 12h fractal-свечи
3. Торговать +5% / -5% с invalidation по пробою wick extreme

## Определение anchor

| | Что |
|---|---|
| **Anchor TIME** | close центральной 12h fractal-свечи |
| **Anchor PRICE** | 0.5 wick midpoint: `(body_extreme + wick_extreme) / 2` |
| FL (LONG) | `(min(o,c) + low) / 2` |
| FH (SHORT) | `(max(o,c) + high) / 2` |

## Qualifying criterion

Forward 1m bars от anchor_ts:
- **FL/LONG**: high ≥ anchor × 1.05 раньше чем low ≤ wick_extreme
- **FH/SHORT**: low ≤ anchor × 0.95 раньше чем high ≥ wick_extreme

## 📊 Baseline (BTC 2020-2026)

| | Count |
|---|---|
| Total 12h Williams N=2 fractals | 1,293 |
| Qualifying | **764 (59%)** |
| FL → LONG +5% | 417 |
| FH → SHORT −5% | 347 |
| Invalidated | 528 |

**Time-to-target**: 10%/50%/90% = 25min / 21.6h / 100h

## 🔍 Предикторы (Phase 0)

Сравнение qualifying vs invalidated:

| Feature | Qual mean | Inval mean | p-value |
|---|---|---|---|
| body_to_range | 0.40 | 0.34 | <0.001 ⭐⭐⭐ |
| rel_wick_to_body | 4.73 | 5.07 | <0.001 ⭐⭐⭐ |
| **ret_3bar_pct** | **-0.27%** | **+0.46%** | **0.001 ⭐⭐** |
| ret_5bar_pct | -0.07% | +0.86% | 0.003 ⭐⭐ |
| range_ratio_5 | 1.49 | 1.33 | 0.014 ⭐ |
| volume_ratio_5 | 1.38 | 1.26 | 0.040 ⭐ |

**Главное открытие**: **counter-trend перед разворотом**. Qualifying FL имеют **отрицательный** ret_3bar — цена шла ВНИЗ → разворот ВВЕРХ ловится. Это базовый принцип counter-trend trading, но теперь формализован.

## Асимметрия FL vs FH

- **FL (LONG)**: длинный нижний wick критичен (sweep ликвидности)
- **FH (SHORT)**: bullish свеча мешает (qual is_bull=0.50 vs inval 0.63). Bullish FH = continuation чаще, не reversal

## 📂 Структура проекта

```
~/smc-lib/projects/vwap-effective-anchors/
├── README.md                                  ← spec + roadmap
├── scripts/
│   ├── fractal_anchor_demo.py                ← PNG визуализация
│   ├── fractal_anchor_scanner.py             ← scanner + qualifying
│   ├── find_vwap_origins.py                  ← backward VWAP origins
│   └── anchor_predictors_analysis.py         ← statistical comparison
├── data/
│   ├── fractal_anchors_12h_qualifying.parquet
│   ├── vwap_origins_per_anchor.parquet
│   └── anchor_predictors_table.csv
└── results/
    └── fractal_anchor_12h_demo.png
```

## 🚀 Roadmap

### ✅ Phase 0 (today)
- Anchor definition
- Qualifying filter
- 10 baseline features
- Statistical comparison

### ⏳ Phase 1 — Extended features
- HTF context (D, W direction via HMA)
- Multi-TF SMC zones overlap (OB, FVG, RDRB)
- Liquidity sweep before fractal
- Predecessor VWAPs confluence
- Volume profile (HVN/LVN)

### ⏳ Phase 2 — ML classifier
- XGBoost on all features
- Walk-forward eval
- Per-direction models (FL/FH)

### ⏳ Phase 3 — Live detector
- Real-time inference at 12h close
- VWAP placement + trade signal

### ⏳ Phase 4 — Multi-asset (BTC/ETH/SOL)

## 🔗 Связь с другими проектами

- **DIRECTIONS.md** направление #2 (предсказатель на день) ← это идеально подходит
- **REALISTIC_TARGET_PRINCIPLE** — 5% это уже realistic TP, не theoretical max
- **FRESH_LOOK_PRINCIPLE** — invalidation = X-mark, пересобираем план
- **12h-фракталы B5_vwap** (W-aligned VWAP sweep) — комплементарный угол

## Tags
#vwap #vwap-effective #fractal #12h #anchored-vwap #scolzyaschie #project-start #counter-trend
