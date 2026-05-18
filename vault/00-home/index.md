---
tags: [home, index]
date: 2026-04-29
---

# ASVK Power Zone — Knowledge Vault

Граф знаний проекта. При старте сессии Claude Code читает этот файл и
[[текущие приоритеты]], а затем переходит к нужным разделам по ссылкам.

## Главное

- [[архитектура проекта flat layout]] — реальная структура (без `src/`), 7 стратегий, точки входа.
- [[стек и зависимости]] — Python 3.13, pandas, websockets, requests.
- [[структура CSV]] — `data/<SYMBOL>_<TF>.csv`, native vs composed ТФ.

## Свежее (2026-05-15) — Floating TP framework, multi-symbol audit, C2 trend filter

См. [[2026-05-15-floating-tp-multi-symbol-c2-trendfilter]] — большая сессия:
- [[4-indicator-momentum-score]] — Hull + MH + RSI + ASVK композитный score
- [[floating-tp-only-helps-low-wr-strategies]] — главный эмпирический закон
- [[strategy-1-1-1-floating-tp-final]] — per-symbol config: BTC/ETH 4.5/-0.25/2, SOL 3.5/0/1 → +35% PnL
- [[strategy-1-1-2-floating-tp-final]] — universal 4.5/0/2 → +31% PnL
- [[strategy-1-1-4-floating-tp-not-applicable]] — 1.1.4 high-WR не любит floating
- [[strategy-1-1-5-multipath-floating-tp]] — 1.1.5 multi-path + F6 + floating: +31R на 24 trades (research only, канон лучше)
- [[strategy-wicked-fractal-ob-d-btc-only]] — Wicked+Fractal OB-D: **7 OOS-validated variants** — B (146/+80R/0 bad), C (513/+129R/1 flat-bad), **H (461/+149.9R/best PnL)**, E (159/+91.6R), F (Asia 150/+60.7R), D (68/+48.8R/best R/tr), Tier-1 (22 BTC, OOS WR 88.9%)
- [[что такое snr]] — Support aNd Resistance, классический S/R концепт (НЕ в книге ICT)
- [[2026-05-18-wicked-ob-variants-rdrb-snr]] — session с полным семейством wicked OB + RDRB зоны V1/V2/V3 + SnR
- [[c2-ema-or-hull6h-trend-filter-winner]] — per-symbol: BTC/SOL OR, ETH AND
- [[etap-42-instant-fill-3-7x-inflation]] — pitfall execution model
- [[multi-shot-detector-2.3x-inflation]] — pitfall duplicate counting

## Live стратегии (с 2026-05-13)

В live запущены 4 параллельных сканера через `asyncio.gather` в `main.py`:

- **Strategy 1.1.1** (с confluence): OB-{1d,12h} + FVG-{4h,6h} → OB-{1h,2h} (SWEPT) + FVG-{15m,20m}. entry=0.80, sl=0.35 sym, RR=2.2. См. [[strategy_1_1_1]].
- **Strategy 1.1.2**: OB-{1d,12h} + OB-{4h,6h} → OB-{1h,2h} + FVG-{15m,20m}. entry=0.70, sl=0.35 sym, RR=2.2. `research/1_1_2/`.
- **Strategy 1.1.3**: OB-{1d,12h} + OB-{4h,6h} → OB-{1h,2h} + FVG того же ТФ. macro_mode=untouched. entry=0.70, sl=0.35 sym, RR=2.2.
- **Strategy 1.1.6** (NEW гибрид, см. [[strategy-1-1-6-fvg-macro-immediate-htf-fvg]]): OB-{1d,12h} + FVG-{4h,6h} → OB-{1h,2h} + FVG того же ТФ. entry=0.70, sl=0.35, RR=2.2.

См. [[2026-05-13-live-bot-vic-ifvg-strategies-117-118]] — добавление в live.

## Disabled live стратегии (в коде, не запущены)

- [[s1 obx4 + ob1h]], [[s2 ob htf + ob1h]], [[s3 rdrb + ob1h]], [[s4 снятие фрактала]],
  [[s5 fvg + ob1h]], [[hammer молот плюс фрактал плюс ob]], [[marubozu тело 95 процентов]] — old STRATEGY_TFS family
