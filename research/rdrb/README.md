# RDRB research-варианты

Status: **research, кандидаты на расширение/замену live.**

В live боте работает базовый RDRB (`strategies/rdrb.py` — пересечение фитилей с ограничением телами). Эти 5 research-вариантов — **отдельные эксперименты**, не дубли. Ни один пока не интегрирован.

## Варианты

| Вариант | Идея | Файл |
|---|---|---|
| **base** | базовый RDRB на BTCUSDT 3y | `backtest_strategy_rdrb.py` |
| **premium** | RDRB + L0 Daily OB filter (entry=0.95, sl=0.35) | `backtest_strategy_rdrb_premium.py` |
| **trend** | RDRB + HTF trend filter sweep | `backtest_strategy_rdrb_trend.py` |
| **wick** | RDRB + wick-ratio filter | `backtest_strategy_rdrb_wick.py` |
| **konfetka** | RDRB + filter stack L1+L2+L3 (fvg_pos middle + 1d confluence + UTC hour) | `backtest_rdrb_konfetka.py` |

## Базовые показатели (3y BTC)

| вариант | RR | total | closed | WR | PnL R |
|---|---:|---:|---:|---:|---:|
| base | 1.0 | 127 | 123 | 54.5% | +11.0R |
| base | 2.2 | 127 | 123 | 35.0% | +14.6R |
| premium | 2.2 | 40 | 38 | 42.1% | +13.2R |
| konfetka L1+L2 | 2.2 | 18 | 16 | **68.8%** | +19.2R |
| konfetka L1+L2+L3 | 2.2 | 2 | 2 | **100%** | +4.4R |

`konfetka` — самый перспективный фильтр-стек (L1: fvg_pos middle + L2: 1d triple confluence + L3: UTC hour). На 3y BTC `L1+L2` даёт WR 68.8% на 16 сделках.

## Файлы

### backtest/
- `backtest_strategy_rdrb.py`, `backtest_strategy_rdrb_premium.py`, `backtest_strategy_rdrb_trend.py`, `backtest_strategy_rdrb_wick.py`, `backtest_rdrb_konfetka.py`

### analyze/
- `analyze_rdrb_confluence_macro.py` — TOTALES + USDT.D confluence
- `analyze_rdrb_winners_losers.py` — split winners/losers по features

### optimize/
- `optimize_rdrb_entry_sl.py` — grid entry × sl

## Что НЕ трогать

- `strategies/rdrb.py` (live) — research-варианты его НЕ модифицируют.
