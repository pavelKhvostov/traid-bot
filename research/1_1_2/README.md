# Strategy 1.1.2 — macro-OB вместо macro-FVG

Status: **research, эталон зафиксирован.**

## Идея

Замена macro-слоя FVG-4h/6h (как в 1.1.1) на **OB-4h/6h**. То есть macro-уровень становится ещё одной OB-зоной вместо FVG.

Иерархия ТФ (6 уровней):
```
OB-{1d, 12h}         ← top
+ OB-{4h, 6h}         ← macro (заменяет FVG в 1.1.1)
→ OB-{1h, 2h}         ← htf
+ FVG-{15m, 20m}      ← entry (как в 1.1.1)
```

SL=15% inside от края top-OB, dedup как в 1.1.1.

## Базовые показатели (3y BTC)

- @ RR=1.0: 449 deduped, 442 closed, **WR 53.8%, +34.0R**
- @ RR=2.2: 448 deduped, 441 closed, WR 32.9%, +23.0R

После 3-stage optimize (`optimize_1_1_2_stage3.py`):
- @ RR=2.2 ALL: WR 44.4%, **+101.4R** (241 closed) — больше PnL чем 1.1.1, ниже R/trade
- @ RR=2.2 SWEPT: WR 43.7%, +75.6R (190 closed)

Best PnL @ RR=4.7: +156.5R, R/trade 0.477.

## Файлы

### backtest/
- `backtest_strategy_1_1_2.py` — базовый
- `backtest_strategy_1_1_2_extended.py` — захватывает macro OB после закрытия cur top-OB (×2.8 пул сигналов)

### optimize/
- `optimize_1_1_2_stage1_compare.py` / `_stage2.py` / `_stage2_swept.py` / `_stage3.py` / `_stages.py` / `_swept_stage1.py` — серия 3-stage экспериментов

### analyze/
- `analyze_1_1_2_all_monthly.py` — помесячная разбивка
- `analyze_1_1_2_extended_final.py` / `_extended_sensitivity.py` — extended-вариант
- `analyze_1_1_2_no_entry.py` — анализ noentry-фильтра
- `analyze_1_1_2_ob_swept.py` — split SWEPT (check_swept)

### export/
- `export_1_1_2_extended_positions.py` — экспорт сделок extended-варианта

## Известные кандидаты на объединение

- `analyze_1_1_2_extended_final.py` + `_extended_sensitivity.py` → можно слить с argparse `--mode={final,sensitivity}`.
- 6 optimize-скриптов — overlapping логика, без анализа не сжимаем.
