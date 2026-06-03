---
tags: [session, prediction-algo, bb-dataset, strategy-1-1-1-v2, floating-tp, mh-ml]
date: 2026-05-30
status: complete
related:
  - "[[prediction-algo-final-results]]"
  - "[[strategy-1-1-1-floating-tp-final]]"
  - "[[2026-05-29-night-mh-ml-pipeline-3064-features-pc2-archive]]"
---

# Session 2026-05-30 — prediction-algo v2 + bb-dataset + strategy 1.1.1 V2 + floating TP verification

## Что сделано (порядок хронологический)

### 1. Prediction-algo v2 walk-forward завершён на PC1 ✅

PC1 финиш в ночь 2026-05-30 01:11. Файлы в `~/Desktop/PC1/`:
- `metrics_all.json` — 4 cadence-конфига × метрики
- `predictions_main.csv` — 2.4M rows, 730 cuts × ~3300 zones avg per cut
- `per_type.csv`, `per_mit.csv`, `ob_vc_comparison.json`

**Главные числа (canon main_5y_monthly):**

| Метрика | v1 (2026-05-28) | **v2** | Δ |
|---|---|---|---|
| Top-5 hit_D | 87.0% | **89.7%** | +2.7pp ✅ |
| Top-3 ABOVE | 80.9% | 83.2% | +2.3pp ✅ |
| Top-3 BELOW | 81.0% | **84.9%** | +3.9pp ✅ |
| Brier D lift | −45% | −44.1% | ≈ same |
| Lift vs random | 72× | 68.2× | baseline вырос |

**Cadence-проверка**: alt_3y_monthly = **90.05%** (лучше всех). Свежие данные > объём; monthly ≈ weekly ≈ oneshot.

**Per-type contribution в top-5**: OB 27.4%, block_orders 20.3%, FVG 20.1%, RDRB 13.7%, **ob_vc 8.3% (NEW, hit_D when in top5 = 90.5%)**, fractal 3.7%, ob_liq 3.0%, iRDRB 2.8%, iFVG 0.5%, marubozu 0%.

**ob_vc доля в top-5 (8.3%) > доля в датасете (7.6%)** — модель его выбирает чаще случайного, hit_D 90.5% когда выбран = на уровне OB.

### 2. Per-month анализ predictions_main.csv

Все 13 месяцев тест-периода positive (84.6% - 94.7%). Top-1 hit_D = **93.7%** (одиночная сильнейшая зона за cut). P_hit_D ≥ 0.95 → **96% hit rate** (1146 events, ~3 в день — actionable filter).

Calibration: top bucket (0.9-1.0) — practically perfect (predicted 0.94 vs actual 0.92); mid buckets slightly overconfident.

### 3. Memory обновлена

`[[prediction-algo-final-results]]` обновлена до v2: 89.7% top-5, ob_vc + per-zone mit canon (4 mit-моделей: wick-fill / sweep / first-touch / sweep-open).

### 4. bb-dataset builder — coding и smoke ✅

`~/smc-lib/projects/bb_dataset/builder.py` — первая версия:
- Filter: `type=="ob_vc" AND tf in ("1h","2h")`
- Touch detection на 1m в окне 72h после `born_ts`
- Label: bounce/break **close-based** (close НЕ должен пробить противоположную границу зоны в окне `2 × HTF_bars`)
- Features groups A+B (~12 фичей) для smoke; расширение до A-I (~70) после первой итерации

**Smoke + full 6y on Mac (5 min):**
- 6680 unique ob_vc zones (1h: 3588, 2h: 3092)
- 100% touch rate в 72h окне (no_touch = 0)
- **P(bounce) = 92.3%** = ob_vc canon уже сам по себе сильный фильтр

### 5. Два bug-fix в bb_dataset

- **Direction case mismatch**: ob_vc events возвращают `direction="long"/"short"`, код сравнивал с `"LONG"/"SHORT"` → все zones обрабатывались как SHORT. Fix: `str(zone["direction"]).lower() == "long"`.
- **Label rule too strict**: исходно brake по `low/high` (wick-based) давал все LONG = break. Перешли на **close-based** ("100% fill зоны" = close за противоположной границей), это match SMC канону.

