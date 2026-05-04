# Baseline metrics — 2026-05-04 14:16

Прогон через `vault/baseline/2026-05-04-14-16/run.sh`. Все 14 скриптов exit=0.

**SHA256 hash variant:** `sort <file>.csv | shasum -a 256` (отсортированный — устраняет ложные MISMATCH в Фазе 4).

## Метрики

| Script | sec | section | total | closed | W | L | WR | PnL R |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| backtest_1_1_1_sl_on_htf.py | 53 | RR=2.2 (SL on ob_htf) | 170 | 168 | 73 | 95 | 43.5% | +68.8R |
| backtest_rdrb_konfetka.py | 28 | baseline (no filter) | 127 | 123 |  |  | 40.7% | +37.0R |
|  |  | L1+L2 (best filter) | 18 | 16 |  |  | 68.8% | +19.2R |
| backtest_strategy_1_1_1.py | 80 | RR=1.0 | 144 | 141 |  |  | 61.7% | +33.0R |
|  |  | RR=2.2 | 143 | 140 |  |  | 41.4% | +45.6R |
| backtest_strategy_1_1_2.py | 219 | RR=1.0 | 449 | 442 |  |  | 53.8% | +34.0R |
|  |  | RR=2.2 | 448 | 441 |  |  | 32.9% | +23.0R |
| backtest_strategy_1_1_2_extended.py | 945 | ? | 449 | 442 | 238 | 204 | 53.8% | +34.0R |
|  |  | ? | 448 | 441 | 145 | 296 | 32.9% | +23.0R |
|  |  | ? | 1272 | 1257 | 637 | 620 | 50.7% | +17.0R |
| backtest_strategy_1_1_3.py | 89 | RR=1.0 | 125 | 122 |  |  | 52.5% | +6.0R |
|  |  | RR=2.2 | 125 | 122 |  |  | 34.4% | +12.4R |
| backtest_strategy_1_1_4.py | 59 | RR=1.0 | 53 | 53 |  |  | 52.8% | +3.0R |
|  |  | RR=2.2 | 53 | 53 |  |  | 37.7% | +11.0R |
| backtest_strategy_1_2_0.py | 10 | variant:full | 24 | 13 | 6 | 7 | 46.2% | -1.00R |
|  |  | variant:no_top_ob | 62 | 32 | 13 | 19 | 40.6% | -6.00R |
| backtest_strategy_rdrb.py | 47 | RR=1.0 | 127 | 123 |  |  | 54.5% | +11.0R |
|  |  | RR=2.2 | 127 | 123 |  |  | 35.0% | +14.6R |
| backtest_strategy_rdrb_premium.py | 22 | baseline @ RR=2.2 | 40 | 38 |  |  | 42.1% | +13.2R |
| backtest_strategy_rdrb_trend.py | 27 | baseline (filter sweep) | 127 | 123 |  |  | 40.7% | +37.0R |
| backtest_strategy_rdrb_wick.py | 28 | baseline (wick sweep) | 127 | 123 |  |  | 40.7% | +37.0R |
| backtest_vic_bos.py | 517 | RR=1.0 | 347 | 347 | 181 | 166 | 52.2% | +15.0R |
|  |  | RR=2.2 | 347 | 347 | 115 | 232 | 33.1% | +21.0R |
| backtest_vic_evot.py | 193 | RR=1.0 | 640 | 635 | 298 | 337 | 46.9% | -39.0R |
|  |  | RR=2.2 | 640 | 635 | 193 | 442 | 30.4% | -17.4R |

## CSV outputs + SHA256 (sorted)

### backtest_1_1_1_sl_on_htf.py
- `signals/strategy_1_1_1_sl_htf_3y_RR2.2.csv` — `357762d721bc5970`

### backtest_strategy_1_1_1.py
- `signals/strategy_1_1_1_3y_RR1.csv` — `b1f5bae17298b1e3`
- `signals/strategy_1_1_1_3y_RR2.2.csv` — `406435c8872e7f3a`

### backtest_strategy_1_1_2.py
- `signals/strategy_1_1_2_3y_RR1.csv` — `ec3c2b7ef3c06e97`
- `signals/strategy_1_1_2_3y_RR2.2.csv` — `ed09abed30e1de9e`

### backtest_strategy_1_1_3.py
- `signals/strategy_1_1_3_3y_RR1.csv` — `d346ad6a40fda046`
- `signals/strategy_1_1_3_3y_RR2.2.csv` — `83921be4d248a95f`

### backtest_strategy_1_2_0.py
- `signals/strategy_1_2_0_full.csv` — `94a6f75f33291c20`
- `signals/strategy_1_2_0_no_top_ob.csv` — `1215261316104b90`

### backtest_strategy_rdrb.py
- `signals/strategy_rdrb_3y_RR1.csv` — `f22ed3d1326a0eda`
- `signals/strategy_rdrb_3y_RR2.2.csv` — `ca73a2e3d22d03af`

### backtest_strategy_rdrb_premium.py
- `signals/strategy_rdrb_premium_3y_RR2.2.csv` — `b9773638287642b7`

### backtest_vic_bos.py
- `signals/vic_bos_3y_RR1.csv` — `228daa4343ad54ed`
- `signals/vic_bos_3y_RR2.2.csv` — `444fe7a8cbdfdb83`

### backtest_vic_evot.py
- `signals/vic_evot_backtest_3y_ob_RR1.csv` — `12e8c51b161b1f02`
- `signals/vic_evot_backtest_3y_ob_RR2.2.csv` — `dba5487d0c6889bd`

## Сравнение с CLAUDE.md

CLAUDE.md (актуально на 2026-04-29): для Strategy 1.1.1 — WR 56.5%, +12R на 3y BTC.

`vault/00-home/текущие приоритеты.md` (свежее) даёт другие числа после фикса
SL=15% inside и bucketing dedup (на 2026-04-29):
- baseline RR=1: WR 61.7%, +33R
- sweet RR=1.24: WR 58.2%, +43R

**Прогон 2026-05-04 даёт:**
- RR=1.0: WR=61.7%, PnL=+33.0R, total=144
- RR=2.2: WR=41.4%, PnL=+45.6R, total=143

**Вердикт:** числа из `текущие приоритеты.md` **совпадают точно** (RR=1: WR 61.7%, +33R). Старые цифры из CLAUDE.md (56.5% / +12R) — до SL=15% и bucketing fix'ов, нужно обновить CLAUDE.md в Фазе 5.

## Broken

Нет broken — все 14 exit=0.
