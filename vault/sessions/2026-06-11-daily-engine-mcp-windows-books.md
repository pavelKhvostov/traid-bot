---
tags: [session, daily-engine, catboost, mcp, tradingview, books, windows]
date: 2026-06-11
---

# Сессия 2026-06-11: 3 книги · merge Павла · MCP на Windows · daily_engine (CatBoost)

## 1. Глубокое чтение 3 книг → мастер-конспекты + синтез
`research/elements_study/refs/`:
- `dalton_market_profile_master.md` — Market Profile/Auction (POC/VPOC/VA-70%/HVN-LVN/excess) + Python-код профиля + якорение 24/7. Verified.
- `harris_microstructure_master.md` — микроструктура, **Binance kline idx 9/10 = taker_buy_base/quote**, `delta=2·tbr−vol`, CVD, Kyle/Amihud λ, VPIN. Verified.
- `grimes_tested_edge_master.md` — random-walk база, **Four Trades** (pullback-continuation = квинтэссенция), «знаем направление ИЛИ магнитуду». Из знаний.
- `books_synthesis_trend_continuation.md` — синтез → спека trend-continuation pullback + фичи + H1/H2/H3 + бары приёмки.

## 2. Order-flow дозагружен (Harris)
`etap_196_fetch_taker_flow.py` → `research/elements_study/data/{SYM}_{1h,12h}_flow.csv` (BTC/ETH/SOL,
OHLCV + taker_buy + delta/cvd/taker_buy_ratio). Live-пайплайн дропает taker_buy — это отдельные CSV.
Pitfall: на ЛОКАЛЬНОЙ Windows Binance идёт через системный SOCKS5 (реестр), `requests` берёт сам;
НЕ ставить NO_PROXY (обратно VPS-pitfall). См. [[binance-rest-прокси-зависит-от-машины-vps-vs-local-windows]].

## 3. Merge ветки `pavel` (origin/pavel, 27 коммитов)
Влиты знания Павла: нейро-ветка (etap_174-185, neural_bot), 3 DL-книги (Goodfellow/Nielsen/Nikolenko),
AFML López de Prado (lec1-10), ICT/SMC курс (12 мес), 4 агента. ⚠️ Двойная нумерация etap_174-185
(мой Bulkowski-ряд vs нейро-ряд Павла сосуществуют). Прочитаны ВСЕ его конспекты (книги/статьи).

## 4. TradingView MCP — ЗАПУЩЕН НА WINDOWS
Павел ставил на Mac; завёл на Windows-машине пользователя. См. [[TradingView-MCP-как-запускать]] (Windows-раздел).
Ключевое: standalone `D:\games\TradingView\TradingView.exe` (НЕ Store/UWP — та флаг не принимает) +
снять `ELECTRON_RUN_AS_NODE` (иначе TV стартует как Node, игнорит --remote-debugging-port). npm install
через socks5. Сервер `C:\Users\Andrew\tradingview-mcp` (launcher health.js пропатчен под D:\games + env).
Регистрацию в ~/.claude.json делает пользователь (Claude блокирует самомодификацию автозапуска).
78 инструментов работают: читает live BINANCE:BTCUSDT, индикаторы ASVK (RSI/Money Hands), рисует зоны.

## 5. 🆕 daily_engine — CatBoost дневной движок (research/daily_engine/)
ТЗ: каждый день — границы/зоны/направление/трейд + аргументация + self-critique. Train 2020-24, test 2025-26.

