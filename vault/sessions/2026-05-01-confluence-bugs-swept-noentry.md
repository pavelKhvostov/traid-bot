---
tags: [session, strategy-1-1-1, rdrb, confluence, bugfix, swept, optimization]
date: 2026-05-01
related: [[strategy_1_1_1]], [[confluence-lookahead-and-rr22-bugs]]
---

# Сессия 2026-05-01: confluence-баги, swept-фильтр, no_entry оптимизация

Большая сессия — нашли 2 критичных бага в анализаторах confluence (которые
давали иллюзию edge), починили, переанализировали. Confluence не работает.
Зато нашли реальный фильтр SWEPT liquidity на OB-htf и доработали 3-stage
оптимизацию с no_entry проверкой.

## Что сделано

### 1. Live bot deploy на VPS

- Реализован `Strategy111Scanner` с WS Binance + TV refresh каждые 30 мин.
- Confluence-сообщения 🟢/🔴 в Telegram (по 1.1.1 / TOTALES / USDT.D / BTC1!).
- DNS-retry в `data_manager._get_with_retry` — backoff 2-32s × 5 попыток.
- `MAX_SIGNAL_AGE_HOURS=2` — стейл-сигналы не отправляются (бывает после
  рестарта когда prefill_silent не успел подтянуть всю историю).
- `message_id` tracking + `admin_delete_last.py` для удаления ошибочных
  рассылок у всех получателей (Telegram allows 48h).
- BTCUSDT only (убрали ETH/SOL).

### 2. **Найдены 2 бага в confluence-анализаторах**

См. отдельную заметку [[confluence-lookahead-and-rr22-bugs]].

**Баг #1:** PnL@RR=2.2 = `wins × 2.2 - losses`, где `wins/losses` из RR=1
симуляции. На RR=2.2 часть RR=1-побед откатывается в loss (цена прошла
+1R и развернулась). Завышение PnL@2.2 в 2-3 раза.

**Баг #2:** `daily_momentum_at` использовал `df.index <= day`, включая
свечу signal-day которая ещё не закрылась. Lookahead в среднем на 12 часов.

