---
tags: [debugging, lookahead, backtest, multi-bar-pattern]
date: 2026-05-08
related: [research/elements_study/etap_31_rdrb_plus_pattern.py, research/elements_study/etap_32_rdrb_plus_fair.py, research/elements_study/etap_33_rdrb_plus_honest.py]
---

# Multi-bar pattern: detect at trigger, but entry MUST be at confirm_idx

## Контекст

Когда стратегия ждёт **подтверждения структурой из N баров** после
триггера (например: «после FVG нужно 3-5 баров balanced range, чтобы
паттерн сформировался»), entry в backtest должен быть на close
`confirm_idx` (последний бар структуры), а НЕ на close `trigger_idx`
(сам триггер).

Это новый класс lookahead, отличный от классики
([[lookahead-anchor-confirm-окно-cur_open-cur_close]]).

## Что было — RDRB+ MMXM concept (etap_31-33)

Концепт: после FVG в течение 10 баров формируется RDRB+ — balanced range
≥3 баров с size ≤ 2.5×fvg_size, который не возвращается в FVG.

**Этап 31** — entry at breakout level (range_high): WR 25% — слишком жёсткое
условие.

**Этап 32 (fair entry)** — entry at FVG c2.close (как обычный FVG-continuation),
но фильтрация по «есть ли RDRB+ потом»:

```
1h:  WITHOUT RDRB+: WR 50%, R/tr -0.05
     WITH RDRB+:    WR 64%, R/tr +0.21  ★ (+14pp, x4 R/tr)
4h:  WITHOUT RDRB+: WR 49%
     WITH RDRB+:    WR 61%             ★ (+12pp)
12h: WITHOUT RDRB+: WR 53%
     WITH RDRB+:    WR 66%             ★ (+13pp)
```

«Идеально, RDRB+ работает на всех ТФ!»

**Этап 33 (honest)** — entry at confirm_idx.close (когда RDRB+ полностью
сформировалась, real-time tradable):

```
1h:  WITH RDRB+ honest:    WR 51%, R/tr -0.04   ★ edge ИСПАРИЛСЯ
1h:  WITH RDRB+ lookahead: WR 64%, R/tr +0.21   ← это был cheat
4h:  WITH RDRB+ honest:    WR 49%
4h:  WITH RDRB+ lookahead: WR 61%
12h: WITH RDRB+ honest:    WR 62%, R/tr +0.36   ★ real edge остался на HTF
1d:  WITH RDRB+ honest:    WR 67%, R/tr +0.41   ★ HTF edge
```

## Симптом

- Multi-bar structure-confirmation strategy показывает WR +10-15pp
  vs baseline на всех ТФ.
- При попытке честного entry (на close confirm_idx, после waiting period)
  edge **полностью пропадает на LTF** и сильно сокращается на HTF.
- Inflation тем больше, чем меньше ТФ (на 1m-15m может быть +20-30pp).

## Причина

В моменте `c2.close` (FVG triggered) **мы ещё НЕ знаем**, сформируется ли
RDRB+ в следующие 10 баров. Это будущая информация. Когда мы фильтруем
trades по «WITH RDRB+» используя entry at c2.close — мы peek into the
future:

1. На c2.close открыли (физически невозможно, ведь RDRB+ не сформирован).
2. Через 5-10 баров проверили «сформировался ли RDRB+».
3. Если да — записали trade в группу WITH; если нет — в WITHOUT.
4. Цена за эти 5-10 баров уже двигалась от entry — и условие
   «не вернулась в FVG» гарантирует что движение было полезным
   для long entry → **искусственный +10-15pp WR**.

То есть фильтр RDRB+ автоматически удаляет «плохие» trades которые быстро
вернулись в FVG (в первые 5-10 баров).

## Правило избегания

**Если стратегия требует waiting period для подтверждения структуры —
entry в backtest должен быть на close N-го бара (confirm_idx),
SL/TP отсчитываются от него:**

```python
# WRONG — lookahead inflation
entry = df.iloc[trigger_idx]["close"]
if rdrb_plus_forms_in_next_N_bars(...):  # peek into future
    take_trade(entry=entry, ...)

# CORRECT — honest waiting
pattern = wait_for_pattern(df, trigger_idx, max_bars=N)
if pattern is None:
    skip
entry = df.iloc[pattern["confirm_idx"]]["close"]   # entry АФТЕР formation
sim_start = pattern["confirm_idx"] + 1              # SL/TP от next bar
```

**Trigger-time vs confirm-time distinction для multi-bar patterns:**
- **Detection time** = trigger (когда понимаем «может сформироваться»).
- **Action time** = confirm_idx (когда полностью сформировалось).
- Backtest entry **всегда** на action time, не detection time.

## Где применимо

- RDRB+ MMXM (этот случай).
- Любые «balanced range above FVG» паттерны.
- Wedges, triangles, M/W tops которым нужно несколько баров для confirmation.
- 5-candle OBX4-цепочки с FVG на c3-c5 — если мы в backtest проверяем
  «c3-c5 имеют FVG» используя entry на c0/c1, это та же ошибка
  (в OBX4 у нас всё корректно — entry на 1h confirm после всего паттерна).
- ICT Breaker block, Liquidity sweep + reversal candle structures.

## Связи

- [[lookahead-anchor-confirm-окно-cur_open-cur_close]] — родственный
  pitfall: anchor подтверждается через `cur_time + tf`, а не на open.
  Discovered раньше, тот же класс «использование данных которые не
  существуют в момент entry».
- [[lookahead-bug-в-vic-evot-backtest]] — другой класс: scan стартует
  до close.
- [[2022-1m-data-gap-symptom-year-missing]] — partner pitfall этой сессии.
- `research/elements_study/etap_33_rdrb_plus_honest.py` — эталонная
  реализация honest entry для multi-bar pattern.
