---
tags: [home, index]
date: 2026-04-29
---

# ASVK Power Zone — Knowledge Vault

Граф знаний проекта. При старте сессии Claude Code читает этот файл и
[[текущие приоритеты]], а затем переходит к нужным разделам по ссылкам.

## Главное

- [[БИБЛИОТЕКА-знаний]] — 📚 индекс ВСЕХ книг/статей (Dalton/Harris/Grimes/Bulkowski/Goodfellow/LdP/ICT) + ключевой применимый вывод каждого + сквозные законы.
- [[архитектура проекта flat layout]] — реальная структура (без `src/`), 7 стратегий, точки входа.
- [[стек и зависимости]] — Python 3.13, pandas, websockets, requests.
- [[структура CSV]] — `data/<SYMBOL>_<TF>.csv`, native vs composed ТФ.

## Свежее (2026-06-16)
- [[reversal-структура-дня-недели-описательный-слой]] — 2026-06-16: модуль теперь ПОМЕЧАЕТ точку разворота дня (rev_up/down + пивот ▲/▼) и недели (свип PWH/PWL); направление=монетка, fill%/магнит=конфаунд/убито → ОПИСАТЕЛЬНО, без прогноза. reversal.py + etap_255, 100 тестов.
- [[2026-06-16-frontier-v2-интеграция-1.1.1-грейд-ict-fvg]] — СЕССИЯ: 3 волны фронтира → 3 KEEP интегрированы; 1.1.1 грейд (BTC); CatBoost=стена; зоны дашборда расхардкожены; ICT double-FVG.
- [[1-1-1-swept-сегментация-и-грейд-сетапа]] — 2026-06-13: net-грейд качества сетапа 1.1.1 (net≥0 60%WR/net<0 30%, год-стаб 7/7 BTC), вшит в signal_grade.
- [[1-1-1-swept-catboost-vs-грейд-потолок]] — 2026-06-13: CatBoost-фильтр = стена learned-meta (0.906→0.466); грейд=потолок, carrier=ширина SL; ETH/SOL не переносится.
- [[ict-double-fvg-формации-по-контексту]] — 2026-06-16: double-FVG направление=монетка, но продолжение/заполнение/ход зависят от контекста (continuation-HQ vs fade).

## Свежее (2026-06-12)
- [[волна-3-календарь-результаты]] — 2026-06-13: FOMC/NFP/экспирации KILL для модели (atr+dow уже ценят, OOS-2025 эффект пропал); описательный flag опционально

- [[волна-2-деривативы-опционы-результаты]] — 2026-06-13: DVOL forward-IV KEEP (+0.021 R²/+0.014 AUC, бьёт atr_pct); funding+OI-квадранты KILL

- [[волна-1-vol-эконометрика-результаты]] — 2026-06-13: HAR-RV (+0.013 R²), eff_ratio (choppiness 0.63→0.735), CQR-лента; 3/3 KEEP, адверс-проверка пройдена

- [[фронтир-v2-тематическая-карта-8-доменов]] — 2026-06-13: разведка 8 доменов (деривативы/опционы/vol-эконометрика/режимы/календарь/макро/1m/ML); план 3 волн

- [[модель-анализа-v2-расследование-вердикты-и-ядро]] — workflow-расследование 40 фич; v2 = новые выходы P(trend-hold)+choppiness, не фичи; ETH/SOL валидация закрыта ✅
 — **Живой Telegram-дашборд: BTC/ETH/SOL + TOTAL/TOTALES, кнопки, Справка**

См. [[2026-06-12-live-dashboard-telegram-bot-total-totales]]. Day-type движок → Telegram-продукт
(etap_223–230): дашборды дня + авто-пуш (etap_227) + бот кнопок с reply-клавиатурой (etap_228) +
карта TOTAL/TOTALES (CoinGecko+F&G, etap_229) + свечные TOTAL/TOTALES из реального TradingView
(CRYPTOCAP через CLI, basket-fallback, etap_230). Бот @new_edge_neiro_bot. Тексты по-человечески, кнопка Справка.

