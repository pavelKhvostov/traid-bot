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

## Стратегии (по одной заметке на каждую)

- [[s1 obx4 + ob1h]] — OBx4-цепочка из 5 свечей → подтверждение 1h.
- [[s2 ob htf + ob1h]] — OB на старшем ТФ + обязательный фильтр FVG 4h.
- [[s3 rdrb + ob1h]] — RDRB-зона (пересечение фитилей с ограничением телами).
- [[s4 снятие фрактала]] — LL/HH-фрактал → свеча-снятие → подтверждение 1h.
- [[s5 fvg + ob1h]] — сырая FVG как зона старшего ТФ.
- [[hammer молот плюс фрактал плюс ob]] — молот + LL/HH-фрактал + OB-связка одновременно.
- [[marubozu тело 95 процентов]] — одна свеча с телом ≥ 95% диапазона.
- [[vic_evot]] — уровень maxV(D-1) + LL/HH-фрактал + FVG, подтверждение **на 15m** (а не 1h).

## Backtest-only стратегии (не в live)

- [[vic_bos]] — VIC уровень + BOS на 3m (quadruple H-L-H-L). 3y +37R на BTC.
- [[strategy_1_1_1]] — OB-{1d,12h} + FVG-{4h,6h} → OB-{1h,2h} + FVG-{15m,20m}.
  3y BTC raw RR=1.0: 144, WR 61.7%, +33R. После 3-stage SWEPT optimize @ RR=2.2:
  115 closed, WR 54.8%, +46.8R, R/trade 0.755. Файлы: `research/1_1_1/`.
- **Strategy 1.1.2** — macro-OB вместо macro-FVG. Stage 3 @ RR=2.2: WR 44.4%, +101.4R на 241 closed. Файлы: `research/1_1_2/`.
- **Strategy 1.1.3** — entry FVG того же ТФ что OB-htf. Слабее 1.1.1: stage3 @ RR=2.2 +11.4R. Файлы: `research/1_1_3/`.
- **Strategy 1.1.4** — гибрид macro-FVG + entry immediate, **WIP**. Файлы: `research/1_1_4/`.
- **Strategy 1.2.0** — новая ветка: EMA-200 + sweep + FVG-15m. В стадии tuning. Файлы: `research/1_2_0/`.
- [[strategy_1_1_6]] — параллельная ветка с инвертированным каскадом FVG-OB-FVG (top-FVG+macro-OB+htf-FVG). 3y BTC raw RR=1: WR 33%, −5R на 15 closed (после lookahead-fix). В live НЕ добавлена. Файлы: `research/1_1_6/`.

## Research-стенд

- `research/README.md` — обзор всех research-веток.
- `research/1_1_1/README.md` — эталонная конфигурация Strategy 1.1.1 + список файлов.
- Также есть `research/rdrb/` (5 кандидатов на расширение live RDRB) и `research/vic/` (out-of-scope).
- Phase 1 baseline metrics: `vault/baseline/2026-05-04-14-16/metrics.md` + `optimized-baselines.md`.
- Phase 4 re-baseline diff: `vault/baseline/2026-05-04-16-37-after-refactor/diff.md` (refactor чистый, все 22 CSV хеша совпадают).

## SMC-примитивы

- [[универсальные определения OB и FVG]] — **canon формулы** зон, применимы во всех стратегиях.
- [[что такое order block]] — пара (prev, cur), формула зоны для LONG/SHORT.
- [[что такое fvg]] — Fair Value Gap, тройка свечей.
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

## Сессии

- [[phase-0-done-2026-04-22]] — каркас Telegram-бота (Phase 0 closed).
- [[phase-1-planned-2026-04-23]] — план Phase 1 (исторический, реализован иначе).
- [[2026-04-27-vic-evot-реализация]] — VIC_EVOT (стратегия №8) реализована end-to-end за 5 коммитов.
- [[2026-04-27-vic-evot-backtest-и-ltf-fix]] — 90d бэктест + двухшаговый fix maxV (1m → 14m → 15m, сверка с TV).
- [[2026-04-28-strategy-1-1-1-vic-bos-research]] — Strategy 1.1.1 + VIC BOS, 3y backtests, lookahead fix, оптимизация VIC_EVOT.
- [[2026-04-28-strategy-1-1-1-multi-htf-multi-ltf]] — Strategy 1.1.1 расширена: OB-2h + FVG-20m + prev-day FVG-4h, 98 сигналов / WR 56.5% / +12R.
- [[2026-04-29-strategy-1-1-1-sl-15-rr-optimizer]] — большая сессия: vault, 4 агента, OB-12h, SL=15%, bucketing dedup, RR-оптимизатор. 14 коммитов, 2 ветки смерджены.
- [[2026-05-01-confluence-bugs-swept-noentry]] — найдены 2 бага в confluence-анализаторах (lookahead + wrong RR=2.2 multiplier), edge от confluence исчез. Новый рабочий фильтр — SWEPT liquidity на OB-htf. 3-stage оптимизация на SWEPT с no_entry: entry=0.80, sl=0.85 → +59.78R на 49 сделках.
- [[2026-05-06-strategy-1-1-6-первый-прогон]] — реализована 1.1.6 (FVG-top + OB-macro + FVG-htf). Найден lookahead в `find_first_fvg_htf_in_zone` (htf-search стартовал до закрытия cur macro-OB). После fix'а: WR 33%, −5R на 15 closed. В live не добавлена.

## Debugging

- [[known-pitfalls]] — **входная точка.** Один экран с 7+ грабли проекта и правилами избегания. Читать при старте сессии.
- [[vic-maxv-расходился-с-pine-индикатором-из-за-1m-вместо-15m]] — VIC maxV считался на сырых 1m, должен на 15m (Pine timeframe.from_seconds rounding).
- [[lookahead-bug-в-vic-evot-backtest]] — backtest сканировал с open(i+2) вместо close(i+2); «магические» 60%+ WR были артефактами.
- [[strategy-1-1-1-look-ahead-15min-vs-tf_duration]] — hardcoded +15min для fill-scan ломал 20m.
- [[strategy-1-1-1-почему-20m-фикс-нулевой-эффект]] — фикс защитный: entry=mid-FVG лежит вне c2.
- [[strategy-1-1-1-разные-sl-на-одном-entry]] — кейс 2026-02-06: расширили dedup-ключ на SL.
- [[strategy-1-1-1-dedup-bucketing-tolerance]] — round() ≠ толерантность, нужен bucketing.
- [[confluence-lookahead-and-rr22-bugs]] — 2 бага в analyze-скриптах создавали иллюзию edge от Triple confluence (WR 71% → реальные 41%).
- [[strategy-1-1-6-look-ahead-macro-htf]] — 1.1.6 htf-search стартовал с `+htf_hours` вместо `+macro_hours`. Брат-близнец 1.1.1 +15min bug, тот же класс ошибки на другом уровне каскада.

## Планы и процесс

- `CLAUDE.md` — правила проекта для Claude Code.
- `.planning/codebase/` — карта реального состояния кода (источник истины для «что есть»).
- vault — источник «почему именно так и история изменений».
