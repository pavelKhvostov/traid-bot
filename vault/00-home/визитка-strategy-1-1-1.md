---
tags: [home, card, strategy_1_1_1, prompt-template]
date: 2026-05-05
status: living-document
---

# 🎴 Визитка — Strategy 1.1.1 (для нового prompt'а сессии)

> Скопируй этот файл целиком как первое сообщение Claude в новой сессии.
> Он восстанавливает рабочий контекст по 1.1.1 за один проход без чтения всего vault.

---

## 📍 Что нужно прочитать ПЕРВЫМ (в этом порядке)

1. **`CLAUDE.md`** — правила проекта (тестирование, known-pitfalls, vault).
2. **`vault/00-home/index.md`** — карта vault.
3. **`vault/00-home/текущие приоритеты.md`** — что сейчас в работе.
4. **`vault/knowledge/debugging/known-pitfalls.md`** — 9 грабель проекта (правило CLAUDE.md).
5. **`vault/knowledge/strategies/strategy_1_1_1.md`** — spec 1.1.1.
6. **`research/1_1_1/README.md`** — эталон + список файлов research.
7. **Эта визитка** — закрепляет ключевые числа и противоречия.

После пунктов 1-7 спроси пользователя: «продолжить по [текущим приоритетам.md] / разобрать
противоречие sl_pct / другая задача?».

---

## 📐 1.1.1 в одном абзаце

Multi-TF nested OB+FVG воронка, **backtest-only**. 4 уровня × 2 ТФ = до 16 параллельных
путей: **OB-{1d|12h} → FVG-{4h|6h} → OB-{1h|2h} → FVG-{15m|20m}**. Вход = середина
entry-FVG, симуляция лимит-входа на 1m. Дедуп — bucketing 0.5% по SL с outcome-split.
Использует **canon OB/FVG** из [[универсальные определения OB и FVG]].

```
TOP (1d|12h)  →  MACRO-FVG (4h|6h)  →  HTF-OB (1h|2h, +SWEPT)  →  ENTRY-FVG (15m|20m)
                                                                          │
                                                          entry = mid FVG │
                                                          fill_scan на 1m │
                                                          no_entry если TP до entry
```

---

## 🏆 Эталонный конфиг (после 3-stage SWEPT optimize)

| Параметр | Значение | Источник |
|---|---|---|
| SWEPT-фильтр | ON | check `min(c1,c2 lows) < min(prev1,prev2 lows)` для LONG |
| entry_pct | **0.80** | Stage 1 best |
| sl_pct | **0.40 в коде / 0.35 в vault** ⚠ ПРОТИВОРЕЧИЕ | Stage 2 ручной выбор «по запросу» (не max pnl) |
| no_entry | ON | TP до entry → отмена |
| RR | **2.2** | Stage 3 best |

**3y BTCUSDT:** 115 SWEPT-групп → 53 no_entry → **62 closed (34W / 28L)** →
**WR 54.8%, +46.8R, R/trade 0.755**. ~16 trades/year.

Валидировано: BTC only. ETH/SOL не зафиксированы. Walk-forward не делали.

---

## 🔬 Трёхстадийная оптимизация — суть

Поэтапный sweep вместо 3D grid: каждая стадия отвечает на отдельный вопрос
с фиксацией остальных через **`TP_const`** (TP при default entry=mid, SL=ob_htf, RR=1).

| Stage | Файл | Цель | Grid | Best |
|---|---|---|---|---|
| **1** | `research/1_1_1/optimize/optimize_1_1_1_swept_stage1.py` | куда входить в FVG | entry_pct ∈ [0..1.0] / 0.05, SL=ob_htf, TP=TP_const | **entry=0.80**, WR 71.4% / +16R / avg_rr 0.87 |
| **2** | `research/1_1_1/optimize/optimize_1_1_1_swept_stage2.py` | как туго ставить SL | sl_pct ∈ [0..1.0] / 0.05 в коридоре `[ob_htf → fvg edge]` | sl_pct=**0.85** дал +59.78R, **финал=0.40** ручной выбор |
| **3** | `research/1_1_1/optimize/optimize_1_1_1_swept_stage3.py` | как далеко вести TP | RR ∈ [1.0..6.0] / 0.1 | **RR=2.2**, WR 54.8% / +46.8R / R/t 0.755 |

Целевая функция везде — `max pnl_r`. **Защит от overfitting (walk-forward / OOS / cross-symbol) НЕТ.**

`optimize_1_1_1_3stage.py` — старая версия БЕЗ SWEPT и no_entry, не эталон.

---

## ⚠️ Топ-5 уроков (грабли, найденные на 1.1.1)

1. **Look-ahead `+15min` хардкод для fill-scan.** Для 20m-FVG сканировал на 5 мин раньше закрытия c2. Геометрически оказался теоретическим (entry=mid вне c2 диапазона). Защитный фикс: `tf_minutes` из `sig["fvg_tf"]`. См. [[strategy-1-1-1-look-ahead-15min-vs-tf_duration]].
2. **Confluence Bug #1 — `pnl@RR2.2 = wins×2.2 − losses`.** Множитель вместо симуляции завышал PnL@2.2 в 2-3×. Triple confluence WR 71% → реальные 41%. Каждый RR симулировать отдельно. См. [[confluence-lookahead-and-rr22-bugs]].
3. **Confluence Bug #2 — `df.index <= day` в `daily_momentum_at`.** Дневная свеча с `index == day` ещё не закрылась. Lookahead в среднем 12 ч. Daily Binance индексирует по open_time → внутри дня используй `<`, не `<=`.
4. **`round(x, N)` ≠ tolerance.** Для bucketing близких SL — sort+merge с явным threshold + outcome-split. См. [[strategy-1-1-1-dedup-bucketing-tolerance]].
5. **Разные SL на одной (signal_time, entry) = разные трейды**, не дубли. Dedup-ключ расширен на SL. Кейс 2026-02-06. См. [[strategy-1-1-1-разные-sl-на-одном-entry]].

