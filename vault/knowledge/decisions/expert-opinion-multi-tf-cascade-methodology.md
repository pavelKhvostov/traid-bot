---
tags: [decision, methodology, expert-opinion, cascade, multi-tf, smc]
date: 2026-05-24
status: locked
location: ~/smc-lib/expert_opinion.md + scripts/expert_opinion.py
related: [[2026-05-24-smc-lib-cascade-expert-opinion-indicators]], [[smc-lib-as-canonical-source]]
---

# Expert Opinion — Multi-TF Cascade Methodology

Canonical pipeline для построения мнения о направлении движения цены, основанный на зонах SMC + классах + индикаторах + магнит-логике.

## Главный принцип

**Экспертное заключение всегда строится top-down каскадом**:

```
W → 3D → 2D → D → 12h → 6h → 4h → 2h → 1h → 15m
```

10 ТФ. Не на одном ТФ. Не bottom-up. HTF priority при конфликте.

## Каскад — что каждый ТФ отвечает

| ТФ | Lookback | Radius | Вопрос |
|---|---|---|---|
| W (Mon-anchor) | 730d | ±20% | Доминирующий трейд года; macro magnets |
| 3D | 365d | ±15% | Годовая структура |
| 2D | 240d | ±12% | 8-месяцев |
| D | 120d | ±8% | Свинг-структура месяцев; primary reaction zones |
| 12h | 60d | ±6% | Intermediate confluence (недели) |
| 6h | 42d | ±5% | Setup zones |
| 4h | 30d | ±5% | Working area |
| 2h | 21d | ±4% | Confirmation zones |
| 1h | 14d | ±3% | Entry context |
| 15m | 5d | ±2% | Precision triggers, execution |

## 4 принципа каскада

1. **HTF priority** — при конфликте HTF побеждает. HTF wick "проглатывает" LTF события (см. [[feedback-fractal-liquidity-strength-and-sweep]]).
2. **Top-down narrative** — мнение строится от W к 15m. Не наоборот.
3. **Confluence** — высокая вероятность setup'a там, где зоны нескольких ТФ выравниваются.
4. **LTF не разрушает HTF** — "пробой" 15m FH внутри 4h wick не отменяет 4h setup.

## Pipeline — 10 шагов

### Шаги 1-5 (автоматизируются скриптом)

1. **Сбор данных** — 1m CSV + докачка через curl + per-TF lookback + forming bar detection
2. **Detection scan** — 11 элементов smc-lib (`elements/`) на окне
3. **Position assessment** — INSIDE / above / below относительно close в radius
4. **Класс зон** — efficiency / inefficiency / liquidity ([[zone-class-liquidity-inefficiency-efficiency]])
5. **Magnets identification** — untraded inefficiency + unswept liquidity

### Шаг 5b — Indicators layer

На каждом ТФ дополнительно:
- **ATR(14)** Wilder — буферы / size moves
- **EMA-200** на close — trend filter
- **Cumulative Delta** (Williams A/D proxy) — order flow direction (proxy)
- **Volume Profile** на последних 150 барах — POC / VAH / VAL (70%)
- **VIC ASVK** на последнем HTF баре с auto LTF — maxV / delta / norm
- **ASVK Trend Line (Hull MA)** — color (up/down) + SHULL
- **ASVK Custom RSI** — ema_3 + zone (red/yellow_ob/neutral/yellow_os/green)
- **Money Hands ASVK** — bw2 + color (green/white_weak_*/red) + MF

**VWAPs ASVK ranking** (отдельный блок):
- Anchor на каждом D-фрактале за последний 1 год (~14-25 anchor'ов)
- VWAP на каждом ТФ каскада + effectiveness scoring per TF
- Composite = weighted avg по log(1+interactions)
- **Selection: 2 closest + 6 most effective + 2 farthest**

### Шаги 6-10 (синтез ассистентом)

6. **Structure reading** per TF: regime (UPTREND/DOWNTREND/CONTRACTION/EXPANSION) из FH/FL sequence
7. **Cascade integration**: trend cascade alignment + confluence zones + HTF magnets
8. **Scenarios** (минимум A/B, обычно A/B/C) с multi-TF triggers + path магнитов
9. **Invalidation map** — decision-tree триггеров по ТФ
10. **Time anchors + caveats** — forming bars, актуальность, ограничения

## Effectiveness scoring (VWAP)

Per TF:
```
bar взаимодействует с VWAP если low ≤ vwap ≤ high
side(bar) = above if close > vwap else below
reaction = side(bar) == side(prev_bar)  (бар на той же стороне)
break    = side(bar) != side(prev_bar)
score_tf = reactions / (reactions + breaks)
```

Composite:
```
composite = Σ_tf (score_tf · log(1 + interactions_tf)) / Σ_tf log(1 + interactions_tf)
```

## Класс зон — что в каком блоке

| Класс | Элементы | Магнит-логика |
|---|---|---|
| **efficiency** | ob, block_orders, ob_liq, rdrb, i_rdrb, i_rdrb_fvg | institutional accumulation, обычное S/R |
| **inefficiency** 🧲 | fvg, i_fvg, marubozu | untraded magnet (см. [[feedback-untraded-area-is-magnet]]) |
| **liquidity** 🧲 | fractal, rb, ob_liq.liq_zone | collected stops, sweep targets |

## Формат финального ответа (8 секций)

1. Текущая цена + время data feed
2. Cascade summary (trend regime per TF)
3. Indicators heatmap (multi-TF table)
4. VWAPs cluster analysis (где сходятся effective anchors)
5. Multi-TF confluence zones (где 2+ ТФ aligned)
6. HTF magnets top-3-5 (выше/ниже)
7. Scenarios A/B/(C) с вероятностями + multi-TF triggers
8. Invalidation map (cross-TF decision-tree) + caveats

## Что НЕ делать

- ❌ Одно-TF мнение без явного указания "только TF X"
- ❌ Опираться только на одну зону / один фрактал — confluence обязателен
- ❌ "Прогнозная цифра" без сценариев и триггеров
- ❌ Игнорировать W / D structure
- ❌ LTF reversal-сигнал = инвалидация HTF trend (это retracement)
- ❌ % уверенности > 75% без strong multi-TF confluence (3+ ТФ aligned)
- ❌ Путать магнит-зоны (inefficiency/liquidity) с S/R (efficiency)

## Производительность

- Полный 10-TF каскад с 11 детекторами + 9 индикаторов + 98 VWAPs: **~3.1s**
- Optimizations: per-TF slice of 1m data + epoch-anchor aggregation + Mon-anchor через integer arithmetic для W

## Связи

- [[2026-05-24-smc-lib-cascade-expert-opinion-indicators]] — session note
- [[feedback-expert-opinion-is-multi-tf-cascade]] — main principle memory
- [[feedback-untraded-area-is-magnet]] — fundamental SMC principle
- [[feedback-fractal-liquidity-strength-and-sweep]] — fractal nuances
- [[zone-class-liquidity-inefficiency-efficiency]] — таксономия классов
- [[smc-lib-as-canonical-source]] — canon source принцип
- [[vic-asvk-indicator-python]] — VIC ASVK canon
- [[asvk-custom-rsi]] — RSI ASVK canon
- [[asvk-trend-line-hull]] — Hull MA canon
- [[money-hands-asvk]] — Money Hands canon
