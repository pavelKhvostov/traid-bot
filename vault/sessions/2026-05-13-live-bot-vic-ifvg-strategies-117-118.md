---
tags: [session, live-bot, vic-asvk, ifvg, strategy-1-1-6, strategy-1-1-7, bugfix]
date: 2026-05-13
---

# 2026-05-13 — Live-бот: новые сканеры, фиксы, ViC, iFVG концепции

Большая сессия охватившая 4 направления:
1. **Live-бот: добавлены 3 новых сканера** (1.1.2, 1.1.3, 1.1.6)
2. **Критические фиксы live-бота** (current-hour filter, race condition)
3. **ViC ASVK индикатор** — реализация в Python + forensic анализ
4. **Inverse FVG (iFVG)** концепция + стратегия 1.1.7

## TL;DR

- Live-бот теперь запускает **4 параллельных сканера**: 1.1.1 (с confluence) + 1.1.2 + 1.1.3 + 1.1.6 (новый гибрид)
- Найдены и исправлены **3 критических бага** в live-логике
- Реализован ViC ASVK с точным совпадением с Pine (TF=D, mlt=100, ref values совпали)
- ViC forensic на 1.1.4 BFJK: найден **+6pp WR filter** (|maxV-1d| > 1 ATR)
- Изучен **inverse FVG**: 31 iFVG за 48 дней на BTC 1h
- Прототип [[strategy-1-1-7-ifvg-continuation]]: +37.5R за 2.3y, 0 bad years, WR 39.4% @ RR=2.5
- Протестировано 7 разных концепций использования iFVG — 3 работают, 4 не работают

## Стратегия 1.1.6 — новая live

См. [[strategy-1-1-6-fvg-macro-immediate-htf-fvg]].

Гибрид 1.1.1 и 1.1.3:
- macro = FVG-4h/6h внутри OB-1d/12h (как 1.1.1)
- entry = immediate FVG того же ТФ что OB-htf (1h/2h) (как 1.1.3)
- entry=0.70, sl=0.35 sym, RR=2.2

Файлы:
- `strategies/strategy_1_1_6.py` — детектор (NEW)
- `multi_strategy_scanner.py` — общий live-сканер для 1.1.2/1.1.3/1.1.6
- `main.py` — обновлён, gather 4 scanners параллельно

## Live-бот: критические баги (исправлены)

См. [[multi-scanner-current-hour-filter]] и [[mark-sent-race-condition-4-scanners]].

### Bug #1 (CRITICAL): MAX_SIGNAL_AGE_HOURS=2 пропускал старые сигналы

Старая логика: `age = now - signal_time`, skip if age > 2h.

Проблема:
- signal_time = c2_OPEN бара (15m FVG), не c2_close
- Для 2h FVG свежий сигнал имел age=2h при WS-delay 100ms → age=2h+ε → silenced
- Для 15m FVG сигнал из ПРОШЛОГО часа (age=1.75h) проходил — слал "stale" signals

**Fix**: использовать `c2_CLOSE = signal_time + tf_duration` и проверять что попадает в текущий 1h-час (`current_hour_close - 1h < c2_close <= current_hour_close`).

### Bug #2 (MEDIUM): mark_sent race condition

`state.mark_sent()` делал load → modify → save без lock. 4 сканера через `asyncio.to_thread` могли терять записи в `sent_signals.json`.

**Fix**: `threading.Lock` в `state.py` вокруг `mark_sent`.

## ViC ASVK индикатор

См. [[vic-asvk-indicator-python]].

Реализация на основе Pine `Volume in Candle` с настройками `auto=true, mlt=100, prem=false`.

**LTF выбор по Pine формуле**:
- 1h chart: LTF=1m (rs=36 → max(60,36)=60s)
- 4h chart: LTF≈3m (rs=144s, closest valid)
- 1d chart: LTF=15m (rs=864s → from_seconds=15m)

**Reference сверка с TradingView** на BTC daily, auto=true, mlt=100:
| Дата | TV maxV | Python (LTF=15m) | Diff |
|------|---------|------------------|------|
| 2026-05-11 | 81080 | 81079.06 | -0.94 ✓ |
| 2026-05-12 | 80290 | 80290.00 | **0.00** ✓ |

Реализация: `vic_levels.calculate_vic_d(df_1m, day, ltf_minutes=15)`.

### Forensic ViC на 1.1.4 BFJK (115 сделок)

См. [[vic-asvk-as-filter-for-cascade-strategies]].

Лучший single-feature filter:
- **|maxV-1d distance| > 1 ATR-1h**: WR 70.6% vs baseline 64.3% (+6.3pp), avg +1.12R vs +0.93R
- Frac кепт: 59% сделок
- Логика: когда entry далеко от dominant volume zone → не "застревает" в institutional pin

Другие неподтверждённые гипотезы:
- delta_1h aligned → counter actually BETTER (но n=11, шум)
- divergence-1h → WR 88.9% но n=9, шум
- Best DUAL filter: ALL 4 testing concerns make this borderline at 10pp threshold

## Inverse FVG (iFVG) концепция

