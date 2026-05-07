# Strategy 1.1.4 — top-FVG вместо top-OB на 1d/12h

Status: **research, basic backtest.**

## Идея

Берём 1.1.1 и заменяем **только верхний слой**: вместо OB-{1d, 12h} сканируем
**FVG-{1d, 12h}**. Macro/htf/entry слои остаются неизменными.

```
FVG-{1d, 12h}        ← top (было OB)
+ FVG-{4h, 6h}        ← macro (как в 1.1.1)
→ OB-{1h, 2h}         ← htf (как в 1.1.1)
+ FVG-{15m, 20m}      ← entry (как в 1.1.1)
```

## Отличия от 1.1.1

1. **Top-зона:** FVG (тройка свечей c0/c1/c2) вместо OB (пара prev/cur).
   - LONG top-FVG: `high(c0) < low(c2)` → zone `[high(c0), low(c2)]`
   - SHORT top-FVG: `low(c0) > high(c2)` → zone `[high(c2), low(c0)]`
2. **search_start для htf-OB:** `top_fvg.c2_time + top_tf_hours`
   (момент закрытия c2 + длина одного top-bar). Аналог `cur_time + top_tf_hours`
   в 1.1.1.
3. **Окно для macro-FVG:** `[top_fvg.c0_time, top_fvg.c2_time + top_tf_hours)`
   (аналог `[ob_top.prev_time, ob_top.cur_time + top_tf_hours)` в 1.1.1).
4. **SL:** `ob_htf.bottom` (LONG) / `ob_htf.top` (SHORT). Без буфера, на самой
   дальней границе htf-OB. В 1.1.1 SL был на 15% inside top-OB.

## Файлы

### backtest/
- `backtest_strategy_1_1_4.py` — базовый прогон, RR=1.0 и RR=2.2, dedup и
  CSV-выгрузка совместимы со схемой 1.1.1 (legacy-имена `ob_d_*` маппятся
  на top-FVG).

## Запуск

```bash
./venv/Scripts/python research/1_1_4/backtest/backtest_strategy_1_1_4.py
```

## Тесты

`tests/test_strategy_1_1_4.py` — happy-path LONG/SHORT, edge cases (нет top-FVG,
mismatch direction macro, нет htf-OB).
