# VIC backtests

Status: **out-of-scope** текущего рефакторинга 1.1.x. Перемещены сюда для единства research-структуры, но не входят в pavel-эталон.

## Что есть

| Файл | Описание |
|---|---|
| `backtest/backtest_vic_evot.py` | research-прогон уже-live VIC_EVOT |
| `backtest/backtest_vic_bos.py` | кандидат VIC_BOS (BOS на 3m, 3y BTC: WR 53.6%, +37R) |
| `optimize/optimize_vic_entry_sl.py` | grid entry × sl |
| `optimize/optimize_vic_yearly.py` | year-by-year breakdown |

## Базовые показатели (3y BTC)

- VIC_EVOT @ RR=1.0: 640 / W=298 / L=337 → WR 46.9%, **−39R** (отрицательный edge на длинной дистанции)
- VIC_BOS @ RR=1.0: 347 / W=181 / L=166 → WR 52.2%, **+15R**
- VIC_BOS @ RR=2.2: 347 / W=115 / L=232 → WR 33.1%, +21R

## Источники

- [[2026-04-27-vic-evot-реализация]]
- [[2026-04-27-vic-evot-backtest-и-ltf-fix]]
- [[vic-maxv-расходился-с-pine-индикатором-из-за-1m-вместо-15m]]
- VIC_EVOT в live: см. `vic_scanner.py` в корне репо.

## Что НЕ трогать

- `strategies/vic_evot.py`, `vic_levels.py`, `vic_scanner.py` (live).
