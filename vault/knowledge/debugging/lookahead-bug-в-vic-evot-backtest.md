---
tags: [debugging, backtest, lookahead, vic-evot]
date: 2026-04-28
related: [[vic_evot]], [[2026-04-28-strategy-1-1-1-vic-bos-research]]
---

# Lookahead bug в VIC_EVOT backtest (2026-04-28)

## Симптом

Grid search по entry_pct × sl_buffer на 3 года BTC показал «магические» результаты:
- `entry_pct=0.0, sl_buffer=0.8`: 678 trades, WR **63.6%**, **+184R**
- `entry_pct=1.0, sl_buffer=0.8`: 680 trades, WR 62.9%, +176R

Это нереалистично для криптостратегии. WR 63%+ на 678 trades = настоящий грааль.
Прозвучал звоночек.

## Причина

В `backtest_vic_evot.py simulate_outcome`:

```python
# БЫЛО (баг):
forward = df_1m[df_1m.index >= signal_time]  # signal_time = open(i+2)
```

`signal_time` = `open_time` свечи `i+2` (= когда сигнал «формируется»). Но bar `i+2`
ЗАКРЫВАЕТСЯ через 15 минут после `open_time`. Сканируя 1m с `open(i+2)`, мы захватываем
1m свечи **внутри bar i+2** — данные, которые в реал-тайме недоступны до close
этого 15m бара.

Особенно затрагивало `entry_pct=1.0`: `entry = low(i+2)`. Внутри бара i+2 заведомо
есть 1m свеча с low = low(i+2) → **fill происходит мгновенно** в момент когда
эта 1m открылась. В реал-тайме этой информации нет.

Для `entry_pct=0.0` (= `high(i)`) баг работал иначе: low(i+2) > high(i) (FVG),
поэтому 1m внутри bar i+2 не могли заполнить entry. Но «магический» WR всё равно
завышен — видимо из-за того, что и SL и TP проверялись с lookahead.

## Фикс

```python
# СТАЛО:
scan_start = signal_time + pd.Timedelta(minutes=15)  # close(i+2)
forward = df_1m[df_1m.index >= scan_start]
```

[backtest_vic_evot.py — место фикса в `simulate_outcome`](../../backtest_vic_evot.py).

## Результаты после фикса

| Конфиг | До фикса WR/PnL | После фикса WR/PnL |
|---|---|---|
| e=0.0 sl=0.8 | 63.6% / +184R | 49.6% / **−6R** |
| e=1.0 sl=0.8 | 62.9% / +176R | **51.0% / +13R** |
| e=0.5 sl=1.0 | 49.5% / −7R | 49.5% / −7R (unchanged) |

«Магия» полностью пропала. Лучшая (реальная) комбинация на 3y BTC:
**e=1.0 sl=0.8** даёт **+13R** на 679 сделках = маргинальный edge.

## Урок

1. **Любой scan от open текущего бара = lookahead.** В backtest всегда
   проверять стартовую точку симуляции — должна быть **close** последнего
   известного бара, а не его open.

2. **Out-of-sample результаты, сильно отличающиеся от 90-дневных пиков,
   = первый звонок проверить lookahead.** 90-дневные WR 70%+ были все артефактами.

3. **«Магические» grid search результаты с экстремальным WR > 60% на сотнях
   сделок крипто-стратегии — обычно lookahead.** Криптотрейдинг даёт WR
   45-55% на честных стратегиях.

## Затронутые скрипты

- `backtest_vic_evot.py` — основной фикс в `simulate_outcome`.
- `optimize_vic_entry_sl.py` и `optimize_vic_yearly.py` — те же scan_start
  правки.

Все три скрипта теперь стартуют сканирование с `signal_time + 15min` для 15m
сигналов и `signal_time + 1h` для 1h сигналов (где применимо).

## Связи

- [[vic_evot]] — текущая логика стратегии.
- [[2026-04-28-strategy-1-1-1-vic-bos-research]] — сессия, в которой был найден баг.
