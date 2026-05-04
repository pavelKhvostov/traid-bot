# Strategy 1.2.0 — trend-aligned sweep reversal

Status: **новая ветка, research.** Минорный bump (1.1 → 1.2) — отказ от nested OB+FVG в пользу EMA + sweep-логики. Другая идея в той же исследовательской линии, не пересборка с нуля.

## Идея

4 фильтра последовательно:
1. **EMA-200 (1d)** — trend gate. LONG если цена выше EMA, SHORT если ниже.
2. **OB-1d** — top zone, в которой ищем сетап.
3. **OB-1h sweep** — liquidity sweep на 1h (не классический OB, а sweep-логика).
4. **FVG-15m** — entry: 80% глубины FVG, SL = sweep_low/high + 0.10% буфер.

NoEntry: TP до entry → отмена сделки.

## Базовые показатели (3y BTC)

- variant `full` (все фильтры): 24 raw → 13 closed, WR 46.2%, **−1.0R**
- variant `no_top_ob`: 62 raw → 32 closed, WR 40.6%, **−6.0R**

Стратегия в стадии tuning, текущие показатели отрицательные. Это ожидаемо для свежей ветки.

## Файлы

### backtest/
- `backtest_strategy_1_2_0.py` — два варианта (`full`, `no_top_ob`)

### tune/
- `tune_strategy_1_2_0.py` — параметризованный тюнинг