### 6. Strategy 1.1.1 от разработчика — verified ✅

Файлы получены: `~/Downloads/strategy_1_1_1_floating.py` + `etap108_floating_tp_human_guide.pdf`. Скопированы в `~/smc-lib/projects/strategy_1_1_1_floating.{py,pdf}` как production reference (НЕ редактировать).

**Сравнение с нашим traid-bot/strategies/strategy_1_1_1.py**: их файл импортирует наш — детектор identical. Их добавление = **Floating TP**: 4 способа выхода (SL / R-cap / score-exit / 7d timeout) + 4-indicator momentum score (Hull/MH/RSI/ASVK).

**Verified by replication (BTC 6y on Mac):**

| | PDF claim | Наш replication |
|---|---|---|
| Период | 6.34y | ~6.08y |
| **Total R** | +179.9R | **+196.9R** (+9%) |
| **WR** | 52% | **51.45%** |
| **medR** | +0.07 | **+0.08** |

Числа подтверждены в пределах ±10%, разница объяснима меньшей историей.

### 7. Strategy 1.1.1 V2 — nested ob_vc cascade + first backtest

Spec: `~/smc-lib/projects/strategy-1-1-1-v2.md`. **Идея**: заменить 2 ad-hoc OB+FVG композита в каскаде на canon ob_vc:
- macro: `ob_vc(HTF=D/12h, LTF=4h/6h)` (заменяет ad-hoc OB-{1d,12h} ∩ FVG-{4h,6h})
- entry: `ob_vc(HTF=1h/2h, LTF=15m/20m)` (заменяет ad-hoc OB-{1h,2h} ∩ FVG-{15m,20m})
- SWEPT + confluence + Floating TP — как в v1

Implementation: `~/smc-lib/projects/strategy_1_1_1_v2.py`. Использует наш `_scan_ob_vc_cross_tf` + Floating TP simulator разработчика (через import).

**Эволюция логики**:
- v0 (мы): spatial overlap только → 6093 trades (×16 vs v1, fat-tail), +2387R
- v1 (правильный с time-window + fractal invalidation как у разработчика): **1115 trades, +227.7R, WR 38.12%, medR −0.55**

**Сравнение V2 vs v1:**

| | v1 (ad-hoc) | **V2 (nested ob_vc)** | Δ |
|---|---|---|---|
| Trades (6y BTC) | 379 | 1115 | ×3 |
| WR | 51.45% | 38.12% | −13pp |
| Total R | +196.9R | **+227.7R** | +15% ✅ |
| medR | +0.08 | −0.55 | хуже |
| Bad years | 1 | 1 | равно |

**Профили разные**: v1 — сбалансированный (medR в плюс, score-exit лидер). V2 — fat-tail-heavy (cap_hits 141 × 4.5R = +634R на 6y). V2 выигрывает в total PnL, но за счёт rare big winners. **Идеальный case для bb-модели filter** — bb отсеет слабые ob_vc → top-quality only.

### 8. Git push на ветку Vadim ✅

