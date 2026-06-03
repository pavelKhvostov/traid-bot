# prediction-algo

Обучающийся алгоритм прогноза зон интереса BTC: на момент NOW
выдаёт top-K зон сверху + top-K снизу с вероятностями касания
в горизонтах 12h и D.

## Финальные результаты walk-forward (год 6 на 6y данных)

| Метрика | Значение |
|---|---|
| Top-5 hit_D accuracy | **87.0%** vs random 1.2% (lift 72×) |
| Brier D | 0.0073 vs baseline 0.0133 (−45%) |
| Top-3 ABOVE | 80.9% |
| Top-3 BELOW | 81.0% |

Re-train cadence не влияет (monthly ≈ weekly ≈ one-shot).
Это значит зональные паттерны на BTC устойчивы во времени.

## Параметры задачи (зафиксированы 2026-05-28)

| # | Параметр | Решение |
|---|---|---|
| 1 | Mitigation | per-zone канон (wick-fill / first-touch / sweep) |
| 2 | Horizon | multi: **12h + D** |
| 3 | TF set | 1h, 4h, 12h, 1d (экспериментально) |
| 4 | Top-K | гибко 2+3 / 3+2 |
| 5 | Re-train | агрессивно на году 6 |
| 6 | Universe | BTC only |
| 7 | Cut-off | run-time (по запросу) |
| 8 | Split | train 1-5 / test 6 |
| 9 | Zone types | 10 типов из `~/smc-lib/elements/` |

## Структура

```
prediction-algo/
├── README.md          (этот файл)
├── data.py            загрузка 1m BTC CSV
├── resample.py        1m → 15 TF, Monday-anchored W, strict cut-off
├── zones.py           детекция и mitigation 10 типов зон
├── labels.py          hit-detection на 12h/D через 1m
├── dataset.py         сбор обучающего датасета + CLI
├── model.py           Phase 1 lookup-модель (иерархический lookup)
├── validate.py        walk-forward harness
├── cli.py             predict_zones BTC — top-K с вероятностями
├── zones_opinion.py   экспертное заключение (кластеризация + сценарии)
└── tests/             66 unit-тестов
```

## Команды

```bash
# Top-K предсказание
python3 cli.py --top-k 5

# Экспертное заключение по зонам (карта + базовый прогноз + сценарии)
python3 zones_opinion.py

# Walk-forward на году 6
python3 -c "
from validate import walk_forward, print_result
import pandas as pd
ds = pd.read_csv('/Users/vadim/Desktop/btc_full.csv')
r = walk_forward(ds, test_start=pd.Timestamp('2025-05-01', tz='UTC'),
                 test_end=pd.Timestamp('2026-05-01', tz='UTC'),
                 train_window_days=365, retrain_freq_days=30)
print_result(r)
"

# Сборка нового датасета
python3 dataset.py --start 2020-05-01 --end 2026-05-01 \
    --step-hours 12 --tfs 1h,4h,12h,1d \
    --out ~/Desktop/btc_full.csv

# Тесты
python3 -m pytest tests/ -v
```

## Триггеры

- «**предскажи зоны BTC**» → `python3 cli.py`
- «**экспертное заключение по зонам**» → `python3 zones_opinion.py`
- «**где цена сперва двинется**» → `zones_opinion.py` (базовый прогноз + сценарии)

## Артефакты

- Тренировочный датасет: `~/Desktop/btc_full.csv` (5.49M записей × 6 лет BTC × 4382 cut-offs)
- Заметки проекта: `~/smc-lib/projects/prediction-algo.md`

## Связанные

- `~/smc-lib/elements/` — детекторы 11 типов зон (10 используем как targets)
- `~/smc-lib/zone_of_interest.md` — канон mitigation rules (wick-fill/first-touch/sweep)
- `~/smc-lib/pivot-money-hands/` — параллельный проект pivot prediction через MoneyHands
- `~/smc-lib/expert/opinion.py` — multi-TF cascade expert opinion (другая методология)
