---
tags: [research, discovery, refactoring]
date: 2026-05-04
status: phase-0-output
---

# Discovery — research-стенд Strategy 1.1.x → 1.2.0

Inventory + canon-формулы + summary версий перед рефакторингом research-ветки.

**Источник истины:** код в корне репо + `vault/knowledge/smc/` + git log.
**Не выдумано.** Где неясно — `??? — спросить Pavel`.

---

## 0.1. Inventory скриптов (56 файлов в корне)

| Файл | Версия | Тип | Last commit | Lines | Author |
|---|---|---|---|---|---|
| backtest_strategy_1_1_1.py | 1.1.1 | backtest | 2026-04-29 | 395 | pavel |
| backtest_1_1_1_sl_on_htf.py | 1.1.1 | backtest | 2026-05-01 | 194 | Andrew |
| analyze_1_1_1_confluence_macro.py | 1.1.1 | analyze | 2026-05-01 | 173 | Andrew |
| analyze_1_1_1_ob_swept.py | 1.1.1 | analyze | 2026-05-01 | 175 | Andrew |
| analyze_1_1_1_swept_monthly.py | 1.1.1 | analyze | 2026-05-01 | 231 | Andrew |
| analyze_1_1_1_swept_multi_asset.py | 1.1.1 | analyze | 2026-05-04 | 256 | Andrew |
| analyze_1_1_1_sync.py | 1.1.1 | analyze | 2026-05-01 | 237 | Andrew |
| optimize_strategy_1_1_1.py | 1.1.1 | optimize | 2026-04-29 | 251 | Andrew |
| optimize_strategy_1_1_1_rr.py | 1.1.1 | optimize | 2026-04-29 | 366 | pavel |
| optimize_1_1_1_3stage.py | 1.1.1 | optimize | 2026-05-01 | 259 | Andrew |
| optimize_1_1_1_swept_stage1.py | 1.1.1 | optimize | 2026-05-01 | 239 | Andrew |
| optimize_1_1_1_swept_stage2.py | 1.1.1 | optimize | 2026-05-01 | 211 | Andrew |
| optimize_1_1_1_swept_stage3.py | 1.1.1 | optimize | 2026-05-01 | 194 | Andrew |
| backtest_strategy_1_1_2.py | 1.1.2 | backtest | 2026-05-04 | 326 | Andrew |
| backtest_strategy_1_1_2_extended.py | 1.1.2 | backtest | 2026-05-04 | 192 | Andrew |
| analyze_1_1_2_all_monthly.py | 1.1.2 | analyze | 2026-05-04 | 225 | Andrew |
| analyze_1_1_2_extended_final.py | 1.1.2 | analyze | 2026-05-04 | 239 | Andrew |
| analyze_1_1_2_extended_sensitivity.py | 1.1.2 | analyze | 2026-05-04 | 208 | Andrew |
| analyze_1_1_2_no_entry.py | 1.1.2 | analyze | 2026-05-04 | 185 | Andrew |
| analyze_1_1_2_ob_swept.py | 1.1.2 | analyze | 2026-05-04 | 183 | Andrew |
| optimize_1_1_2_stage1_compare.py | 1.1.2 | optimize | 2026-05-04 | 232 | Andrew |
| optimize_1_1_2_stage2.py | 1.1.2 | optimize | 2026-05-04 | 190 | Andrew |
| optimize_1_1_2_stage2_swept.py | 1.1.2 | optimize | 2026-05-04 | 203 | Andrew |
| optimize_1_1_2_stage3.py | 1.1.2 | optimize | 2026-05-04 | 224 | Andrew |
| optimize_1_1_2_stages.py | 1.1.2 | optimize | 2026-05-04 | 296 | Andrew |
| optimize_1_1_2_swept_stage1.py | 1.1.2 | optimize | 2026-05-04 | 206 | Andrew |
| export_1_1_2_extended_positions.py | 1.1.2 | export | 2026-05-04 | 270 | Andrew |
| backtest_strategy_1_1_3.py | 1.1.3 | backtest | 2026-05-04 | 324 | Andrew |
| optimize_1_1_3_new_geometry.py | 1.1.3 | optimize | 2026-05-04 | 265 | Andrew |
| optimize_1_1_3_stage1_compare.py | 1.1.3 | optimize | 2026-05-04 | 243 | Andrew |
| optimize_1_1_3_v1_stage1_clean.py | 1.1.3 | optimize | 2026-05-04 | 177 | Andrew |
| optimize_1_1_3_v1_stage2_compare_ep.py | 1.1.3 | optimize | 2026-05-04 | 193 | Andrew |
| optimize_1_1_3_v1_stage2_extended_entry.py | 1.1.3 | optimize | 2026-05-04 | 209 | Andrew |
| optimize_1_1_3_v1_stage3_compare_ep.py | 1.1.3 | optimize | 2026-05-04 | 201 | Andrew |
| optimize_1_1_3_v2_stage2.py | 1.1.3 | optimize | 2026-05-04 | 205 | Andrew |
| compare_1_1_3_fvg_variants.py | 1.1.3 | compare | 2026-05-04 | 222 | Andrew |
| backtest_strategy_1_1_4.py | 1.1.4 | backtest | 2026-05-04 | 317 | Andrew |
| backtest_strategy_1_2_0.py | 1.2.0 | backtest | 2026-05-04 | 195 | Andrew |
| tune_strategy_1_2_0.py | 1.2.0 | tune | 2026-05-04 | 202 | Andrew |
| backtest_strategy_rdrb.py | RDRB | backtest | 2026-05-01 | 285 | Andrew |
| backtest_strategy_rdrb_premium.py | RDRB | backtest | 2026-05-01 | 279 | Andrew |
| backtest_strategy_rdrb_trend.py | RDRB | backtest | 2026-05-01 | 173 | Andrew |
| backtest_strategy_rdrb_wick.py | RDRB | backtest | 2026-05-01 | 212 | Andrew |
| backtest_rdrb_konfetka.py | RDRB | backtest | 2026-05-01 | 185 | Andrew |
| analyze_rdrb_confluence_macro.py | RDRB | analyze | 2026-05-01 | 149 | Andrew |
| analyze_rdrb_winners_losers.py | RDRB | analyze | 2026-05-01 | 299 | Andrew |
| optimize_rdrb_entry_sl.py | RDRB | optimize | 2026-05-01 | 236 | Andrew |
| backtest_vic_bos.py | VIC | backtest | 2026-04-28 | 470 | Andrew |
| backtest_vic_evot.py | VIC | backtest | 2026-04-28 | 416 | Andrew |
| optimize_vic_entry_sl.py | VIC | optimize | 2026-04-28 | 181 | Andrew |
| optimize_vic_yearly.py | VIC | optimize | 2026-04-28 | 149 | Andrew |
| backtest_year.py | shared/?? | backtest helper | 2026-04-27 | 197 | Andrew |