- [[vic_evot]] — VIC level + LL/HH-fractal + FVG на 15m

## Backtest-only стратегии (не в live)

- [[vic_bos]] — VIC уровень + BOS на 3m (quadruple H-L-H-L). 3y +37R на BTC.
- [[strategy_1_1_1]] — OB-{1d,12h} + FVG-{4h,6h} → OB-{1h,2h} + FVG-{15m,20m}.
  3y BTC raw RR=1.0: 144, WR 61.7%, +33R. После 3-stage SWEPT optimize @ RR=2.2:
  115 closed, WR 54.8%, +46.8R, R/trade 0.755. Файлы: `research/1_1_1/`.
- **Strategy 1.1.2** — macro-OB вместо macro-FVG. Stage 3 @ RR=2.2: WR 44.4%, +101.4R на 241 closed. Файлы: `research/1_1_2/`.
- **Strategy 1.1.3** — entry FVG того же ТФ что OB-htf. Слабее 1.1.1: stage3 @ RR=2.2 +11.4R. Файлы: `research/1_1_3/`.
- **Strategy 1.1.4** — мульти-цепочечный каскад FVG-d/12h → OB-4h/6h → OB-1h/2h → FVG-15m/20m. **Portfolio B+F+J+K (2026-05-11)**: WR 64.3%, +107R, +0.93R/trade, 6.3y, 0 bad years 2020-2024+2026 (2025 bad). См. [[strategy-1-1-4-bfjk-portfolio]]. Файлы: `research/elements_study/etap_74_*` + `research/1_1_4/`.
- **Strategy 1.1.5** — 1d-фрактал → 4h/6h sweep+OB в окне `[sweep, sweep+k]` → 1h/2h OB + 15m/20m FVG. Только детектор зон, бэктест-обвязка TBD.
- [[strategy-1-1-7-ifvg-continuation]] — iFVG (4h) → OB-1h → FVG-15m, continuation in B direction. V2c RR=2.5: WR 39.4%, +37.5R, **0 bad years** (BTC 2024-2026). С age>=5 filter: +0.46R/trade. Prototype, not approved.
- **Strategy 1.2.0** — новая ветка: EMA-200 + sweep + FVG-15m. В стадии tuning. Файлы: `research/1_2_0/`.
- **Strategy 3.2** — FVG-4h → 2 свечи rejection → FVG-1h в 8h окне. Entry=mid FVG-1h, SL=c0(low/high), RR=1. 3y BTC: 245 closed, WR 55.1%, +25R.

## Research-стенд

- `research/README.md` — обзор всех research-веток.
- `research/1_1_1/README.md` — эталонная конфигурация Strategy 1.1.1 + список файлов.
- Также есть `research/rdrb/` (5 кандидатов на расширение live RDRB) и `research/vic/` (out-of-scope).
- Phase 1 baseline metrics: `vault/baseline/2026-05-04-14-16/metrics.md` + `optimized-baselines.md`.
- Phase 4 re-baseline diff: `vault/baseline/2026-05-04-16-37-after-refactor/diff.md` (refactor чистый, все 22 CSV хеша совпадают).

## Индикаторы

- [[asvk-custom-rsi]] — авторский Pine: amplified RSI + адаптивные OB/OS + NWE-канал + 4 типа дивергенций. Python-реализация в `research/asvk_rsi/`.
- [[money-hands-asvk]] — авторский Pine: WaveTrend bw2 + цветовая state machine + HA Money Flow + двойной Stochastic + дивергенции. Python-реализация в `research/money_hands/`.
- [[asvk-trend-line-hull]] — авторский Pine: Hull MA в 3 модах (HMA/EHMA/THMA) с 2-bar shift band и trend-coloring. Default len=49·1.6=78. Python-реализация в `research/asvk_trend_line/`.
- [[vic-asvk-indicator-python]] — Volume in Candle (ViC ASVK). LTF auto-select по Pine формуле (D=15m, 1h=1m). Сверка с TV exact. См. [[vic-asvk-as-filter-for-cascade-strategies]] — фильтр |maxV-1d|>1 ATR даёт +6pp WR на 1.1.4 BFJK.

