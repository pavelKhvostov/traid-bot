# Prediction-algo — справочник по канону

> ⚠ **Файл частично восстановлен 2026-05-29 после сбоя BSD sed** (стёр файл при unicode-замене efficiency → блок). Содержит только таблицу типов зон, которую удалось извлечь из контекста сессии. Полное содержимое (преамбула, методология, результаты) — нужно восстановить из Time Machine, либо пересобрать заново.

См. также:
- `~/smc-lib/prediction-algo/README.md` — production-документация модуля
- `~/.claude/projects/-Users-vadim/memory/prediction-algo-final-results.md` — финальные результаты (87% top-5)
- `~/.claude/projects/-Users-vadim/memory/prediction-algo-roadmap-5-questions.md` — roadmap
- [[Правило 8]] в `~/smc-lib/rules.md` — таксономия классов зон

## Таблица типов зон (канон prediction-algo)

| # | Type | Свечей | Zone formula | Mitigation | Категория | Зависимости |
|---|---|---|---|---|---|---|
| 1 | **OB** | 2 | LONG `[min(prev.low,cur.low), prev.open]` / SHORT `[prev.open, max(prev.high,cur.high)]` | wick-fill | блок | — |
| 2 | **block_orders** | 3+ (N₁+N₂+1) | LONG `[block.low, block.close]` / SHORT `[block.close, block.high]` | wick-fill | блок | — |
| 3 | **FVG** | 3 | LONG `[c1.high, c3.low]` / SHORT `[c3.high, c1.low]` | wick-fill | inefficiency | — |
| 4 | **RDRB POI** | 3 | LONG `[c1.body_top, block.top]` / SHORT `[block.bottom, c1.body_bottom]` | wick-fill | блок | — |
| 5 | **i-RDRB** | 4 | наследует POI/block/liq из RDRB | wick-fill | блок | RDRB |
| 6 | **i-FVG** | 6+ | overlap `[max(A.bot,B.bot), min(A.top,B.top)]` | wick-fill | inefficiency | FVG×2 |
| 7 | **ob_liq** | 2 | LONG `[min(prev.low,cur.low), prev.open]` (= canon-OB) | first-touch | liquidity (composite) | OB |
| 8 | **fractal** (Williams) | 2N+1 (default 5) | **точка/level** = `center.high` (FH) / `center.low` (FL) | sweep | liquidity | — |
| 9 | **marubozu** | 1 | body `[open, close]`; **open level** = точечный магнит | sweep (open level) | inefficiency (body) + liquidity (open) | — |
| 10 | **RB** | 1 | TOP `[max(o,c), high]` / BOTTOM `[low, min(o,c)]` | first-touch | liquidity | — |
| 11 | **ob_sweep_liq_4candles** | 2 (anchor + Y) | liq SHORT `[anchor.high, y.high]` / LONG `[y.low, anchor.low]` | sweep | liquidity | fractal (anchor) |

**Примечание:** #11 `ob_sweep_liq_4candles` **исключён** из ALL_TYPES в коде `~/smc-lib/prediction-algo/zones.py` как retrospective event (не forward-looking зона).

## История переименования

- **2026-05-29:** Класс «efficiency» переименован в «блок» по решению пользователя — для согласованности с термином «блок наторгованный» (maxV ASVK).