**По версиям:** 1.1.1 = 13, 1.1.2 = 14, 1.1.3 = 8, 1.1.4 = 1, 1.2.0 = 2, RDRB = 8, VIC = 4, shared = 1.

---

## 0.2. Reference-формулы (canon)

Сверка `vault/knowledge/smc/*.md` ↔ `strategies/*.py` — **расхождений НЕТ**.

| Concept | Canon (`vault/knowledge/smc/`) | Implementation |
|---|---|---|
| **Order Block** | LONG: prev медвежья + cur.close > prev.open → zone = `[min(prev.low, cur.low), prev.open]`. SHORT: зеркально через max | `strategies/ob1h_core.py::detect_ob` ✅ |
| **FVG** | LONG: `c0.high < c2.low` → zone = `[c0.high, c2.low]`. SHORT: `c0.low > c2.high` → `[c2.high, c0.low]` | `strategies/fvg.py::detect_fvg` ✅ |
| **RDRB** | 3-свеча: пересечение фитилей с ограничением телами; ложный пробой с возвратом | `strategies/rdrb.py::detect_rdrb` ✅ |
| **Fractal (LL/HH)** | i±2 строгое неравенство: LL — `low[i]` строго ниже соседей i-2, i-1, i+1, i+2 | `strategies/fractal.py::detect_fractal` ✅ |

⚠️ Расхождения детектор vs canon: **нет**.

---

## 0.3. Описания версий 1.1.2 / 1.1.3 / 1.1.4 / 1.2.0

### Strategy 1.1.2 (14 файлов, all Andrew, 2026-05-04)

- **Идея:** замена macro-слоя FVG-4h/6h (как в 1.1.1) на **OB-4h/6h**. То есть macro-уровень становится ещё одной OB-зоной вместо FVG.
- **SMC-блоки:** OB-{1d,12h} (top) + **OB-{4h,6h}** (macro) → OB-{1h,2h} (htf) + FVG-{15m,20m} (entry).
- **Иерархия ТФ:** 6 уровней — 1d → 12h → 4h/6h → 1h/2h → 15m/20m.
- **Entry/SL:** mid FVG-15m/20m, SL=15% inside от края top-OB (как в 1.1.1).
- **Extended-вариант:** проверяет macro OB, формирующиеся **после** закрытия cur top-OB.
- **Файлы:** 2 backtest + 5 analyze + 6 optimize + 1 export.

### Strategy 1.1.3 (8 файлов, all Andrew, 2026-05-04)

