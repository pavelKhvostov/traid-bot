---
date: 2026-06-20
tags: [session, vwap, vwap-effective, backtest, honest-validation, strict-filter, project]
projects: [vwap-effective-anchors]
related: [[2026-06-19-vwap-effective-anchors-12h-fractals]], [[2026-06-20-vwap-origins-fractals-confluence]]
---

# 2026-06-20 — VWAP strict strategy + honest backtest

## TL;DR
Признал прошлый heatmap WR 86% **lookahead biased**. Сделал **честный backtest без lookahead**: 136 trades, WR 35.4%, +7R за 4.5 мес — marginal edge. Phase 6 (approach features filter) дал WR 65% но **через overfit** — оптимизировал thresholds на тех же данных. User отказался от out-of-sample validation, требует **WR > 70% на 4-6 trades/мес** через жёсткий фильтр. **Phase 7 — SMC element analysis на touch** ждёт PC1.

## 🔍 Что было сделано сегодня

### 1. Confluence heatmap (отвергнут как невнятный)
Heatmap «# VWAPs in zone» был визуально расплывчат, не actionable.

### 2. Tight clusters detection (lookahead WR 86%)
Detect ≥3 VWAPs в полосе 0.5%, merge consecutive zones, find first touch.
Получил **WR 86%** на 21 touched zone. **User поймал на lookahead**:
- Filter `duration ≥ 24h` использовал future
- Zone bounds (lo_avg, hi_avg) усреднялись по всей жизни кластера = future leak
- Selection bias на touched zones (78/99 no_touch исключены)
- Bounce direction logic дискриминировала с approach knowledge

### 3. Honest backtest без lookahead
Honest walk-forward:
- Walk по 12h timeline
- В каждый T: compute VWAPs (только origin < T)
- Detect cluster СЕЙЧАС (без future)
- Wait first touch в 48h, заранее зафиксировать SL/TP, hold 24h max

**Результат**:
| Metric | Value |
|---|---|
| Total trades | 136 |
| TP / SL / Timeout | 40 / 73 / 23 |
| **WR (TP/(TP+SL))** | **35.4%** |
| **R PnL** | **+7.0R** за 4.5 мес |
| Expected per trade | +0.051R |
| Breakeven WR @RR 1:2 | 33.3% |

**Вердикт**: marginal edge. Не «волшебная стратегия».

### 4. Phase 6 — approach features filter (OVERFIT WARNING)
Approach features при touch:
- LONG bounce: vol_ratio_5h ≥ 1.4 + range_ratio ≥ 1.1 (p=0.002)
- SHORT bounce: ret_1h_immediate ≤ 1.0% (p=0.037)
- HTF trend alignment: ret_10_12h direction matters

**Filter combos** (in-sample, OVERFIT):

| Filter | n | WR | R |
|---|---|---|---|
| Baseline | 136 | 35.4% | +7 |
| Filter A (basic) | 59 | 46.8% | +19 |
| Filter D (HTF aligned) | 22 | **65.0%** | +19 |
| LONG, vol≥2.0 | 14 | 72.7% | +13 |
| SHORT, ret_1h≤0% | 7 | 71.4% | +8 |

**Caveat**: thresholds picked AFTER seeing results = **classical p-hacking**. Реальный WR будет ниже на out-of-sample. User отказался валидировать walk-forward — посчитал «не интересно».

## 🎯 User's pivot — WR > 70% при 4-6 trades/мес

User требует **жёсткую selectivity** через **множественные confluence**, не через optimization.

Запустил strict strategy:
- ≥5 VWAPs в полосе 0.3%
- HTF 12h + 1D оба aligned (≥1.5%)
- Strong move ≥3% в 24h до cluster

**Результат**: 0 trades. Слишком жёстко.

Релаксировано до 4 VWAPs / 0.4% / 0.5% HTF / 2% strong move — ждёт повторного запуска.

## 🚀 Roadmap status (vwap-effective-anchors)

### ✅ Phase 0-4: Foundation done (yesterday)
### ✅ Phase 5: Honest backtest done — WR 35.4%, +7R
### ⏳ Phase 6: In-sample filter WR 65% (overfit) — **отменён по запросу user'a**
### ⏳ Phase 7: SMC element reaction analysis — **ЖДЁТ PC1**
### ⏳ Phase 8 (new): Strict multi-confluence strategy
- Target: WR > 70%, 4-6 trades/мес
- Stack: 5+ VWAPs tight cluster + HTF aligned + context

## 💡 Ключевые инсайты дня

1. **Heatmap WR 86%** = lookahead. Признал ошибку.
2. **Honest WR baseline = 35.4%** при RR 1:2 — слабо но positive.
3. **HTF trend alignment** — самый сильный single filter (p<0.05).
4. **Threshold optimization** на same data = overfit. Не доверять.
5. **«4-6 trades/мес WR > 70%»** = реалистичная trader goal. Нужны:
   - Multi-TF cluster confluence (5+ VWAPs)
   - HTF directional agreement
   - SMC element confirmation на touch (Phase 7)
   - Liquidity sweep context

## 🛠 Когда вернёмся

1. **Закончить Phase 8** — найти strict thresholds дающие 4-6 trades/мес WR ≥ 65% на honest data
2. **Phase 7 (PC1 нужен)**: events_v11.parquet → tag каждый touch с SMC events (ob_vc, OB, FVG, CHoCH, Marubozu, sweep) → проверить что подтверждает bounce
3. **Out-of-sample validation** на 2020-2025 (если user захочет)
4. **Multi-asset** test (ETH, SOL)

## 📂 Файлы

```
~/Desktop/honest_backtest_trades.parquet       ← 136 trades без lookahead
~/Desktop/touch_reaction_features.parquet      ← approach features per trade
~/Desktop/btc_vwap_tight_clusters.png         ← heatmap с lookahead (deprecated)
~/Desktop/btc_2026_02_full_vwaps_55k_85k.png  ← 51 strong VWAPs на window

~/smc-lib/projects/vwap-effective-anchors/
  README.md                          ← updated с Phase 5-7
  STRONG_VWAP_ORIGIN_RULE.md         ← canon правило
  scripts/                           ← все скрипты (нужно sync new ones из /tmp)
```

## 🔧 Скрипты в /tmp (нужно sync в lib когда будет время)
- `honest_backtest.py` — backtest без lookahead
- `touch_reaction_predictors.py` — approach features
- `phase6_filter_test.py` — filter combinations
- `strict_strategy_test.py` — strict multi-gate (work in progress)
- `vwap_clusters_clean.py` — tight cluster detection (lookahead version, deprecated)
- `vwap_confluence_heatmap.py` — heatmap (deprecated)
- `btc_chart_51_strong_vwaps.png` script

## Tags
#vwap #vwap-effective #honest-backtest #strict-filter #lookahead-audit #anti-overfit #counter-trend #project-update
