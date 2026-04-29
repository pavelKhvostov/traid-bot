---
tags: [session, strategy_1_1_1, sl, rr, dedup, ob-12h, agents, vault]
date: 2026-04-29
related: [[strategy_1_1_1]], [[known-pitfalls]]
---

# Сессия 2026-04-29: вечерняя — SL=15%, bucketing dedup, RR-оптимизатор + парабола

Большой день. Всего 14 коммитов в main, две ветки смерджены (`feat/strategy-1-1-1-ob-12h`,
`feat/strategy-1-1-1-sl-85-rr-optimizer`).

## Часть 1 — Vault и инфраструктура (раннее утро/день)

### Документация под реальный код
- `CLAUDE.md` актуализирован: 4 → 10 стратегий, двойной WS, Level dataclass,
  раздел «Тестирование», раздел «Самообучение: known-pitfalls.md».
- `vault/knowledge/debugging/known-pitfalls.md` создан с 7 пунктами проектных грабель.
- `vault/00-home/index.md` дополнен ссылкой на known-pitfalls как «входную точку».

### 4 агента в .claude/agents/
Созданы и закоммичены через whitelist в `.gitignore`
(`!.claude/agents/{spec-syncer,backtest-auditor,pitfall-checker,smc-reviewer}.md`):

- **spec-syncer** — ловит рассинхрон strategies/*.py ↔ vault/knowledge/strategies/*.md ДО коммита.
- **backtest-auditor** — 8-пунктный чек-лист look-ahead/bias.
- **pitfall-checker** — форсит чтение known-pitfalls в начале сессии.
- **smc-reviewer** — ревью логики стратегий по canon из vault/knowledge/smc/.

GSD-агенты остались под gitignore (each developer installs separately).

## Часть 2 — Strategy 1.1.1 эволюция (день/вечер)

### Ветка feat/strategy-1-1-1-ob-12h (8 коммитов)

1. **Pitfall #8 + заметка** про hardcoded +15min для 20m fill → look-ahead.
2. **Ф1 — фикс +15min → +tf_minutes** в `simulate_outcome`. Smoke-test показал
   0 outcome изменений на 3y BTC — оказался **теоретическим look-ahead'ом**:
   entry=mid-FVG лежит вне c2, fill внутри c2 невозможен. Защитный фикс.
   См. [[strategy-1-1-1-почему-20m-фикс-нулевой-эффект]].
3. **Ф2 — dedup ключ** `(signal_time, direction, entry, sl)` с meta-полями
   count/tf. Расследовали кейс 2026-02-06: 1 пара сигналов с разными SL на
   одной entry — легитимные разные трейды.
   См. [[strategy-1-1-1-разные-sl-на-одном-entry]].
4. **Ф3 — OB-12h как параллельный top-level**. Параметризация
   `top_tf_hours`, helper `_scan_top`, dedup объединяет 12h+1d через
   meta-поля. 3y BTC: 87 → **144 deduped**, WR 60.7% → 61.0%, PnL +18R → +31R.
5. **Ф4 — 8 unit-тестов** в `tests/test_strategy_1_1_1.py`. Все 39 тестов
   проекта зелёные.
6. **Spec обновлён** под код (1d/12h, 4h/6h, dedup, CSV layout).

### Ветка feat/strategy-1-1-1-sl-85-rr-optimizer (3 коммита, смерджена через PR #1)

7. **SL = 15% от края OB** (вместо границы). `OB_SL_DEPTH = 0.15`. Узкий SL
   → быстрее закрытие → больше эффективный RR. 3y: WR 61.0% → 63.9%,
   PnL +31R → +43R. См. [[strategy-1-1-1-sl-15-percent]].
8. **Bucketing dedup** через `SL_TOLERANCE = 0.005` (0.5% от entry).
   Изначально пробовали `round(sl/entry, 4)` — 0 эффекта (ширина bin ≠
   tolerance). Двухэтапный: primary group по (signal_time, direction, entry),
   bucketing по close-SL и совпадающему outcome. 3y: 158 → 144 deduped.
   См. [[strategy-1-1-1-dedup-bucketing-tolerance]].
9. **RR-оптимизатор** `optimize_strategy_1_1_1_rr.py`. MFE-based timeline
   через `argmax(sl_hit), argmax(tp_hit)` на vectorized numpy. 501 точек
   RR от 1.0 до 6.0 за ~94s. PNG с двумя осями (PnL, WR), зонами комфорта
   ≥50% WR, маркерами sweet spot и math peak. См. [[strategy-1-1-1-rr-sweet-spot]].

## Главные численные результаты (3y BTC, n=144)

| Метрика | RR=1.0 baseline | RR=1.24 sweet | RR=2.2 гипотеза | RR=5.89 math peak |
|---|---|---|---|---|
| wins | 87 | 82 | 58 | 36 |
| losses | 54 | 59 | 83 | 104 |
| WR | 61.7% | **58.2%** | 41.1% | 25.7% |
| PnL | +33R | **+43R** | +45R | **+108R** |
| R/trade | 0.23 | 0.30 | 0.31 | 0.75 |

**WR=50% boundary:** RR=1.45 (точка перехода).
**Sanity check:** 0 сделок переходят loss@RR=1 → win@RR=5.89 →
look-ahead в оптимизаторе нет.

## Главные insights

1. **Look-ahead в backtest может быть теоретическим**, не практическим.
   Зависит от конкретной геометрии entry. Фикс делать всё равно — защитный
   на будущее.

2. **Dedup tolerance — bucketing > rounding.** `round(x, N)` определяет
   ширину bin, но два значения с diff < N могут попасть в соседние корзины.
   Для семантического схлопывания нужен sort+merge с явным threshold.

3. **Stratagy 1.1.1 — trend-following.** Низкий WR + high R-multiple даёт
   максимальный edge. На RR=5.89 WR=25.7% (75% сделок убыток) но +108R.
   Психологически тяжёлая, но математически оптимальная.

4. **WR стабилен по годам на math peak.** 25-26% в 2023/2024/2025 — НЕ
   артефакт bull-market. 2023 (медвежий) на RR=5.89 даёт +21R, на RR=1
   даёт −1R. Стратегия пропускает большие движения на узком TP.

5. **12h-only ветка не мусорная.** WR 61.4% (vs 1d-only 55.7%, vs
   confluence 1d+12h 85.7%). Confluence работает на каждом уровне:
   1d/12h, 4h/6h, 15m/20m.

6. **Reрже = качественнее.** На 3 из 4 уровней более редкий ТФ давал
   выше WR (6h > 4h, 12h > 1d, 20m > 15m). Гипотеза «фильтр шума через
   confluence» подтверждается.

## Открытые вопросы / next steps

- **ETH/SOL прогоны.** 3y BTC недостаточно для решения «деплоить или нет».
- **Live deployment.** Требует WS-подписки на 12h, 6h(composed), 4h, 2h(composed),
  20m(composed), 1m. Адаптация под scanner-архитектуру.
- **RR=1.24 sweet vs RR=5.89 peak — какой деплоить?** Sweet даёт стабильность
  WR≥50% (психологически приятнее), peak даёт почти 3x R/trade. Для
  алгоритмической торговли — peak; для дискреционной с подписчиками — sweet.
- **Кейс 2026-02-04 LONG entry=98423** (loss во всех RR, два OB-D на 16
  месяцев): достаточно ли строгий фильтр fractal-инвалидации?

## Что НЕ сделано

- Не было WR-аудита по символам (только BTC).
- Не было адаптации к scanner-архитектуре.
- Не были обновлены остальные strategies/*.md под canon OB/FVG.

## Файлы

**Изменены:**
- `strategies/strategy_1_1_1.py` — top_tf_hours param, _scan_top, OB_SL_DEPTH=0.15
- `backtest_strategy_1_1_1.py` — bucketing dedup, +tf_minutes fix, top_tf в base_row
- `tests/test_strategy_1_1_1.py` — Test 1 SL=93.05 update
- `vault/knowledge/strategies/strategy_1_1_1.md` — RR-оптимизатор раздел
- `vault/knowledge/debugging/known-pitfalls.md` — 8-й pitfall + sub-bullet
- `vault/00-home/index.md` — ссылки на новые заметки
- `vault/00-home/текущие приоритеты.md` — обновлённое состояние

**Созданы:**
- `optimize_strategy_1_1_1_rr.py` — RR-оптимизатор
- `tests/test_strategy_1_1_1.py` — 8 unit-тестов
- `vault/knowledge/debugging/strategy-1-1-1-look-ahead-15min-vs-tf_duration.md`
- `vault/knowledge/debugging/strategy-1-1-1-почему-20m-фикс-нулевой-эффект.md`
- `vault/knowledge/debugging/strategy-1-1-1-разные-sl-на-одном-entry.md`
- `vault/knowledge/debugging/strategy-1-1-1-dedup-bucketing-tolerance.md` (этой сессии)
- `vault/knowledge/decisions/strategy-1-1-1-dedup-результаты-3y.md`
- `vault/knowledge/decisions/strategy-1-1-1-sl-15-percent.md` (этой сессии)
- `vault/knowledge/decisions/strategy-1-1-1-rr-sweet-spot.md` (этой сессии)
- `vault/sessions/2026-04-28-strategy-1-1-1-vic-bos-research.md` (днём ранее)
- `vault/sessions/2026-04-28-strategy-1-1-1-multi-htf-multi-ltf.md` (днём ранее)

**Артефакты бэктеста (gitignored, локальные):**
- `signals/strategy_1_1_1_3y_RR{1.0,2.2}.csv` — 144 сделки
- `signals/strategy_1_1_1_rr_optimizer_BTCUSDT_3y.csv` — 501 точка RR-сетки
- `signals/strategy_1_1_1_rr_optimizer_BTCUSDT_3y.png` — парабола PnL(RR)
- `signals/verify_RR{1.24,1.45,2.20}.csv` — для ручной TV-верификации

## Связи

- [[strategy_1_1_1]] — обновлённый spec
- [[strategy-1-1-1-sl-15-percent]] — решение про SL формулу
- [[strategy-1-1-1-rr-sweet-spot]] — решение про RR
- [[strategy-1-1-1-dedup-bucketing-tolerance]] — баг round-as-bin
- [[known-pitfalls]] — pitfalls 1-9
