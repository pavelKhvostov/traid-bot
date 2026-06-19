# pivot

> Status: **validated → merged into pred12h** (2026-06-01).
>
> Цель проекта подтверждена эмпирически: композиция (1.1.1 SWEPT cascade ∩ 12h Williams n=2 pivot ≥2%) даёт на BTC 6y **WR 61.6% / PF 3.47 / +132R** vs pure floating 51.3% / 2.20 / +196R.
>
> Дальнейшая доработка ведётся в [`pred12h-fractal-three-candles`](pred12h-fractal-three-candles.md) — у него уже есть basket F1∩F2∩F3 + C1-C7 (P=66.8%, 15/18 imp), который надо проверить как filter вместо упрощённого Williams+2%.
>
> Этот документ остаётся как **session summary + label rule** для pivot-проекта.

## Цель

**Отбирать высококачественные точки разворота тренда** и торговать только их.

Целевой ритм: **8-12 сделок в месяц** (хороший трейдер). То есть проект про **selectivity / precision**, а не про объём:
- лучше пропустить 100 ситуаций, чем взять 5 плохих
- метрика главная — **WR + RR на отобранных сделках**, а не recall фракталов
- false-positive дороже false-negative

## Trading constraints (fixed)

- **Leverage = 50x** (margin / perp futures)
- **Главный ТФ = 12h** (LTF swing pivots), таргет 8-12 сделок/мес → ровно 11 точек за 5 недель (2026-04-26 — 2026-06-01) подтверждают эту гранулярность
- **Минимальное движение от пивота = 2%** (= +100% к позиции при 50x)
- Следствия, которые проект обязан учитывать:
  - liquidation при ~2% adverse, поэтому **SL обязан быть структурным и ≤ 1% от entry**
  - **RR target ≥ 2** (2% move ÷ 1% SL); при таком SL даже WR 50% даёт +0.5R/trade
  - энтри только по **точному касанию зоны** на 12h LTF (ob_vc/FVG entry zone), не market — slippage ×50
  - holding time ≤ 2-3 дня (funding × 50)
- Эти ограничения задают rubric для Q3 (качество) и Q4 (precision budget)

## Архитектура: 4 уровня → 2 зоны (fixed)

| Уровень | TFs | Роль |
|---|---|---|
| **Уровень 1** | D, 12h | macro HTF |
| **Уровень 2** | 6h, 4h | macro LTF (подтверждение зоны 1) |
| **Уровень 3** | 2h, 1h | entry HTF |
| **Уровень 4** | 15m, 20m | entry LTF (подтверждение зоны 2) |

- **Зона 1** = формируется Уровнями 1 + 2 (macro pivot context)
- **Зона 2** = формируется Уровнями 3 + 4 (entry trigger)
- Сделка валидна, только когда **Зона 2 ⊆ Зона 1** и same direction
- Точное касание Зоны 2 на 1m → сигнал

Это **полностью совпадает** с архитектурой **Strategy 1.1.1 V2** (`strategies/strategy_1_1_1/`):
- Z1 ≡ macro `ob_vc(HTF=D/12h, LTF=4h/6h)`
- Z2 ≡ entry `ob_vc(HTF=1h/2h, LTF=15m/20m)`

Pivot-проект = переиспользование уже описанной 4-TF cascade под новый rubric (50x / ≥2% / 12h pivot label).

## Label rule — working draft (Q1)

```
pivot = Williams n=2 fractal на 12h
      AND |move до следующего противоположного pivot'а| ≥ 2%
      AND time-to-next-opposite ≥ 1 × 12h bar
      AND не same-bar с противоположным fractal
      AND не unconfirmed на правом краю (нужно ≥ 2 × 12h post-bars)
```

**Эмпирическая валидация (2026-04-26 — 2026-06-01):**
- Williams n=2 на 12h дал 16 raw кандидатов
- После filter ≥2%, ≥1×12h, не same-bar, не unconfirmed → 11-13 кандидатов
- Ground truth от пользователя (TradingView): **11 точек**
- Расхождение ≤2 кандидата на borderline 2-3% swing'ах

## Ground truth

_TBD_ — нужно определить, что значит «точка разворота тренда» формально:
- какой ТФ — главный для метки разворота? (D / 12h / 4h?)
- как помечается «состоявшийся разворот» — по смене HH/LL структуры, по N-ATR ходу против предыдущего тренда, по сроку удержания?
- как помечается «качество» — RR≥X, drawdown≤Y, время до подтверждения≤Z?
- символ + период baseline: BTC 6y (как остальные проекты)?

## Methodology

_TBD_ — архитектура. Кандидаты:
- **Cascade**: HTF тренд → mid-TF исчерпание → LTF триггер (top-down как expert opinion)
- **OR-basket условий** (как pred12h-fractal-three-candles): набор предикатов на (i-2, i-1, i), фрактал отбирается если ≥1
- **ML head** поверх SMC-fingers: bb-style, score = P(true reversal | features)
- **Гибрид**: SMC strict cascade даёт events ↓ recall, ML head даёт rank ↑ precision

Связанные модули, которые могут быть «пальцами»:
- `pivot-money-hands/` — LONG-cascade 62.9% (резонанс bear+cascade≤1h) — кандидат на один из bullish-сигналов
- `12h-fractal-prediction` — (sweep_FH ∪ OB_sweep) ∩ sweep_maxV[i] = 82% HH / 73% LL на 6y BTC — сильный 12h pivot-сигнал
- `expert/opinion.py` — multi-TF cascade W→D→12h→4h→1h→15m — для финальной валидации

## Этапы / условия

_TBD_ — таблицы заполняются по мере дизайна.

## Текущая корзина

_TBD_ — пока пусто.

## Открытые задачи (design phase)

- [ ] **Q1**: что такое «точка разворота тренда» формально (label rule)
- [ ] **Q2**: главный ТФ метки и торговли (D / 12h / 4h?)
- [ ] **Q3**: критерий «качества» сделки (RR / DD / время)
- [ ] **Q4**: budget false-positive vs false-negative (precision target ≥ ?)
- [ ] **Q5**: методология — strict cascade / OR-basket / ML head / гибрид
- [ ] **Q6**: какие из существующих сигналов берём за «пальцы» (pivot-money-hands, 12h-fractal, ob_vc, expert opinion)
- [ ] **Q7**: датасет ground truth (BTC 6y in-sample?)
- [ ] **Q8**: метрики приёмки (sample/month ≈ 8-12, WR ≥ ?, RR ≥ ?)

## Связи

- Соседний модуль: [`pivot-money-hands/`](../pivot-money-hands/) — LONG-cascade 62.9%, асимметрия SHORT
- 12h fractal prediction: memory `12h-fractal-prediction-final-strategy` ((sweep_FH ∪ OB_sweep) ∩ sweep_maxV[i] = 82% HH / 73% LL)
- Expert top-down cascade: memory `feedback-expert-opinion-is-multi-tf-cascade`
- Canon: [`rules.md`](../rules.md), [`zone_of_interest.md`](../zone_of_interest.md)