**Файлы с багами:**
- `analyze_1_1_1_confluence_macro.py`
- `analyze_rdrb_confluence_macro.py`
- `analyze_1_1_1_sync.py` (только Bug #1)
- `backtest_1_1_1_sl_on_htf.py` (только Bug #2)

**Аудит провели через 2 параллельных Agent'а** — каждый искал свой баг,
быстро дали конкретные snippets.

**Чисто (не имели багов):** `backtest_strategy_1_1_1.py`,
`backtest_strategy_rdrb.py`, `optimize_*.py`, `analyze_rdrb_winners_losers.py`.

### 3. Переанализ confluence после фикса — edge ИСЧЕЗ

| 1.1.1 7d Triple WR | До фикса | После |
|---|---|---|
| Triple confluence | 71.2% | **40.8%** |
| No-sync | 53.2% | 41.5% |
| Diff | +18pp | **−0.7pp** |

PnL@2.2 для Triple: было +75R, стало +21.8R (3.5× завышение).

**Confluence не даёт edge ни на одном lookback (1d, 3d, 7d).** Кружки 🟢🟢🟢
в Telegram декоративные — ничего не предсказывают. Всё было артефактом
двух багов.

### 4. **Новый рабочий фильтр — SWEPT liquidity на OB-htf**

Условие: `min(low_c1, low_c2) < min(low_c1-1, low_c1-2)` для LONG (зеркально
для SHORT). То есть OB-1h/2h пара ушла ниже двух предыдущих свечей —
классический SMC «liquidity grab» паттерн.

**На 144 deduped трейдах 1.1.1:**
- SWEPT: 115 (80%)
- NOT-SWEPT: 29 (20%)

| RR | Group | WR | PnL |
|---|---|---|---|
| 1.0 | SWEPT | 62.3% | +28R |
| 1.0 | NOT-SWEPT | 64.3% | +8R (тот же WR) |
| **2.2** | **SWEPT** | **44.2%** | **+47R** |
| **2.2** | NOT-SWEPT | 28.6% | **−2.4R** ⚠ |

**На RR=2.2 NOT-SWEPT убыточен.** Swept-фильтр единственный реально
работающий после фикса confluence-багов.

### 5. Новый параметр **no_entry** в симуляции

Если TP price достигнут ДО entry (цена ушла прямо к цели без retest'а
FVG) — сделка отменяется. Раньше такие случаи считались как «filled» —
неточно. С no_entry картина честнее.

**На 115 SWEPT трейдов: 66 (57%) `no_entry`** — больше половины setups
не дают возможности войти limit'ом по FVG.mid.

### 6. 3-stage оптимизация на SWEPT только

**Stage 1** (vary entry, SL=ob_htf edge, TP=TP_const):
- Best: **entry_pct=0.80** → 35W/14L/66 no_entry → WR 71.4%, +16.13R, avg_rr 0.87
- Тренд развернулся (vs без no_entry где best был entry=0.05)
- При no_entry shallow entry лучше — fillится чаще

**Stage 2** (entry=0.80, vary SL [ob_htf → fvg edge], TP=TP_const):
- Best: **sl_pct=0.85** → 27W/22L → WR 55.1%, **+59.78R**, avg_rr 3.43
- R/trade взлетел с 0.33 до **1.22** — тугой SL даёт огромный rr на победах
- Убыточная зона: sl_pct=1.00 (SL прямо у fvg.bottom) — почти все стопы

**Stage 3** (vary RR с фиксированными entry/SL) — не запускали в этой сессии.

## Финальный конфиг 1.1.1 (сейчас)

```
SWEPT filter ON
entry_pct  = 0.80   (shallow в FVG)
sl_pct     = 0.85   (близко к fvg.bottom для LONG, fvg.top для SHORT)
TP         = TP_const (цена при default entry=0.5, SL=ob_htf, RR=1)
no_entry   = ON (отмена если TP до entry)

Результат на 3y BTC:
  49 closed (из 115 SWEPT, остальные no_entry)
  WR 55.1%
  PnL +59.78R
  R/trade 1.22
  ~16 trades/year
```

## Файлы

**Новые в этой сессии:**
- `analyze_1_1_1_ob_swept.py` — split 1.1.1 deduped по swept liquidity
- `optimize_1_1_1_swept_stage1.py` — Stage 1 на SWEPT с no_entry
- `optimize_1_1_1_swept_stage2.py` — Stage 2 (vary SL)
- `admin_delete_last.py` — удаление последней рассылки у всех

**Изменены (фиксы багов):**
- `analyze_1_1_1_confluence_macro.py` — оба бага
- `analyze_rdrb_confluence_macro.py` — оба бага
- `analyze_1_1_1_sync.py` — Bug #1 (убрали wrong pnl@2.2)
- `backtest_1_1_1_sl_on_htf.py` — Bug #2 (lookahead)

**Live infra:**
- `strategy_1_1_1_scanner.py` — MAX_SIGNAL_AGE_HOURS, tv_refresh_loop
- `data_manager.py` — `_get_with_retry` для DNS-устойчивости
- `telegram_bot.py` — `last_broadcast.json` + `delete_last_broadcast()`
- `config.py` — `SYMBOLS=["BTCUSDT"]` (убрали ETH/SOL)

## Главные insights

1. **Не доверяй analyze-скриптам без аудита.** Два независимых бага
   создавали иллюзию edge от confluence. Спустя месяц работы и десятки
   решений на основе этих чисел — обнаружили только когда user описал
   симптом из внешнего источника.

2. **Анализаторы которые шортят симуляцию (умножая на множитель) — bug-prone.**
   Каждый RR должен симулироваться отдельно с реальной 1m проверкой.

3. **`<=` vs `<` в фильтрах по дате** — критично. День сигнала включает
   ту свечу которая ещё не закрылась. lookahead на 12+ часов.

4. **SWEPT liquidity** — реальный edge паттерн. OB-1h/2h должна «снять»
   ликвидность ниже/выше предыдущих 2 свечей. NOT-SWEPT убыточен @RR=2.2.

5. **no_entry — обязательная проверка для FVG-стратегий.** ~57% сетапов
   уходят к TP без retest'а — limit-вход не исполняется.

6. **С no_entry shallow entry > deep entry.** Был отскок — успели зайти.
   Не было — пропустили. Глубокий лимит чаще пропускается.

## Что дальше

- Stage 3 (vary RR) на SWEPT с entry=0.80, sl_pct=0.85 — посмотреть
  можно ли ещё увеличить PnL через нестандартный RR.
- Применить SWEPT-фильтр в live боте — отрезать NOT-SWEPT setups.
- Применить no_entry проверку в live — сделать настоящие limit-orders
  (или симулировать аналогичную логику в сканере).

## Связи

- [[confluence-lookahead-and-rr22-bugs]] — детали багов
- [[strategy_1_1_1]] — обновлён под новый swept+stage2 best config
