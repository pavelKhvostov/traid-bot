---
tags: [decision, bulkowski, pattern-selection, ml-pivot]
date: 2026-06-03
status: chosen
---

# Top-12 Bulkowski reversal-паттернов для BTC 12h ML

Из 75 chart-pattern глав 3rd-ed. Encyclopedia of Chart Patterns выбраны 12 наиболее
edge-богатых reversal-паттернов для имплементации детекторов в [[etap_172]].

## Критерии отбора

1. **Reversal**, не continuation (исключены flags, pennants, triangles ascending/descending не-как-reversal).
2. **Daily/intraday scale** — исключены weekly-only паттерны (Horn Top/Bottom, Pipe Top/Bottom). Хотя они #1 по edge в книге, на BTC 12h интервал «1 неделя = 14 баров» делает их неотличимыми от обычных swing-паттернов.
3. **Не Fibonacci-based** (исключены Bat, Butterfly, Crab, Gartley, AB=CD — Bulkowski даёт им малое sample size).
4. **Метрики Bulkowski**: top-10 by lowest failure rate (master Statistics Summary, p.~1561).
5. **Реализуемость на 12h без HTF lookups** — паттерн полностью описывается геометрией на одном TF.

## Финальная выборка

### Long (7)

| Паттерн | Bulkowski rank | Avg rise | Fail % | Почему выбран |
|---|---|---|---|---|
| **BARR Bottom** (Bump-and-Run Reversal Bottom) | **1/39** | +55% | 9% | Best long-reversal в книге. Lead-in downtrend + accelerated bump |
| **Rounding Bottom** | 7/39 (bull), **1/20 (bear)** | +48% (bull), +37% (bear) | **4.3%** (best!) | Самый низкий fail rate. Лучший паттерн в bear regime |
| **Cup with Handle** | 3/39 | +54% | 5.3% | #2 fail rate. Канонический trend continuation/reversal hybrid |
| **Big W** | 11/39 | +46% | 9.3% | Twin bottom с tall left side. Часто встречается |
| **DB Eve&Eve** (Double Bottom rounded) | 5/39 | +50% | 12% | Классический "W" без spike. Top-5 в книге |
| **H&S Bottom** (Inverse H&S) | 13/39 | +45% | 11% | Канонический 3-valley reversal |
| **V-Bottom** | — | +27-32% (depends on extension) | 14-18% | Sharp reversal — характерен для крипты |

### Short (6)

| Паттерн | Bulkowski rank | Avg decline | Fail % | Почему выбран |
|---|---|---|---|---|
| **BARR Top** | **1/36** | -17% | 14% | Best short-reversal. Mirror of BARR Bottom |
| **Big M** | 2/36 (best by fail) | -17% | 14% | Twin top с tall left rise. Самый частый short-сигнал |
| **H&S Top** | 4/19 bear (**5% fail**) | -16% bull / -24% bear | 19% / 5% | Best fail rate в bear. **Bonus: busted +67%** (top edge во всей книге) |
| **Diamond Top** | 3/36 | -17% | 15% | Broadening → narrowing top |
| **V-Top** | — | -20% | 17% | Sharp short reversal |
| **Triple Top** | — | -15% | 26% | Сам по себе так-себе, но **busted single → +60%** (single-bust ratio 67%) |

## Что НЕ выбрано и почему

| Паттерн | Причина исключения |
|---|---|
| Horn Top/Bottom | Weekly-only (1 неделя = 14 баров на 12h, теряется смысл) |
| Pipe Top/Bottom | То же — weekly scale |
| Gartley/Bat/Butterfly/Crab/AB=CD | Fibonacci-harmonic, требуют точных XABCD ratios, sample size слишком мал |
| Broadening Top/Bottom | Чаще continuation в живых рынках, ranks 22-28 |
| Symmetrical Triangle | Worst frequency-adjusted (32-48% bust rate, ranks 34-36) |
| Roof / Inverted Roof | Bulkowski "считал убрать из книги" — ранги 35-37/39 |
| Island Reversal | Worst в bear (rank 20/20). На крипте 12h гэпы редки |
| Wolfe Wave | Малый sample size, требует XABCD-like geometry |
| Three Falling Peaks / Three Rising Valleys | Mid-rank, дублируют Triple Top/Bottom |

## Дополнительная фича — busted patterns

См. master stats:
- **H&S Top single-bust** → **+67%** (best busted edge в книге, single-bust ratio 80%)
- **Triple Top single-bust** → +60%
- **Rect Bottom single-bust** → +68%
- **DT Eve&Eve single-bust** → +54%

В etap_172 это пока не реализовано как отдельная фича — в etap_173 планируется добавить:
- `<pattern>_busted_recent`: паттерн закрылся в обратную сторону за N баров

## Источники

- [[2026-06-03-bulkowski-12-reversal-detectors-etap-172]] — текущая сессия
- `research/elements_study/refs/bulkowski_master_stats.md` — консолидированная справка
- Bulkowski "Encyclopedia of Chart Patterns" 3rd Ed. (2021)
