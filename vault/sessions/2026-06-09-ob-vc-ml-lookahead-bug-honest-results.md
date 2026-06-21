---
tags: [session, ob_vc, ml, hma, lookahead, honest, walk-forward]
date: 2026-06-09
related: [[strategy-ob-vc-v33-lean-picked]] [[ob-vc-hma-features-lookahead-fix]] [[ml-snapshot-not-trajectory]]
---

# Сессия 2026-06-09 — ob_vc ML lookahead bug + honest production walk-forward

## TL;DR

**v3.3 production canon (WR 72%, +1288R) построен на lookahead bug** в HMA feature builder. После fix реальный AUC = 0.54 (vs lookahead 0.79). Production walk-forward на 600+ honest fts даёт **+6R/year** vs random pick — marginal edge.

## Что произошло

### 1. Утверждение v3.3 как production canon (утром)

```
v3.3 lean (22 picked features):
  WR 72.4%, Σ +1288R, AUC 0.79, PBO 0.55
  → принят как production canon (Variant A)
  → сохранён в smc-lib/strategies/strategy_ob_vc_v33_lean_picked/
  → сохранён в vault/knowledge/strategies/strategy-ob-vc-v33-lean-picked.md
  → построены PNG (24-types + strategy row, dashboard, 3 BTC trades, etc.)
```

### 2. Обнаружение lookahead bug (вечером)

Пользователь спросил: **«ты не смотришь в будущее? проверь порядок»**. После thorough check кода `hma_at_entry.py:80-87`:

```python
# BUG:
idx_at_event = np.searchsorted(ts_arr, entry_ms, side="right") - 1
close_at_event = closes[idx_at_event]   # close БУДУЩЕЙ in-progress бара
hma_arr[idx_at_event]                    # HMA на этом close
```

Для 1d TF при entry в 14:00 UTC: closes[idx] = close в 24:00 UTC = **10 часов в будущем**. Для 3d TF — до **72 часов в будущем**.

**Quick check на Mac:**
```
Lookahead version:    CV AUC = 0.81
Honest INTRADAY:      CV AUC = 0.52  ← реальность
HONEST last-closed:   CV AUC = 0.54
Δ:                    -0.27 (масштаб бага)
```

### 3. Stage 1 honest rebuild + PC1

Создан `hma_at_entry_honest.py` с INTRADAY partial-bar:
```python
closed_idx = searchsorted(ts_arr, entry_ms - tf_ms, side="right") - 1
partial_close = close_1m at entry_ms
series = closes[:closed_idx+1] + [partial_close]
hma_value = hma_np(series, L)[-1]
```

Rebuild dataset → `features_v3_hma_honest.parquet` (601 features). PC1 results (`output s1v2`):
- AUC LGB: 0.531-0.542 (best hit_RR_23 = 0.542)
- WR @ N=1100: 32-50% (никогда не достигает 70% goal)
- PBO: 0.55
- Top permutation: wait_directional_efficiency, hma_4h_9_slope5, hma_12h_9_dist

### 4. Stage 2A — cross-TF crosses (по запросу пользователя)

Пользователь предложил: **«ML рассматривала пересечение разных HMA на разных ТФ?»** Это было пропущено — у нас были только within-TF cross features.

Добавлены 60 новых features (15 пар × 4 derivatives):
```
Step-up: (2h,21)×(4h,9), (4h,21)×(12h,9), (12h,21)×(1d,9), etc.
Same-L: (15m,9)×(1h,9), (1h,9)×(4h,9), (4h,9)×(1d,9), etc.
Wide gap: (15m,9)×(1d,21), (1h,9)×(3d,21), etc.
```

PC1 results (`output_bl`):
- AUC LGB hit_RR_20: 0.544 (vs v3 honest 0.537)
- **PBO дропнулся 0.55 → 0.30** ← существенное улучшение
- Cross-asset transfer +0.02 (BTC+ETH→BTC: 0.582)
- **#1 permutation: cross_15m_9 × 1h_9 hours_since_flip** (0.0113)
- 8 cross-TF features в топ-50

**Cross-TF intuition пользователя оказалась правильной.**

### 5. Production walk-forward simulation

Пользователь правильно отметил: **«ml должна учиться 4 года потом тесты потом переучиваться, а не как статистика работать»**.

Реализован на Mac (упрощённая HGB версия, не full LightGBM ensemble):
```
Train: rolling 4-year window
Retrain: every 6 months at: 2024-01, 2024-07, 2025-01, 2025-07, 2026-01
Test: top-17% selection per test window
Total OOS: 2024-01 → 2026-06 (2.5 years)
```

**Финальные числа:**
```
ML selected:    N=367   WR=38.4%   Σ +56R   E[R]=+0.15R
Baseline all:   N=2158  WR=37.1%   Σ +245R  E[R]=+0.11R
ML uplift vs random pick same N: +14R за 2.5y (~+6R/year)

Per year:
  2024: WR 35.2% (ML neutral)
  2025: WR 42.4% (ML +0.27R/trade — год хорошо отработал)
  2026: WR 36.8% (ML neutral)
```

