---
tags: [session, pred12h, ml, extended, chart, expert, vwap, hma, andrey]
date: 2026-06-05
strategy: pred12h-fractal-prediction
status: chart-canon-and-extended-ml-integrated
---

# Pred-12h: extended ML coverage + canonical chart

Продолжение работы над 12h fractal basket. Две темы:
1. **Extended ML predictions** — backfill 1m с 2018 + патч etap_171 для predictions на свежие 14 баров
2. **Канонический chart** — expert-style PNG для отображения basket ∩ ML с HMA + VWAP overlays

## Часть 1: ML Extended Coverage

### Backfill 1m с 2018-01-01

Реальная история 1m в `~/traid-bot/data/BTCUSDT_1m_vic_vadim.csv` начиналась с 2020-01-01. Для anchored VWAP с macro context потребовалась 2018+. Запустил backfill:

- Script: `~/smc-lib/scripts/fetch_btc_1m_backfill_2018.py`
- 1.05M свечей за 2018-01-01 → 2020-01-01
- Время: ~20 мин (Binance public API, ratelimit safe)
- Merged in main CSV: 4,422,767 rows total (2018-01-01 → 2026-06-05)

### Inverted-split ML (extended train coverage)

Original Andrey etap_173 ML trained на 2020-2024, predicted на 2025-2026 (1015 OOS bars). 495/676 наших basket events в train period не имели predictions.

**Solution:** inverted split — train on 2025-2026, predict on 2020-2024.

- Script: `~/traid-bot-andrey/research/elements_study/etap_173_inverted.py` (clone andrey branch + patched 1m loading)
- Time: 2.5 min на Mac
- AUC inverted: 0.89-0.92 (vs original 0.92-0.94 на большем train)
- Predictions: 3410 bars for 2020-2024 → covers 491/495 train basket events
- Output: `~/Desktop/etap_173_inv_pred_*.csv` × 6 targets

Full coverage merge: `etap_173_full_pred_*.csv` = train+OOS объединено → 4425 bars.

### Extended period predictions (последние 14 баров)

Original etap_171 build_dataset скипал последние 14 баров (требует future labels для move_after_low/high). Поэтому свежие basket events (25-28 мая) не имели ML.

**Solution:** `etap_171_extended.py` patch
- Убран skip последних 14 баров
- move_after_low/high = 0.0 default для prediction-only bars
- Features считаются на все bars

После запуска etap_173 с extended dataset:
- Predictions до 2026-05-30 (vs 2026-05-23 раньше)
- Новые ML scores для 4 свежих basket events 25-28 мая

### Hybrid signals_caught (original + synthetic)

`signals_caught.csv` Andrey фильтруется по hit_X labels (которые 0 для bars без future). Поэтому новые predictions не появлялись в signals_caught.

**Solution:** synthetic signals_caught + hybrid merge:
- `etap_173_signals_synthetic.csv` — все 511 bars с p_3 ≥ 0.3 (с synthetic tier)
- `etap_173_signals_hybrid.csv` — оригинальный (до 21-05) + synthetic (22-05+)
- Original calibration preserved для исторических events

### Basket × ML магнитуда

`~/Desktop/basket_andrey_magnitude_full.csv` — **676 events × 11 cols** (ts, dt, direction, confirmed, p_3, p_4, p_5, E_pct, p_main, tier)

Из 676: **672 have ML predictions** (4 без = baseline bars не Williams-confirmed, не показываются в chart).

## Часть 2: Canonical Chart Specification

### Эталон-скрипт

`~/smc-lib/scripts/plot_basket_ml_intersection_2026_expert.py` → PNG `~/Desktop/i-rdrb-charts/btc_12h_basket_ml_intersection_6mo.png`.

### Параметры

| Аспект | Значение |
|--------|----------|
| **Timeframe** | 12h (events на своей 12h-свече) |
| **Окно** | rolling последние 180 дней (динамическое) |
| **Y-range** | 50,000 → 100,000 (фиксированный, +1000 margin) |
| **Right buffer** | 24 бара (12 дней) свободно справа для future bars |
| **Grid/spines** | OFF полностью |
| **Tick marks** | hidden (length=0) |

### Маркеры (basket ∩ ML)

| Element | Style |
|---------|-------|
| Filter | p_main ≥ 0.3 (любой tier от F_min до A_sniper) |
| FH (SHORT) marker | ▼ `#c62828` red |
| FL (LONG) marker | ▲ `#2e7d32` green |
| Filled | confirmed Williams pivot |
| Hollow | not confirmed |
| Marker size | 180 (uniform, без tier-scaling) |
| Position | center 12h bar; offset 0.4% от high/low |

### Звёзды (n_C basket confluence)

