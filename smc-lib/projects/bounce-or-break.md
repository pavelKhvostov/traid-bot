# Bounce-or-Break Classifier (#3 roadmap)

> Feature spec для задачи **«удержит ли блок при касании зоны»**.
> Status: **approved** (8 вопросов закрыты 2026-05-29 + label rule переформулирован под production).
> Owner: prediction-algo v2 / экспертное заключение по зонам.
> Первая модель в серии: **ob_vc на HTF={1h, 2h}** (LTF=15m/20m зашита в canon ob_vc).

## Production use case (главное)

Модель — это **entry filter** для **Strategy 1.1.1 V2** (см. [[strategy-1-1-1-v2]]):
- **macro** = `ob_vc(D/12h + 4h/6h)` — задаёт зону интереса верхнего уровня
- **entry** = `ob_vc(1h/2h + 15m/20m)` ← **bb-модель работает здесь** (P_bounce)

**Train scope = canon `ob_vc(1h+2h)`** (без дополнительных filters типа macro/SWEPT) — это ровно distribution Strategy 1.1.1 V2 entry-зон. Decision зафиксирован 2026-05-29.

V1-стратегии (1.1.1/1.1.2/1.1.6) тоже близки по entry-zone format (`OB-{1h,2h} + FVG-{15m,20m}`), но **не идентичны** нашему canon ob_vc — у них нет spatial/temporal canon conditions, плюс есть SWEPT/macro/confluence как hard-filters. К ним bb-модель применима как **дополнительный** фильтр поверх их логики, не как замена.

```
Strategy 1.1.1 detects entry zone:  ob_vc(2h, [73000, 73500])  + LTF FVG
                ↓
Price arrives:  touch event  (low ≤ 73500)
                ↓
bb_model.predict(zone_features)  →  P_bounce = 0.73
                ↓
Decision rule (configurable per strategy):
    if P_bounce ≥ 0.60:  ENTRY  (фильтр пропустил)
    else:                SKIP   (зона слабая, риск 100% fill)
```

**P_bounce = вероятность что цена развернётся ПРЕЖДЕ чем достигнет противоположную границу зоны.** Это actionable signal score напрямую для trading-стратегии.

## Финальные решения (2026-05-29)

| # | Вопрос | Решение |
|---|---|---|
| 1 | Label window | **`2 × HTF_bars`** (для 1h-зоны → 2h окно, для 2h-зоны → 4h окно) |
| 2 | ~~ATR-buffer~~ Label trigger | **граница зоны** (LONG: `low ≤ lo`, SHORT: `high ≥ hi`). ATR-buffer не нужен — толщина зоны сама фильтр шума |
| 3 | Label scheme | **binary** (bounce / break) — где break = 100% fill зоны (wick достиг противоположной границы) |
| 4 | Inherited zones | **включать** + фича `n_touches_prior` |
| 5 | Distance filter | **без filter** — берём первое касание любой зоны |
| 6 | Calibration | **isotonic** |
| 7 | Архитектура | **per-element series**, первая = `ob_vc(1h+2h)` с `tf` как фича. Series потом: `ob_vc(4h+6h)`, `OB_classic_*`, `iFVG_*`, ... |
| 8 | No-touch zones | **drop**, но окно поиска касания = **48-72h** (увеличено с 24h) |

## Цель

При первом касании зоны интереса предсказать:

```
P(bounce) ∈ [0, 1]  — вероятность что зона удержит цену
P(break)  = 1 - P(bounce)
```

Это самый **actionable** вопрос трейдера. Текущая модель (`zones_opinion.py`) предсказывает только *достигнет* ли цена зону (P_hit_D), но не *удержит* ли её зона.

**Гипотеза:** один и тот же тип зоны (например, OB-4h) с одинаковой `distance_pct`/`age_bars` ведёт себя по-разному в зависимости от **контекста на момент касания** — HTF тренда, накопленного давления (cum delta), позиции относительно VWAP, ATR-режима. Эти контекстные фичи и есть то, что должен выучить ML head.

