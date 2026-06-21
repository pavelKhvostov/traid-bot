# 2026-06-11 — MA-RR-Predictor Phase 0: инфраструктура + первое обучение

## Цель проекта

**Production indicator**: на каждом закрытии 1h-бара модель смотрит на ~2530 features + raw OHLCV и **5-10 раз в месяц** говорит «вход в сделку, цена коснётся +3/+4/+5% (или −3/−4/−5%) раньше чем −1% против в течение 60 дней» с calibrated honest probability.

**Acceptance (Гибрид)**:
- Primary: top-5% WR ≥ **65%** на 4+/6 walk-forward folds
- Secondary: top-1% WR ≥ **70%** + top-0.5% WR ≥ **75%**
- Production threshold: top-0.3% → 5-10 сигналов/месяц

Связано: [[gbdt-failed-on-rr-prediction]], [[feedback-result-quality-bar]], [[feedback-ml-research-not-validation]]

## Spec (42 решения, LOCKED)

Полный документ: `~/smc-lib/projects/ma-rr-predictor/phase0-spec.md` (on Mac and PC1).

**Ключевое:**
- Окно: 2020-01-01 → 2026-06-11, BTC+ETH joint с `is_eth` фичей
- Labels: triple-barrier RR 3/4/5% × 1% SL × 60d horizon, Conservative tie-break (SL первым)
- Entry TF: только **1h** в Phase 0 (15m/4h позже)
- Архитектура: hybrid **TCN sequence + FT-Transformer tabular** + 6 heads + calibration + abstention
- Compute: PC1 (RTX 5070 Ti + Ryzen 7 7700), всё на PC1, Mac только для чата (per [[feedback-all-compute-on-pc1]])

## Инфраструктура (всё работает)

### PC1 remote access — настроено ✅
- Tailscale + SSH + WSL2 Ubuntu 22.04
- `ssh vadim-pc` алиас на Mac → подключается к WSL
- Python 3.11 venv в `~/smc-lib/projects/ma-rr-predictor/.venv`
- PyTorch 2.11.0+cu128 (Blackwell sm_120)
- GPU benchmark: **99 TFLOPS FP16 sustained**, 300W TDP, 78°C
- См. [[reference-pc-remote-access]]

### Audit framework — done ✅
- `~/smc-lib/projects/ma-rr-predictor/audits/no_lookahead.py`
- Проверяет: feature(t, data) == feature(t, data + future_noise) → bit-perfect
- Self-test пройден, NO LOOKAHEAD invariant обязателен (см. катастрофу v3.3 [[ob-vc-v33-production-canon]])

### Features (2337 tabular) — done ✅

| Модуль | Фичей | Файл | Размер |
|---|---|---|---|
| MA family (8 TF × 3 fam × 20 period × 4 derivs) | 1920 | `features_{asset}_ma_family.parquet` | 337 MB |
| SMC (FVG/iFVG/OB/OB_LIQ/OB_VC/i-RDRB/Williams × 8 TF × 4 fts) | 224 | `features_{asset}_smc.parquet` | 36-37 MB |
| Extras (anatomy/seq/non-MA + is_eth) | 193 | `features_{asset}_extras.parquet` | 34-35 MB |

Все прошли no-lookahead audit. Median NaN: MA 2.3%, SMC 9-11%, Extras 0%.

Code в `~/smc-lib/projects/ma-rr-predictor/features/`:
- `ma_compute.py` — SMA/EMA/HMA/ATR/WMA primitives
- `partial_bar.py` — 1m→TF resample с partial bar live (no-lookahead)
- `ma_family.py` — slow + fast cached MA pipeline
- `smc/base.py + fvg.py + fractals.py + ob.py + rdrb.py + smc_family.py`
- `extras_family.py` — pre-computed RSI/ATR/volume z-scores

### Labels (triple-barrier) — done ✅
- `labels_{asset}.parquet` (6 columns × 56k rows × 2 assets)
- Numba JIT-compiled, 8 секунд total
- Baseline WR: LONG_3=25-26%, LONG_4=21%, LONG_5=18-19%, SHORT_3=25%, SHORT_4=20%, SHORT_5=16-17%
- File: `labels/triple_barrier.py`

