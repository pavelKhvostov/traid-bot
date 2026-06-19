# Phase 3 Paper Trading — Runbook

Hybrid setup: **PC1 обучает checkpoint** (одноразово, ~30-60 мин на RTX 5070 Ti), **PC2 запускает hourly inference** (production-бокс). Использует production canon из `production-strategy.md`.

**Why split:** PC1 остаётся под heavy research (vc-ml-predictor, CPCV extensions, walk-forward), PC2 берёт постоянную лёгкую production-нагрузку. Inference ~10 сек/час — RTX 4070 более чем хватает.

## Архитектура

```
PC1 (research, RTX 5070 Ti):
└── training/train_for_phase3_checkpoint.py   ← одноразово обучает checkpoint

PC2 (production, RTX 4070, always-on):
├── phase3_checkpoint/      ← rsync'нут с PC1
│   ├── model.pt
│   ├── scaler.npz
│   ├── feat_cols.json
│   └── group_sizes.json
├── phase3_inference.py     ← hourly, выдаёт сигнал
├── phase3_runner.sh        ← cron wrapper (BTC + ETH)
└── phase3_log.csv          ← журнал всех сигналов
```

## Шаги установки

### 1. Train production checkpoint на PC1 (один раз, ~30-60 мин)

После того как PC1 свободен (vc_lean закончил):

```bash
ssh vadim-pc
source ~/smc-lib/projects/ma-rr-predictor/.venv/bin/activate
cd ~/smc-lib/projects/ma-rr-predictor
python training/train_for_phase3_checkpoint.py
```

Это обучит ОДИН seed на ВСЕХ данных до **2026-04-01** и сохранит:
- `phase3_checkpoint/model.pt` — веса модели
- `phase3_checkpoint/scaler.npz` — mu/sd для standardization
- `phase3_checkpoint/feat_cols.json` — порядок фич
- `phase3_checkpoint/group_sizes.json` — token groups для FT

### 2. Перенос checkpoint и скриптов PC1 → PC2

```bash
# С Mac (или с PC1 напрямую). Все пути уже корректны для PC2.
ssh vadim-pc 'cd ~/smc-lib/projects/ma-rr-predictor && \
  rsync -av phase3_checkpoint/ vadim-pc2:smc-lib/projects/ma-rr-predictor/phase3_checkpoint/ && \
  rsync -av phase3_inference.py phase3_runner.sh vadim-pc2:smc-lib/projects/ma-rr-predictor/ && \
  rsync -av training/train_for_phase3_checkpoint.py vadim-pc2:smc-lib/projects/ma-rr-predictor/training/'
```

Verify на PC2:
```bash
ssh vadim-pc2 'ls ~/smc-lib/projects/ma-rr-predictor/phase3_checkpoint/ \
  && ls ~/smc-lib/projects/ma-rr-predictor/phase3_inference.py'
```

### 3. Тест inference на PC2 (1 запуск, ~10 сек)

```bash
ssh vadim-pc2
source ~/smc-lib/projects/ma-rr-predictor/.venv/bin/activate
cd ~/smc-lib/projects/ma-rr-predictor
python phase3_inference.py --asset BTCUSDT
python phase3_inference.py --asset ETHUSDT
```

Должно вывести:
```
[2026-06-13 11:00:00+00:00] BTCUSDT regime=BEAR L3=12.3% S3=51.4% → SHORT
```

И добавить строку в `phase3_log.csv`.

### 4. Настроить hourly cron на PC2

```bash
ssh vadim-pc2
crontab -e
```

Добавить:
```cron
0 * * * * /home/vadim/smc-lib/projects/ma-rr-predictor/phase3_runner.sh >> /home/vadim/phase3_cron.log 2>&1
```

### 5. (Опц.) Telegram уведомления (на PC2)

В `~/.bashrc` или systemd env-file **на PC2**:
```bash
export TELEGRAM_BOT_TOKEN="..."
export TELEGRAM_CHAT_ID="..."
```

При срабатывании сигнала `signal_fire=True` отправится сообщение:
```
📈 LONG BTCUSDT
Time: 2026-06-13 11:00:00+00:00
Regime: BEAR
P(LONG_3): 53.2%, P(SHORT_3): 12.1%
Entry: 67432.50, TP: 69456.65, SL: 66758.18
```

## Production canon parameters

| Параметр | Значение | Источник |
|---|---|---|
| Threshold | 0.50 | `production-strategy.md` |
| LONG regime filter | skip CHOP | `production-strategy.md` |
| SHORT regime filter | (any) | |
| Cooldown | 12 часов | |
| TP | +3R (3% от entry, SL=1%) | |
| SL | -1% от entry | |
| Position size | 1% bank risk | NOT auto — manual для paper |

## Decision gate Phase 3 → Phase 4

После **1-2 месяцев** paper trading:

| Метрика | Pass | Действие |
|---|---|---|
| Live WR | ≥ 50% | → Phase 4 (live micro 0.1-0.5%) |
| Live WR | 45-50% | Marginal — ещё месяц наблюдения |
| Live WR | < 45% | STOP — re-research модели |
| Drawdown | < 15% | OK |
| Drawdown | > 15% | Stop new entries, review |

## Что НЕ делает Phase 3

❌ Не отправляет реальные ордера на биржу
❌ Не использует ансамбль из 4 seeds (только 1 для скорости)
❌ Не обновляет фичи в реальном времени из 1m (использует pre-computed parquets)

## TODO для Phase 3.1 (улучшения)

- [ ] **Реальный 1m fetch** — добавить `fetch_btc_1m_missing.py` перед inference
- [ ] **Real-time feature computation** — incremental, не из parquets
- [ ] **4-seed ensemble inference** — больше robust signals
- [ ] **PnL tracker** — после Phase 3 окна посчитать realized R
- [ ] **Dashboard** — web view phase3_log.csv

## Связь

- Production canon: `production-strategy.md`
- Architecture: `architecture.md`
- Phase 1 results: `findings.md`
- Phase 2 results: `results-comparison.md`
