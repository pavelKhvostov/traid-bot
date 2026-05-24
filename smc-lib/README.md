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
- `ob_liq/` — **OB с явно выраженным уровнем ликвидности**. Composite: canon-OB (пара `prev`/`cur`) + 3-условный маркер (выраженность фитиля 3×, фитиль > тела, prev = Williams 5-bar HH/LL). 5-свечное окно `(prev-2, prev-1, prev, cur, cur+1)`. Зона входа = canon-OB, отдельная **liq_zone** — полоса фитиля prev.
- `i_rdrb_fvg/` — **i-RDRB с последующим FVG**. 5-свечный композит: i-RDRB (C1-C4) + FVG (C3-C4-C5) одного направления. Основной паттерн forensic-стенда (1h BTC, baseline 780 сделок).
- `rb/` — **RB (Rejection Block)**. Одиночная свеча: доминирующий фитиль ≥ 2× второго И ≥ 3× тела. TOP RB (bearish) / BOTTOM RB (bullish). Зона интереса = область доминирующего фитиля. Эталон: BTC 12h 2026-04-14 15:00 MSK, TOP RB, zone=[74376.52, 76038.00].
- `block_orders/` — **Блок ордеров (HTF-OB)**. Композит: **preceding** свеча (противоположной направленности) + N₁ ≥ 1 initial-свечей + N₂ ≥ 1 counter-свечей. Counter STOP на ПЕРВОЙ свече с close-crossing `block.open`. `(N₁, N₂) ≠ (1, 1)` — иначе canon-OB. Зона интереса: LONG `[block.low, block.close]` / SHORT `[block.close, block.high]` (breaker block + drop/rally area). Эталон: BTC 1h 2026-05-05 LONG, zone=[79744.91, 80352.00].
- `i_fvg/` — **Inverse FVG**. Композит: FVG-B противоположного направления первой касается ранее untouched FVG-A. Зона интереса = overlap A ∩ B. Роль A инвертирует (support ↔ resistance). Направление = направление B.
- `marubozu/` — **Marubozu**. Одиночная свеча без фитиля со стороны open. Canon Pine WICK.ED: LONG `open == low AND close > open`, SHORT `open == high AND close < open`. Зона = тело свечи.
- `fractal/` — **Williams Fractal (FH/FL)**. Strict swing point на `(2N+1)`-bar окне (default N=2 = 5-bar). FH = `center.high` > всех соседей, FL = `center.low` < всех соседей. Зона = **точка/уровень** (единственный primitive с точечной зоной). Class = liquidity.

## Планируется

- `maxv/` — ViC ASVK maxV (LTF=1m canon)
- `liquidity/` — liq-таргеты, иерархия по TF

## Справочники

- [`zone_of_interest.md`](./zone_of_interest.md) — что считать «зоной интереса» для каждого элемента (OB, FVG, RDRB, ob_liq, фракталы и др.). Главный лукап, когда пользователь говорит «зона интереса».
- [`rules.md`](./rules.md) — общие рыночные правила, применимые ко всем элементам. **Правило 1** — закрепление цены за уровнем (2 close = пробой).

## Методология

- [`expert_opinion.md`](./expert_opinion.md) — pipeline из 10 шагов для построения **экспертного заключения** о направлении движения цены (на основе зон + классов + магнит-логики). Применять при запросах "куда пойдёт цена" / "что на графике X".
- [`scripts/expert_opinion.py`](./scripts/expert_opinion.py) — reference-реализация шагов 1–5 (data → detection → position → classification → magnets), output для синтеза шагов 6–10 (structure / scenarios / invalidation).
- [`scripts/fetch_btc_1m_missing.py`](./scripts/fetch_btc_1m_missing.py) — докачка 1m-свечей с Binance через curl (обходит SSL-проблемы urllib).

## Запуск тестов

```bash
cd ~/smc-lib
python3 -m pytest elements/<name>/tests/ -v
```