| Element | Style |
|---------|-------|
| Symbol | ★ above ▼ (FH) / below ▲ (FL) |
| Count | n_C = число fired conditions C1-C9 на event |
| Color | matches marker color (red/green) |
| Font | 10pt, no bbox |

### HMA TrendLines (Правило 7)

| Line | Color | Style |
|------|-------|-------|
| HMA-78 12h LIVE | `#4a90d9` light blue | `--` dashed |
| HMA-200 12h LIVE | `#1a3f6f` dark blue | `--` dashed |
| HMA-78 D LIVE | `#4a90d9` light blue | `-` solid |
| HMA-200 D LIVE | `#1a3f6f` dark blue | `-` solid |
| Linewidth | 0.9, zorder 1 |

LIVE = HMA[i] computed on close i-1 (strict-causal). Smooth интерполяция между HTF bars.

### VWAPs ASVK (Правило 6)

D-fractals (Williams N=2) anchored. Anchor пул: **с 2018-01-01** (full 1m history).

| Категория | Кол-во | Цвет | Фильтр range |
|-----------|-------:|------|--------------|
| Эффективный под ценой | 2 | 🟠 `#ff7f0e` | $50,000 → current_price |
| Эффективный над ценой | 2 | 🔴 `#c62828` | current_price → $70,000 |
| Проработанный под ценой | 1 | 🟣 `#7e57c2` | $50,000 → current_price |
| Проработанный над ценой | 1 | 🟣 `#7e57c2` | current_price → $70,000 |

- Эффективный = top-2 по composite effectiveness (cascade 1h-12h)
- Проработанный = max total_interactions
- Diversity min_dist 1% между picked VWAPs
- Linewidth 0.9, alpha 0.85

### Title (canonical expert format)

```
BTC  |  12h  |  DD-MM-YYYY  |  HH:MM MSK   +   Basket ∩ Andrey ML (p≥0.3) за последние 6 мес  |  N=X (FH=Y, FL=Z)  |  confirmed N/X = WR%
```

- Position: top center, 14pt bold
- No legend (markers self-explanatory)

### Current price + today emphasis

- Horizontal red dotted line at last_close (`#c62828`)
- Y-tick at last_close → красная плашка (white text on red bg, bold 11pt)
- Today's date X-tick → красная плашка

## Текущее состояние basket

```
Baseline F1∩F2∩F3 = 1275 / P(W)=48.6% / 18/18 imp / 22 targets
↓
C1∪…∪C9 = 676 / 66.4% / 15/18 imp / 18/22 targets
↓
Filter basket × ML (p≥0.3) в 6mo window = 44 events
  35 confirmed = WR 79.5%
  (за весь OOS 6 лет: 315 high-E events, ~74% WR)
```

## Что улучшилось этой сессией

- Coverage ML: 181 → 672 basket events (с predictions)
- Coverage с 2020 → с 2018 для VWAPs
- Свежие 2 недели (22-28 мая) имеют ML scores
- Canonical chart с full HMA + VWAP overlays

## Артефакты

### Скрипты (новые этой сессии)
- `~/smc-lib/scripts/fetch_btc_1m_backfill_2018.py` — 2018+ 1m backfill
- `~/smc-lib/scripts/plot_basket_ml_intersection_2026_expert.py` — canonical chart
- `~/traid-bot-andrey/research/elements_study/etap_173_inverted.py` — inverted-split ML
- `~/traid-bot-andrey/research/elements_study/etap_171_extended.py` — patched (no skip)

### Output data
- `~/Desktop/etap_173_pred_*.csv` × 6 — fresh predictions (через 2026-05-30)
- `~/Desktop/etap_173_inv_pred_*.csv` × 6 — train period predictions (2020-2024)
- `~/Desktop/etap_173_full_pred_*.csv` × 6 — merged full 6y coverage
- `~/Desktop/etap_173_signals_synthetic.csv` — synthetic signals
- `~/Desktop/etap_173_signals_hybrid.csv` — hybrid (original + synthetic)
- `~/Desktop/basket_andrey_magnitude_full.csv` — 676 events × ML

### Charts
- `~/Desktop/i-rdrb-charts/btc_12h_basket_ml_intersection_6mo.png` — canonical (актуальный)

## Связано

- [[2026-06-04-pred12h-c8-vwap-w-aligned-canon]] — C8 canon
- [[2026-06-05-pred12h-c9-reverse-force-divergence]] — C9 canon
- `~/smc-lib/projects/pred12h-fractal-three-candles.md` — basket canon
- `~/smc-lib/projects/andrey-12h.md` — Andrey project mirror
- `~/smc-lib/expert/chart.py` — original expert chart code (reference для HMA/VWAP logic)
