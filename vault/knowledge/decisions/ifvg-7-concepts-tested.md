---
tags: [decision, ifvg, strategies, empirical]
date: 2026-05-13
---

# iFVG: 7 концепций — что работает, что нет

Семь альтернативных подходов к использованию [[inverse-fvg-definition]], протестированы на BTC 2024-2026.

## Сводка

| # | Концепция | Результат | Урок |
|---|-----------|-----------|------|
| C1 | Failed iFVG (fade B, торговать в A direction) | +11R, WR 38% | ❌ Не работает |
| C2 | iFVG-against как anti-filter для 1.1.4 | СЮРПРИЗ | ⭐ Reversed — iFVG-against = POSITIVE сигнал |
| C3 | iFVG как TP target | SKIPPED | Требует кастомный simulator |
| C4 | iFVG count regime detector | n/a | ❌ Слишком редкие на 4h |
| **C5** | **FVG-A age filter (untouched >= 5 bars)** | **+0.46R/trade** | ✅ Лучшее улучшение 1.1.7 |
| C6 | iFVG-B + maxV-1d confluence | +10R, n=25 | Marginal |
| **C7** | **Breakout entry on iFVG c2 close (no retest)** | **+35R RR=2** | ✅ Альтернативная архитектура |
| C8 | Sequence patterns (chains of iFVG) | SKIPPED | Требует FSM |

## Детальные находки

### C1 — Failed iFVG: КОНЦЕПТ НЕ РАБОТАЕТ

Гипотеза: если iFVG-B сам не подтвердился (цена пробила обратно через B), это double inversion → fade B → trade in A direction.

Реальность:
- RR=1.5: +2R, WR 41%
- RR=2.0: +11R, WR 38%
- RR=2.5: +4R, WR 30%

**Вывод**: iFVG надёжно работает как continuation. Случаи double inversion редки и шумные. **НЕ ТОРГОВАТЬ против iFVG**.

### C2 — iFVG-against на 1.1.4: ПЕРЕВЁРНУТЫЙ результат

Гипотеза: если iFVG противоположного направления образовался до 1.1.4 LONG → skip (плохой сетап).

Реальность:
```
Baseline 1.1.4 (115 trades):           WR 64.3%, +107R, avg +0.93
WITHOUT iFVG-against (kept) n=99:      WR 62.6%, +87R,  avg +0.88
WITH iFVG-against (skipped) n=16:      WR 75.0%, +20R,  avg +1.25  ⭐
```

**iFVG-against = СИЛЬНЫЙ ПОЛОЖИТЕЛЬНЫЙ сигнал**, не anti-filter.

Объяснение: counter-direction structural break → mean-reversion в FVG-d работает сильнее. Когда уже была инверсия против нас, цена с большей вероятностью bounce-нёт обратно (наш 1.1.4 LONG ловит этот возврат).

⚠️ n=16 — малая выборка. Нужна replication на ETH/SOL и больших периодах перед утверждением.

### C4 — Regime detector не применим

iFVG count за 7 дней на BTC 2024-2026 4h: все trades имели count 0-3. Нет разнообразия для buckets. Concept НЕ применим на 4h. Может работать на 1h iFVG (детальная решётка), не тестировано.

### C5 — FVG-A age filter: ✅ Лучшее улучшение 1.1.7

Только iFVG где FVG-A была untouched >= N бар до touch:
| min_age | n | WR | Total R | avg R |
|---------|---|-----|---------|-------|
| 0 (baseline) | 99 | 39.4% | +37.5R | +0.38 |
| **5** | **72** | **41.7%** | +33R | **+0.46** |
| 10 | 56 | 39.3% | +21R | +0.38 |
| 20 | 36 | 36.1% | +9.5R | +0.26 |
| 50 (premium) | 29 | 44.8% | +16.5R | **+0.57** |

age >= 5 — balanced sweet spot.
age >= 50 — premium quality, малая выборка.

### C6 — maxV-1d confluence: marginal

Setups где entry в пределах 1 ATR-1h от maxV-1d: n=25, WR 40%, +10R. Не значимо лучше baseline.

### C7 — Breakout entry без retest: ✅ Альтернативная архитектура

Войти сразу на c2 close iFVG-B, SL под/над c1 импульс свечой:
| RR | n | closed | WR | Total R | avg R |
|----|---|--------|-----|---------|-------|
| 1.5 | 138 | 132 | 49.2% | +30.5R | +0.23 |
| **2.0** | **138** | **124** | **42.7%** | **+35R** | **+0.28** |
| 2.5 | 138 | 109 | 33.9% | +20.5R | +0.19 |
| 3.0 | 138 | 102 | 27.5% | +10R | +0.10 |

Все 0 bad years/3. Кандидат на **1.1.8 = iFVG breakout без retest**.

## Применение

1. **1.1.7 v2 = V2c (RR=2.5) + C5 (age>=5)** — улучшенная continuation cascade
2. **1.1.8 = C7** — альтернативная архитектура без retest, для live execution
3. **iFVG-against premium filter для 1.1.4** — n=16, нужна replication

## Связи

- [[inverse-fvg-definition]]
- [[strategy-1-1-7-ifvg-continuation]]
- [[2026-05-13-live-bot-vic-ifvg-strategies-117-118]] — session note
