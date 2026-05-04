# Strategy 1.1.3 — entry FVG того же ТФ что OB-htf

Status: **research, эталон зафиксирован.**

## Идея

Убираем нижний слой 15m/20m. Entry FVG берётся **на том же ТФ что OB-htf** (1h или 2h), c0 FVG = свечи внутри OB-pair.

Иерархия ТФ (4-5 уровней):
```
OB-{1d, 12h}         ← top
+ OB-{4h, 6h}         ← macro (как в 1.1.2)
→ OB-{1h, 2h} + FVG того же ТФ ← htf + immediate entry
```

## Базовые показатели (3y BTC)

- @ RR=1.0: 125 deduped, 122 closed, **WR 52.5%, +6.0R**
- @ RR=2.2: 125 deduped, 122 closed, WR 34.4%, +12.4R

После v1_stage3 optimize (compare_ep ∈ {0.0, 1.0}):
- @ RR=2.2 ep=0.0: WR 37.3%, +11.4R, R/trade 0.193
- @ RR=2.2 ep=1.0: WR 34.1%, +8.0R, R/trade 0.091
- Best PnL @ RR=5.9: +53.9R, R/trade 0.592

## Замечание

**1.1.3 заметно слабее 1.1.1 и 1.1.2 во всех метриках.** Гипотеза «entry FVG immediate на htf вместо 15m/20m» — не улучшила. Версия остаётся в research для исторической полноты.

## Файлы

### backtest/
- `backtest_strategy_1_1_3.py`

### optimize/
- `optimize_1_1_3_new_geometry.py` — alternative geometry
- `optimize_1_1_3_stage1_compare.py` — stage 1 baseline
- `optimize_1_1_3_v1_stage1_clean.py` — v1 геометрия, stage 1
- `optimize_1_1_3_v1_stage2_compare_ep.py` — v1, stage 2 sweep entry
- `optimize_1_1_3_v1_stage2_extended_entry.py` — v1, stage 2 расширенный entry
- `optimize_1_1_3_v1_stage3_compare_ep.py` — v1, stage 3 RR sweep × ep
- `optimize_1_1_3_v2_stage2.py` — v2 геометрия

### compare/
- `compare_1_1_3_fvg_variants.py` — сравнение FVG-вариантов

## Кандидат на объединение

4 файла `optimize_1_1_3_v1_*.py` — серия экспериментов с одной геометрией v1, могут быть слиты в `optimize_1_1_3_v1_stages.py` с argparse.
