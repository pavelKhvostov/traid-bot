# Strategy 1.1.1 V2 — Nested ob_vc Cascade

> Унификация Strategy 1.1.1 (`traid-bot`) — обе ступени каскада заменены на единый canon `ob_vc` с разными HTF/LTF параметрами.
> Status: **design** (2026-05-29).
> Base: Strategy 1.1.1 в `~/traid-bot/strategies/strategy_1_1_1.py` (production, WR 54.8%, +46.8R на 3y BTC).
> Owner: trade-strategies branch.

## Идея

Strategy 1.1.1 (v1) каскад использует **2 разных composite-структуры**:
- macro: `OB-{1d,12h} + FVG-{4h,6h}` (ad-hoc композит)
- entry: `OB-{1h,2h} + FVG-{15m,20m}` (= близок к ob_vc, но без spatial/temporal canon)

V2 заменяет обе на **единый canon `ob_vc`** с разными TF параметрами:
- macro: `ob_vc(HTF=D/12h, LTF=4h/6h)` — все 9 conditions canon применяются
- entry: `ob_vc(HTF=1h/2h, LTF=15m/20m)` — все 9 conditions canon применяются

## Архитектура каскада

```
1. Macro detection:
   ob_vc(HTF=D/12h, LTF=4h/6h) с canon conditions:
     - сонаправленность OB ↔ FVG
     - spatial overlap с drop/rally area
     - spatial range до first opposite LTF fractal
     - temporal bounds
     - FVG actionable to FH confirmation
   → macro_zone = ob_vc.zone (OB-часть)

2. Entry detection (внутри macro_zone):
   ob_vc(HTF=1h/2h, LTF=15m/20m) с теми же canon conditions
   + дополнительное условие: entry.zone ⊆ macro_zone (или существенное пересечение)
   + сонаправленность с macro: entry.direction == macro.direction
   → entry_zone = entry_ob_vc.zone

3. Trade trigger:
   касание entry_zone на 1m → сигнал
```

## Trade rules (база v1 + Floating TP из etap108)

### Entry / SL (как v1)

| параметр | значение |
|---|---|
| Entry point | `fvg_bottom + 0.80 × (fvg_top - fvg_bottom)` (mid 80% по FVG-LTF) |
| SL | `ob_htf_bottom + 0.35 × (fvg_bottom - ob_htf_bottom)` (symmetric, 35%) |

### Exit — Floating TP (из etap108, обязательно для V2)

Заменяет fixed RR=2.2 на 4-способную exit-механику:

| # | exit type | rule | %trades (ист.) |
|---|---|---|---|
| **1** | **SL hit** | Цена пробила SL → R = −1 | ~40% |
| **2** | **R-cap (hard ceiling)** | Цена достигла R_cap × risk → R = +R_cap | ~8% |
| **3** | **Score-exit (Floating TP)** | momentum score ≤ threshold N consecutive 1h bars → exit at close | ~50% |
| **4** | **Max-hold timeout (7d)** | Прошло 7 дней без триггера → close at market | ~2% |

### Per-symbol R-cap configs (из etap108)

| symbol | R_cap | threshold | confirm |
|---|---|---|---|
| BTCUSDT | 4.5 | −0.25 | 2 |
| ETHUSDT | 4.5 | −0.25 | 2 |
| SOLUSDT | 3.5 | 0.00 | 1 |

### 4-indicator momentum score

```
score(t) = mean(s_hull, s_mh, s_rsi, s_asvk) ∈ [-1, +1]

s_hull  = sign(close[t] - hull78[t-2])           # lookahead-safe Hull MA от 2h назад
s_mh    = MoneyHands bw2 color → {-1, -0.5, 0, +0.5, +1}
s_rsi   = clip((RSI14 - 50) / 50, -1, +1)
s_asvk  = ASVK red/green zone label (direction-aware)
```

Reference imp: `~/smc-lib/projects/strategy_1_1_1_floating.py` функции `build_score_series`, `simulate_floating`.

### Ожидаемый эффект (по etap108 на v1 детекторе)