**ГЛАВНЫЙ ЧЕСТНЫЙ РЕЗУЛЬТАТ:**
- ❌ **Направление дня НЕ предсказуемо**: purged-CV 0.546 (null p=0.000, in-sample реален), но **OOS AUC 0.507** (статика) И **0.501** (walk-forward). Режимно-зависимый паттерн 2020-24 не переносится. Подтверждает стену проекта (Bayes error, Grimes random-walk). Order-flow (CVD/delta) в топ НЕ вышел.
- ✅ **Диапазон/режим дня ПРЕДСКАЗУЕМ** (vol-кластеризация): range **OOS R² 0.50** (бьёт persistence 0.017), big_day **AUC 0.73** стабильно 2025+2026. Драйверы: `atr_pct` + **`dow` (день недели!)** = ICT недельный профиль.
- ✅ **Self-critique loop** (etap_202): нашёл дефекты — границы держали 31%, регрессия-к-среднему (большие дни −1.74пп / флэт +1.06пп), 37% больших дней пропущено. SHAP-атрибуция: dow ведущая в 55% верных дней.
- ✅ **Self-correction** (etap_203): калиброванный k → границы **31%→77%** контейнмент; режимная де-калибровка. Честный негатив: breakout-risk фича НЕ помогла (vol-шоки экзогенны, непрогнозируемы).
- ✅ **Фаза 4** (etap_204): intraday 1h order-flow + VIC maxV-прокси НЕ улучшают (importance мизер vs atr/dow) — честный негатив, диапазон правят волатильность+dow.
- Продукт: `etap_201_daily_analyzer.py` (коррекции вшиты) — границы/режим/зоны(VP+ICT+DOL)/structural-bias/трейд/SHAP.

Файлы: etap_198 (baseline+null), 199 (walk-forward), 200 (range), 201 (анализатор), 202 (critique), 203 (correct), 204 (prod+extended).

## 6. Multi-horizon зоны BTC (etap_205)
Зоны по D/W/M (Dalton VP + ICT unmitigated OB/FVG + untested liquidity + naked POC). VP-окно
под текущий режим (M=18мес, W=26нед, D=90д). Текущий BTC (~63k): ниже стоимости на D+M (discount),
у нижнего края недельной стоимости (W VAL 62.7k — опора). Сопротивление 64.2-66.2k (D+W FVG),
опора 57.5-61.7k (D OB-стопка); макро: M FVG bear 79-84k / M FVG bull 49-59k. Нанесено на TV.

## 7. VWAP-исследование (etap_206/207) — ЧЕСТНЫЙ НЕГАТИВ
Индикатор VWAPs-ASVK = 10 anchored-VWAP от 10 последних D-фракталов (логика из
smc-lib/plot_d_10_fractals_vwap.py; Pine через MCP не открылся). Проверка с null-тестом:
- VWAP как S/R: hold **57.7%** vs случайный уровень **56.8%** (p=0.033) — edge +0.9пп, экономически ~0.
- **Значимость якоря НЕ важна**: react% ~59% одинаков у N=2/N=5/N=10/SWEEP и **RANDOM (60%)**.
- **Конфлюэнс ≥2 VWAP НЕ усиливает** (0.572 vs 0.583).
- «Топ важных дат» = артефакт возраста (старые VWAP при 35k, нерелевантны).
**Вывод: VWAP — контекст справедливой цены, НЕ самостоятельный сигнал.** Опровергает прежний
оптимизм vault ([[2026-05-24-smc-lib-canon-vwap-asvk-introduction]] был единичным примером).
Пользователю предложен head-to-head тест его конкретных дат (ждём даты).

## 8. Библиотека знаний (index)
Создан [[БИБЛИОТЕКА-знаний]] — индекс ВСЕХ источников (8 книг + ICT-курс + arxiv) с ключевым
применимым выводом каждого + 6 сквозных законов. Добавлен в [[index]].

## 9. Правило работы (память)
Зафиксировано: когда юзер просит анализ — **сразу рисовать на TradingView + пояснения в чате,
не спрашивать** (full reset графика ОК). Память: feedback-analysis-draw-on-tv.

## Вывод
daily_engine даёт РОБАСТНЫЙ honest продукт: **границы дня (R²0.50) + режим (AUC0.73) + детерминированные зоны**,
направление = честный low-conviction structural bias (не фейк ML). Self-learning loop реально улучшил продукт
(границы 31→77%) и честно признал непреодолимое (vol-шоки, направление). Order-flow/VIC edge для дневных целей
не дали — 4-е подтверждение, что предсказуемость дня = волатильность+сезонность, не поток.

## Открытое (следующее)
- Вшить структурный bias-skew в границы (сейчас симметрично вокруг open).
- Зоны в daily_engine считать из smc-lib canon (сейчас упрощённый OB/FVG).
- Backtest «трейда дня» (mean-reversion к POC во флэт-дни / continuation в широкие) на edge.
- VIC настоящий (vic_levels.calculate_vic_d, 1m) — но прокси не помог, низкий приоритет.