## Главные уроки

### A. Lookahead bug в HMA features

`closes[idx_at_event]` где `idx_at_event` = бар, СОДЕРЖАЩИЙ entry_ms — использует FINAL close ещё не закрытого бара (до 72h в будущем для 3d). Прямое чтение будущего. См. [[ob-vc-hma-features-lookahead-fix]].

### B. ML видит snapshot, не trajectory

Tabular ML (LightGBM, HGB) принимает **точку** в feature space, не **путь**. Два сетапа с identical snapshot но разным past trajectory выглядят одинаково — ML не различает. Для trajectory analysis нужны sequence models (LSTM/Transformer). См. [[ml-snapshot-not-trajectory]].

### C. AUC на cross-validation ≠ AUC на production WF

PC1 nested CV даёт averaged AUC = 0.54-0.58 honest. Production walk-forward на Mac показал WR variance 35-49% между годами. **CV averages skрывают non-stationarity.** Pure CV AUC не предсказывает production performance.

### D. Cross-TF crosses — реально работают (хоть и слабо)

Cross-TF features подняли PBO 0.55 → 0.30 (главное generalization improvement) и попали в топ permutation. Не дали огромного AUC boost (+0.007), но **сделали strategy stable**.

### E. HMA-derived features имеют структурный потолок

Honest ~0.54-0.58 AUC = фундаментальный предел tabular ML на pure HMA features на 14-day directional target. Чтобы поднять выше — нужны другие сигналы (volatility regime, structural confluence, macro context, on-chain).

## Production реальность

```
ob_vc baseline (без ML, всех 6325 events):  35% WR, +374R за 6y (~+62R/year)
v3.5 honest ML (top-17% selection):         38% WR, +56R за 2.5y OOS (~+22R/year)

ML uplift vs random: +6R/year — marginal
Edge есть, но мал. Transaction costs (0.05%×trade × 2) могут "съесть" половину.

При risk 1% per trade: ~125 trades/year × 0.15R E[R] × 1% = ~19% annual return
(idealized, без drawdowns/slippage)
```

## Не сделанные пути forward

1. **Stage 2 honest re-engineering features** — volatility (ATR, BB width), structural (untested fractals, HTF FVG), macro (BTC.D, calendar). Возможно AUC 0.60-0.65.
2. **PC1 full production walk-forward** — точная replica PC1 pipeline за 5 retrain points. ETA 3-4 часа.
3. **Sequence models** — LSTM/Transformer для trajectory pattern matching. Возможно +0.02-0.04 AUC.
4. **Pivot на проверенный setup** — 12h fractal (82% WR canonical), maxV force model (Phase 1 ready), 1.1.1 floating (+428R/6y proven).

## Артефакты

```
~/smc-lib/projects/ob-vc/ml_v3/
  ├── features/hma_at_entry.py              ⚠ LOOKAHEAD (deprecated)
  ├── features/hma_at_entry_honest.py       ✓ HONEST INTRADAY (canon)
  ├── features/cross_tf_crosses.py          ✓ Cross-TF crosses (honest)
  ├── build_features_v3_honest.py           ✓ Honest builder
  ├── build_features_v35_honest_cross.py    ✓ Honest + cross builder
  ├── features_v3_hma.parquet                ⚠ LOOKAHEAD data
  ├── features_v3_hma_honest.parquet         ✓ HONEST (601 fts)
  └── features_v35_hma_honest_cross.parquet  ✓ HONEST + cross (661 fts)

~/Desktop/compute-archives/
  ├── compute-2026-06-09-ob-vc-hma-v3-pc1.zip      ⚠ Used to be lookahead, rebuilt as honest
  └── compute-2026-06-09-ob-vc-hma-v35-pc1.zip     ✓ HONEST + cross-TF (43 MB)

~/Desktop/output PC1 hma/      ⚠ v3 LOOKAHEAD results (deprecated)
~/Desktop/output3/             ⚠ v3.2 LOOKAHEAD results (deprecated)
~/Desktop/output4/             ⚠ v3.3 LOOKAHEAD results (deprecated production canon)
~/Desktop/output s1v2/         ✓ v3 HONEST results (post-fix)
~/Desktop/output_bl/           ✓ v3.5 HONEST + cross results
```

## Related

- [[strategy-ob-vc-v33-lean-picked]] — strategy doc, нужно пометить как deprecated/иллюзия
- [[ml-snapshot-not-trajectory]] — feature design lesson
- [[ob-vc-hma-features-lookahead-fix]] — debugging note
- [[ob_vc_canon_relaxed_7]] — underlying setup canon (НЕ задет багом)
- [[floating-tp-only-helps-low-wr-strategies]] — relevant for future Layer 1 work
