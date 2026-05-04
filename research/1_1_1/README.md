# Strategy 1.1.1 — multi-TF nested OB+FVG

Status: **в live + research-эталон.**

## Идея

Воронка из 4 уровней × 2 ТФ:
```
OB-{1d, 12h}        ← top-OB (suppliable от обеих параллельно)
+ FVG-{4h, 6h}       ← macro-FVG (валидная FVG нужного направления внутри top-OB)
→ OB-{1h, 2h}        ← htf-OB (с фильтром SWEPT по фрактал-условию)
+ FVG-{15m, 20m}     ← entry-FVG (вход = mid)
```

## Эталонная конфигурация (после 3-stage SWEPT optimize)

- **SWEPT-фильтр ON** (фрактал по двум соседям слева)
- **entry_pct = 0.80** — 80% глубины FVG entry (дальняя граница)
- **sl_pct = 0.35** — между ob_htf edge и FVG entry edge
- **no_entry ON** — TP до entry → отмена сделки
- **target RR = 2.2**

3y BTC: **34W / 28L / 53 noentry, WR 54.8%, PnL +46.8R, R/trade 0.755**.

## Файлы

### backtest/
- `backtest_strategy_1_1_1.py` — базовый бэктест (SL=15% inside ob_htf, RR=1 и 2.2)
- `backtest_1_1_1_sl_on_htf.py` — вариант с SL на ob_htf (вместо top-OB)

### optimize/
- `optimize_strategy_1_1_1.py` — early baseline optimizer
- `optimize_strategy_1_1_1_rr.py` — RR sweep с фиксированным entry/sl
- `optimize_1_1_1_3stage.py` — 3-stage оптимизация (entry × sl × RR) на ВСЕХ сигналах
- `optimize_1_1_1_swept_stage1.py` — Stage 1 на SWEPT: vary entry, fixed sl=ob_htf edge, TP=TP_const
- `optimize_1_1_1_swept_stage2.py` — Stage 2: fixed entry=0.80, vary sl ∈ [ob_htf → fvg edge]
- `optimize_1_1_1_swept_stage3.py` — Stage 3: fixed entry/sl, vary RR (это эталон Pavel'а)

### analyze/
- `analyze_1_1_1_confluence_macro.py` — TOTALES + USDT.D confluence (бесполезен, см. confluence-bugs)
- `analyze_1_1_1_ob_swept.py` — split по SWEPT/NOT-SWEPT (содержит check_swept)
- `analyze_1_1_1_swept_monthly.py` — помесячная разбивка финального конфига
- `analyze_1_1_1_swept_multi_asset.py` — прогон на ETH/SOL для проверки переносимости edge
- `analyze_1_1_1_sync.py` — sync с TOTAL2/USDT.D (старый анализ)

## Запуск

Из корня репо:
```bash
./venv/bin/python research/1_1_1/backtest/backtest_strategy_1_1_1.py
./venv/bin/python research/1_1_1/optimize/optimize_1_1_1_swept_stage3.py
./venv/bin/python research/1_1_1/analyze/analyze_1_1_1_swept_monthly.py
```

## Cross-imports внутри 1.1.1

5 файлов импортируют `from backtest_strategy_1_1_1 import dedupe_signals/simulate_outcome/to_utc3`. После refactor — sys.path injection в начале каждого файла добавляет `research/1_1_1/backtest/` в путь.