---

## 🤔 Открытые противоречия (проверить в начале сессии!)

1. **`sl_pct`: код=0.40 vs vault=0.35.** [optimize_1_1_1_swept_stage3.py:40](../../research/1_1_1/optimize/optimize_1_1_1_swept_stage3.py#L40) хардкодит `SL_PCT = 0.40` с комментарием «по запросу пользователя». Vault везде пишет 0.35. **Числа эталона +46.8R получены при 0.40** — vault, скорее всего, опечатка. Прогнать Stage 3 и сверить.
2. **«115 closed = 34W/28L/53 noentry»** — формулировка путаная. Реально closed = 62 (W+L), 115 = «всех после SWEPT-фильтра». Поправить в vault.
3. **Почему выбрано sl_pct=0.40, а не Stage 2 max=0.85?** Решение нигде не задокументировано — пробел в decision-заметках.

---

## 🚧 Открытые задачи на 1.1.1

- **ETH/SOL прогон** через `analyze_1_1_1_swept_multi_asset.py` — скрипт есть, vault-результата нет.
- **Live deployment** SWEPT-эталона. В live сейчас работает **до-SWEPT** версия (`strategy_1_1_1_scanner.py` + `strategy_1_1_1_confluence.py` в корне репо, BTCUSDT only, MAX_SIGNAL_AGE_HOURS=2). Нужно интегрировать SWEPT-фильтр + no_entry-симуляцию.
- **Аудит lookahead-паттерна** `df.index <= day` в analyze-скриптах 1.1.1 после Andrew'ского fix'а в 1.1.2 (commit `78d4302`, 2026-05-05).
- **Walk-forward / OOS validation** — не делали ни разу.

---

## 🔗 Семейство версий

- **1.1.1** — macro-**FVG**. Эталон (этот файл).
- **1.1.2** — macro-**OB** вместо macro-FVG. Stage3 RR=2.2: WR 44% / +101R / 241 closed (больше сигналов, ниже WR).
- **1.1.3** — entry-FVG того же ТФ что OB-htf. Слабее: stage3 RR=2.2 +11R. Параметр `macro_mode={untouched|extended|baseline}` (Andrew, 2026-05-05).
- **1.1.4** — гибрид (macro-FVG из 1.1.1 + entry-immediate из 1.1.3). WIP.
- **1.2.0** — другая идея (EMA-200 + sweep + FVG-15m). Tuning, отрицательный edge.

`detect_strategy_1_1_3_signals` импортирует `collect_valid_macro_obs` из 1.1.2 — единственный cross-import между версиями.

---

## ❌ Что НЕ делать в этой сессии

- Не запускать оптимизаторы без явной просьбы — они тянут 1m данные за 3 года.
- Не править `signals/` (gitignored, локальные артефакты).
- Не возвращаться к **`round()` как tolerance** или **множителю на RR** — урок усвоен.
- Не использовать `df.index <= today` для дневных фильтров — всегда `<`.
- Не интегрировать новую логику в live без re-baseline в research/.
- Не добавлять метрики/фильтры без аудита analyze-скриптов через backtest-auditor agent.

---

## 🛠 Команды для быстрой ориентации

```bash
git log --oneline -20            # последние коммиты
git status                       # изменения
ls research/1_1_1/optimize/      # 6 optimize-скриптов
./venv/bin/python -m pytest tests/ -v   # 39 тестов должны быть зелёные
tail -50 state/bot.log           # если бот запущен локально
```

Прогон эталона:
```bash
./venv/bin/python research/1_1_1/optimize/optimize_1_1_1_swept_stage3.py
```

---

## 📚 Полная карта документов 1.1.1

**Spec:** [[strategy_1_1_1]]
**Decisions:** [[strategy-1-1-1-rr-sweet-spot]] (superseded), [[strategy-1-1-1-sl-15-percent]] (superseded), [[strategy-1-1-1-dedup-результаты-3y]]
**Debugging:** [[strategy-1-1-1-look-ahead-15min-vs-tf_duration]], [[strategy-1-1-1-почему-20m-фикс-нулевой-эффект]], [[strategy-1-1-1-dedup-bucketing-tolerance]], [[strategy-1-1-1-разные-sl-на-одном-entry]], [[confluence-lookahead-and-rr22-bugs]]
**Sessions:** [[2026-04-28-strategy-1-1-1-multi-htf-multi-ltf]], [[2026-04-29-strategy-1-1-1-sl-15-rr-optimizer]], [[2026-05-01-confluence-bugs-swept-noentry]], [[2026-05-04-рефакторинг-research-1-1-x]]
**SMC canon:** [[универсальные определения OB и FVG]], [[что такое order block]], [[что такое fvg]]
**Code:** `strategies/strategy_1_1_1.py`, `research/1_1_1/{backtest,optimize,analyze}/`, `tests/test_strategy_1_1_1.py`
