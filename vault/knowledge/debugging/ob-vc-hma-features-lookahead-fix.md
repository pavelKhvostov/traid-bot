---
tags: [debugging, lookahead, ob_vc, hma, ml, feature-engineering]
date: 2026-06-09
related: [[lookahead-anchor-confirm-okno-cur_open-cur_close]] [[htf-lookup-must-use-last-closed-bar-not-forming]]
---

# ob_vc HMA features lookahead bug (INTRADAY fix)

## Что было

В `features/hma_at_entry.py:80-87` — builder HMA features for ob_vc ML:

```python
# BUG:
idx_at_event = np.searchsorted(ts_arr, entry_ms, side="right") - 1
close_at_event = closes[idx_at_event]
val_now[valid] = hma_arr[idx_at_event[valid]]
```

`idx_at_event` = бар TF X, СОДЕРЖАЩИЙ entry_ms. Для entry_ms посреди бара:
- `closes[idx_at_event]` = **FINAL close этого бара**, который произойдёт в будущем (до 72h для 3d TF)
- `hma_arr[idx_at_event]` = HMA value at this future close

## Симптом

ML давала аномально высокие AUC:
- v3 lookahead: AUC 0.75
- v3.3 lookahead: AUC 0.79
- WR @ N=1100: 72%
- Σ R за 6y: +1288R

Это казалось "слишком хорошо" но не вызывало подозрений потому что:
1. Уже использовался entry_fill_ms anchor (не born_ms) — выглядело "honest"
2. Wait-window features действительно honest
3. Bug был тонкий — на границе между "бар содержащий entry" и "бар закрытый до entry"

## Причина

`searchsorted(side="right") - 1` возвращает индекс бара whose `open_time <= entry_ms`. Это включает бары `[open, open+tf_ms]` где `open <= entry_ms < open+tf_ms` — т.е. **бар в процессе формирования** на момент entry_ms.

Для use case "HMA значение **известное в entry_ms**" нужен бар уже **полностью закрытый**: `open+tf_ms <= entry_ms` ⟺ `open <= entry_ms - tf_ms`.

## Reproduce

```python
import numpy as np

# 1d TF (24h bars), entry at 14:00 UTC
entry_ms = 14 * 3600 * 1000  # day 0 at 14:00
ts_arr = np.array([0, 86400000, 172800000])  # day 0, 1, 2 (00:00 UTC opens)

# BUG: searchsorted finds bar containing entry_ms
idx_bug = np.searchsorted(ts_arr, entry_ms, side="right") - 1
# = 0 → bar that started 00:00 of day 0, will close at 24:00 of day 0
# closes[0] = close at 24:00 day 0 = 10 hours in FUTURE from entry_ms!

# FIX: use last bar whose close_time <= entry_ms
cutoff = entry_ms - 86400000  # = -36000000 (negative = before day 0)
idx_fix = np.searchsorted(ts_arr, cutoff, side="right") - 1
# = -1 (no bar fully closed yet — need more history)

# At entry_ms = 14:00 day 1:
entry_ms_2 = 86400000 + 14 * 3600 * 1000
cutoff_2 = entry_ms_2 - 86400000  # = 50400000 (14:00 day 0)
idx_fix_2 = np.searchsorted(ts_arr, cutoff_2, side="right") - 1
# = 0 (bar that opened at 00:00 day 0, closed at 00:00 day 1) ✓ honest
```

## Fix — INTRADAY partial-bar (PineScript-style live)

```python
# 1. Find LAST FULLY CLOSED bar
closed_idx = np.searchsorted(ts_arr, entry_ms - tf_ms, side="right") - 1

# 2. Current 1m close at entry_ms (price NOW)
partial_close = close_1m at entry_ms

# 3. HMA series: closed bars + virtual partial close
series = closes[:closed_idx+1] + [partial_close]
hma_value = hma_np(series, L)[-1]

# 4. dist_pct uses partial_close (current price) — known at entry_ms
dist_pct = (partial_close - hma_value) / hma_value * 100
```

Реализация: `~/smc-lib/projects/ob-vc/ml_v3/features/hma_at_entry_honest.py`,
функция `hma_value_at_virtual_partial()`.

## Quick check impact

5-fold CV AUC (Mac, HGB):
```
Lookahead version:   AUC 0.76 ± 0.02
Honest INTRADAY:     AUC 0.52 ± 0.03
HONEST last-closed:  AUC 0.54 ± 0.03
Δ:                   -0.22 (lookahead "edge" disappeared)
```

PC1 full pipeline:
```
v3.3 lookahead:  AUC 0.79, WR 72.4%, Σ +1288R, PBO 0.55
v3 honest:       AUC 0.54, WR 32-50% (per RR), PBO 0.55
v3.5 honest+cross: AUC 0.55, WR 32-50%, PBO 0.30 ← much better stability
```

## Severity per TF

```
TF      Bar duration   Avg lookahead   Max lookahead
15m     15 мин         ~7 мин          15 мин          (low)
1h      60 мин         ~30 мин         60 мин          (medium)
2h, 4h  2-4 часа       1-2 часа        2-4 часа        (medium)
12h     12 часов       ~6 часов        12 часов        (high)
1d      24 часа        ~12 часов       24 часа         (VERY HIGH)
2d, 3d  48-72 часа     24-36 часов     48-72 часа      (VERY HIGH)
```

Most damage from daily TFs — direct knowledge of next 1-3 days price.

## Правило избегания

**Любой feature, использующий HTF (TF > 15m) value в момент моложе закрытия HTF бара, требует partial-bar update.**

Чек-лист для feature builder:
1. ✗ Если код берёт `closes[idx_at_event]` для idx, найденный через `searchsorted(side="right")` — лук-aheаd.
2. ✓ Должен быть `closed_idx = searchsorted(ts, entry_ms - tf_ms, side="right") - 1`.
3. ✓ "Current" value — отдельно через 1m close at entry_ms.
4. ✓ Производные (slopes, crosses) — используют closed HMA values (honest).

Альтернатива при сомнениях: **отдавать ML только последний ЗАКРЫТЫЙ HTF close**, без partial — теряем live точность, но zero risk leak.

## Связи

- [[lookahead-anchor-confirm-okno-cur_open-cur_close]] — другой lookahead case в 1.1.1
- [[htf-lookup-must-use-last-closed-bar-not-forming]] — аналогичное правило для HTF lookups
- [[ml-snapshot-not-trajectory]] — почему даже honest snapshot имеет fundamental limit
- [[strategy-ob-vc-v33-lean-picked]] — пострадавший strategy doc
