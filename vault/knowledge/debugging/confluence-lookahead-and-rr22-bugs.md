---
tags: [debugging, confluence, lookahead, rr-multiplier, analyze-scripts]
date: 2026-05-01
related: [[2026-05-01-confluence-bugs-swept-noentry]]
---

# Confluence-анализаторы: 2 бага которые давали иллюзию edge

Найдено 2026-05-01 после внешнего описания симптома пользователем.
Оба бага существовали > месяца, на их основе делались выводы про "tripple
confluence работает". После фикса edge исчез.

## Bug #1 — PnL@RR=2.2 = wins × 2.2 − losses

### Симптом

В `stats()` функциях анализаторов:

```python
def stats(rows):
    closed = [r for r in rows if r["outcome"] in ("win", "loss")]
    wins = sum(1 for r in closed if r["outcome"] == "win")
    losses = len(closed) - wins
    return {
        "pnl_rr1": wins - losses,
        "pnl_rr2.2": wins * 2.2 - losses,   # ← БАГ
    }
```

Outcomes загружались из CSV симулированного на RR=1. Затем для отчёта
RR=2.2 просто домножали `wins × 2.2 − losses`.

### Почему это неправильно

На RR=2.2 часть RR=1-побед откатывается в loss:
- Сетап симулирован на RR=1 → win (цена прошла +1R, дошла до TP_RR1)
- На RR=2.2 TP дальше, цена прошла +1R → потом развернулась → выбила SL
- Это уже LOSS на RR=2.2, не win.

Реально на RR=2.2 побед существенно меньше (примерно −30% к RR=1).
Поражений больше. Множитель `× 2.2` усугублял ошибку.

Эффект: PnL@2.2 завышался **в 1.5-3 раза** по всем группам сразу. Главное
— равномерно по группам, поэтому дельта между триплет/no-sync сохраняла
относительные пропорции, но абсолютные значения были ложью.

### Файлы с багом

- `analyze_1_1_1_confluence_macro.py` (стр. 87)
- `analyze_1_1_1_sync.py` (стр. 124-125)
- `analyze_rdrb_confluence_macro.py` (стр. 69)

### Файлы без бага

- `backtest_strategy_1_1_1.py` — `RR_RUNS = [(1.0, ...), (2.2, ...)]`
  с раздельной симуляцией.
- `backtest_strategy_rdrb.py` — то же.
- `analyze_rdrb_winners_losers.py` — фиксированный RR=2.2 + локальная
  симуляция.

### Фикс

Загружать ОБА CSV (RR=1 и RR=2.2), для каждой группы считать pnl_rr1
из rr1-outcomes, pnl_rr2.2 из rr2.2-outcomes. Никаких множителей.

## Bug #2 — daily_momentum lookahead через `<= day`

### Симптом

```python
def daily_momentum_at(df_1d, ts, lookback_days):
    day = ts.normalize()                     # 00:00 UTC того же дня
    prev_day = day - pd.Timedelta(days=lookback_days)
    close_now = df_1d[df_1d.index <= day]    # ← БАГ: включает свечу signal-day
    close_prev = df_1d[df_1d.index <= prev_day]
    delta = close_now["close"].iloc[-1] - close_prev["close"].iloc[-1]
```

`day = ts.normalize()` = 00:00 UTC дня сигнала. Daily-свеча Binance
индексируется по open_time = 00:00 UTC. Свеча с `index == day`
**открылась в 00:00 этого дня** и **закрывается в 00:00 следующего**.

Если сигнал в 23:55 UTC, `day = 00:00 того же дня`, свеча `index == day`
ещё не закрылась (5 минут до закрытия). Но `<= day` её включает.

`close_now["close"].iloc[-1]` — это close свечи signal-day, которая
известна только в конце дня. Использование = подсматривание в будущее.

### Эффект на confluence

Анализатор определял "куда движется TOTALES" используя close
**сегодняшней (незакрытой) свечи**. Это означает что на момент сигнала
направление уже было известно "из будущего".

Итог: Triple confluence группа набирала "правильные" сделки задним
числом — те где TOTALES к концу дня действительно ушёл в нужную сторону.
WR Triple был завышен.

В среднем lookahead = 12 часов. На 17% сигналов = день и больше.

### Файлы с багом

- `analyze_1_1_1_confluence_macro.py` (стр. 53-73)
- `analyze_rdrb_confluence_macro.py` (стр. 44-55)
- `backtest_1_1_1_sl_on_htf.py` (стр. 46-56) — копипаста хелпера

### Файлы без бага

- `backtest_vic_evot.py` (стр. 144) — `df.index < D` с комментарием
  «no look-ahead» — было осознанным паттерном
- `backtest_vic_bos.py` (стр. 287) — `df.index < D`
- `backtest_strategy_rdrb_premium.py` — `df.index < rdrb_trigger`

Существование правильных примеров доказывает что confluence-баг —
**локальная регрессия**, не общий стиль.

### Фикс

`<= day` → `< day` и `<= prev_day` → `< prev_day`. Берём только свечи
которые УЖЕ закрылись до сигнала.

## До и после фикса (Strategy 1.1.1, 7d lookback, Triple confluence)

| Метрика | Buggy | Fixed |
|---|---|---|
| Triple WR | 71.2% | 40.8% |
| No-sync WR | 53.2% | 41.5% |
| **Diff WR** | **+18pp** | **−0.7pp** |
| Triple PnL@2.2 | +75.4R | +21.8R |
| No-sync PnL@2.2 | +54.2R | +21.4R |

После фикса edge от Triple confluence **отсутствует**. Совпадение или
не совпадение макро-источников с BTC сигналом не предсказывает исход.

## Уроки

1. **Аудит analyze-скриптов перед публикацией результатов.** Эти баги
   выглядят локальными, но влияют на ключевые decision points
   (включать ли confluence в live, отдавать ли подписчикам кружки).

2. **Множители вместо симуляции — bug pattern.** При желании показать
   PnL на разных RR — симулируй каждый RR отдельно. Не множь wins.

3. **`<=` vs `<` для свечей по дате — серьёзно.** Daily свечи
   индексируются по open_time, закрываются на следующий день. Любое
   сравнение `index <= today_open` в момент signal'а внутри дня = lookahead.

4. **Копипаста хелперов растаскивает баги.** `daily_momentum_at` существует
   в 3 файлах с одинаковым багом. Лучше было бы вынести в общий util.

## Связи

- [[2026-05-01-confluence-bugs-swept-noentry]] — сессия с детальным разбором
- [[lookahead-bug-в-vic-evot-backtest]] — другой lookahead кейс из истории
