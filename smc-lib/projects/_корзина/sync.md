# sync — проект синхронизации BTC × TOTAL × USDT.D

> Status: **active design** (2026-06-02).

## Цель

Использовать **3 представления одной силы рынка** для отбора качественных setups в BTC:
- **BTC** (BTCUSDT spot) — таргетируемый actively-traded asset
- **TOTAL** (CRYPTOCAP) — capa крипты = BTC + альты + (stables). **Co-directional с BTC** (BTC ~56% веса)
- **USDT.D** (CRYPTOCAP) — доля стейблов. **INVERSE к BTC/TOTAL** (USDT.D ↑ = bears)

Ключевая гипотеза: «Зачастую один из этих 3 показывает разворот **более технично** чем остальные».

Стратегия НЕ "все три согласны" (слишком строго), а **«cleanest technical signal wins»**:
1. Ищем чёткий setup на ЛЮБОМ из 3 (Williams pivot / sweep / divergence / etc.)
2. Переводим на BTC direction:
   - BTC technical → directly
   - TOTAL technical → directly (co-directional)
   - USDT.D technical → **inverse** (USDT.D bear setup = BTC bull)
3. Confluence check: другие 2 не противоречат (могут быть neutral, не должны быть opposite)
4. Trade BTC по полученному direction

## Scope (фиксированный)

| Параметр | Значение |
|---|---|
| **Период** | 2025-01-01 → 2026-06-02 (17 мес) |
| **Главный TF** | **2h** (доступен для всех трёх) |
| **Доступные TFs** | 1d, 4h, 2h (1h только с 2026-04 для USDT.D) |
| **Assets** | BTC, TOTAL, USDT.D |
| **Альтернатива TOTAL** | TOTAL2 (без BTC) — для контр-проверки |

## Ground truth

- **Данные**: `~/traid-bot/data/{BTCUSDT_1m, TOTAL_2h, USDT_D_2h}.csv`
- **BTC** ресэмплится из 1m → 2h
- **Common window 2h**: ~6 200 баров

## Methodology

_TBD — нужно определить:_

| Открытый вопрос | Варианты |
|---|---|
| Direction definition per asset | net change % за N баров / sign(close-open) / slope |
| Sync categories | UP-UP-DOWN (триплет идеальный bull) / DOWN-DOWN-UP (bear) / mixed |
| Lag analysis | TOTAL ведёт BTC? USDT.D опережает разворот? |
| Divergence threshold | когда «разошлись» считается значимым |
| Confluence as filter | как использовать в trade-strategy |

## Этапы (план, переориентированы под «cleanest signal wins»)

### Этап 1 — Baseline structural analysis
Для каждого из 3 assets отдельно:
- Williams n=2 фракталы на 2h, 4h, 12h
- Sweeps и BOS events
- HMA-78/200 положение и crosses
- Williams pivot frequency (sanity check что один не overdetects)

### Этап 2 — Per-asset «cleanliness» score
Для каждого setup на каждом asset measure:
- Technical clarity (наличие divergence, sweep, structural break)
- Volume/strength signals
- Multi-TF confluence на ЭТОМ asset

Output: per-setup score 0-1 «насколько чисто».

### Этап 3 — Translation to BTC direction
- Setup на BTC → BTC direction directly
- Setup на TOTAL → BTC direction directly (co-directional)
- Setup на USDT.D → INVERSE BTC direction (mirror rule)

### Этап 4 — Confluence cross-check
Когда у одного asset чистый setup:
- Что показывают другие 2?
- Категории: STRONG CONFIRM / WEAK CONFIRM / NEUTRAL / WEAK CONFLICT / STRONG CONFLICT
- Только NEUTRAL+ trades разрешены

### Этап 5 — Backtest + comparison
- BTC 1.1.1 floating standalone (baseline)
- BTC 1.1.1 + sync filter (только trades when confluence non-conflict)
- BTC 1.1.1 + sync triggered (entry на «cleanest signal» of any of 3, BTC trade)

Compare metrics (WR / PF / RR / freq).

## Открытые вопросы

| # | Вопрос |
|---|---|
| 1 | Direction definition: net change за 1 бар / N баров / slope? |
| 2 | Window для sync категоризации — instantaneous (один бар) или rolling? |
| 3 | Strictness sync — три направления или «два из трёх»? |
| 4 | Magnitude threshold — игнорировать слабые движения < X%? |
| 5 | Lag — фиксированный или поиск optimal? |
| 6 | Confluence rule: AND, OR, score? |
| 7 | Какую trade-стратегию использовать как «benchmark» для sync filter? |
| 8 | OOS validation: split 2025 на train/test или walk-forward? |

## Связанное

- **Правило 12** в `~/smc-lib/rules.md` — каноническое определение TOTAL и USDT.D
- `[[feedback-1-1-1-floating-without-totales-usdtd]]` — memory: 6y benchmark BTC без macro confluence
- `~/traid-bot/research/rdrb/analyze/analyze_rdrb_confluence_macro.py` — старый analyzer (lookahead bug fixed)
- `[[2026-06-02-pivot-mec-p4zr-multi-expert-deep-dive]]` — предыдущая сессия

## Артефакты (planned)

- `~/smc-lib/scripts/sync_baseline_corr.py` — Этап 1
- `~/smc-lib/scripts/sync_classify_direction.py` — Этап 2
- `~/smc-lib/scripts/sync_divergence_catalog.py` — Этап 3
- `~/Desktop/sync_per_2h_bar.parquet` — основной dataset
