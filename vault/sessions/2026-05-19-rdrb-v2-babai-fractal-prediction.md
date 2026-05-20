---
tags: [session]
date: 2026-05-19
status: closed
---

# 2026-05-19 — RDRB V2 в код + бабай-сетап + эмпирика предсказания фракталов

Большая сессия. Установлено 6 терминов пользователя в memory, добавлен V2
в детектор RDRB с тестами и обновлением canon, спроектирована стратегия
«бабай» (отложена после бэктеста), собран эмпирический отчёт по предсказанию
HH/LL фракталов на D BTCUSDT с топ-стэками 84.6% / 76.9% precision.

## Установленная терминология (в memory)

- **RSI** = ASVK Custom RSI (см. [[asvk-custom-rsi]]), а не классический Wilder RSI.
- **Время в чате** = всегда UTC+3 (данные внутри проекта остаются UTC).
- **VC** = volume confirmation = FVG-15m/20m внутри OB-1h/2h того же направления (геометрия, объём не участвует).
- **RDRB V1 / V2** = разные версии зоны одного паттерна, обе канон.
- **i-RDRB** = зона RDRB V1, пробитая 1h-close и инвертированная (4-свечной элемент).
- **NF** = свеча марубозу (тело ≥ 95% диапазона).

## RDRB V2 в коде + canon-фиксация V1+V2

Решение пользователя 2026-05-19: **V1 и V2 — канон, V3 (MAX) отклонён**.

**Canon обновлён** ([[что такое rdrb]]): V3 помечен ❌, trade-off-секция переписана.

**Код** (`strategies/strategy_rdrb.py`):
- `RDRBZone` — добавлено поле `zone_version`.
- `detect_rdrb(df, idx, zone_version="V1")` — поддерживает V1/V2; неизвестная (в т.ч. `"V3"`) → `ValueError`.
- `detect_strategy_rdrb_signals(..., zone_version="V1")` — пробрасывает версию.
- В выход сигнала добавлено `rdrb_zone_version`.

**Тесты** (`tests/test_strategy_rdrb.py`, новый файл): 9 тестов — happy-path LONG/SHORT × V1/V2, edge cases (нет паттерна, idx вне диапазона, пустой df, невалидная версия). Полный pytest проекта зелёный (67 тестов).

**Приоритеты обновлены** — A/B test «V1 vs V2 vs V3» → «V1 vs V2».

## Стратегия «бабай» — спроектирована, забэктестена, отложена

См. [[babai]] и память `babai-strategy-in-design.md`.

Сетап **LONG only** (12h):

| Элемент | Правило |
|---|---|
| OB | LONG OB с выраженной зоной ликвидности (12h) |
| Зона ликвидности | `[prev.low, cur.low]` |
| Вход | `entry = prev.low + 0.9·(cur.low − prev.low)`, buy-limit без срока |
| SL | `sl = prev.low + 0.2·(cur.low − prev.low)` |
| Зона 1 | `[cur.low, cur.high]` |
| Фильтр зоны 1 | LONG FVG на 2h/3h/4h (окно OB 24h, пересечение) |
| TP | самый низкий `bottom` из этих FVG |

**Замер 2026-05-19 (BTCUSDT 12h, с 2020):** 58 OB с маркером → 53 с FVG в зоне 1 → −12 вырожденных (TP≤entry) → **41 валидный** → 25 win / 12 loss / 4 unfilled, **WR 67.6%, +4.78R**, +0.13R/сделку, avg win 0.67R. CSV: `signals/babai_backtest_12h_2020.csv`.

Edge тонкий — правило «TP = самый низкий bottom» делает таргет крошечным и даёт 23% нерабочих сетапов. **Отложено** до решения по TP-правилу и роли ASVK Trend Line / Money Hands (пока без роли).

## Главное эмпирическое открытие — предсказание фракталов

См. [[reversal-3candle-fractal-prediction]].

База на D BTCUSDT (3194 свечей с 2017): P(HH)=13.5%, P(LL)=13.7%.

### Топ-стэки

- **HH (вершина):** `shooting_star + left_half_done + (FVG-first-touch | OB-liq-first-touch) SHORT` → **84.6% (11/13)**, lift ×6.3, +71.2 pp.
- **LL (дно):** `hammer + low_left_half_done + (FVG-first-touch | OB-liq-first-touch) LONG` → **76.9% (20/26)**, lift ×5.6, +63.2 pp.

### Ключевые субусловия

- shooting_star → P(HH)=37.3% (N=83). hammer → P(LL)=36.1% (N=147).
- left_half_done (`high[i] > high[i-1, i-2]`) → P(HH)=37.1% (N=1158). low_left_half → P(LL)=43.2%.
- FVG first-touch (SHORT) → P(HH)=29.7%; OB-liq first-touch (LONG) → P(LL)=**49.2%** ⚡
- Doji, bearish_engulfing — почти не работают.
- Sweep — есть сигнал (+10–13pp), но размывает precision после ss+lh.

### Асимметрия HH vs LL

LL-сигналы стабильно сильнее на BTC (uptrend bias): OB-liq LONG first-touch 49% vs SHORT 18%, llh 43% vs lh 37%, LL-топ имеет 2× выборку HH-топа.

## Новый pitfall — zone mitigation

См. [[zone-mitigation-filter-required]], добавлен в [[known-pitfalls]].

Zone-overlap фильтры **обязательно** должны учитывать митигацию (минимум — «первый touch»). Без этого FVG/OB фильтры покрывают 94% свечей за 8.7 лет и теряют дискриминантную силу. С митигацией: lift ×0 → lift ×2.2.

## Reversal-3candle setup — отложен на одном условии

См. [[reversal-3candle-fractal-prediction]] и память `reversal-3candle-setup.md`.

**Условие 1** зафиксировано: `cur.close < prev.high` — тело свечи i закрылось ниже хая предыдущей (затухание восходящего импульса). Условия 2+ не названы — пользователь свернул к brainstorm + эмпирике фрактал-предсказания (см. главное открытие выше).

## Артефакты

- **Код**: `strategies/strategy_rdrb.py` (+V2), `tests/test_strategy_rdrb.py` (новый).
- **Canon**: `vault/knowledge/smc/что такое rdrb.md` (V3 ❌).
- **Backtest CSV**: `signals/babai_backtest_12h_2020.csv` (58 строк).
- **Memory** (8 файлов): `rsi-means-asvk-custom-rsi`, `display-time-in-utc-plus-3`, `vc-means-volume-confirmation`, `rdrb-v1-v2-distinct-zones`, `i-rdrb-definition`, `nf-means-marubozu-candle`, `babai-strategy-in-design`, `reversal-3candle-setup`.

## Открытые задачи

1. **Бабай**: пересмотреть TP-правило (TP = top FVG / fixed RR / другое?), задать роль ASVK Trend Line + Money Hands. Снять «без срока годности» у лимитки (тайм-стоп).
2. **Backtest торговли на HH/LL топ-стэках**: SHORT/LONG @ close(i), SL за экстремумом — стабильность по годам.
3. **OOS на ETH/SOL** для HH/LL-сетапов — повторяется ли асимметрия HH < LL?
4. **Reversal-3candle setup** — добавить условия 2+ при возобновлении.
5. **A/B тест RDRB V1 vs V2** на `strategy_rdrb.py` — V2 ещё не использовалась реально.

## Шрифты

Пользователь упомянул проблему с отображением (эмодзи/Unicode). При возобновлении сессии — если шрифты не починены, перейти на ASCII-вывод без эмодзи-стрелок.
