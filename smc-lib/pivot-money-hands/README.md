# pivot-money-hands

Мини-библиотека для исследования: предсказание **pivot'ов на 1h TF**
через мульти-TF состояние индикатора **MoneyHands**.

## Задача

Синхронизированно снимать значения MoneyHands на 7 TF
(3D, 1D, 12h, 8h, 4h, 2h, 1h) → искать паттерны которые предшествуют
pivot'ам на 1h → предсказывать долгосрочные/краткосрочные точки
разворота на горизонте 12-24h.

## Структура

```
pivot-money-hands/
├── README.md              (этот файл)
├── multi_tf_mh.py         multi-TF снимок MoneyHands @ ts
├── pivots.py              детекция 1h pivots (Williams N=2 + фильтры)
├── dataset.py             сбор labeled датасета
├── analysis.py            EDA + pattern mining
├── model.py               classifier
├── validate.py            walk-forward
└── tests/
```

## Конвенции

- 1m исходник: `~/traid-bot/data/BTCUSDT_1m_vic_vadim.csv`
- Resample: используем `~/smc-lib/prediction-algo/resample.py`
  (Monday-anchored W, strict cut-off)
- MoneyHands: `~/smc-lib/indicators/money_hands_asvk.py`
- Pivot canon: Williams fractal N=2 на 1h (`~/smc-lib/elements/fractal/`)
  - FH = SHORT-pivot (top)
  - FL = LONG-pivot (bottom)

## Базовое определение pivot

Williams fractal N=2 на 1h — 5-свечной локальный экстремум.
Подтверждается через 2 бара после центра.

Возможные доп. фильтры (опционально):
- **hold-time**: pivot не свипнут K баров после подтверждения
- **magnitude**: цена развернулась минимум на X% от уровня pivot

## Связанные memory

- `[[feedback-fractal-liquidity-strength-and-sweep]]` — сила фрактала
- `[[12h-fractal-prediction-final-strategy]]` — параллельный 12h fractal проект
- `[[btc-data-1m-csv]]` — путь к 1m данным
