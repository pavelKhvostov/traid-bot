# smc-lib

Библиотека формальных определений и кода SMC-элементов.

## Структура

Каждый элемент — самостоятельная папка в `elements/`:

```
elements/<element_name>/
  definition.md       # формальное определение (предусловия, формулы, примеры)
  code.py             # эталонная реализация
  tests/
    test_<name>.py    # юнит-тесты на эталонных примерах
    fixtures.json     # OHLCV-фикстуры (опционально)
```

## Соглашения

- **Свечи** — OHLCV-словарь или dataclass с полями `open, high, low, close, volume, open_time` (UTC).
- **Тело свечи**: `body_top = max(open, close)`, `body_bottom = min(open, close)`.
- **Вики**: верхний = `[body_top, high]`, нижний = `[low, body_bottom]`.
- **Зоны** возвращаются как `(bottom, top)` в ценовых координатах.
- **Время в коде/данных** — UTC. В чате/визуализации — UTC+3.
- **Версии паттернов** (V1, V2, ...) — стабильные, не переписываются. Новая ревизия = новая папка `<name>_v2/`.

## Текущие элементы

- `ob/` — **OB (Order Block)**. Канонический 2-свечный паттерн (`prev`, `cur`): LONG = prev bear + cur bull, `cur.close > prev.open`; SHORT — зеркально. Зона интереса (vault canon): LONG `[min(prev.low, cur.low), prev.open]`, SHORT `[prev.open, max(prev.high, cur.high)]`.
- `rdrb/` — 3-свечный RDRB. Три зоны: **POI** (гэп тел), **block** (пересечение виков, `⊆ POI`), **liq** (`POI \ block`). Варианты: **V1** (liq непустой) / **V2** (block == POI, liq пустой). Направление задаёт C2 (bear → SHORT, bull → LONG).
- `i_rdrb/` — 4-свечный i-RDRB: RDRB (C1-C3) + displacement-свеча C4. Направление задаёт **C4**, независимо от направления подлежащего RDRB. LONG: C4 bull AND `C4.close > block.top`. SHORT: C4 bear AND `C4.close < block.bottom`.
- `fvg/` — 3-свечный Fair Value Gap. LONG (bullish): `c1.high < c3.low`, zone = `[c1.high, c3.low]`. SHORT (bearish): `c1.low > c3.high`, zone = `[c3.high, c1.low]`. При композиции с i-RDRB: FVG.c1=C3, FVG.c2=C4, FVG.c3=C5.
- `ob_liq/` — **OB с явно выраженным уровнем ликвидности**. Composite: canon-OB (пара `prev`/`cur`) + 2-условный маркер (выраженность фитиля 3×, фитиль > тела). **2-свечный паттерн** `(prev, cur)`. Зона входа = canon-OB, отдельная **liq_zone** — полоса фитиля prev. *(Williams-фрактальность УБРАНА из канона 2026-05-27.)*
- `rb/` — **RB (Rejection Block)**. Одиночная свеча: доминирующий фитиль ≥ 2× второго И ≥ 3× тела. TOP RB (bearish) / BOTTOM RB (bullish). Зона интереса = область доминирующего фитиля. Эталон: BTC 12h 2026-04-14 15:00 MSK, TOP RB, zone=[74376.52, 76038.00].
- `block_orders/` — **Блок ордеров (HTF-OB)**. Композит: **preceding** свеча (противоположной направленности) + N₁ ≥ 1 initial-свечей + N₂ ≥ 1 counter-свечей. Counter STOP на ПЕРВОЙ свече с close-crossing `block.open`. `(N₁, N₂) ≠ (1, 1)` — иначе canon-OB. Зона интереса: LONG `[block.low, block.close]` / SHORT `[block.close, block.high]` (breaker block + drop/rally area). Эталон: BTC 1h 2026-05-05 LONG, zone=[79744.91, 80352.00].
- `i_fvg/` — **Inverse FVG**. Композит: FVG-B противоположного направления первой касается ранее untouched FVG-A. Зона интереса = overlap A ∩ B. Роль A инвертирует (support ↔ resistance). Направление = направление B.
- `marubozu/` — **Marubozu**. Одиночная свеча без фитиля со стороны open. Canon Pine WICK.ED: LONG `open == low AND close > open`, SHORT `open == high AND close < open`. Зона = тело свечи.
- `fractal/` — **Williams Fractal (FH/FL)**. Strict swing point на `(2N+1)`-bar окне (default N=2 = 5-bar). FH = `center.high` > всех соседей, FL = `center.low` < всех соседей. Зона = **точка/уровень** (единственный primitive с точечной зоной). Class = liquidity.