См. [[inverse-fvg-definition]].

**Определение**: iFVG = FVG противоположного направления, чьи свечи ПЕРВЫМИ перекрывают зону ранее untouched FVG.

```
FVG-A (bull) сформирована, untouched
  ↓ через N баров цена возвращается
FVG-B (bear, противоположная) формируется — её c0/c1/c2 ПЕРВЫЕ касаются A
  → B = inverse FVG
  → зона A инвертирована: была support, стала resistance
```

Статистика BTC 1h за 48 дней:
- 233 FVG всего (124 bull, 109 bear — баланс)
- 31 iFVG events (13.3% от всех FVG)
- Median delay A→touch: 3 бара, mean 20, max 307
- Balanced: 15 bull→bear iFVG, 16 bear→bull iFVG

Детектор: `research/elements_study/etap_93_inverse_fvg.py`.

## Strategy 1.1.7 — iFVG Continuation Cascade

См. [[strategy-1-1-7-ifvg-continuation]].

```
L1: iFVG на 4h (event = structural break)
L2: retest zone B
L3: OB-1h в направлении B, overlap zone B
L4: FVG-15m inside L3 + zone B
SL: external side of B + 0.5*B_width
allow_multi: 3
```

**Direction = B.direction** (continuation in inversion direction, NOT fade).

### Тюнинг — RR sweep на BTC 2024-2026

| Вариант | n | closed | WR | Total R | avg R | bad |
|---------|---|--------|-----|---------|-------|-----|
| V1 RR=2.0 baseline | 117 | 96 | 38.5% | +15R | +0.16 | 0/3 |
| V2 RR=1.5 | 117 | 91 | 49.5% | +21.5R | +0.24 | 0/3 |
| **V2c RR=2.5** | 117 | 99 | **39.4%** | **+37.5R** | **+0.38** | **0/3** ⭐ |

RR=2.5 > RR=2.0 потому что iFVG-continuation captures large structural moves.

### 7 концепций iFVG — что работает что нет

См. [[ifvg-7-concepts-tested]].

| # | Концепция | Результат | Урок |
|---|-----------|-----------|------|
| C1 | Failed iFVG (fade B) | +11R, WR 38% | ❌ **НЕ работает** — iFVG надёжная continuation |
| C2 | iFVG-against anti-filter на 1.1.4 | **СЮРПРИЗ ПЕРЕВЁРНУТЫЙ** | ⭐ iFVG-against = POSITIVE сигнал (WR 75% на n=16) |
| C4 | iFVG count regime | n/a | ❌ Слишком редкие iFVG на 4h для variation |
| **C5** | **age filter (>= 5 бар untouched)** | **+33R, +0.46R/trade** | ✅ **Best improvement to 1.1.7** |
| C6 | maxV-1d confluence | +10R, n=25 | Marginal |
| **C7** | **breakout entry no-retest** | **+35R RR=2, WR 42.7%** | ✅ Альтернативная архитектура |
| C3, C8 | TP target, sequence patterns | SKIPPED | Требуют большего кода |

### Финальный 1.1.7 v2 = V2c + C5

| | n | closed | WR | Total R | avg R | bad |
|---|---|--------|-----|---------|-------|-----|
| V2c baseline | 117 | 99 | 39.4% | +37.5R | +0.38 | 0/3 |
| **V2c + C5 age>=5** | **87** | **72** | **41.7%** | +33R | **+0.46** | **0/3** |

+21% avg R/trade, 0 bad years держится. Не утверждено пользователем.

### Сюрприз C2 — iFVG-against на 1.1.4

```
Baseline 1.1.4 BFJK (115 trades): WR 64.3%, +107R
WITHOUT iFVG-against (99 trades): WR 62.6%, +87R
WITH iFVG-against (16 trades):    WR 75.0%, +20R, avg +1.25R
```

iFVG-bear против 1.1.4 LONG = СИЛЬНЫЙ ПОЛОЖИТЕЛЬНЫЙ сигнал (не anti-filter). Объяснение: counter-direction structural break → mean-reversion в FVG-d работает сильнее.

n=16 малая выборка. Нужна replication на ETH/SOL и больших периодах.

## Открытые задачи

1. **Утвердить 1.1.7 v2** или V2c base (решение пользователя pending)
2. **Replication C2 surprise**: iFVG-against на 1.1.4 ETH/SOL
3. **1.1.8 = breakout entry (C7)** — альтернативная архитектура без retest
4. **Live-интеграция ViC filter B** для 1.1.4 BFJK (+6pp WR)
5. **Live-integration 1.1.7** — не выполнено, ждёт approval

## Связи

- [[strategy-1-1-6-fvg-macro-immediate-htf-fvg]]
- [[strategy-1-1-7-ifvg-continuation]]
- [[vic-asvk-indicator-python]]
- [[inverse-fvg-definition]]
- [[ifvg-7-concepts-tested]]
- [[multi-scanner-current-hour-filter]]
- [[mark-sent-race-condition-4-scanners]]
- [[vic-asvk-as-filter-for-cascade-strategies]]
- [[known-pitfalls]]