### Walk-Forward harness — done ✅
- 6 folds, 2y train + 60d embargo + 6mo val
- Test holdout 2026-04-01 → 2026-06-11 (1704 timestamps, не трогаем до финала)
- File: `training/walk_forward.py`

### Модель (TCN + FT-Transformer + Fusion) — written, smoke-tested ✅

Архитектура (`~/smc-lib/projects/ma-rr-predictor/models/`):
- `tcn.py` — MultiResTCN с 7 каналами OHLCV (15m/1h/2h/4h/6h/12h/1d), 5 dilation levels
- `ft_transformer.py` — FT-Transformer per-element tokenization (~561 tokens × 128 embed × 6 layers × 8 heads)
- `fusion.py` — RRPredictor: concat TCN+FT → 6 sigmoid heads + temperature calibration
- `dataset.py` — feature_groups builder + sequence dataset (slow, on-the-fly resample)

Smoke test (`models/test_model_smoke.py`):
- 10.24M params (full TCN+FT)
- Forward+backward работают на GPU
- Batch=32: 169 samples/sec, VRAM 1.64 GB

## Sanity Training v2 (FT-only, no TCN) — done ✅
- File: `training/train_simple_v2.py` (FP32 + standardize)
- Fold 4, 8 epochs, single seed
- **Mean top-5% WR ≈ 30%** (vs baseline ~21%, **+9pp uplift**)
- Loss конвергирует (0.13 → 0.07), нет NaN/Inf

## Multi-fold v2 (overfit) — done ❌

`training/train_multifold.py` (15 epochs, 6 folds, embed=128 layers=4 dropout=0.2)

**Fold 0 результат**:
- Best ep1: top-5% mean = 0.265, top-1% LONG_5 = 0.42
- Loss падает 0.13→0.08, **но val WR деградирует от ep1 (0.265) к ep15 (0.147)**
- → **Классический overfitting**, остановлено

## Training v3 (regularized) — В ПРОЦЕССЕ 🔄

`training/train_v3_regularized.py`:
- embed_dim=64, n_layers=2, dropout=0.4, wd=1e-2, lr=1e-4
- 0.34M params (vs 1.25M в v2)
- 25 epochs max, early stopping patience=5

**Fold 0** (закончен):
- Early stop ep7, best ep2
- top-1% = [0.34, 0.27, 0.42, 0.31, 0.34, 0.31], **mean = 0.331**
- top-5% = [0.32, 0.27, 0.27, 0.30, 0.27, 0.21], **mean = 0.273**
- top-10% = [0.33, 0.25, 0.22, 0.31, 0.26, 0.20]
- vs v2 fold 0: top-1% **+5pp**, top-5% +0.8pp marginal

**Fold 1+**: идут на момент сохранения.

PID на PC1: `15376`. Лог: `/tmp/train_v3.log`.

## Текущий статус (на момент сохранения)

Multi-fold v3 крутится на PC1. Каждый fold ~7-10 минут (с early stopping), всего ~50-60 минут на 6 folds. После завершения → агрегат + JSON в `~/smc-lib/projects/ma-rr-predictor/results/v3_regularized.json`.

Чтобы проверить статус после рестарта Claude Code:
```bash
ssh vadim-pc 'tail -30 /tmp/train_v3.log'
ssh vadim-pc 'ps -p 15376 -o pid,pcpu,pmem,etime,cmd 2>/dev/null'
```

## Что осталось в Phase 0

После v3 finish:
- [ ] Если v3 даёт top-5% WR ≥ 50% — двигаемся к TCN integration
- [ ] Иначе — попробовать смешанные подходы (TCN добавит сигнал, или ансамбль моделей разной мощности)
- [ ] Optuna 300 trials с ASHA pruning (Phase 0 финал)
- [ ] Top-10 trial × 5 seeds = 50-model ensemble
- [ ] Calibration (temperature scaling + isotonic) + abstention threshold tuning
- [ ] Evaluation: WR curve на 0.1%/0.3%/0.5%/1%/5%/10%, calibration error, net R
- [ ] Final test on holdout 2026-04 → 2026-06

## Параллельно сделано

