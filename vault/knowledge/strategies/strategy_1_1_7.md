---
tags: [strategy, smc, fractal, sweep, ob, fvg, research]
date: 2026-05-12
related: [[strategy_1_1_1]], [[strategy_1_1_5]], [[фракталы билла уильямса]]
---

# Strategy 1.1.7 — Fractal-4h sweep + 1h confirmation + OB + FVG

Параллельная research-ветка к 1.1.x family. Top-структура — снятие
4h-фрактала, htf-структура — OB-1h/2h, entry — FVG-15m/20m.

## Каскад

```
4h фрактал LL/HH (Bill Williams i±2)
  └── свеча-снятие 4h (sweep, первая после i+2)
        └── POI зона = [sweep.low, min(sweep.open, sweep.close)] (LONG)
              └── 8h окно: проверка что sweep сам стал фракталом
                    └── На 1h:
                          confirmation = close > POI.top (LONG)
                          invalidation = close < POI.bottom (LONG)
                          Если invalidation раньше confirmation → мертво.
                          └── Возврат в POI → OB-1h/2h внутри POI
                                до invalidation
                                └── FVG-15m/20m внутри OB
                                      entry = mid FVG
                                      SL    = OB.bottom (LONG)
                                      RR    = 1.0
```

Для SHORT — зеркально.

## Lookahead-prevention

- FL валиден на (FL.i + 2).close_time
- sweep search ПОСЛЕ (FL.i + 2)
- 8h окно от sweep.close_time
- confirmation/invalidation поиск с sweep_close + 8h
- OB поиск с confirmation_close
- FVG поиск с ob.cur_close

## Backtest 3y BTC raw RR=1.0

- 286 raw → 220 deduped → 76 closed (W=40, L=36)
- WR 52.6%, PnL +4R, R/trade +0.053
- LONG лучше (WR 55.8%, +5R), SHORT слабее (WR 48.5%, −1R)
- 65% NO_ENTRY — entry на mid-FVG часто не достигается

## Файлы

- `strategies/strategy_1_1_7.py` — детектор
- `tests/test_strategy_1_1_7.py` — 7 smoke-тестов
- `research/1_1_7/backtest/` — 3y backtest
- `research/1_1_7/preview/` — preview свежих сигналов

## Статус

**Research-only**, в live не интегрирована. Edge слабый, нужна RR-кривая
или изменение entry. См. [[2026-05-12-strategy-1-1-7-fractal-sweep]].
