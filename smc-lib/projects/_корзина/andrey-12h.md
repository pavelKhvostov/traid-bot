# Проект Андрей 12h — ML pivot detection (BTC 12h)

**Author:** Andrew Masyuckevich `<masyuckevich12345@gmail.com>`
**Source:** `~/traid-bot @ origin/andrey` (commit `a17a686`, 2026-06-04)
**Status:** Active research, etap 156-173 закрыт, AUC 0.91-0.94 honest CV.

## 1. Описание

Honest ML pipeline для детекции **HH/LL фракталов на BTC 12h** (Williams N=2). Цель — найти точки разворота с высокой precision на 6 таргетах (3/4/5% move в обе стороны).

Серия из 18 этапов (156-173), методология — Lopez de Prado «Advances in Financial ML» (Ch.3 TBM/meta-labeling, Ch.4 sample weights, Ch.5 frac diff, Ch.7 Purged K-Fold, Ch.17 SADF, Ch.19 microstructure). Без lookahead'а, CV std ~0.01 = подтверждённо честный.

## 2. Таймфрейм и инструменты

- **Базовый TF:** 12h
- **Активы:** BTC
- **Train:** 2020-2024 (3652 events)
- **OOS Holdout:** 2025 — 2026.05 (1015 events)
- **HTF features:** 1d/12h/4h/2h/1h (zone strength)

## 3. Эволюция этапов

| Etap | Содержание | Result |
|------|-----------|--------|
| 156-166 | V1/V2 strategy compare, expert opinion, honest fractal pivot detector — Williams N=2 + HTF Hull fix | baseline precision 53.7% @ thr 0.7 |
| 167 | Zone strength features (age/width/touches/HTF flag) × LONG/SHORT × OB/FVG × 5TFs | 240 фич, precision 53.7% → 63% |
| 168 | Murphy strategies backtest — Fibonacci EMA 13/34 best (+30.6R), RSI div fail (-17.3R) | — |
| 169 | Triple-barrier + meta-labeling (Lopez Ch.3) on failed_sweep | AUC 0.488, no edge alone |
| 170 | Lopez features: SADF (Ch.17), Amihud, VPIN, Roll, Parkinson, Garman-Klass (Ch.19), Frac-diff d=0.4 (Ch.5) + Purged K-Fold embargo=14 + sample_weights = uniqueness × \|return\| (Ch.4 + 7) | **AUC 0.91-0.94 honest** (CV std 0.01) |
| 171 | + VSA cluster (Williams) + Nison candle patterns + doji + phase_state + confluence_score | 270 фич, AUC 0.92-0.94 |
| 172 | 13 Bulkowski reversal-pattern detectors из Encyclopedia 3rd Ed. (2076p) → 4 parallel extraction agents | 520 raw signals, 11 detectors actual |
| 173 | Integration Vadim 12h-fractal-predictor + Bulkowski на base etap_171 | 308 фич, precision@0.7-0.8 jumped 67→82%, 69→89% (SHORT) |

## 4. Ключевые результаты (etap 173)

### AUC по 6 targets

| Target | Baseline pos% | CV AUC | CV std | Holdout AUC | Brier | AP |
|--------|---------------|--------|--------|-------------|-------|-----|
| `y_low_strong_3` | 13.1% | 0.942 | 0.014 | 0.941 | 0.064 | 0.614 |
| `y_low_strong_4` | 12.0% | 0.937 | 0.014 | 0.935 | 0.062 | 0.580 |
| `y_low_strong_5` | 11.1% | 0.934 | 0.012 | 0.923 | 0.062 | 0.475 |
| `y_high_strong_3` | 12.3% | 0.929 | 0.014 | 0.936 | 0.061 | 0.626 |
| `y_high_strong_4` | 11.2% | 0.925 | 0.013 | 0.921 | 0.064 | 0.495 |
| `y_high_strong_5` | 9.8% | 0.916 | 0.014 | 0.912 | 0.061 | 0.411 |

**OOS=CV match** → нет overfit'а. **CV std 0.012-0.015** = honest.

### Top-5 features (y_low_strong_3, LONG side ≥3% move)

| Rank | Feature | Importance |
|------|---------|-----------|
| 1 | `sweep_SSL_mag_24h_pct` | **0.362** ← доминирует |
| 2 | `candle_close_pos_in_range` | 0.134 |
| 3 | `sweep_SSL_24h` | 0.108 |
| 4 | `sweep_SSL_failed_24h` | 0.024 |
| 5 | `vsa_climax_bull` | 0.023 |

**Sweep magnitude — главный сигнал**. Confluence ≥3 групп фич в top-30.

### Bulkowski top-5 patterns (etap 172)