### Andrey → Vadim handoff (tradingview-mcp) — DONE ✅
- Клонирован `~/tradingview-mcp` (upstream tradesdontlie/tradingview-mcp)
- Применён фикс §1: добавлен `const { evaluate, getChartApi } = _resolve();` в первые строки 4 функций (`listDrawings`, `getProperties`, `removeOne`, `clearAll`) в `src/core/drawing.js`
- Тест CLI: `draw list` вернул 12 shapes (раньше падало с `getChartApi is not defined`) ✓
- Тест CLI: `draw get` вернул координаты ✓
- **TODO после рестарта Claude Code**: MCP-сервер переподключится автоматически → можно использовать MCP-инструменты `draw_list`/`draw_remove_one`/`draw_clear`

## Главные файлы

### Mac
- `/Users/vadim/smc-lib/projects/ma-rr-predictor/phase0-spec.md` — финальный spec (42 решения)
- `/Users/vadim/tradingview-mcp/src/core/drawing.js` — фикс применён
- `/Users/vadim/traid-bot/vault/sessions/2026-06-11-ma-rr-predictor-phase0.md` — этот файл

### PC1 (через `ssh vadim-pc`)
- `~/smc-lib/projects/ma-rr-predictor/phase0-spec.md`
- `~/smc-lib/projects/ma-rr-predictor/features/` — все feature pipelines + parquets в `data/`
- `~/smc-lib/projects/ma-rr-predictor/data/labels_{asset}.parquet`
- `~/smc-lib/projects/ma-rr-predictor/models/` — TCN/FT/Fusion модули
- `~/smc-lib/projects/ma-rr-predictor/training/train_v3_regularized.py` — текущий бегущий
- `~/smc-lib/projects/ma-rr-predictor/audits/no_lookahead.py` — обязательный audit
- `/tmp/train_v3.log` — текущий лог

## Известные открытые вопросы

1. **Сильный overfitting на v2 (embed=128 layers=4)** → v3 (embed=64 layers=2 + heavy reg) пробуем сейчас. Если v3 тоже даст ~25-30% top-5% WR, причина может быть в **слабом сигнале самих фичей**, а не в модели — тогда добавление TCN критично.
2. **TCN ещё не интегрирован в training**. Smoke-test работал на random tensor, но real-data sequence loading не оптимизирован — slow on-the-fly resample. Нужен sequence cache (pre-compute (5, T) tensors per (asset, timestamp)) → ~1.6 GB disk, ~1 min build per asset.
3. **Acceptance gap**: 30% top-5% WR vs 65% target. Ожидаемый uplift: +5-15pp от TCN, +5-10pp Optuna, +3-5pp ensemble, +3-5pp pretraining. **Реалистично достичь 50-55%, до 65% сомнительно** но не закрыто.

## Команды для возобновления после рестарта Claude Code

```bash
# Проверить тренировку
ssh vadim-pc 'tail -30 /tmp/train_v3.log; echo ---; ps -p 15376 2>/dev/null'

# Если v3 закончилась — посмотреть результат
ssh vadim-pc 'cat ~/smc-lib/projects/ma-rr-predictor/results/v3_regularized.json | python3 -m json.tool | head -100'

# Если что-то упало — последние ошибки
ssh vadim-pc 'tail -100 /tmp/train_v3.log | grep -i error -A3'

# GPU status
ssh vadim-pc '/usr/lib/wsl/lib/nvidia-smi'
```

## Связано

- [[reference-pc-remote-access]] — настройки SSH+Tailscale+WSL2
- [[gbdt-failed-on-rr-prediction]] — почему не GBDT
- [[feedback-result-quality-bar]] — критерий acceptance
- [[feedback-ml-research-not-validation]] — принцип «ищем неизвестное»
- [[feedback-all-compute-on-pc1]] — всё на PC1
- [[feedback-ml-lookahead-must-verify]] — обязательность audit
- [[feedback-hma-live-per-tf-at-entry]] — HMA live per TF
- [[ob-vc-v33-production-canon]] — катастрофа из-за lookahead
- [[2026-06-09-ob-vc-ml-lookahead-bug-honest-results]] — предыдущая сессия по той же теме

## Decisions для следующей сессии

- Если v3 ≥ 50% top-5% WR → добавляем TCN, retrain, ожидаем 55-65%
- Если v3 < 35% → не хватает сигнала; пробуем фичи на больших horizon'ах или другие labels
- Если v3 в диапазоне 35-50% → Optuna search с TCN, попытка пробить 55%
