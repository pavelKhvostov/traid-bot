---
name: feedback-ob-vc-strict-detection-timing
description: "Канон strict detection time для ob_vc — нужны закрытые: cur HTF + LTF c3 + Williams n=2 opposite fractal. Текущий backtest имеет lookahead 30мин-2ч"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 5dfe8bf0-bba6-41f4-89b4-4c25014664a4
---

**Strict earliest detection time для ob_vc** = `max(cur_HTF.close, c3.close, opposite_fractal_confirm.close)`.

**Why:** Все три условия канона ob_vc должны быть подтверждены закрытыми барами:
1. `cur_HTF.close` — OB-pair полностью валидна только после закрытия cur (bearish для SHORT, bullish для LONG)
2. `c3.close` — LTF FVG валидна только после закрытия c3 (тогда можно проверить `c1.low > c3.high` для SHORT)
3. **`opposite_fractal_confirm.close`** — first opposite fractal на LTF (`OBVC.first_opposite_fractal_level`) должен быть **Williams n=2 confirmed**, т.е. **2 закрытые свечи СПРАВА от pivot**.

**How to apply:**

### Strict fill_start formula
```python
htf_minutes = 60 if sig["ob_htf_tf"] == "1h" else 120
ob_cur_close = sig["ob_cur_time"] + pd.Timedelta(minutes=htf_minutes)
ltf_minutes = 15 if sig["fvg_tf"] == "15m" else 20
c3_close = sig["signal_time"] + pd.Timedelta(minutes=2 * ltf_minutes)
# fractal_confirm_ts должен сохраняться при scan_ob_vc_events
fractal_confirm = pivot_open_time + pd.Timedelta(minutes=3 * ltf_minutes)
fill_start = max(ob_cur_close, c3_close, fractal_confirm)
```

### Текущий backtest имеет lookahead
- Current: `fill_start = signal_time + tf_min` (= c2.close)
- Strict: `fill_start = max(...)` (см. выше)
- Lookahead зазор: **30мин — 2ч** (зависит от конфига и того когда формируется fractal)

### Конкретные examples (3 крайних ob_vc на BTC 29-30 мая 2026)

| # | Signal MSK | HTF | cur HTF.close | c3.close | Fractal confirm | **Strict** | Lookahead |
|---|---|---|---|---|---|---|---|
| 1 | 29-05 21:15 | 2h | 23:00 | 21:45 | **pre-existing** ≤21:45 | **29-05 23:00** | 1ч 30мин |
| 2 | 30-05 00:15 | 1h | 01:00 | 00:45 | post: pivot 01:00 → confirm 01:45 | **30-05 01:45** | 1ч 15мин |
| 3 | 30-05 06:15 | 1h | 07:00 | 06:45 | post: pivot 07:30 → confirm 08:15 | **30-05 08:15** | 1ч 45мин |

Средний лукахед ≈ 1.5 часа на трейд.

### Важно: opposite fractal может быть pre-existing

Не всегда формируется ПОСЛЕ c3. Иногда уже сидит в данных к моменту c3.close (пример #1) — тогда не добавляет lookahead. Иногда формируется через 30-90 мин после c3 (примеры #2, #3) — блокирует detection.

В `scan_ob_vc_events` нужно искать opposite fractal **во всём окне до и после c2** — найти первый валидный outside rally area, записать его `confirm_close_ts`. Это и есть тот таймстемп для strict fill_start.

### Что НЕЛЬЗЯ делать
- Использовать `fill_start = signal_time + fvg_tf` без коррекции — это lookahead
- Делать live deployment с текущим бактестом — реальные результаты будут хуже на ~lookahead%
- Обучать ML на lookahead-tainted данных — модель будет «переобучена» на нереальном edge

### План фикса (когда вернёмся)
1. `scan_ob_vc_events` (backtest.py): записывать в event `fractal_confirm_ts` от ob_vc canon
2. `simulate_floating` (strategy_1_1_1_floating.py): `fill_start = max(c3_close, ob_cur_close, fractal_confirm_ts)`
3. Re-baseline ob_vc backtest на стрикте — честный WR/RR
4. Phase 4 архив на стрикте

## Why I missed it initially

В первом разборе я учёл только closed HTF и closed c3, забыл что canon condition #9 (opposite fractal вне drop/rally area) требует Williams n=2 confirmation = pivot + 2 bars right.

## Связи

- `[[vc-volume-confirmation-definition]]` — VC canon
- `~/smc-lib/elements/ob_vc/code.py` — OBVC canon (first_opposite_fractal_level field)
- `~/smc-lib/projects/strategy_ob_vc_v1rules/backtest.py` — scan_ob_vc_events (нужно патчить)
- `~/smc-lib/projects/strategy_1_1_1_floating.py` — simulate_floating (нужно патчить)
