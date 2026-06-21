# Expert layer

Самостоятельный слой экспертной оценки рынка: канон-чарт + multi-TF cascade-заключение. Использует всё нижестоящее (`elements/`, `vc/`, `patterns/`, `candle_patterns/`, `indicators/`, `projects/`) как input.

## Состав

| Файл | Что |
|---|---|
| `chart.md` | Спецификация **Экспертного графика** — композит: chart_format база + Pred-12h overlay + HMA 78/200 (12h+D) + VWAPs эффективные/проработанные |
| `chart.py` | Эталон-скрипт. CLI: `python3 chart.py [BTC\|ETH\|SOL]` |
| `opinion.md` | Методология **Экспертного заключения** — multi-TF top-down cascade (W → D → 12h → 4h → 1h → 15m), 10 шагов |
| `opinion.py` | Реализация шагов 1-5 (data → detection → position → classification → magnets) |

## Триггеры (как меня вызывать)

| Запрос пользователя | Что запускается |
|---|---|
| «экспертный график» / «представить экспертный график» / «expert chart» | `python3 ~/smc-lib/expert/chart.py [ASSET]` |
| «экспертное заключение» / «куда пойдёт цена» / «дай мнение» | `python3 ~/smc-lib/expert/opinion.py --tfs W,D,12h,4h,1h,15m` + синтез шагов 6-10 |
| оба | график + заключение в одном ответе |

Output:
- **chart.py** → PNG в `~/Desktop/i-rdrb-charts/<asset>_6h_pred12h_basket_<date>.png`
- **opinion.py** → stdout multi-TF cascade dump для синтеза текстового заключения

## Зависимости

| Модуль | Используется в |
|---|---|
| `../chart_format.md` | визуальная база chart.py |
| `../rules.md` (Правила 6, 7) | VWAPs anchored, TrendLine HMA |
| `../projects/pred12h-fractal-three-candles.md` | F1∩F2∩F3 + C1-C7 basket overlay в chart.py |
| `../indicators/` | HMA, VWAP, ATR, RSI, CD, Hull, MoneyHands, VolumeProfile (opinion.py) |
| `../elements/` | OB, FVG, RDRB, ob_liq, fractal, marubozu, rb, block_orders (opinion.py detection scan) |
| `../zone_of_interest.md` | классификация блок/inefficiency/liquidity (opinion.py Step 4) |
| `../scripts/fetch_1m_missing.py` | auto-update 1m data |

## История

- **2026-05-28** — раздел создан. Перенесены `expert_chart.md` → `chart.md`, `expert_opinion.md` → `opinion.md`, `scripts/plot_expert_chart.py` → `chart.py`, `scripts/expert_opinion.py` → `opinion.py`.
