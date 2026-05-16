---
tags: [strategy, 1-1-4, floating-tp, decision]
date: 2026-05-15
---

# Strategy 1.1.4 BFJK — Floating TP не применимо

## Краткий вывод

1.1.4 BFJK имеет baseline WR 64.3% — слишком высокий для floating TP.
Все 10 протестированных альтернатив автоследования (etap_115) **ухудшили**
PnL от baseline +107R до +35..+95R.

**Решение: keep baseline RR=2.0 на 1.1.4.** Floating exit здесь contraindicated.

## Проверенные альтернативы (BTC 6.3y, 115 closed)

| Variant | n | WR | PnL | Δ | Verdict |
|---|---:|---:|---:|---:|---|
| **Baseline RR=2.0** ★ | 115 | **64.3%** | **+107R** | — | optimal |
| A2: BE-ratchet @ +1.5R | 115 | 56.5% | +95R | −12R | wins protection cuts winners |
| G: TP-ext +0.25 cap=3 | 115 | 64.3% | +94R | −13R | extends some, loses on others |
| G2: TP-ext +0.5 cap=4 | 115 | 64.3% | +94R | −13R | **bad years 1→0** ★ |
| D: Strict score th=−0.7 | 115 | 60.9% | +90R | −17R | rare exits, still cuts wins |
| A: BE-ratchet @ +1R | 115 | 47.0% | +80R | −27R | aggressive BE cuts WR |
| E2: Lock-step cap=4 | 115 | 47.0% | +78R | −29R | bad years 1→0, but big PnL drop |
| E: Lock-step cap=3 | 115 | 47.0% | +75R | −32R | same problem |
| F2: ATR trail K=2.5 | 115 | 51.3% | +73R | −35R | fat-tail (top5 28%) |
| F: ATR trail K=2.0 | 115 | 50.4% | +42R | −65R | tight trail kills edge |
| C: Strict score th=−0.5 | 115 | 53.9% | +36R | −72R | too lenient threshold |

См. полную таблицу в [[2026-05-15-floating-tp-multi-symbol-c2-trendfilter]].

## Почему 1.1.4 НЕ хочет floating

| | 1.1.1 (45% WR) | 1.1.4 (64% WR) |
|---|---|---|
| Trades reach TP cleanly | редко | **часто** |
| Drawdown к TP | большой | мала |
| Score-exit интерпретация | catches reversal | cuts during normal vol |
| Floating effect | wins more often | misses TP that would have hit |

**Высокая baseline WR = trades статистически добегают до TP**. Любая
«защита» от drawdown = пропуск прибыли.

## Единственный приемлемый trade-off: G2

Если для тебя важна **robustness** (минимум bad years), G2 даёт компромисс:

| | Baseline | G2 |
|---|---:|---:|
| PnL | +107R | +94R |
| WR | **64.3%** | **64.3%** (сохранена!) |
| medR | +2.00 | +1.00 |
| **Bad years** | 1/7 | **0/7** ★ |

Логика G2: при touch +2R, если score > +0.5 (сильный bull для LONG) →
extend SL до +1R и продолжать до cap=4. Иначе — взять +2R.

Цена: −13R / 6.3y за **исключение единственного bad year (2025)**.

## Live integration

**Рекомендация**: 1.1.4 в live использовать с **fixed RR=2.0** (canonical).
НЕ добавлять score-exit.

Если хочется robust path — рассмотреть G2 как опцию.

## Универсальный закон

См. [[floating-tp-only-helps-low-wr-strategies]] — floating TP работает
только если baseline WR < 50%.

## Файлы

- `research/elements_study/etap_114_floating_1_1_4.py` — floating attempt (fail)
- `research/elements_study/etap_115_alternatives_1_1_4.py` — 10 alternatives audit

## Связи

- [[strategy-1-1-4-bfjk-portfolio]] — canonical baseline
- [[floating-tp-only-helps-low-wr-strategies]]
- [[4-indicator-momentum-score]]
- [[2026-05-15-floating-tp-multi-symbol-c2-trendfilter]]
