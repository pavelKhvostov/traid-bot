---
tags: [debugging, multi-shot, inflation, dedup, pitfall]
date: 2026-05-15
---

# Multi-shot detector добавляет 1.7-2.3× duplicate inflation

## Что было

Multi-shot detector framework (etap_98 для 1.1.1, etap_109 для 1.1.2)
собирает **все** (OB-htf, entry-FVG) пары в каждой macro-зоне, а не
только earliest. Это нужно для retry-after-SL анализа и floating TP audit.

Без дедупа `(signal_time, direction, entry)` число trades **завышено
в 1.7-2.3×** относительно реальной торговли с дедупом на уровне entry.

## Симптом

Cтpaтeгия 1.1.2 BTC 6.34y multi-shot baseline отчитала **+726R** на
**2157 closed trades**. Пользователь усомнился. После funnel audit:

| Layer | Count |
|---|---:|
| Raw signals from multi-shot | 3907 |
| Unique `(signal_time, direction, entry)` | 1702 |
| Closed after no_entry filter | 2157 |
| **Unique closed** после полного дедупа | **968** |

Inflation factor: **2.23×**. Реальный baseline после дедупа: **+315R** (vs +726R).

## Причина

В 1.1.2 (и 1.1.1) один top-OB может содержать **много macro candidates**:

- 4h-баров в 1d-баре = 6 штук → ~3-5 OB-пар
- 6h-баров в 1d-баре = 4 штуки → ~2-3 OB-пар
- top-OB генерирует **5-15 macro-OB кандидатов**
- Каждый macro-OB ищет ОДИН и тот же entry-FVG в дочерней OB-htf зоне

Многие производят **тот же** `(signal_time, direction, entry)`. В multi-shot
все считаются отдельно.

Максимум duplicates на entry для 1.1.2 BTC: **14 раз!**

## Inflation factors per strategy

| Strategy | n raw multi-shot | n dedup | Inflation |
|---|---:|---:|---:|
| 1.1.1 SWEPT | 677 | 200 | **1.83×** |
| **1.1.2 no SWEPT** | **2157** | **968** | **2.23×** |

1.1.2 имеет больший inflation чем 1.1.1 потому что:
- Нет SWEPT фильтра (1.1.1 SWEPT убивает ~50% setups, меньше остаётся для дублей)
- Macro OB более частый чем macro FVG (3-bar pattern rarer)
- 12h top + 1d top пересекают часто → один entry от обоих

## Правило избегания

1. **При сравнении PnL multi-shot vs canonical detector** — учитывать
   inflation factor. Multi-shot НЕ воспроизводит canonical-числа (CLAUDE.md).

2. **Multi-shot OK для relative comparison** (baseline vs floating) если оба
   используют ту же multi-shot выборку — uplift % corrected.

3. **Для абсолютных live-expectations** — применить дедуп
   `(signal_time, direction, round(entry, 2))`.

4. **Sanity check**: canonical 1.1.2 stage3 = 241 closed @ 3y → ~480 на 6y.
   Multi-shot 2157 ÷ 480 = **4.5×**, что разлагается на:
   - Multi-shot inflation 2.23×
   - + canonical-vs-multi-shot 2.0× (от различий dedup ключа)

## Когда multi-shot полезен

- **Retry-after-SL анализ** — нужно знать ВСЕ возможные OB-htf пары
- **Floating TP comparison** — оба варианта используют ту же выборку,
  uplift в R-числах сравним
- **Sensitivity analysis** — посмотреть зависимость от dedup level

## Когда multi-shot вводит в заблуждение

- **Абсолютная цифра PnL для live-expectations** — ÷2 для реальной
- **Сравнение с canonical numbers** из CLAUDE.md — несравнимо без коррекции

## Реальные live-expectations 1.1.2 после дедупа

| Symbol | Multi-shot floating | Dedup floating (real) |
|---|---:|---:|
| BTC 6y | +1016R | ~+456R |
| ETH 6y | +1018R | ~+467R |
| SOL 6y | +727R | ~+330R |
| **Total** | +2761R | **~+1253R** |

Зависит от того, дублирует ли trader конвергентные Telegram-сигналы.

## Источник

[[2026-05-15-floating-tp-multi-symbol-c2-trendfilter]] — etap_110 funnel audit.

## Связи

- [[etap-42-instant-fill-3-7x-inflation]] — параллельный класс инфляции
- [[strategy-1-1-1-floating-tp-final]]
- [[strategy-1-1-2-floating-tp-final]]
