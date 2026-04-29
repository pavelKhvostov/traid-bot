---
tags: [debugging, look-ahead, strategy_1_1_1]
date: 2026-04-29
status: fix-pending
---

# Strategy 1.1.1: hardcoded +15min для fill-scan ломает 20m FVG сигналы

## Симптом

В backtest_strategy_1_1_1.py при прогоне 3y BTC выявлен «магический» WR
64.2% на 123 closed сделках (RR=1, +35R). Это попадает в красную зону
по pitfall #1 (WR > 60% на 100+ сделках = кандидат на look-ahead).

## Причина

[backtest_strategy_1_1_1.py:47](../../../backtest_strategy_1_1_1.py#L47):

```python
fill_scan_start = signal_time + pd.Timedelta(minutes=15)
```

`signal_time = fvg_entry.c2_time` ([strategy_1_1_1.py:392](../../../strategies/strategy_1_1_1.py#L392))
— это open_time свечи c2 entry-FVG. Хардкод `+15min` корректен только
для FVG-15m (close = open + 15min). Для FVG-20m close = open + 20min,
а scan стартует за **5 минут до фактического закрытия c2 свечи** —
на этих 5 минутах живут 1m бары, которые в реал-тайме всё ещё являются
частью формирующейся 20m c2 (FVG ещё не подтверждена в этот момент).

Из funnel прогона: 30 из 129 сигналов на 20m (~23%). Для них fill
может срабатывать на 1m свече, которая в реал-тайме ещё не попала
бы в валидную FVG.

Это та же категория ошибки, что look-ahead в VIC_EVOT (см.
[[lookahead-bug-в-vic-evot-backtest]]) — отличается только амплитудой
(5 мин на 23% сигналов vs 15 мин на 100% VIC сигналов).

## Фикс (запланирован Фазой 1 ветки feat/strategy-1-1-1-ob-12h)

```python
# БЫЛО:
fill_scan_start = signal_time + pd.Timedelta(minutes=15)

# СТАНЕТ:
tf_minutes = 15 if sig["fvg_tf"] == "15m" else 20
fill_scan_start = signal_time + pd.Timedelta(minutes=tf_minutes)
```

После фикса ожидается:
- Падение числа filled-сделок на 20m-сигналах (часть «успевала» зайти
  на 1m внутри ещё-не-закрытой 20m c2 — теперь не успеет).
- Падение WR на 1–3pp (тяжело предсказать амплитуду; зависит от того,
  насколько часто 5-минутный лаг был решающим).

## Почему не пофиксили сразу при первом обнаружении

Yellow flag был зафиксирован backtest-auditor'ом в сессии 2026-04-29.
Юзер выбрал прогон «как есть с дисклеймером» (вариант 2 ШАГ 3) для
получения первичных чисел. Фикс выделен в отдельную фазу следующей
задачи.

## Правило избегания (для будущих стратегий с multi-LTF entry)

Любой `signal_time + Timedelta` хардкод — RED FLAG. Длительность бара
**должна выводиться из метаданных сигнала** (`sig["fvg_tf"]` или
`sig["entry_tf_minutes"]`), не из контекста скрипта.

Pattern:
```python
TF_MINUTES = {"15m": 15, "20m": 20, "30m": 30, "1h": 60}
fill_scan_start = sig["signal_time"] + pd.Timedelta(
    minutes=TF_MINUTES[sig["entry_tf"]],
)
```

## Связано

- [[known-pitfalls]] — добавлен как 8-й пункт.
- [[lookahead-bug-в-vic-evot-backtest]] — родственный баг другой амплитуды.
- [[strategy_1_1_1]] — spec, обновится после фикса.