| | baseline RR=2.2 | **Floating TP** |
|---|---|---|
| Total PnL (6y BTC+ETH+SOL) | +317.8R | **+428.9R (+35-44%)** |
| BTC 6.34y | +165.2R, WR 45% | +179.9R, **WR 52%** |
| Медианный трейд | −1.00R (убыток) | **+0.07–0.12R (прибыль)** |

V2 (canon ob_vc вместо ad-hoc OB+FVG) **должна работать не хуже** — те же базовые принципы exit. Сравнение в backtest.

## Интеграция с bounce-or-break модели

`P_bounce` от модели `bb_obvc_1h2h` (см. [[bounce-or-break]]) подается как **дополнительный фильтр**:

```
Strategy 1.1.1 V2 detects nested ob_vc cascade
       ↓
Price touches entry_zone
       ↓
bb_obvc_1h2h.predict(zone_features + path + inventory) → P_bounce = 0.73
       ↓
Decision:
   if P_bounce >= threshold:  → ENTRY
   else:                      → SKIP (зона недостаточно сильная)
```

Threshold подбирается per-backtest. Кандидаты: 0.55, 0.60, 0.65, 0.70.

## Открытые вопросы (для design pass)

| # | Вопрос | Варианты | Моё предложение |
|---|---|---|---|
| 1 | **SWEPT** condition на entry OB (как в v1)? | Оставить SWEPT / убрать | **убрать** — ob_vc canon уже строгий; SWEPT на entry стадии может убить много валидных сигналов |
| 2 | **Confluence** с BTC1!/TOTALES/USDT.D (как в v1)? | Оставить / убрать / опционально | **опционально** — добавить как ml-фичу, не как hard filter |
| 3 | **Macro mode** | untouched (macro_zone не касалась с born) / любая | **untouched** (как в v1.1.3 macro_mode) — свежий macro сильнее |
| 4 | **Spatial condition** entry внутри macro | strict `entry.zone ⊆ macro.zone` / partial overlap ≥ X% | **partial overlap ≥ 50%** — strict subset слишком редкий |
| 5 | **Time-decay** macro | macro актуален N дней после born | **до первого касания** macro_zone (классическая SMC) или N=14d cap |
| 6 | **Entry timeout** | сколько часов entry актуален после рождения | **24h** (canon ob_vc validity) |
| 7 | **bb-model** для macro тоже? | только entry / обе ступени | **только entry** на старте; модель macro_ob_vc — следующая в серии |
| 8 | **Symbol scope** | BTC / + ETH/SOL | **BTC only** на старте (как и v1) |

## Зависимости

| компонент | где |
|---|---|
| ob_vc canon | `~/smc-lib/elements/ob_vc/definition.md` + `code.py` |
| Базовая Strategy 1.1.1 (детектор) | `~/traid-bot/strategies/strategy_1_1_1.py` + `vault/knowledge/strategies/strategy_1_1_1.md` |
| **Floating TP simulator + score** | `~/smc-lib/projects/strategy_1_1_1_floating.py` (etap108 reference) |
| Floating TP guide | `~/smc-lib/projects/strategy_1_1_1_floating.pdf` (human-readable) |
| bb-модель entry filter | [[bounce-or-break]] (этот же projects/) |
| zones_opinion (для live карты) | `~/smc-lib/prediction-algo/zones_opinion.py` |
| Канон mitigation для entry | `~/smc-lib/zone_of_interest.md` (wick-fill для OB) |

## План работ

1. ~~Design discussion~~ **в процессе** — этот документ + 8 открытых вопросов
2. **Detector** — `~/smc-lib/projects/strategy_1_1_1_v2/detector.py` (cross-TF nested ob_vc scanner)
3. **Backtest на 3y BTC** — Mac-задача (быстро) или PC1 (на 6y)
4. **Сравнение с v1**: WR / R / median trade / drawdown
5. **Интеграция bb-фильтра** (когда bb-модель готова)
6. **Live deployment** в `traid-bot` как параллельная стратегия рядом с v1 (не замена)

## Связи

- [[bounce-or-break]] — bb-модель для entry filter
- [[prediction-algo-roadmap-5-questions]] — общий roadmap
- Базовая v1 — `~/traid-bot/strategies/strategy_1_1_1.py`