## SMC-примитивы

- [[универсальные определения OB и FVG]] — **canon формулы** зон, применимы во всех стратегиях.
- [[что такое order block]] — пара (prev, cur), формула зоны для LONG/SHORT.
- [[что такое fvg]] — Fair Value Gap, тройка свечей.
- [[inverse-fvg-definition]] — iFVG: FVG противоположного направления, чьи свечи ПЕРВЫМИ перекрывают untouched зону предыдущей FVG. Маркирует Break of Structure через volume imbalance. 31 iFVG / 48 дней BTC 1h.
- [[что такое rdrb]] — ложный пробой с возвратом, 3 свечи.
- [[что такое обx4 цепочка]] — 5 свечей с чередованием + FVG c3-c5.
- [[фракталы билла уильямса]] — i±2.

## Главные правила движка

- [[главное правило ob только на последней закрытой 1h]] — `confirm_time == last_1h_open`.
- [[три типа подтверждения 1h ob fvg rdrb]] — OB-1h → FVG-1h → RDRB-1h, приоритет.
- [[правило первого OB после возврата]] — частный случай OB-1h, актуально как принцип.
- [[trigger_time равен open_time плюс tf]] — единое соглашение о времени зон.
- [[prefill silent при старте]] — маркируем сегодняшние без рассылки.

## Принятые решения

- [[почему csv а не postgres]] — MVP, простота, совпадает с reference.
- [[почему binance а не bybit]] — стабильный WS, публичный API без ключей.
- [[почему только btc eth sol]] — ликвидность, совпадает с reference.
- [[pandas-frequency-lowercase]] — `"3h"`, `"2d"` (pandas 3.x не принимает uppercase).
- [[zone-lifecycle-no-ttl]] — D-09/D-10, без TTL и без коллизий между HTF.
- [[bootstrap-sync-hard-exit]] — D-11 пересмотрено: async без hard-exit.
- [[технический долг апрель 2026]] — 5 открытых пунктов из CONCERNS.md.
- [[vic-evot-отдельная-ws-сессия]] — отдельный VicScanner вместо `TIMEFRAMES_NATIVE += [1m,15m]`.
- [[strategy-1-1-1-dedup-результаты-3y]] — наблюдения после bucketing dedup (до 12h).
- [[strategy-1-1-1-sl-15-percent]] — SL формула 15% inside от края OB.
- [[strategy-1-1-1-rr-sweet-spot]] — RR=1.24 sweet vs RR=5.89 math peak.
- [[strategy-ob-4h-fvg-1h-pro-trend]] — production-кандидат от 2026-05-08, WR 56.9%, +18R/year на BTC. Без size-фильтра, FVG-1h pro-trend, RR=1.0, min_sl=1%.
- [[strategy-c2-ob-6h-fvg-2h-pro-rr1]] — baseline C2. OB-6h × FVG-2h pro, RR=1.0. WR 55.3%, +70R за 6.33y, 0 минусовых лет. Превзойдена C2v2 ниже.
- [[strategy-c2v2-ob-6h-fvg-2h-pro-hull-1d]] — C2 + Hull-1d trend filter. **После audit (etap_37):** lookahead bug дал inflation +35R; safe-версия на BTC RR=1.5 +66R / 1 bad year (vs baseline +52.5R). **OOS:** ETH провалился (-30R / 4/4 bad), SOL marginal (+37R / 1 bad). **BTC-specific edge, не universal.**
- [[strategy-1-1-1-honest-audit-failed]] — case study failed strategy. Заявленное +46.8R / 3y оказалось +20R / 6.33y, RR≥1.5 отрицательный.
- [[7-criteria-of-good-strategy]] — рубрика оценки кандидатов: stability, WR, R/tr, frequency, no-lookahead, min_sl, простота.
- [[strategy-1-1-4-bfjk-portfolio]] — финальная стратегия 1.1.4 multi-chain (2026-05-11). 4 цепочки B/F/J/K, allow_multi=5, RR=2.0. WR 64.3%, +107R, +0.93R/trade. 6.5/7 по [[7-criteria-of-good-strategy]].
- [[allow-multi-несколько-сетапов-на-одну-l1]] — design decision: до 5 каскадов на одну макрозону. WR растёт с allow_multi (повторные retest качественнее первых).
- [[fvg-12h-сильнее-fvg-1d-как-макро-якорь]] — эмпирическая находка: 12h как L1 даёт 2× больше валидных зон и +62% к total R vs 1d.
- [[3-stage-цепочки-системно-хуже-4-stage]] — пропуск среднего OB в каскаде роняет WR на 10-15pp и резко ухудшает bad-year профиль.
- [[ifvg-7-concepts-tested]] — 7 концепций iFVG. Работает: continuation (1.1.7), age filter, breakout no-retest. Не работает: failed iFVG fade, regime detector. Сюрприз: iFVG-against на 1.1.4 = POSITIVE сигнал (WR 75% n=16).
- [[vic-asvk-as-filter-for-cascade-strategies]] — ViC forensic на 1.1.4 BFJK: |maxV-1d|>1 ATR-1h даёт +6pp WR.

