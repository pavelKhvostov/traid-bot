---
tags: [strategy, detector, bulkowski, etap-172, ml-pivot]
date: 2026-06-03
status: baseline-done
file: research/elements_study/etap_172_bulkowski_patterns.py
---

# Bulkowski reversal detectors — BTC 12h baseline (etap_172)

13 чистых детекторов reversal-паттернов на BTC 12h. **Pure detection layer**:
не торговая логика, не фильтрация — только геометрическое распознавание + walk-forward
Bulkowski-style outcome statistics.

См. [[bulkowski-top-12-patterns-for-btc-12h]] для обоснования выбора и
[[2026-06-03-bulkowski-12-reversal-detectors-etap-172]] для контекста сессии.

## Контракт детектора

```python
def detect_<name>(df: pd.DataFrame, i: int, lookback: int = ...) -> dict | None:
    """
    Возвращает dict с meta паттерна если на баре i подтверждён breakout впервые;
    иначе None.

    Все компоненты паттерна (peaks/valleys) — confirmed (фрактал N=2, right-side
    подтверждение j+2 ≤ i). Никакого lookahead'а.
    """
```

Структура возвращаемого dict:
```python
{
    'pattern': str,           # 'big_w', 'hs_top', ...
    'side': 'long' | 'short',
    'breakout_idx': int,      # = i
    'breakout_price': float,  # = close[i]
    'low_idx': int,
    'low_price': float,
    'high_idx': int,
    'high_price': float,
    'height_pct': float,      # высота паттерна в %
    'duration_bars': int,
    'neck_price': float,      # confirmation line price на breakout
}
```

## Реализованные 13 паттернов

| Side | Pattern | Lookback | Главные геометрические условия |
|---|---|---|---|
| LONG | `big_w` | 60 | 2 swing lows ±3%, peak ≥3%, **tall left** ≥ height, close > peak |
| LONG | `db_eve_eve` | 60 | 2 lows ≥5 баров apart, rounded (body/range<0.6), close > peak |
| LONG | `hs_bottom` | 60 | 3 valleys, middle deepest, shoulders ±6%, close > neckline |
| LONG | `v_bottom` | 20 | drop≥8% + rebound≥50% drop, close > midpoint |
| LONG | `barr_bottom` | 40 | lead-in downtrend slope<0, bump slope steeper, close > lead-in line |
| LONG | `rounding_bottom` | 40 | парабола y=ax²+bx+c, a>0, R²≥0.55, vertex в средней 1/3, rims ±6% |
| LONG | `cup_handle` | 60 | rounded U + handle 3-15 баров, retrace ≤50%, R²≥0.45, close > right rim |
| SHORT | `big_m` | 60 | mirror big_w |
| SHORT | `hs_top` | 60 | mirror hs_bottom |
| SHORT | `triple_top` | 60 | 3 peaks ±3%, ≥2 valleys, close < lowest valley |
| SHORT | `v_top` | 20 | mirror v_bottom |
| SHORT | `barr_top` | 40 | mirror barr_bottom |
| SHORT | `diamond_top` | 40 | range slope_left>0 (broadening), slope_right<0 (narrowing), close < last low |

## Walk-forward outcome (Bulkowski-style)

Ultimate extreme = максимальный favor (move в сторону сигнала) до **20% counter-move**
от пика. Если 20% не достигнуто за 240 баров (120 дней) — берём max favor на отрезке.

Метрики per signal:
- `bars_to_extreme` — баров до ultimate
- `ult_move_pct` — финальный favor в %
- `max_adverse_pct` — худшее adverse в %
- `busted` — `peak_favor < 10%` И close пересёк противоположную сторону паттерна
- `reached_target` — `ult_move ≥ height_pct` (full measure rule)
- `reached_half_target` — `ult_move ≥ height_pct/2` (half measure rule)

## TRAIN результаты (2020-01 → 2024-12, 520 сигналов)

Топ-5 по комбинированному edge:

1. **big_w** (long): 89 сигналов, +29.8% avg, 17% fail, **90% half-target**
2. **db_eve_eve** (long): 49, +29.6%, 16% fail
3. **v_bottom** (long): 42, +26.6%, **14% fail** (best)
4. **hs_bottom** (long): 30, **+31.6%** (best avg), 13% fail
5. **big_m** (short): 87, +16%, 21% fail — единственный short с массой

`cup_handle` и `rounding_bottom` **не находятся** на BTC 12h — R²-thresholds
слишком строгие для волатильности крипты. В etap_173 v2 планируется
loose: R²≥0.40 + расширенный lookback 80.

## Что детектор НЕ делает

- ❌ Не ставит SL / TP / RR (это не торговая логика)
- ❌ Не комбинирует паттерны (один бар может породить 2+ сигнала независимо)
- ❌ Не различает bull/bear market regime (это задача ML)
- ❌ Не фильтрует по тренду / зонам / индикаторам

## Зависимости

- `data_manager.load_df`, `compose_from_base` — данные
- `numpy` — `polyfit` для регрессий
- `pandas` — DataFrame ops

Никаких `talib`, `ta-lib`, никакого ML кода.

## Артефакты

- Код: [etap_172_bulkowski_patterns.py](../../research/elements_study/etap_172_bulkowski_patterns.py)
- Stats per pattern × period: `research/elements_study/output/etap_172_stats.csv`
- Raw сигналы с outcomes: `research/elements_study/output/etap_172_signals.csv`
- Run log: `research/elements_study/output/etap_172_run.log`

## Next: etap_173

Добавить top-5 паттернов как фичи в etap_171 модель:
- `pattern_fired_<name>`: 1 если на текущем баре fired
- `bars_since_<name>`: decay-count с последнего fire (max 60)
- `height_pct_<name>`: last height_pct
- `busted_<name>_recent`: для shorts — флаг busted (потенциальный +67% edge на H&S Top)

Сравнить AUC и precision@P≥0.7 с baseline etap_171.