- **Идея:** entry FVG берётся **на том же ТФ что и OB-htf** (1h или 2h), а не на 15m/20m. То есть immediate FVG, c0 FVG = свечи внутри OB-pair.
- **SMC-блоки:** OB-{1d,12h} + **OB-{4h,6h}** (macro как в 1.1.2) → OB-{1h,2h} + immediate **FVG того же ТФ**.
- **Иерархия ТФ:** 4-5 уровней (нет «нижнего» 15m/20m слоя).
- **Entry/SL:** mid FVG-htf (1h/2h), SL=15% в top-OB.
- **Отличие от 1.1.2:** компактнее (меньше ТФ), entry-FVG на htf вместо 15m/20m.
- **Варианты v1/v2:** 7 optimize-скриптов с разной геометрией (`v1_stage1_clean`, `v1_stage2_compare_ep`, `v1_stage3_compare_ep`, `v2_stage2`, `new_geometry`).
- **Файлы:** 1 backtest + 7 optimize + 1 compare. Нет analyze для 1.1.3 (??? — спросить).

### Strategy 1.1.4 (1 файл, Andrew, 2026-05-04) — **status: WIP**

- **Идея:** гибрид macro-слой как в 1.1.1 (**FVG**-4h/6h) + entry-слой как в 1.1.3 (immediate FVG того же ТФ что OB-htf). «Что если взять macro-FVG обратно, но entry оставить как в 1.1.3».
- **SMC-блоки:** OB-{1d,12h} + **FVG-{4h,6h}** (macro) → OB-{1h,2h} + immediate FVG того же ТФ.
- **Иерархия ТФ:** 4-5 уровней.
- **Файлы:** только backtest_strategy_1_1_4.py — optimize/analyze просто не успели. Не закрытый эксперимент, остаётся как research/wip.

### Strategy 1.2.0 (2 файла, Andrew, 2026-05-04) — **новая ветка**

- **Идея:** trend-aligned sweep reversal. Минорный bump (1.1 → 1.2) — другая идея в той же исследовательской линии, не пересборка с нуля. Отказ от nested OB+FVG в пользу EMA+sweep.
- **SMC-блоки:** EMA-200 (1d) + OB-1d (top) + OB-1h (sweep, не классический OB) + FVG-15m (entry).
- **Иерархия ТФ:** 1d → 1h → 15m (3 уровня).
- **Entry/SL:** entry на 80% глубины FVG-15m, SL = sweep_low/high + 0.10% буфер, TP по RR=1.0.
- **NoEntry:** TP до entry → отмена.
- **Файлы:** 1 backtest + 1 tune. Отдельная папка `research/1_2_0/`.

---

## 0.4. Ответы Pavel'а (закрыто)

1. **1.1.4** ✅ WIP. Гибрид 1.1.1+1.1.3 (macro-FVG обратно, entry как в 1.1.3). Optimize/analyze не успели — оставляем как research/wip.
2. **1.2.0** ✅ Новая ветка. Отказ от nested OB+FVG в пользу EMA+sweep. Минорный bump потому что «другая идея в той же исследовательской линии».
3. **RDRB** ✅ В live базовый RDRB (`strategies/rdrb.py`). 5 research-вариантов (premium/trend/wick/konfetka/base) — отдельные эксперименты, ни один пока не интегрирован. Все в `research/rdrb/`. Live `strategies/rdrb.py` не трогать.
4. **VIC** ✅ `backtest_vic_evot.py` — research-прогоны для уже-live VIC_EVOT. `backtest_vic_bos.py` — кандидат VIC_BOS (backtest-only). Оба в `research/vic/`.
5. **backtest_year.py** ✅ Shared-helper, не привязан к версии. Прогоняет любой бектест по конкретному году. В `research/_shared/`.
6. **strategy_1_1_1_confluence.py / strategy_1_1_1_scanner.py** ✅ Live-обвязка, **не research**. Не трогаем, остаются в корне.

---

## Резюме для Фазы 1 (baseline)

**Кандидаты на прогон в Фазе 1 (только `backtest_*.py`):** 14 backtest-скриптов
- 1.1.1 × 2: `backtest_strategy_1_1_1.py`, `backtest_1_1_1_sl_on_htf.py`
- 1.1.2 × 2: `backtest_strategy_1_1_2.py`, `backtest_strategy_1_1_2_extended.py`
- 1.1.3 × 1: `backtest_strategy_1_1_3.py`
- 1.1.4 × 1: `backtest_strategy_1_1_4.py`
- 1.2.0 × 1: `backtest_strategy_1_2_0.py`
- RDRB × 5
- VIC × 2

`backtest_year.py` — пропустить пока не классифицирован.

`optimize_*.py` / `analyze_*.py` / `compare_*.py` / `export_*.py` / `tune_*.py` — не входят в baseline-прогон (их выходы зависят от backtest-входов; baseline backtests достаточно для проверки логики).