## Research-стенд элементов

- [[2026-05-08-elements-study-grid-search-production-setup]] — глубокое изучение
  OB/FVG/RDRB/FH-FL по всем ТФ + grid search 114 комбинаций на BTCUSDT 6 лет.
  Результат: production-кандидат [[strategy-ob-4h-fvg-1h-pro-trend]] с WR 56.9%.
- `research/elements_study/` — 13 этапов скриптов + полные отчёты в `output/`.

## Сессии

- [[phase-0-done-2026-04-22]] — каркас Telegram-бота (Phase 0 closed).
- [[phase-1-planned-2026-04-23]] — план Phase 1 (исторический, реализован иначе).
- [[2026-04-27-vic-evot-реализация]] — VIC_EVOT (стратегия №8) реализована end-to-end за 5 коммитов.
- [[2026-04-27-vic-evot-backtest-и-ltf-fix]] — 90d бэктест + двухшаговый fix maxV (1m → 14m → 15m, сверка с TV).
- [[2026-04-28-strategy-1-1-1-vic-bos-research]] — Strategy 1.1.1 + VIC BOS, 3y backtests, lookahead fix, оптимизация VIC_EVOT.
- [[2026-04-28-strategy-1-1-1-multi-htf-multi-ltf]] — Strategy 1.1.1 расширена: OB-2h + FVG-20m + prev-day FVG-4h, 98 сигналов / WR 56.5% / +12R.
- [[2026-04-29-strategy-1-1-1-sl-15-rr-optimizer]] — большая сессия: vault, 4 агента, OB-12h, SL=15%, bucketing dedup, RR-оптимизатор. 14 коммитов, 2 ветки смерджены.
- [[2026-05-01-confluence-bugs-swept-noentry]] — найдены 2 бага в confluence-анализаторах (lookahead + wrong RR=2.2 multiplier), edge от confluence исчез. Новый рабочий фильтр — SWEPT liquidity на OB-htf. 3-stage оптимизация на SWEPT с no_entry: entry=0.80, sl=0.85 → +59.78R на 49 сделках.
- [[2026-05-08-validation-data-gap-fix-c2-winner]] — большая validation-сессия. 480-day data gap fix (2022 пропадал!), C2 новый #1 winner (+70R, 0 bad years), Strategy 1.1.1 не оправдалась в honest audit (+20R / RR≥1.5 отрицательный). 2 новых pitfall.
- [[2026-05-08-strategy-111-forensic-indicator-filters]] — forensic 262 trades 1.1.1 × 14 features. Топ-edges: Hull-4h (+13.6pp), HA-MF sign (+9.8pp), DO-discount (+7.3pp). Filter спасает RR=1.5 в +R, но frequency 0.29/wk остаётся ниже C2.
- [[2026-05-11-strategy-114-bfjk-portfolio-bug-audit]] — большая ресёрч-сессия по 1.1.4. 10 этапов (etap_66..75). Survey 18 цепочек, allow_multi, портфельные комбо, forensic audit. Найден критический баг [[l3-не-фильтровался-против-l1-invalidation]] (13% сетапов на мёртвой L1, WR 21%). Финал: portfolio B+F+J+K — WR 64.3%, +107R, +0.93R/trade.
- [[2026-05-13-live-bot-vic-ifvg-strategies-117-118]] — большая сессия: добавлены 3 новых live-сканера (1.1.2/1.1.3/1.1.6), исправлены 2 критических live-бага (current-hour filter, mark_sent race), реализован ViC ASVK Python (сверка с TV точная), изучена iFVG концепция (31 events / 48d), создан прототип [[strategy-1-1-7-ifvg-continuation]] (+37.5R / 2.3y / 0 bad), протестированы 7 концепций iFVG.