## Ground truth

### Event = «первое касание зоны»

Зона определена как `[lo, hi]`. **Касание** — **первый** бар на 1m в окне `[born_ts, born_ts + 72h]`, у которого:

| direction | trigger |
|---|---|
| LONG (side=`below`) | `low ≤ hi` (цена впервые вошла в зону сверху) |
| SHORT (side=`above`) | `high ≥ lo` (цена впервые вошла снизу) |

**Touch search window = 72h** (3 суток). Зоны без касания за 72h — drop (вне scope #3; покрывает zones-модель: «достигнет ли»).

### Label = binary bounce vs break (геометрически по границам зоны)

**Окно решения после touch** = `2 × HTF_bars`:
- HTF=1h → окно 2h после touch
- HTF=2h → окно 4h после touch

Зона = `[lo, hi]`. Break = «100% fill зоны» — wick достиг противоположной границы.

| direction | label = **bounce (0)** | label = **break (1)** |
|---|---|---|
| LONG (side=below) | `min(low[t..t+W]) > lo` | `min(low[t..t+W]) ≤ lo` |
| SHORT (side=above) | `max(high[t..t+W]) < hi` | `max(high[t..t+W]) ≥ hi` |

**Почему не нужен ATR-buffer:**
1. Толщина зоны `(hi - lo)` уже сама по себе — фильтр шума
2. «100% fill» = чёткое геометрическое определение, не требует tuning
3. Сразу actionable для трейдера: «зона удержала» (=bounce) vs «зона исчерпала ресурс» (=break)
4. ОБЕ границы зоны — структурные уровни (open + LTF FVG), не arbitrary
5. Output `P_bounce` совпадает по семантике с тем что трейдер интуитивно понимает

## Methodology

### Conditional sample

Первая модель (canon): **только `ob_vc` на HTF ∈ {1h, 2h}** с touch event в окне 72h после рождения.

| фильтр | счёт |
|---|---|
| `type == "ob_vc"` в btc_full v2 | 776K rows |
| `tf ∈ {"1h", "2h"}` | 1h:219K + 2h:249K = **468K rows** |
| После dedup по `(zone_id, born_ts)` — уникальные зоны | ~10-20K (грубая оценка) |
| После фильтра «есть touch в 72h» | TBD (вероятно 70-90% от уникальных) |
| Финальный train+test pool | ожидаем **8-15K events** |

Зоны должны быть уникальные — каждая ob_vc-зона в датасете один раз (первое касание), а не по cut_off snapshot.

### Архитектура: SMC fingers → ML head

| Слой | Что делает |
|---|---|
| **SMC fingers** (этот документ) | На каждое touch event строим feature vector ~50 фичей: контекст зоны + HTF тренд + волатильность + давление + позиция vs VWAP/HMA + сосед-зоны |
| **ML head** | LightGBM Binary Classifier с **isotonic** calibration → откалиброванный P(bounce) |
| **Walk-forward** | 5y train / 1y test / monthly retrain (тот же канон что zones-model) |
| **Per-element series** | Первая модель: `ob_vc(1h+2h)`. Следующие в очереди: `ob_vc(4h+6h)`, `OB_classic_*`, `iFVG_*`, `iRDRB_*`. Каждый element/TF-set — отдельная модель |

### Метрики

| Метрика | Цель |
|---|---|
| Brier score | ≤ baseline × 0.6 (40% lift) |
| Calibration (reliability bins) | Slope ≈ 1.0, intercept ≈ 0 |
| Top-decile precision | P(bounce \| pred ≥ 90%) ≥ 0.85 |
| AUC-ROC | ≥ 0.70 (выше = retroactive useful) |
| Per-type breakdown | bounce-rate ratio (max/min) ≤ 1.3 — модель не должна просто запоминать тип |

## Feature catalog

7 групп. Все фичи вычислены на момент **touch** (не на момент born_ts).

### A. Свойства самой зоны (inherits from zones-dataset)

| фича | смысл |
|---|---|
| `tf` | ТФ зоны (1h/4h/12h/1d/...) |
| `type` | OB / FVG / RDRB / iFVG / ob_vc / ob_liq / fractal / marubozu / block_orders / iRDRB |
| `direction` | long/short |
| `width_pct` | (hi-lo)/level — относительная толщина |
| `level` | mid зоны (для distance расчётов) |
| `age_bars` (на момент touch) | сколько баров от born до touch (свежесть) |
| `mitigation_model` | wick-fill / sweep / first-touch / sweep-open |

### B. Penetration features (на момент touch)

| фича | смысл |
|---|---|
| `penetration_pct` | глубина wick внутрь зоны как % от width |
| `close_inside` | флаг: 1m-close первого касания внутри зоны |
| `wick_to_body_touch` | wick_len / body_len первого касания (большой wick = sweep, большой body = momentum) |
| `n_touches_24h_prior` | сколько раз эта зона касалась за 24h до born (для inherited zones) |

### C. HTF trend context

| фича | смысл |
|---|---|
| `hma78_slope_1h` | наклон HMA-78 на 1h (+/-) |
| `hma200_slope_D` | наклон HMA-200 на D |
| `dist_to_hma78_pct` | расстояние цены до HMA-78 (1h) в % |
| `dist_to_hma200_pct` | расстояние до HMA-200 (D) в % |
| `trend_agreement_4h_D` | бинарно: совпадает ли направление зоны с HMA-tilt на 4h и D |
| `aligned_with_htf` | LONG zone + HTF uptrend → 1; иначе 0 |

### D. Volatility regime

| фича | смысл |
|---|---|
| `atr_1h_pct` | ATR(14) на 1h в % от цены |
| `atr_4h_pct` | то же на 4h |
| `atr_1h_z` | z-score ATR_1h vs 30-дневного среднего |
| `expansion_ratio` | ATR(14)/ATR(60) — контракция/экспансия |

### E. Pressure / volume context

| фича | смысл |
|---|---|
| `cum_delta_4h` | накопленная delta за 4h до touch (buy-sell pressure) |
| `cum_delta_24h` | то же на 24h |
| `volume_z_at_touch` | z-score volume 1m-бара касания vs 60-min среднего |
| `dirvol_at_touch` | directional volume (Vic-style) на 12h(i-1) — для контекста близости к VIC уровню |
| `cd_slope_pre_touch_1h` | наклон CD за час перед touch (давление к зоне) |

### F. Confluence / position

| фича | смысл |
|---|---|
| `dist_to_vwap_session_pct` | дистанция до anchored VWAP сессии (от ближайшего фрактала) |
| `vwap_side` | цена выше/ниже VWAP сессии |
| `dist_to_poc_d_pct` | дистанция до Volume Profile POC за день |
| `dist_to_maxv_d_pct` | дистанция до VIC maxV(D-1) |
| `n_zones_same_side_within_1pct` | сколько других активных зон того же направления в радиусе 1% (cluster strength) |
| `n_zones_opposite_side_within_2pct` | сколько противоположных зон в 2% — кандидаты на BSL/SSL цели |

### G. Money Hands context (4 фактора)

| фича | смысл |
|---|---|
| `mh_color_state_15m` | bull/bear color factor на 15m |
| `mh_color_state_1h` | то же на 1h |
| `mh_bw2_15m` | WaveTrend mid (bw2) |
| `mh_bw2_1h` | то же на 1h |
| `mh_mf_state_15m` | Heikin Ashi state |
| `mh_stoch_signal` | двойной Stoch sig/over |
| `mh_cascade_active` | флаг bear-cascade ≤ 1h на момент touch (из pivot-MH rule) |

### H. Path dynamics — КАК цена возвращалась к зоне

Окно расчёта: `[max(born_ts, last_extremum_ts), touch_ts]` — от последнего HH/LL до момента касания.

| фича | смысл |
|---|---|
| `bars_since_extremum` | сколько 1h-баров от последнего HH/LL до touch (свежесть импульса) |
| `path_duration_hours` | длительность участка «extremum → touch» в часах |
| `displacement_speed_pct_h` | (цена @ extremum) - (цена @ touch) в % / часах — скорость возврата |
| `path_directness_pct` | доля баров двигавшихся к зоне / общее число баров (impulse vs chop) |
| `path_atr_z` | средний ATR за участок vs 30-day baseline (sharp impulse vs slow drift) |
| `n_fractals_in_path` | сколько Williams-фракталов сформировалось ПО ПУТИ возврата |
| `n_sweeps_in_path` | сколько свипов промежуточных уровней (фрактал / OB.high / pivot) случилось |
| `last_bar_is_marubozu` | флаг: последняя 1h перед touch — marubozu (impulse close) |
| `last_3bars_same_color` | флаг: 3 предыдущие 1h одного цвета по направлению к зоне |
| `cum_delta_path` | накопительная delta на участке возврата |
| `cd_acceleration_pre_touch` | (CD за последние 1h) / (CD за предыдущие 4h) — ускорение давления |

### I. Structural inventory — ЧТО оставила цена в графике

Снимок ВСЕХ активных зон (не только ob_vc) в момент touch — используем тот же snapshot-механизм что zones-model. Все фичи направление-relative (для LONG ob_vc «same_side» = below, для SHORT — above).

| фича | смысл |
|---|---|
| `n_untouched_fvg_between` | количество неисполненных FVG между ценой и нашей зоной (по пути её достижения) |
| `n_untouched_ob_between` | то же для OB |
| `n_liquidity_pools_between` | количество не-свипнутых фракталов (BSL/SSL) между ценой и зоной |
| `untraded_inventory_pct` | сумма ширины untouched FVG/iFVG/marubozu между ценой и зоной — «магнит» по фундаментальному принципу |
| `n_active_zones_same_side` | плотность зон того же направления в радиусе 2× width текущей зоны |
| `n_active_zones_opposite` | плотность зон противоположного направления в том же радиусе |
| `dist_to_nearest_opposite_zone_pct` | расстояние до ближайшей противоположной зоны (= цель сценария B / invalidation) |
| `dist_to_nearest_fractal_same_side_pct` | расстояние до ближайшей ликвидности своей стороны (target за зоной) |
| `htf_fractal_swept_24h` | флаг: HTF (D/12h) fractal sweep случился за последние 24h (energy «вдоха») |
| `structural_drain_count_24h` | сколько зон того же направления митigated за последние 24h (исчерпание structure) |
| `fvg_imbalance_above_minus_below` | sum(untouched FVG sizes выше цены) - sum(ниже) — directional bias |

**Итого ~70 фичей** (50 базовых + 11 path + 11 inventory). При variants (per-TF expansion) — до ~120. Старт с базовым набором, расширение по feature importance после первой walk-forward итерации.

## Почему path + inventory критичны

Соответствует **базовым SMC принципам** (зафиксированы в memory):

1. **«Untraded area is a magnet»** ([[feedback-untraded-area-is-magnet]]) — непроторгованная область притягивает цену. Если между ценой и нашей ob_vc есть untouched FVG — модель должна знать что эта FVG «попросит» исполнение раньше bounce.
2. **«HTF sweep проглатывает LTF события»** ([[feedback-fractal-liquidity-strength-and-sweep]]) — недавний HTF sweep кардинально меняет силу зоны.
3. **Cascade резонанс** ([[pivot-money-hands-long-cascade-rule]]) — последовательные структурные события в коротком окне дают +27% accuracy в pivot-MH модели; та же логика применима здесь.
4. **Структурный inventory** — если зона уже «осталась одна» (нет inventory того же направления) — bounce от неё статистически слабее, цена пойдёт дальше за liquidity.

## Walk-forward plan

Идентичен zones-model (для voltage consistency):

| параметр | значение |
|---|---|
| Train window | 5 лет (rolling) |
| Test window | 1 год (последний год dataset) |
| Retrain freq | monthly (30d) |
| Test cuts | ~12 retrains/год |
| Hardware | PC2 (LightGBM 20 threads) |

### Output

```
output/
├── bb_predictions.csv         per-event: ts_touch, P_bounce, actual_label, type, tf, ...
├── bb_metrics.json            brier, AUC, calibration, top-decile precision, per-type breakdown
├── bb_feature_importance.csv  LightGBM gain importance
└── bb_calibration.png         reliability curve
```

## Зависимости с canon

| компонент | где |
|---|---|
| Зоны | `~/smc-lib/elements/` + `zone_of_interest.md` |
| Mitigation модели | `zone_of_interest.md` (per-zone канон) |
| HMA Trend Line | `~/smc-lib/indicators/trend_line_asvk.py` |
| VIC maxV | `~/smc-lib/indicators/vic_asvk.py` |
| Money Hands | `~/smc-lib/indicators/money_hands_asvk.py` |
| Volume Profile / POC | `~/smc-lib/indicators/volume_profile.py` |
| Anchored VWAP | `~/smc-lib/indicators/vwap_anchored.py` |
| ATR / RSI / EMA | `~/smc-lib/indicators/` |
| Cum Delta | `~/smc-lib/indicators/cumulative_delta.py` |
| 1m данные | `~/traid-bot/data/BTCUSDT_1m_vic_vadim.csv` |
| Walk-forward harness (заимствуем) | `~/smc-lib/prediction-algo/validate.py` (адаптировать под binary classifier) |

## План следующих шагов

1. ~~Decision pass~~ ✅ **закрыто 2026-05-29** — все 8 вопросов зафиксированы
2. **Dataset builder** — `bb_dataset.py` (для первой модели ob_vc(1h+2h)):
   - входит: `~/Desktop/btc_full.csv` v2 + `~/traid-bot/data/BTCUSDT_1m_vic_vadim.csv`
   - filter: `type=="ob_vc" AND tf in ("1h","2h")`
   - dedup до уникальных зон
   - touch detection на 1m в окне 72h
   - **path computation**: lookup на отрезке `[last_extremum_ts, touch_ts]` → группа H
   - **structural inventory snapshot**: zone-snapshot для всех типов в момент touch → группа I
   - feature computation (9 групп, ~70 фичей)
   - label: bounce/break геометрически по границе зоны (без ATR-buffer)
   - output: `bb_obvc_1h2h.parquet`

   Heavy compute, особенно H+I (требует full 1m lookup + zones snapshot per event). Уйдёт архивом на PC1.
3. **PC1 dataset generation** — heavy compute (1m лукапы на 6 лет данных)
4. **PC2 walk-forward** — LightGBM Binary + isotonic, как mh-ml но classifier
5. **Evaluation** — Brier, AUC, calibration, top-decile precision, breakdown по `tf` (1h vs 2h)
6. **Integration** — `P_bounce` в `zones_opinion.py` output для ob_vc-зон в карте
7. **Next model in series** — `ob_vc(4h+6h)` тем же pipeline

## Связи

- [[prediction-algo-roadmap-5-questions]] — задача #3 из roadmap
- [[prediction-algo-final-results]] — текущая модель zones (которая отвечает только на «достигнет ли»)
- [[feedback-fractal-liquidity-strength-and-sweep]] — sweep канон (используется в `penetration_pct` логике)
- [[feedback-untraded-area-is-magnet]] — fundamental SMC принцип (магнит, не точка отскока)
- [[zone-class-liquidity-inefficiency-block]] — class breakdown может быть полезен как фича
