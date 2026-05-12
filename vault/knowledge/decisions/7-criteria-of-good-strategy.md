---
tags: [decision, principle, criteria, strategy-evaluation]
date: 2026-05-08
status: active-rubric
---

# 7 критериев удачной стратегии

Принят 2026-05-08 после honest audit Strategy 1.1.1 и сравнения C2 vs D2 vs 1.1.1.
Применяется к любой backtest-стратегии **до** обсуждения live-deployment.

## Контекст

Single metric (WR, total R, R/trade) — недостаточно. Бывают:
- WR 70% но 3 минусовых года → нестабильно
- +100R total но 80% от 2 лет → не повторится
- R/tr 0.5 но 0.3/нед → не наберём statistically significant сделок
- WR 65% на 50 сделках → могло быть случайностью

Поэтому стратегию надо проходить через **все 7 критериев**, а не точечный
maximum по одной метрике.

## Список критериев

### 1. Стабильность по годам (ZERO bad years preferred)

```
Все годы test-периода: total_R ≥ 0
ИЛИ максимум 1 минусовый год с modest loss (не более −15R)
```

Causes-rejection: 2+ минусовых лет (например D2 показал 2022 и 2026 минусовых).

**Why critical:** одна-две убыточные серии не должны убивать год.
Стратегия с 1 ужасным годом и 6 хорошими часто = overfit на 6 хороших.

### 2. Win Rate ≥ 50%

```
WR на полном test-period ≥ 50% при выбранном RR
```

Допускается WR < 50% если RR > 2 и expected value > 0 (см. trend-following).
Но для RR=1 (наш default) — обязательно ≥ 50%.

**Why:** психологически и practically — серия 5+ losses подряд при WR<50%
часто случается даже у математически прибыльной стратегии. Это убивает
дисциплину.

### 3. R/trade > 0 (positive expected value)

```
total_R / closed > 0
```

Обязательное минимальное условие. Без этого — гарантированный slow drain.

### 4. Frequency ≥ 1 setup/неделю

```
total_setups / weeks_in_period ≥ 1.0
```

**Why:** ниже 1/нед — статистически слабая выборка для оценки edge'а;
psychologically трудно ждать сетапы; transaction cost (spread, fees) на
малой частоте съедает edge.

Sniper portfolios из 5+ редких стратегий — не альтернатива одной нормальной
по частоте (etap_24 показал: 10 sniper × 0.7/нед = 6.9R/year vs 1 нормальная
2.4/нед = 14.1R/year).

### 5. No lookahead

```
Backtest проходит проверку на lookahead bug
```

Обязательно проверить:
- Anchor confirm time = `anchor_open + tf_anchor` (не open)
  ([[lookahead-anchor-confirm-окно-cur_open-cur_close]])
- Multi-bar pattern entry на confirm_idx, не trigger_idx
  ([[multi-bar-pattern-confirm-vs-trigger-lookahead]])
- Scan стартует от close, не open ([[lookahead-bug-в-vic-evot-backtest]])
- Round RR ≥ {1.0, 1.5, 2.0}, не custom-fitted (например RR=2.2)
- Нет hardcoded `+15min` для fill-scan
  ([[strategy-1-1-1-look-ahead-15min-vs-tf_duration]])

**Red flag:** WR > 60% на 100+ крипто-сделках = lookahead suspect, не feature.

### 6. Min SL ≥ 1% (futures-friendly)

```
Все trades должны иметь SL ≥ 1% от entry
```

Узкий SL даёт высокий R/trade в backtest, но в реальности:
- Маркет-импакт и slippage съедают
- Spread и комиссии на open+close ≈ 0.1% уже значимы при SL 0.5%
- Мелкие SL чувствительны к шуму внутри 1m баров

Стандартная формула: `sl = max(15% · zone_depth, 1% · entry)`.

### 7. Простота: ≤ 2 уровня вложенности

```
Стратегия = anchor zone + trigger zone + опционально 1 фильтр
Не более 2 уровней вложенных зон + 1 простого фильтра (pro-trend, ICT hour)
```

**Why:** каждый дополнительный уровень фильтрации = свободный параметр =
потенциальный overfit. На наших датасетах (6 лет крипто) bias-variance
говорит «больше 3 параметров = переобучение».

3-stage оптимизация (entry/SL/RR) — это поиск параметров, НЕ добавление
уровней. Ok.

4-stage cascade (HTF anchor → MID anchor → LTF trigger → micro trigger) —
overfit catastrophe. Strategy 1.1.1 — case study.

## Применение

Для оценки кандидата:

```
[ ] 1. Все годы ≥ 0R?  ___
[ ] 2. WR ≥ 50% (или RR>2, EV>0)?  ___
[ ] 3. R/tr > 0?  ___
[ ] 4. ≥ 1 setup/нед?  ___
[ ] 5. No lookahead (5 проверок выше)?  ___
[ ] 6. min_sl ≥ 1%?  ___
[ ] 7. ≤ 2 уровня?  ___
```

Если **все 7 ✅** → кандидат на OOS validation (other symbols, walk-forward).
Если **6/7** → fix gap, re-test, не deploy.
Если **<6** → не годится, copy parts to other research.

## Текущее состояние кандидатов (2026-05-08)

| Кандидат | 1 | 2 | 3 | 4 | 5 | 6 | 7 | Итог |
|---|---|---|---|---|---|---|---|---|
| C2 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | **7/7** |
| C3 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | 7/7 |
| C6 | ⚠ (2 минус) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | 6/7 |
| D2 | ❌ (2 минус) | ❌ 44% | ✅ | ✅ | ✅ | ✅ | ✅ | 5/7 |
| 1.1.1 honest | ❌ | ⚠ | ✅ | ✅ | ✅ | ✅ | ❌ 4 ур. | 4/7 |
| VIC_EVOT (live) | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | 3/7 |

C2 уникальна — единственный кандидат с 7/7. Это и делает её #1.

## Связи

- [[strategy-c2-ob-6h-fvg-2h-pro-rr1]] — текущий champion
- [[strategy-1-1-1-honest-audit-failed]] — case study failed strategy
- [[lookahead-anchor-confirm-окно-cur_open-cur_close]] — критерий 5
- [[multi-bar-pattern-confirm-vs-trigger-lookahead]] — критерий 5
- [[bounce-1x-не-равно-wr-при-rr]] — почему не использовать прокси-метрики