99 файлов, +18 623 строк → `origin/Vadim` (https://github.com/pavelKhvostov/traid-bot.git).
2 коммита запушены: `0b69228` (smc-lib expert opinion + 11 elements) + `1fba632` (vault sessions + research/vic_vadim + CLAUDE.md Floating TP refs).

### 9. PC2 завершил feature_importance dump ✅

Финиш 2026-05-30 08:46. Файлы в `~/Desktop/PC2/`:
- `mh_predictions.csv` — те же 35K rows, identical metrics (детерминистично, random_state=42)
- `mh_metrics.csv` — 6 horizons (best 12h dir_acc 53.2%, 96h 52.6%)
- `mh_feature_importance_aggregated.csv` — **18 384 rows** (3064 features × 6 horizons)
- `mh_feature_importance_per_retrain.csv` — 78 278 rows (long format, non-zero only)

**Главные находки feature importance:**

1. **Sparsity 40-47%** активных фичей per horizon. ~1700 фичей — чистый шум, можно отсечь.

2. **`bars_since_mf_zero_32h`** — №1 феча на 4h, 12h, 24h, 48h, 96h одновременно. «Время с последнего zero-crossing Money Flow на 32h TF» = long-term regime change clock.

3. **Money Flow доминирует на длинных горизонтах**: 65% top-20 для 96h — mf-related. Это объясняет почему 96h работает лучше всех.

4. **Horizon ↔ TF match**:
   - 1h-4h: 15m-2h dominant
   - 12h-24h: 4h-16h
   - 48h-96h: **8h, 16h, 32h** dominant

5. **Variants (vslow/vfast) работают** — присутствуют в top-20 каждого horizon → расширение через EMA-сглаженные variants было правильным.

6. **Стабильность**: top features имеют CV < 0.4 = стабильно через 13 retrains. Самые стабильные `bars_since_*_8h/32h` (CV < 0.15).

## Главные открытия дня

1. **Prediction-algo v2 на новом каноне ЛУЧШЕ v1** — +2.7pp top-5 hit_D, ob_vc usefully contributes
2. **ob_vc canon — сам по себе сильный фильтр**: 92.3% P(bounce) baseline
3. **Strategy 1.1.1 Floating TP verified by replication** — разработчик использует наш существующий detector
4. **Strategy 1.1.1 V2 даёт другой профиль**: больше signals, фат-тейл-heavy, +15% PnL — идеальный case для bb-фильтра
5. **MH-ml feature importance**: 50% фичей — шум, mf-based features доминируют на длинных горизонтах

## Открытые задачи (для следующих сессий)

| трек | следующий шаг |
|---|---|
| **prediction-algo v2** | ✅ закрыт (89.7% confirmed) |
| **bb-модель** | walk-forward на 6680 events (Mac, 30-40 min) → AUC, calibration |
| **Strategy 1.1.1 V2** | dedup macro→entry mapping (для honest signal count) + bb-фильтр |
| **Strategy V2 4 design questions** | time-decay, entry timeout, bb для macro, symbol scope — отложены |
| **MH-ml feature selection** | top-500 → переобучить → сравнить |
| **MH-ml parametric MH variants** | теперь обосновано (mf доминирует) — варьировать smoothing/sma/stoch |
| **Live integration Floating TP** | Position manager в traid-bot — отдельная backend задача |

## Артефакты сессии

### Code
- `~/smc-lib/projects/bb_dataset/builder.py` — bb-dataset builder (новый)
- `~/smc-lib/projects/strategy_1_1_1_v2.py` — V2 detector + backtest (новый)
- `~/smc-lib/projects/strategy_1_1_1_floating.py` + `.pdf` — production reference (от разработчика)
- `~/smc-lib/projects/strategy-1-1-1-v2.md` — V2 spec обновлён (Floating TP добавлен)
- `~/smc-lib/projects/bounce-or-break.md` — bb-spec обновлён (8 вопросов закрыты)

### Compute archives
- `~/Desktop/compute-archives/compute-2026-05-29-prediction-algo-walkforward.zip` (PC1, completed)
- `~/Desktop/compute-archives/compute-2026-05-30-mh-ml-feat-imp.zip` (PC2, completed)

### Data outputs
- `~/Desktop/PC1/` — prediction-algo v2 (metrics, predictions, per-type, per-mit, ob_vc)
- `~/Desktop/PC2/` — MH-ml (metrics, predictions, **feature_importance × 2**)
- `~/Desktop/btc_full.csv` (1.6 GB) — v2 zones dataset 10.17M rows
- `/tmp/bb_full_v3.parquet` — bb-dataset 6680 events (smoke; full версия пойдёт после расширения features)

### Memory updates
- `[[prediction-algo-final-results]]` — обновлена до v2 (89.7%, 4 mit-моделей, 10 типов)

### Git push
- Branch `Vadim` @ `1fba632` (commits `0b69228` + `1fba632`)

## Связи

- [[prediction-algo-final-results]] — главное состояние модели
- [[strategy-1-1-1-floating-tp-final]] — Floating TP canon
- [[strategy_1_1_1]] — base detector (impl shared с floating)
- [[2026-05-29-night-mh-ml-pipeline-3064-features-pc2-archive]] — MH-ml pipeline (вчерашний контекст)
- [[2026-05-29-prediction-algo-verification-and-roadmap]] — verification roadmap (предыдущая сессия)