## Свежее (2026-06-11) — **Модуль направления: честно = режим + структура, не прогноз**

См. [[2026-06-11-direction-module-honest-regime-daytype-layer]].

Направление дня вперёд = монетка (AUC 0.51, поймал lookahead в bulk_side). Построен честный
модуль: **day-type слой** (Dalton Initial Balance, TREND/ROTATION 73%/23%, etap_217) +
nowcaster (калиброванное состояние, etap_212) + дашборды (etap_224–226) + живой бот (etap_227).
6 улучшений из книг: работают только IB (#2) и vol-нормировка (#3); order flow / сессии-AMD /
**Technicals Pro** / обучаемый мета — edge не дают. Bulkowski×CatBoost-режим: busted 55%→22%.

## Свежее (2026-06-03) — **Bulkowski Encyclopedia → 13 reversal-детекторов на BTC 12h (etap_172)**

См. [[2026-06-03-bulkowski-12-reversal-detectors-etap-172]].

Bulkowski "Encyclopedia of Chart Patterns" 3rd Ed. (2076 стр.) распарсили через 4
параллельных агента на 4 PDF-части. Консолидированная справка по 75 паттернам:
`research/elements_study/refs/bulkowski_master_stats.md`.

**etap_172** — 13 чистых детекторов reversal-паттернов на BTC 12h ([[bulkowski-reversal-detectors-btc-12h-baseline]]):
- Long: BARR Bottom, Rounding Bottom, Cup with Handle, Big W, DB Eve&Eve, H&S Bottom, V-Bottom
- Short: BARR Top, Big M, H&S Top, Diamond Top, V-Top, Triple Top

См. [[bulkowski-top-12-patterns-for-btc-12h]] для обоснования выбора.

**Bulkowski-style backtest** на BTC 12h 2020-2024 = 520 сигналов от 11 детекторов
(cup_handle и rounding_bottom не нашли паттернов — R²-фит слишком строг для крипты).

**Top-5 по edge:**
| Паттерн | n | fail% | avg_mov% | half_tgt% |
|---|---|---|---|---|
| big_w | 89 | 17 | +29.8 | **90** |
| db_eve_eve | 49 | 16 | +29.6 | 90 |
| v_bottom | 42 | **14** | +26.6 | 83 |
| hs_bottom | 30 | 13 | **+31.6** | 83 |
| big_m | 87 | 21 | +16.0 | 90 |

**Закрыт вопрос про "250 сетапов"**: baseline etap_163 при thr=0.3 = 252 setups,
после всех книг (etap_171) = 316 при thr=0.3 + precision вырос с ~50% до ~62%.
Объём сохранён, качество выросло.

**Pitfalls (2 новых)**: [[socks-proxy-блокирует-binance-rest]],
[[compose_from_base-reset_index-теряет-имя-time]].

## Свежее (2026-05-26) — **VC канонизирована как концепция (не зона) + F5 search для 12h фракталов**

См. [[2026-05-26-vc-concept-canon-in-smc-lib-and-f5-search]] и [[что такое VC volume confirmation]].

- **VC = Volume Confirmation = обобщённая концепция подтверждения** (предикат над HTF-зоной, не зона интереса). Канонический случай: LTF FVG (15m/20m) ⊆ HTF OB (1h/2h) того же направления. Объём не используется (название vestigial). Добавлен в `~/smc-lib/elements/vc/` (7 тестов; 113 passed full regression).
- F4 v3 per-element mitigation canon (wick-fill / first-touch / sweep-level): 1105 keep / P=49.6% / 16 imp (теряет fresh-extreme FL #4, #9).
- F5 search: 70% барьер не пройден без потери imp. Best: counter FVG ≥1h (572 / 63.1% / 9 imp) — precision-leader; counter VC any (894 / 52.9% / 13 imp) — recall-leader. **Aligned LTF FVG/VC = anti-signal** (−2…−12pp) — direction-asymmetry закон.

## Свежее (2026-05-25, ночью) — **i-RDRB+FVG V2 определён + block_orders anti-filter найден**

См. [[2026-05-25-irdrb-fvg-v2-block-orders-confluence]]. Продолжение работы над стратегией с целью RR≥1 при ~10 trades/мес.

**Главные находки:**

1. **i-RDRB+FVG V2** — новый 6-bar pattern (continuation-FVG). FVG на (C4, C5, C6), НЕ на (C3, C4, C5) как V1. → [[i-rdrb-fvg-v2-definition]]
   - На BTC 1h за 6y: V1=800, V2=294, total=1094 setups
   - V2-FVG чаще над V2-RDRB (58% vs ~43% baseline) — подтверждает "deep reversal → strong follow-through"

2. **Backtest Combined D entry/SL @ RR=1.0 на 1094 setups:**
   - V1+V2: 1050 closed, WR **57.62%**, ΣR **+160.0R**, R/tr +0.152, **14.6 trades/мес**
   - V1 только: 773 closed, WR 57.70%, +119R, **10.7 trades/мес** ✅ (точно в цель)
   - LONG доминирует (61.9% WR vs SHORT 53.1%)

3. ⭐ **block_orders × i-RDRB+FVG confluence — анти-фильтр**:
   - **FULL overlap + SAME direction**: 125 setups, WR **47.97%**, **−5R** (отрицательный edge)
   - **NO overlap (clean structure)**: 111 setups, WR **62.73%**, R/tr +0.255 (best subset)
   - **PARTIAL same**: 567 setups, WR 59.74%, +105R (основная масса)
   - **Применение exclusion-filter (FULL SAME out)**: +5R прирост на 969 setups, WR 58.9%, 12.9/мес

**Интерпретация:** наш паттерн полностью внутри same-direction 1h block_orders = late entry в already-resolved institutional structure → momentum иссяк. Clean structure (no HTF block) — лучший edge.

**Завтра продолжить:** apply exclusion-filter официально + наложить cascade-фильтры (W→15m, RSI ASVK zone, MH color) на 969 setups, цель WR 65-70% при ~10-12/мес. См. [[текущие приоритеты]] для приоритетов.

## Свежее (2026-05-24, ночью) — **smc-lib 11 элементов + Expert Opinion methodology + 10 индикаторов**

См. [[2026-05-24-smc-lib-cascade-expert-opinion-indicators]]. Расширили smc-lib с 8 до **11 primitive-элементов**:
- `+i_fvg/` (Inverse FVG, composite) — 10 тестов
- `+marubozu/` (canon Pine WICK.ED, **не** body/range ≥ 0.95!) — 13 тестов
- `+fractal/` (Williams N=2, единственный point-zone primitive) — 14 тестов

Создан главный артефакт — **Expert Opinion методология** ([[expert-opinion-multi-tf-cascade-methodology]]): multi-TF top-down каскад **W → 3D → 2D → D → 12h → 6h → 4h → 2h → 1h → 15m** для построения мнения о цене. Реализация в `~/smc-lib/expert_opinion.md` + `scripts/expert_opinion.py` — полный каскад работает за 3.1s.

Создан `indicators/` layer (10 модулей): ATR, EMA-200, Cumulative Delta (Williams A/D proxy), Volume Profile (POC/VAH/VAL), Anchored VWAP + Effectiveness scoring, **VIC ASVK** (порт canon, auto LTF), **ASVK Trend Line** (Hull MA), **ASVK Custom RSI** (adaptive OB/OS + NWE), **Money Hands ASVK** (WaveTrend + color state).

**VWAPs ranking**: anchor на каждом D-фрактале за 1 год (98 фракталов), effectiveness через все 10 ТФ каскада, selection = 2 closest + 6 most effective + 2 farthest.

Фундаментальный принцип, зафиксированный пользователем: 🧲 **непроторгованная область = магнит, притягивающий цену** ([[feedback-untraded-area-is-magnet]]). Применимо к FVG / i_FVG / marubozu (там целевая точка = уровень open, не всё тело).

Текущий expert opinion на BTC 2026-05-24 20:33 MSK (close 76 627): bullish bias ~60-65% для завершения D-retracement в HTF uptrend (3D/2D HH+HL не нарушены, D+12h RSI ASVK в зелёной OS-зоне, 6h Hull flipped UP, VWAP cluster 76 100-76 700 = 7 effective VWAPs на цене). Trigger A: 1h close > 77 543 → path 78 200 → 80 500 → 82 850.

## Свежее (2026-05-24, поздно вечером) — **smc-lib canon 8 элементов + VWAPs ASVK introduction**

См. [[2026-05-24-smc-lib-canon-vwap-asvk-introduction]]. Расширение `~/smc-lib/` с 3 до 8 элементов (+ob, +ob_liq, +i_rdrb_fvg, +block_orders, +rb). Создан справочник [[zone_of_interest]] для канонических зон. Начали изучать VWAPs ASVK — найден optimal anchor 2026-03-23 09:40 MSK (score +26 на 2-мес forward, rebound rate 64.1%); VWAP@now (74505) совпал с reversal low 23-05 (74289) — точная HTF-проекция. Multi-TF анализ разворота 23-05 на 74289 нашёл массивный confluence (1w RDRB liq + 2-летний untouched 1w/2d FVG из Oct-Nov 2024 + 1d/2d RB BOTTOM). Текущий setup: SHORT-cluster выше 77100-78400 — оценка SHORT-разворота 75-85% на 1-3 дня.

## Свежее (2026-05-24, обновление) — **Combined D zafiksирован** как baseline upgrade

См. [[i-rdrb-fvg-combined-d-block-edge-sl-01]]. Первый upgrade i-RDRB+FVG, улучшающий ОБЕ метрики одновременно:
- LONG: entry = block.top, SL = pl + 0.1×(bb-pl)
- SHORT: entry = block.bottom, SL = ph − 0.1×(ph-bt)
- TP unchanged (baseline price)
- **6y BTC 1h: 781 trades, WR 59.80% (vs 56.67% baseline), ΣR +122.6R (vs +104R, +17.9%)**
- LONG: 392 trades, 65.31% WR, +102.5R (+19%)
- SHORT: 389 trades, 54.24% WR, +20.0R (+11%)

## Свежее (2026-05-24) — i-RDRB+FVG: feature mining (EVoT/VWAPs/FL/RDRB) + SL grid

См. [[2026-05-24-i-rdrb-fvg-evot-vwap-features-sl-optim]] — большая аналитическая сессия. Главные находки:
- **R/ATR(14) ∈ [0.5, 0.85)** — топ-фильтр: 305 trades, 63.28% WR, **+81R из +104 base** (78% всего edge, 39% выборки). Независимо переоткрыт фильтр из [[i-rdrb-v1-pattern]].
- EVoT bimodal: maxV "глубоко под entry" (≤−0.5R) OR "выше entry" — ~67% WR; "под, но близко" (−0.5..0) — 47% anti-edge
- EVoT time в C1/C2 — 65.5% WR (153 trades, +47R, +0.31R/tr)
- VWAP-FL 4h distance [1, 2)R над entry — 67.92% WR (53 trades)
- **30m bullish FVG в zone [pattern_low, block.bottom] = anti-edge** (WR 50.91% vs 62.61% без). 3-TF FVG confluence — 45.95% WR (anti).
- **15m FL.low — надёжный support** (71% удержание в WIN), но как SL не помогает
- **15m RDRB.block.bottom — late re-entry trap**: 76% wins "касаются", но многие fills происходят ПОСЛЕ baseline TP
- **SL grid optimization** на 239 winners:
  - SL offset 0.10 от (pattern_low → block.bottom): WR 97.91%, +252.9R (+5.8%) — conservative upgrade
  - SL offset 0.50: WR 74.90%, +275.3R (+15%) — aggressive trend-rider (new R-units)

## Свежее (2026-05-23) — smc-lib + VWAPs ASVK experiments на i-RDRB+FVG

См. [[2026-05-23-smc-lib-vwap-entry-experiments]] — основная сессия дня:
- Создана независимая Python-библиотека `~/smc-lib/` (RDRB, i-RDRB, FVG) — см. [[smc-lib-as-canonical-source]]
- Зафиксированы каноны: RDRB direction по C2 (bear→SHORT, bull→LONG); i-RDRB всегда reversal; POI/block/liq геометрия
- BTC 1h 6y: 808 i-RDRB+FVG паттернов, baseline RR=1 даёт **+112R, WR 57.02%** (LONG 61.4% +91R, SHORT 52.6% +21R)
- VWAPs ASVK как entry / TP / filter — **не даёт существенного edge** (см. [[i-rdrb-fvg-vwap-entry-experiment]]):
  - VWAP-entry strict: режет 94% сетапов, edge не улучшен
  - VWAP-TP (3 anchor варианта): хуже baseline на ΣR, но SHORT side +34R vs +18R
  - VWAP-filter (F1-F10): маржинальный +0.5pp WR ценой −2..−7R
- 1m CSV догнан до 2026-05-23 18:25 UTC через `~/smc-lib/scripts/update_btc_1m_csv.py`
- Графики: `~/Desktop/i-rdrb-charts/vwap_entry_*.png` (3 эталона)

## Свежее (2026-05-22) — i-RDRB V1 + FVG · F1∪F2_same · F3(R/ATR) · 257 setups WR 71.6%

См. [[i-rdrb-v1-fvg-f1-f2-f3-strategy-257-setups-wr72]] — финальная версия:
- 5-свечной паттерн i-RDRB V1 + bullish FVG (LONG; SHORT зеркально)
- F1 = HTF Order Block (4h/6h/8h/12h/D, same dir)
- F2_same = HTF RDRB 3-candle (same dir, c3 closed by fill)
- F3 = R/ATR(20) ∈ [0.55, 1.03] — sweet spot R относительно волатильности
- 6y: 257 трейдов, WR 71.60%, +111R, MDD −6R, Sharpe 3.13
- Поэтапная воронка 809 → 525 → 257; все 7 лет прибыльны
- Структурные SL правила на 15m TF (V.1/V.2/V.3 OB + FVG-1/FVG-2 entry) запаркованы — на 257 ухудшают: +57R vs +111R
- Альтернативная версия (F4 multi-OR + hour exclude) → [[i-rdrb-v1-fvg-f1-f2-f4-strategy-401-setups-wr71]] (superseded)

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
- [[i-rdrb fvg митигация зоны 1h btc eth]] — i-RDRB+FVG (5-свечной element) + zone-mitigation entry. **BTC + ETH 1h**, 6 лет: entry=0.9, SL=0.2, RR=1.4 универсально. Σ портфель: **WR 49.26%, +269.2R / 6y (+44.9R/год)**, ~245 сделок/год. BTC: +150.8R/+25.1y, ETH: +118.4R/+19.7y. Cross-asset validated. Файлы: `research/vic_vadim/backtest_irdrb_fvg_*.py`.
- [[vadim 12 confluens asvk]] — confluence-score стратегия поверх i-RDRB+FVG. 11 факторов (max 16 баллов): trendline, OB/FVG HTF, sweep на LTF/HTF, ViC.D нетронутый, RSI, дивы на 5 осцилляторах, rel_vol. **In-research**: score ≥ 12.0 даёт WR 53.60%, R/tr +0.286, ΔWR +4.34pp (n=278). Но ΣR падает с baseline +269.2R до +79.6R — confluence повышает R/tr, не ΣR. Открыто: score-based RR. Файл: `research/vic_vadim/vadim_confluens_asvk.py`.

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
- [[что такое VC volume confirmation]] — **обобщённая концепция подтверждения** (предикат, не зона): LTF FVG ⊆ HTF-зоны same direction. Канонично OB-1h/2h × FVG-15m/20m. Объём не используется. Smc-lib: `elements/vc/`.

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
- [[12h фрактал — эмпирика снятия зон 6y BTC]] — 2026-05-20. **Финальная стратегия:** (sweep_FH ∪ OB_sweep) ∩ sweep_maxV[i] → HH 81.9% / LL 73.4% (n=177 за 6y BTC, ~30/год). Sniper AND: HH 90.3% / LL 68.3% (n=72). Артефакты в `research/vic_vadim/`.
- [[стратегия ViC Vadim 12h вариант 1]] — 2026-05-21. **Финальная стратегия (mlt=45 / LTF=16m).** BTC Core: HH 83.3% / LL 75.0% (n=176, ~29/год). ETH Core (OOS): HH 73.0% / LL 75.4% (n=120, ~20/год). LL стабилен между BTC и ETH. HH Sniper BTC: 93.6% (n=31).
- [[2026-05-21-vic-vadim-12h-fractal-finalize]] — session: финализация стратегии, brute-force mlt 30-200, OOS ETH, новый pitfall.
- [[2026-05-21-vic-vadim-c3-research-paused]] — продолжение: исследование C3 (ASVK RSI отклонён, Money Hands / Hull MA — варианты), SOL pending.
- [[pine-ltf-12h-chart-ceil-round-up-to-integer-minutes]] — pitfall: Pine `from_seconds` на 12h-chart round-up до integer-minute (≠ closest valid на D-chart).

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
- [[2026-05-19-rdrb-v2-babai-fractal-prediction]] — RDRB V2 в код + тесты + canon (V3 отклонён), [[babai]] LONG-сетап на 12h спроектирован/забэктестен/отложен (+4.78R на 41 сделке, слабый edge), главное открытие — эмпирика предсказания HH/LL фракталов на D с топ-стэками 84.6%/76.9% precision (см. [[reversal-3candle-fractal-prediction]]). Новый pitfall [[zone-mitigation-filter-required]].
- [[2026-05-23-smc-lib-vwap-entry-experiments]] — построена независимая `~/smc-lib/` (RDRB/i-RDRB/FVG), 23 теста, baseline 1h 6y BTC = +112R / 57% WR. VWAP-варианты протестированы (entry, TP, filter) — edge не улучшается. Локальный 1m CSV догнан до 2026-05-23.
- [[2026-05-24-i-rdrb-fvg-evot-vwap-features-sl-optim]] — feature mining на 798 trades + SL grid optimization. R/ATR ∈ [0.5, 0.85) — топ-фильтр (+81R из +104 на 305 trades). EVoT, VWAP-FL 4h, multi-TF FVG, 15m FL/RDRB разобраны. SL offset 0.5 от pattern_low → block.bottom даёт +275R на 239 winners в new R-units (+15% vs baseline).
- [[i-rdrb-fvg-combined-d-block-edge-sl-01]] — Combined D upgrade: entry на block edge + SL 0.1 offset. 781 trades, WR 59.80%, ΣR +122.6R (vs +104R baseline, +17.9%). Симультантное улучшение WR и ΣR на обеих сторонах.

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
- [[zone-mitigation-filter-required]] — zone-overlap фильтры (FVG, OB, любые ценовые зоны) без учёта mitigation покрывают 94% свечей за 8.7 лет и дают нулевой lift. Фикс — «первый touch на немитигированной зоне»: с ним lift ×0 → ×2.2, топ-стэк 84.6% precision.

## Планы и процесс

- `CLAUDE.md` — правила проекта для Claude Code.
- `.planning/codebase/` — карта реального состояния кода (источник истины для «что есть»).
- vault — источник «почему именно так и история изменений».