| Pattern | Signals | Edge | Fail rate |
|---------|---------|------|-----------|
| `big_w` | 89 | **+29.8R** | 17% |
| `db_eve_eve` | 49 | +29.6R | 16% |
| `v_bottom` | 42 | +26.6R | 14% |
| `hs_bottom` | 30 | +31.6R | 13% |
| `big_m` | 87 | +16.0R | 21% |

`cup_handle` / `rounding_bottom` нашли 0 на BTC 12h — R² слишком strict для крипты.

## 5. Sniper / Core composite (Vadim's rule-based)

| Mode | Definition | Precision |
|------|-----------|-----------|
| **HH Sniper** | `sweep_FH ∧ sweep_OB_SHORT ∧ maxV_sweep_HH` | 93% (~5/yr) |
| **LL Sniper** | зеркально | ~93% |
| ML @ thr 0.8 | etap 173 features | 82-89% SHORT |

ML догнал rule-based Sniper, но с большей flexibility на lower thresholds.

## 6. Методология (Lopez de Prado canon)

| Ch | Применение | etap |
|----|-----------|------|
| 3.2 TBM | Triple-barrier labeling | 169 |
| 3.6 Meta-labeling | failed_sweep primary + ML secondary | 169, 173 |
| 4.2-4.4 Sample weights | uniqueness × \|return\| | 170+ |
| 5 Fractional diff | d=0.4 для close series | 170 |
| 7 Purged K-Fold | embargo=14 | 170+ |
| 17 CUSUM/SADF | structural break feature | 170 |
| 19 Microstructure | Amihud, VPIN, Roll, Parkinson, Garman-Klass | 170 |

## 7. Скрипты (origin/andrey)

| Path | Что |
|------|-----|
| `research/elements_study/etap_167_zone_strength.py` | 240 zone features |
| `research/elements_study/etap_170_lopez_features.py` | **honest CV baseline (AUC 0.91-0.94)** |
| `research/elements_study/etap_171_vsa_candlesticks.py` | + VSA + Nison (270 фич) |
| `research/elements_study/etap_172_bulkowski_patterns.py` | 13 Bulkowski detectors |
| `research/elements_study/etap_173_vadim_bulkowski_integration.py` | 308 фич, Vadim + Bulkowski |
| `research/vic_vadim/predict_fractal_zones.py` | Vadim's sweep[i] (referenced) |
| `research/vic_vadim/predict_fractal_maxv_pine.py` | Vadim's maxV(i-1) Pine LTF=8m |

## 8. Output артефакты

| File | Что |
|------|-----|
| `output/etap_173_summary.csv` | AUC + CV scores per target |
| `output/etap_173_signals_caught.csv` | 305 OOS ML signals @ thr≥0.3 |
| `output/etap_173_feature_importance.csv` | per-target top features |
| `output/etap_173_pred_y_{low,high}_strong_{3,4,5}.csv` | 6 prediction files |
| `output/etap_172_signals.csv` | 520 Bulkowski raw fires |
| `output/etap_172_stats.csv` | per-pattern × period |
| `refs/bulkowski_master_stats.md` | master reference из Encyclopedia |

## 9. Vault sessions (Obsidian)

- `2026-06-03-bulkowski-12-reversal-detectors-etap-172.md`
- `knowledge/decisions/bulkowski-top-12-patterns-for-btc-12h.md`
- `knowledge/strategies/bulkowski-reversal-detectors-btc-12h-baseline.md`

## 10. Пересечения с моим (Vadim) research

- **maxV(i-1) C2** — Pine ASVK LTF=**8m** (12h/45=16m? Andrey uses 8m? проверить — расхождение с моим mlt=45 D-canon)
- **Sweep features** Group A (Vadim 12h/1d OB/FH-FL) — **redundant** с zone features etap_165-167
- **Bulkowski patterns** — новые, не пересекаются с моим
- **maxV force model** Phase 1 — независим от Andrey 12h, но методология Lopez совпадает

## 11. Открытые вопросы

1. LTF=8m vs LTF=32m (mlt=45 D-canon) — нужна сверка определений
2. Можно ли применить Andrey's pipeline (etap_170 honest CV) к D-фракталам как «maxV force model Phase a»?
3. Sniper precision 93% — стоит сравнить с моим heuristic AMP top-quantile
4. 308 features → есть ли смысл добавить мои 5 AMP-условий как доп. features в etap_174?

## Related

- `[[maxv-force-model-5-conditions]]` — мой проект (D-фокус)
- `~/traid-bot/research/elements_study/` — все etap скрипты Andrey
- `~/traid-bot @ origin/andrey` — actual branch
