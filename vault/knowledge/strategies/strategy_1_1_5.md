---
tags: [strategy, smc, ob, fvg, rdrb, research]
date: 2026-05-06
related: [[strategy_1_1_1]], [[strategy_1_1_6]], [[что такое rdrb]]
---

# Strategy 1.1.5 — OB-top + FVG-macro + RDRB4-htf

Параллельная ветка к 1.1.x family. Новая htf-структура — **4-свечной RDRB**.

## Каскад

```
top OB (1d / 12h)
  └── macro FVG (4h / 6h) внутри top OB (zones_overlap)
        └── htf RDRB-4 (1h / 2h) — расширенная зона zones_overlap с FVG
              └── entry: касание ближнего края зоны
```

Все одного направления. Все 4 (macro_tf, htf_tf) комбинации валидны.

## RDRB-4 геометрия

Свечи c1, c2, c3, c4 (по времени). c4 = триггер.

**SHORT:**
- `c1.low > c2.low` (c2 выносит low c1)
- `c1.low < c2.close` (c2 закрытие выше c1.low — ловушка)
- `c2.low < c4.high` (c4 заходит в фитиль c2)
- `c3.close < c2.low` (c3 поглощает фитиль c2)
- `c1.low > c4.high` (c4 не пробивает c1.low)

**LONG** — зеркально (swap low/high).

## Расширенная зона

**SHORT:** `[max(c2.low, c4_body_high), c1.low]`
где `c4_body_high = max(c4.open, c4.close)`.

**LONG:** `[c1.high, min(c2.high, c4_body_low)]`
где `c4_body_low = min(c4.open, c4.close)`.

Логика: пересечение фитилей c2 и c4 + растяжка крайней границы до
экстремума c1. Это даёт зону шире чем `[c4.high, c1.low]`, что
кратно увеличивает fill-rate.

## Entry / SL / TP

- **SHORT entry** = bottom расширенной зоны = `max(c2.low, c4_body_high)`
- **LONG entry** = top расширенной зоны = `min(c2.high, c4_body_low)`
- **SL SHORT** = `max(c1.high, c2.high)`
- **SL LONG** = `min(c1.low, c2.low)`
- **RR = 1.0** (фикс)

Без буфера. Без SWEPT.

## Lookahead-prevention

- `macro-FVG search_start = top_ob.cur_time + top_tf_hours`
- `htf-RDRB c1_time >= fvg_macro.c2_time + macro_tf_hours`

Урок [[strategy-1-1-6-look-ahead-macro-htf]].

## Backtest 3y BTC raw RR=1.0

- 318 raw → 140 deduped → 91 closed (W=53, L=38)
- WR 58.2%, PnL +15R, R/trade +0.165
- 2026 провал: WR 25%, −8R (требует анализа)

## Файлы

- `strategies/strategy_1_1_5.py` — детектор
- `tests/test_strategy_1_1_5.py` — 12 тестов
- `research/1_1_5/backtest/` — backtest 3y
- `research/rdrb_4candle/` — standalone RDRB-4 scanner (749 структур CSV)

## Статус

**Research-only.** В live не интегрирована. См. [[2026-05-06-strategy-1-1-5-rdrb4]].
