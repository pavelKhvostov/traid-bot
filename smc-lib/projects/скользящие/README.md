# Скользящие (Sliding Averages) — Production ML Strategy

Раздел документирует **открытие что crypto edge на 1h entry TF сидит в multi-TF MA-семействе** (MA/EMA/HMA) — не в SMC структурных элементах. И как использовать это для production.

**Базовое открытие** (12 июня 2026):
> Permutation importance на двух breakthrough моделях показала: **15 из 15 топ-фич** = MA-family на HTF. SMC элементы (FVG/OB/OB_LIQ/OB_VC/i_RDRB/Williams) появляются ниже top-20. Регим определяет какие именно MA смотреть: bull rally = short MAs MTF, bear/chop = long MAs HTF.

## Структура раздела

- **[architecture.md](architecture.md)** — модель v4 TCN + FT-Transformer + regime feature
- **[findings.md](findings.md)** — что мы выяснили эмпирически (и что НЕ работает)
- **[features-by-regime.md](features-by-regime.md)** — какие фичи в каком режиме доминируют
- **[walk-forward.md](walk-forward.md)** — A+B+C+D методологии валидации (anchored, embargo, 12-fold, CPCV)
- **[labels.md](labels.md)** — эволюция labels (60d / 48h strict / 7d strict + clean entry)
- **[ensembles.md](ensembles.md)** — 4-seed averaging probs, метрики по вариантам
- **[clustering.md](clustering.md)** — production signal extraction (cooldown, multi-seed, regime-adaptive)
- **[production-strategy.md](production-strategy.md)** — financial config для real money
- **[results-comparison.md](results-comparison.md)** — полная таблица всех экспериментов
- **[scripts.md](scripts.md)** — индекс всех training/analysis скриптов

## Главные находки одной строкой

1. **MA-family дoминирует edge** (15/15 топ важности в обоих breakthrough фолдах)
2. **Регим определяет period+TF** MA-семейства (bull = LTF short, bear = HTF long)
3. **TCN sequence channel** даёт +3-9pp uplift (sequence patterns читаются особенно на распродажах)
4. **Regime feature как input** = breakthrough (+25pp LONG_3, +12pp SHORT_5 top-0.5%)
5. **Strict 48h labels killят LONG** (drift winners исключены), boost SHORT (impulse moves)
6. **Hybrid strategy = production**: 60d ensemble для LONG, anchored 48h strict для SHORT
7. **Clustering critically reduces noise**: 5-10 sig/мес at 55-60% WR

## Production-ready результат (по состоянию на 2026-06-12)

| Direction | Ensemble | Strategy | Sig/мес | WR (backtest) |
|---|---|---|---|---|
| **LONG** | v4+regime-feat 60d 4-seed | thr=0.50, cooldown 12h, skip CHOP | 5-7 | 55-60% |
| **SHORT** | v4+regime-feat 48h anchored strict 4-seed | thr=0.45, multi-seed 4/4, cooldown 12h | 5/мо | 61.6% |
| **Combined** | hybrid (разные модели для разных направлений) | | **10-12/мес** | **55-60%** |

**Expectancy:** 0.55 × 3R − 0.45 × 1R = **+1.20R per trade** → теоретически **+12R/мес** на 1% risk.
После transaction costs (~0.5%): ~**+10-11R/мес** или ~**+10-12%/мес** на банкролл.

## Что НЕ готово к production

❌ Test holdout 2026-04→06 не вскрыт (запланирован Phase 1)
❌ Live paper trading не сделан
❌ Execution costs не моделированы
❌ Position sizing на ATR не настроен
❌ Bot infrastructure не написан

См. [production-strategy.md](production-strategy.md) для полного pre-launch checklist.

## Ссылка на исходный код и данные

- **Тренировочные скрипты:** `~/smc-lib/projects/ma-rr-predictor/training/`
- **Features:** `~/smc-lib/projects/ma-rr-predictor/data/features_*.parquet` (~1GB)
- **Labels:** `~/smc-lib/projects/ma-rr-predictor/data/labels_*.parquet`
- **Ensemble probs:** `~/smc-lib/projects/ma-rr-predictor/results/`
- **Compute:** PC1 (RTX 5070 Ti, 16GB VRAM) + PC2 (RTX 4070, 12GB VRAM)
