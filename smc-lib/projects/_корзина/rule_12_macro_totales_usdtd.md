# [ARCHIVED] Правило 12 — Макроиндикаторы TOTALES и USDT.D

> ⚠ **Архивировано 2026-06-14** решением пользователя. Перенесено из `~/smc-lib/rules.md`.
>
> Macro confluence канон deprecated как часть справочника правил. Macro features whitelist остаётся в memory (`feedback-macro-features-preference`).

---

Контекст рынка для подтверждения BTC-сигналов (confluence layer над стратегиями).

### Определения

**TOTALES** — суммарная капитализация криптовалютного рынка **БЕЗ учёта стейблкоинов**.
- = total market cap (BTC + ETH + ALTS) − stablecoin caps
- TradingView ticker: `CRYPTOCAP:TOTAL2` или агрегат
- Семантика: «деньги в крипте» (риск-он капитал)
- TOTALES ↑ = capital flowing into crypto (bullish)
- TOTALES ↓ = capital выходит (bearish)

**USDT** — самый популярный стейблкоин (Tether). Привязан 1:1 к USD.

**USDT.D** (USDT Dominance) — **индекс доли USDT в общей капитализации крипторынка**.
- = USDT_market_cap / TOTAL_crypto_market_cap × 100%
- TradingView ticker: `CRYPTOCAP:USDT.D`
- Семантика: «доля кэша в крипто-портфелях»
- USDT.D ↑ = капитал перетекает в стейблы (risk-off, **bearish для BTC/altcoins**)
- USDT.D ↓ = капитал из стейблов идёт в крипту (risk-on, **bullish для BTC/altcoins**)

### Важнейшее свойство — зеркальность

USDT.D **антикоррелирован** с TOTALES (и BTC):
- TOTALES ↑ обычно ↔ USDT.D ↓ (деньги входят в крипту → доля USDT уменьшается)
- TOTALES ↓ обычно ↔ USDT.D ↑ (деньги выходят в стейблы → доля USDT растёт)

Это даёт **двойную независимую проверку** market regime.

### Confluence rule для BTC-стратегий

Для BTC trade в направлении X (LONG / SHORT):

| Indicator | Same / Mirror | Логика |
|---|---|---|
| **TOTALES** | **SAME** direction | crypto market растёт ↔ BTC LONG валиден |
| **USDT.D** | **OPPOSITE** direction (mirror) | капитал выходит из стейблов ↔ BTC LONG валиден |

**Подгруппы confluence**:
- `TOTALES match only` — только TOTALES согласен
- `USDT.D mirror only` — только USDT.D согласен (mirror)
- `Triple confluence` — оба согласны (TOTALES same + USDT.D mirror)
- `Any sync` — хотя бы один
- `No sync` — оба против → **отказать в сделке** (или signal вне макро-контекста)

### Critical lookahead guardrail

Direction TOTALES / USDT.D определять **ТОЛЬКО по закрытым свечам** (например предыдущий 1d close).

**Известный bug** (исправлен в сессии): прошлая реализация анализатора `analyze_rdrb_confluence_macro.py` использовала close **сегодняшней (незакрытой) свечи** для определения direction. Это давало lookahead ~12 часов в среднем, ~24+ часа в 17% случаев. WR Triple confluence был завышен на ~10pp.

**Канон**: для timestamp T использовать direction за период `[T - N×1d, T_prev_closed_day_close]`, где `T_prev_closed_day_close` — close последней **полностью** закрытой daily candle (не включает intra-day движение текущего дня).

См. `~/traid-bot/vault/knowledge/debugging/confluence-lookahead-and-rr22-bugs.md`.

### Параметры (canonical defaults)

| Параметр | Значение | Обоснование |
|---|---|---|
| Lookback period | **3 closed daily bars** | Стабильность direction без noise |
| Direction rule | `close[T_now] > close[T_now − N]` для UP / mirror для DOWN | Net change за N дней |
| Strict timing | Только closed candles | Никакого lookahead |
| Default N | 3 (по умолчанию) | Из старой логики; можно тюнить per-стратегия |

### Data sources

| Indicator | Файл | TF | Статус |
|---|---|---|---|
| TOTALES | `~/traid-bot/data/TOTALES_{15m,1h,4h,1d}.csv` | 15m, 1h, 4h, 1d | ✓ есть |
| USDT.D | _нет локально_ | Fetch требуется | ✗ TBD |

### Применение в стратегиях

Confluence — **опциональный фильтр** или **scoring boost**, не hard filter. Опции:

| Подход | Применение |
|---|---|
| **Hard filter** | Trade ONLY если Triple confluence — selective, freq −50% |
| **Direction veto** | Skip если No sync (оба против) — мягко, freq −10-20% |
| **Sizing modifier** | Triple = 1.5× position, Any sync = 1× , No sync = 0.5× |
| **Scoring feature** | Добавить в ML head как feature, не hard rule |

Strategy 1.1.1 V2 design doc: «опционально — как ml-feature, не hard filter».

### Связи

- `[[Правило 5 (ARCHIVED)]]` — основная стратегия ASVK (может использовать confluence как F4 layer)
- `feedback-1-1-1-floating-without-totales-usdtd` — мой 6y benchmark +196R НЕ включает TOTALES/USDT.D
- `feedback-macro-features-preference` — whitelist macro features (canonical preferences остаются в memory)
- `~/traid-bot/vault/knowledge/debugging/confluence-lookahead-and-rr22-bugs.md` — lookahead bug post-mortem
- `~/traid-bot/research/rdrb/analyze/analyze_rdrb_confluence_macro.py` — existing analyzer (используется как reference, не как production code)

### Открытые вопросы

1. **Lookback N**: 1, 3, 5, 7 дней? Зависит от стратегии (intraday vs swing)
2. **TF для direction**: 1d default, но 4h для быстрых стратегий, 1w для swing?
3. **TOTAL vs TOTAL2 vs TOTAL3**: какой агрегат канонический? (TOTAL = вся капитализация включая BTC; TOTAL2 = без BTC; TOTAL3 = без BTC+ETH)
4. **Threshold** для «direction confirmed»: net change > 0%? > 0.5%? > 1%?
5. **USDT.D vs USDC.D vs USD.D combined**: смотреть только USDT или агрегат stablecoin dominance?
6. **Fetch USDT_D**: source (TradingView API? CoinGecko? Binance index?)