## Debugging

- [[known-pitfalls]] — **входная точка.** Один экран с 7+ грабли проекта и правилами избегания. Читать при старте сессии.
- [[vic-maxv-расходился-с-pine-индикатором-из-за-1m-вместо-15m]] — VIC maxV считался на сырых 1m, должен на 15m (Pine timeframe.from_seconds rounding).
- [[lookahead-bug-в-vic-evot-backtest]] — backtest сканировал с open(i+2) вместо close(i+2); «магические» 60%+ WR были артефактами.
- [[strategy-1-1-1-look-ahead-15min-vs-tf_duration]] — hardcoded +15min для fill-scan ломал 20m.
- [[strategy-1-1-1-почему-20m-фикс-нулевой-эффект]] — фикс защитный: entry=mid-FVG лежит вне c2.
- [[strategy-1-1-1-разные-sl-на-одном-entry]] — кейс 2026-02-06: расширили dedup-ключ на SL.
- [[strategy-1-1-1-dedup-bucketing-tolerance]] — round() ≠ толерантность, нужен bucketing.
- [[bounce-1x-не-равно-wr-при-rr]] — bounce_X% в zone-units не прокси для realistic WR при RR-strategy.
- [[confluence-lookahead-and-rr22-bugs]] — 2 бага в analyze-скриптах создавали иллюзию edge от Triple confluence (WR 71% → реальные 41%).
- [[2022-1m-data-gap-symptom-year-missing]] — 480 дней (2022-01-01..2023-04-26) отсутствовали в `data/BTCUSDT_1m.csv`. Год пропадал из year-by-year breakdown — выглядело как «no setups», было data gap.
- [[multi-bar-pattern-confirm-vs-trigger-lookahead]] — для multi-bar patterns entry должен быть на confirm_idx (после waiting period), не на trigger_idx. RDRB+ filter показывал +14pp WR из-за этого peek-in-future.
- [[multi-scanner-current-hour-filter]] — live-сканеры использовали `age > 2h` против c2_OPEN, что пропускало сигналы из ПРЕДЫДУЩИХ часов и блокировало свежие 2h FVG из-за WS delay. Fix: проверять c2_CLOSE в `(now.floor('h')-1h, now.floor('h')]`.
- [[mark-sent-race-condition-4-scanners]] — `state.mark_sent()` без `threading.Lock` при 4 concurrent сканерах через `asyncio.to_thread`. Риск потери записей в `sent_signals.json`. Fix: добавлен Lock.
- [[lookahead-anchor-confirm-окно-cur_open-cur_close]] — anchor зона использовалась с `cur_open` вместо `cur_close + tf`. Edge испарился после fix (WR 67-77% → 26-49%).
- [[htf-lookup-must-use-last-closed-bar-not-forming]] — HTF lookup в LTF-стратегии читал FORMING bar's close (etap_36 hull_1d filter). Inflation +35R/53%. Правильно: использовать `idx - 1` (last closed bar).
- [[l3-не-фильтровался-против-l1-invalidation]] — в каскаде 1.1.4 проверка инвалидации макрозоны была только на L2; L3/L4 могли формироваться после смерти L1. 13% сетапов на «мёртвых» зонах с WR 21.1%, total -7R. Правило: при многоуровневом каскаде с TTL — проверка валидности на КАЖДОМ уровне.

## Планы и процесс

- `CLAUDE.md` — правила проекта для Claude Code.
- `.planning/codebase/` — карта реального состояния кода (источник истины для «что есть»).
- vault — источник «почему именно так и история изменений».
