---
tags: [decision, c2, trend-filter, hull, ema, per-symbol]
date: 2026-05-15
---

# C2 trend filter — EMA-200 OR Hull-6h (per-symbol правило)

## Решение

Для C2 (OB-6h + FVG-2h pro-trend) лучший trend-filter **зависит от символа**:

| Symbol | Best filter | Δ vs EMA-200 alone |
|---|---|---:|
| **BTC** | **EMA-200 OR Hull-6h** | +8R (+24%) |
| **ETH** | **EMA-200 AND Hull-6h** | +21R (+1050%) |
| **SOL** | **EMA-200 OR Hull-6h** | +27R (+193%) |

Per-symbol filter даёт +56R (+114%) vs universal EMA-200.

## Логика

### Маппинг

```python
# trigger FVG-2h формируется в момент t. Проверка на close c2_2h (= t + 2h):

f_ema = close_2h(c2_2h_close) <relation> EMA_200_2h
f_hull6h = close_6h(last_closed_before_c2_2h_close) <relation> hull_6h[t-2]

# Для LONG: relation = ">", для SHORT: "<"
```

Hull-6h использует `length=78` (default из [[asvk-trend-line-hull]]).

### Per-symbol

```python
TREND_FILTER_C2 = {
    "BTCUSDT": lambda t: f_ema(t) or f_hull6h(t),   # OR
    "ETHUSDT": lambda t: f_ema(t) and f_hull6h(t),  # AND
    "SOLUSDT": lambda t: f_ema(t) or f_hull6h(t),   # OR
}
```

## Результаты (BTC/ETH/SOL 3y, RR=1.0)

### Полная сводка

| Filter | BTC | ETH | SOL |
|---|---:|---:|---:|
| NO_FILTER | +15R / WR 51.4% | −11R / WR 48.9% | +12R / WR 51.3% |
| EMA-200 only (orig) | +33R / WR 55.2% | +2R / WR 50.4% | +14R / WR 52.5% |
| Hull-6h only | +10R / WR 51.5% | +7R / WR 51.2% | +38R / WR 56.7% |
| **EMA OR Hull-6h** | **+41R / 54.6%** | −11R / 48.7% | **+41R / 55.3%** |
| **EMA AND Hull-6h** | +3R / 50.7% | **+23R / 57.1%** | +10R / 52.9% |

Per-symbol optimal: BTC +41R, ETH +23R, SOL +41R = **+105R total**
(vs original EMA-only +49R total).

## Почему AND для ETH, OR для BTC/SOL

- **ETH C2 baseline слабая** (+2R / 3y) — слишком много false positives → строгий двойной фильтр (AND) повышает quality
- **BTC/SOL C2 baseline сильные** (+14-33R) — Hull-6h **дополняет** EMA, ловя setup'ы что EMA пропустил → liberal OR расширяет охват
- На ETH OR-комбинация **−11R**, хуже raw — слишком много слабых setups

## Конкретные индикаторы

### EMA-200 (2h trigger TF)
```python
df_2h["ema200"] = df_2h["close"].ewm(span=200, adjust=False).mean()
```

### Hull-6h length=78
```python
hull_6h = hull_ma(df_6h["close"], length=78)
# check: close_6h[t-1] > hull_6h[t-2] для LONG
```

См. [[asvk-trend-line-hull]] для формулы Hull MA.

## Robustness

| Config | Bad years total (3 symbols × 4 yrs = 12) |
|---|---:|
| Original EMA only | 4/12 |
| Universal OR | 2/12 |
| **Per-symbol optimal** | **1/12** ★ |

Per-symbol даёт минимум bad years.

## Live integration

C2 пока не в live (backtest-only). Если будет добавляться:

```python
def is_pro_trend_c2(symbol, trigger_fvg):
    if symbol in ("BTCUSDT", "SOLUSDT"):
        return ema_check(trigger_fvg) or hull6h_check(trigger_fvg)
    elif symbol == "ETHUSDT":
        return ema_check(trigger_fvg) and hull6h_check(trigger_fvg)
```

## Файлы

- `research/elements_study/etap_111_c2_hull_trend.py` — BTC A/B test
- `research/elements_study/etap_112_c2_combined_trend.py` — 10 combinations BTC
- `research/elements_study/etap_113_c2_combined_3sym.py` — ETH/SOL verify

## Связи

- [[strategy-c2-ob-6h-fvg-2h-pro-rr1]] — canonical C2
- [[asvk-trend-line-hull]] — Hull indicator
- [[2026-05-15-floating-tp-multi-symbol-c2-trendfilter]]