## Setup patterns (вне elements/)

- `patterns/` — полные setup-паттерны с entry/SL/TP (в отличие от `elements/` где только canon zone):
  - `patterns/run_3candles_sweep/` — 3-свечный liquidity grab continuation (3 same direction + c2 wick ≥2.5×body + **sweep c1 high/low**). Setup: Entry=0.3×wick c2, SL=c2 extremum, TP=c3 opposite extremum. Эталон: BTC 8h 2026-05-26.
  - `patterns/i_rdrb_fvg/` — **i-RDRB с последующим FVG**. 5-свечный композит: i-RDRB (C1-C4) + FVG (C3-C4-C5) одного направления. Основной паттерн forensic-стенда (1h BTC, baseline 780 сделок).
- `ob_sweep_liq_4candles/` — **Снятие ликвидности Williams-фрактала**. Reference = Williams FH/FL anchor любой давности. Sweep candle Y: открытие по другую сторону от фрактала + wick через уровень + close за close фрактал-бара. SHORT/LONG mirror. Имя `_4candles` — историческое. Эталон: BTC 6h SHORT, anchor 2026-05-25 15:00 MSK FH 77906, y 2026-05-26 15:00.

## Candle patterns (вне elements/ и patterns/)

- `candle_patterns/` — **классические свечные паттерны** (japanese candlesticks): hammer, doji, engulfing, morning star, three soldiers и т.п. **Только сигнал** (signal-only), без entry/SL/TP. Не имеют встроенной zone of interest (если есть зона — это `elements/`, например marubozu / rb). 🟡 в разработке.

## Predicate (вне elements/)

- `vc/` — **VC (Volume Confirmation)**. **Не зона интереса, а предикат** над HTF-зоной. Расположен на top-level (а не в `elements/`), т.к. это семейство boolean-проверок, не SMC primitive. Канонические варианты — см. Правило 3 в `rules.md`. API: `has_vc(ob, fvg) → bool`, `find_vc_confirmations(ob, ltf_fvgs) → list[FVG]`.

## Планируется

- `maxv/` — ViC ASVK maxV (LTF=1m canon)
- `liquidity/` — liq-таргеты, иерархия по TF

## Справочники

- [`zone_of_interest.md`](./zone_of_interest.md) — что считать «зоной интереса» для каждого элемента (OB, FVG, RDRB, ob_liq, фракталы и др.). Главный лукап, когда пользователь говорит «зона интереса».
- [`rules.md`](./rules.md) — общие рыночные правила, применимые ко всем элементам. **Правило 1** — закрепление цены за уровнем (2 close = пробой).
- [`chart_format.md`](./chart_format.md) — канонический шаблон прорисовки графиков (формат, цвета, layout, какие индикаторы / зоны / маркеры). 🟡 в разработке.
- [`expert/`](./expert/) — **Экспертный слой**: каноничный композит-чарт + multi-TF cascade-заключение. Содержит `chart.md` + `chart.py` (триггер «экспертный график») и `opinion.md` + `opinion.py` (триггер «экспертное заключение»).

## Проекты

- [`projects/`](./projects/) — прикладные пайплайны на основе canon (semi-canon). Текущие:
  - [`pred12h-fractal-three-candles`](./projects/pred12h-fractal-three-candles.md) — прогнозирование Williams-фрактала 12h по (i-2, i-1, i) + OR-basket С1-С7. Recall 15/18, basket WR 66.8%.

## Методология

- [`expert/`](./expert/) — экспертный слой (chart + opinion), см. выше в разделе «Справочники».
- [`scripts/fetch_btc_1m_missing.py`](./scripts/fetch_btc_1m_missing.py) — докачка 1m-свечей с Binance через curl (обходит SSL-проблемы urllib).

## Запуск тестов

```bash
cd ~/smc-lib
python3 -m pytest elements/<name>/tests/ -v
```
