# Скрипты проекта 12h-fractal-new

Все 14 B-class фильтр-скриптов перенесены в **`~/smc-lib/projects/12h-fractal-new/scripts/`**.

Старые экспериментальные скрипты остаются в `~/smc-lib/scripts/pred12h_*.py` как **архив** (см. внизу).

## Структура папки scripts/

```
scripts/
├── _lib.py                    — shared utilities (1m load, agg, ATR, baseline match, stats, fires save)
├── _fvg.py                    — FVG scan + event timeline (для всех B1Cx)
├── A_cascade.py               — A1∩A2∩A3∩A4 → baseline parquet (foundation)
├── B1C1_strict_S100_wide.py
├── B1C2_strict_S50_age_wide.py
├── B1C3_strict_S70_age50.py
├── B1C4_strict_S50_htf_wide.py
├── B1C5_vol_spike.py
├── B1C6_retest.py
├── B2C1_ob_sweep.py
├── B2C2_ob_liq_sweep.py
├── B3C1_maxv_sweep.py
├── B4C1_hma78_sweep.py
├── B4C2_hma200_sweep.py
├── B5C1_vwap_w_aligned.py
├── B8C1_force_div_reverse.py
├── B9C1_p11_count.py
└── run_all.py                 — orchestrator (запускает все 14 + считает union)
```

## Канон 14 B-скриптов

| Script | Block | Filter | Causal | Verified |
|---|---|---|:---:|:---:|
| `B1C1_strict_S100_wide.py`        | B1 FVG | pen≥100 + close OUT + WIDE        | ✅ | ✅ |
| `B1C2_strict_S50_age_wide.py`     | B1 FVG | pen≥50 + close OUT + AGE50∧WIDE   | ✅ | ✅ |
| `B1C3_strict_S70_age50.py`        | B1 FVG | pen≥70 + close OUT + AGE50        | ✅ | ✅ |
| `B1C4_strict_S50_htf_wide.py`     | B1 FVG | pen≥50 + close OUT + HTF∧WIDE     | ✅ | ✅ |
| `B1C5_vol_spike.py`               | B1 FVG | pen≥50 + close OUT + vol_z≥+2σ    | ✅ | ✅ |
| `B1C6_retest.py`                  | B1 FVG | sweep + close inside ≤3 bars      | ✅ | ✅ |
| `B2C1_ob_sweep.py`                | B2 OB  | FIRST 50%-sweep block_orders multi-TF | ✅ | ✅ |
| `B2C2_ob_liq_sweep.py`            | B2 OB  | FIRST 50%-sweep ob_liq multi-TF    | ✅ | ✅ |
| `B3C1_maxv_sweep.py`              | B3 FL  | high/low cross maxV(i-1) + close back | ✅ | ✅ |
| `B4C1_hma78_sweep.py`             | B4 HMA | HMA-78 (12h ∪ D) LIVE sweep        | ✅ | ✅ |
| `B4C2_hma200_sweep.py`            | B4 HMA | HMA-200 D LIVE sweep               | ✅ | ✅ |
| `B5C1_vwap_w_aligned.py`          | B5 VW  | ≥2 W-aligned swept anchored VWAPs  | ✅ | ✅ |
| `B8C1_force_div_reverse.py`       | B8 PZ  | reverse force div ∪3               | ✅ | ✅ |
| `B9C1_p11_count.py`               | B9 Ot  | P11_count 4-window OR              | ✅ | ✅ |

**Правила (отражены в коде):**
- Strict causality: только данные ≤ pivot bar i. Per [[feedback-b-series-strict-causal-i]].
- Window: 2020-01-01 → текущий момент. Per [[feedback-pred12h-window-and-noimp]].
- **НЕТ** is_imp tracking — удалено из всех скриптов. Метрики: только n / conf / WR / Δ.
- Каждый скрипт самодостаточен: `python3 BxCy_*.py` запускает фильтр и пишет fires в `~/Desktop/12h-fractal-new-out/BxCy_fires.parquet`.

## Зависимости

| Скрипт | Внешние модули |
|---|---|
| `_lib.py` | `pandas`, `numpy`. Read: `~/traid-bot/data/BTCUSDT_1m_vic_vadim.csv`, `~/Desktop/pred12h_baseline_v2.parquet` |
| `_fvg.py` | `~/smc-lib/elements/fvg/code.py`, `~/smc-lib/candle.py` |
| `B2C1` | `~/smc-lib/elements/block_orders/code.py` |
| `B2C2` | `~/smc-lib/elements/ob_liq/code.py` |
| `B4C1/C2` | `~/smc-lib/indicators/trend_line_asvk.py` (HMA helpers) |
| `B8C1` | Pre-computed `~/Desktop/force_all_bars_per_tf.parquet` |
| `A_cascade` | None (только 1m csv) |

## Использование

### Generate baseline:
```bash
cd ~/smc-lib/projects/12h-fractal-new/scripts
python3 A_cascade.py
```

### Run single B-filter:
```bash
python3 B1C1_strict_S100_wide.py
# output: console summary + ~/Desktop/12h-fractal-new-out/B1C1_fires.parquet
```

### Run all 14 + union:
```bash
python3 run_all.py
```

## Output

`~/Desktop/12h-fractal-new-out/` — fires parquets для каждого BxCy:
```
B1C1_fires.parquet
B1C2_fires.parquet
...
B9C1_fires.parquet
```

Каждый содержит: `pivot_open_ts_ms`, `zone_direction`, `bar_idx`.

## Архив (старые скрипты в `~/smc-lib/scripts/`)

Эти **НЕ канон для проекта** — оставлены для исторической справки:

| Source | Логика, мигрированная в новый канон |
|---|---|
| `pred12h_baseline_v2.py` | → `A_cascade.py` |
| `pred12h_b1_v4_union.py` | → B1C1..B1C6 + run_all |
| `pred12h_c4_subbasket.py` | → разнесён по B1C1..B1C6 |
| `pred12h_c4_d7_d14.py` | → grid-эксперимент, не canon |
| `pred12h_C1_C2_orbasket.py` | → B3C1 (maxV) + B9C1 (P11) |
| `pred12h_cond2_p11_union.py` | → B9C1 (P11) |
| `pred12h_cond3_*.py` | → B2C2 (ob_liq) |
| `pred12h_ob_liq_condition.py` | → B2C2 |
| `pred12h_fvg_50sweep_condition.py` | → B1Cx (поглощено) |
| `pred12h_trendline_*.py` | → B4C1, B4C2 (HMA) |
| `pred12h_c6_mining.py` | → B4C2 (HMA-200 mining experiment) |
| `pred12h_C8_*.py` | → B5C1 (VWAP, поглощено) |
| `pred12h_basket_c1c2c3.py` | → B2C1, B3C1, B8C1, run_all |
| `basket_andrey_magnitude.py` | → B8C1 (force div ∪3) |
| `pred12h_evot_*.py` | **rejected** (был кандидат в C2, не принят) |
| `pred12h_F4_*.py`, `pred12h_F5_*.py` | **rejected** (cascade extensions, не приняты) |
| `pred12h_3bar_predictor.py` | early prototype (эволюционировал в A-cascade) |
