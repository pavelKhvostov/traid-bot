---
tags: [debugging, data-integrity, backtest, lookahead-adjacent]
date: 2026-05-08
related: [research/elements_study/etap_27_fix_2022_gap.py]
---

# 2022 пропадал из year-by-year breakdown — это был data gap, а не «нет setups»

## Что было

В `data/BTCUSDT_1m.csv` отсутствовали 480 дней — с 2022-01-01 00:00
до 2023-04-26 21:33. CSV содержал ~3.3M баров вместо ожидаемых ~3.95M.

Все backtests (etap_14, etap_15, ранние confluence-анализы) запускались
от `2020-01-01` и в year-by-year выводили:

```
2020: n=42, WR 55%, +4R
2021: n=57, WR 58%, +9R
2023: n=40, WR 52%, +2R   <-- начинается с мая, выглядит как "low activity"
2024: n=48, WR 56%, +6R
```

2022 просто отсутствовал в выводе. Никто не задал вопрос «почему?» —
все автоматически интерпретировали как «не было setups в bear market».

## Симптом

- **Year отсутствует** в year-by-year breakdown (не «n=0», а вообще нет строки).
- Соседний год (2023) имеет аномально мало setups в начале.
- Год покрывает мощный bear/event period (LUNA май 2022, FTX ноябрь 2022) —
  стратегия должна была давать setups, и их «отсутствие» странно.
- Total setups резко ниже наивного `years × avg_setups_per_year`.

## Причина

Bootstrap CSV изначально качался с лимитом или прервался; gap не был замечен,
потому что `pd.read_csv` молча возвращает то что есть, а year-by-year groupby
не выдаёт строки для пустых годов.

## Правило избегания

**При backtest от длинной даты (2-3+ года) — всегда проверять полноту
данных перед интерпретацией результатов:**

```python
years_in_data = df.index.year.unique()
expected_years = set(range(start_year, end_year + 1))
missing = expected_years - set(years_in_data)
if missing:
    raise ValueError(f"Data gap: missing years {missing}")

# Дополнительно — gap между соседними барами
gaps = df.index.to_series().diff()
big_gaps = gaps[gaps > pd.Timedelta(hours=1)]
if not big_gaps.empty:
    print(f"WARNING: {len(big_gaps)} gaps > 1h, max gap {gaps.max()}")
```

**Если год отсутствует в year-by-year — это НЕ «не было setups», это data gap.**
Любой `groupby(df.index.year)` который не показывает год — RED FLAG.

## Что fix дал

После `etap_27_fix_2022_gap.py` (Binance REST `fetch_klines_range`,
692,561 баров за 471 секунду):

| Кандидат | До fix | После fix | Δ |
|---|---|---|---|
| C2 (OB-6h × FVG-2h pro) | +48R, 4y | **+70R, 7y** | +22R благодаря 2022 |
| D2 (OB-12h opt) | WR 47.2% | WR 44.4% | 2022 был −6.25R |
| C1, C6 | 0-1 минусовых лет | +1 минусовый год | 2022 был трудный |

C2 стала новым #1 winner с **0 минусовых лет за 7 лет** — лучшая статистика
именно благодаря тому что 2022 (ужасный год) тестировался с правильными данными.

Strategy 1.1.1 «honest audit» обнаружила что заявленные +46.8R/3y превратились
в +20R/6.33y частично потому что 2022 (отсутствовавший в исходном тесте) для неё
был нейтральный/отрицательный.

## Связи

- [[lookahead-anchor-confirm-окно-cur_open-cur_close]] — другой pitfall
  обнаруженный в той же сессии
- [[multi-bar-pattern-confirm-vs-trigger-lookahead]] — partner pitfall #2 этап 33
- [[strategy-1-1-1-honest-audit-failed]] — case study где data gap дал
  inflation +30% к total_R
- [[strategy-c2-ob-6h-fvg-2h-pro-rr1]] — winner после fix
