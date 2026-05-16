---
tags: [strategy, 1-1-2, floating-tp, live-candidate]
date: 2026-05-15
---

# Strategy 1.1.2 — финальная версия с Floating TP

Аналог 1.1.1, но macro = **OB-4h/6h** (не FVG-4h/6h), без SWEPT фильтра.
LIVE params: entry=0.70, sl=0.35 sym. С floating TP даёт лучшие
relative и absolute результаты чем 1.1.1.

## Логика входа — не изменилась

```
L1: OB-{1d, 12h} top
└─ L2: OB-{4h, 6h} macro
   └─ L3: OB-{1h, 2h} HTF
      └─ L4: FVG-{15m, 20m} entry
```

Entry: `fb + 0.70 × (ft - fb)`. SL: `obb + 0.35 × (fb - obb)` sym.
**Нет SWEPT фильтра** (в отличие от 1.1.1).

## Логика выхода — Floating TP (universal config)

Все 3 символа используют **одинаковую** конфигурацию:

| Параметр | Значение |
|---|---|
| R_cap | 4.5 |
| threshold | 0.00 |
| confirm bars | 2 |

Score из [[4-indicator-momentum-score]] (Hull + MH + RSI + ASVK).

## Результаты (multi-shot, limit-fill, 6y)

| Symbol | Years | Baseline RR=2.2 | **Floating TP** | Δ |
|---|---:|---:|---:|---:|
| BTC | 6.34 | +726R / WR 41.8% | **+1016R / WR 50.6%** | +290R (+40%) |
| ETH | 6.00 | +861R / WR 45.1% | **+1018R / WR 49.8%** | +157R (+18%) |
| SOL | 5.76 | +515R / WR 41.6% | **+727R / WR 48.2%** | +212R (+41%) |
| **TOTAL** | ~6y | **+2102R** | **+2761R** | **+659R (+31.4%)** |

Smoothness — все 3 символа имеют top5% < 4% (огромное число trades делает
fat-tail невозможным):

| Symbol | medR | top5% | Bad |
|---|---:|---:|---:|
| BTC | 0.00 | 2.2% | 0 |
| ETH | −0.01 | 2.2% | — |
| SOL | −0.05 | 3.1% | — |

## Caveat: multi-shot inflation 2.23×

1.1.2 имеет **больше дубликатов** чем 1.1.1 (нет SWEPT-фильтра, macro OB
более частый чем macro FVG):

- 3907 raw signals → 2157 closed → **968 unique** после дедупа
- Inflation factor: **2.23×**

Real baseline после дедупа: **+315R / 6y BTC** (vs +726R inflated)
Real floating после дедупа: ~+456R / 6y BTC

В реальной торговле:
- Если каждый Telegram-сигнал = отдельная позиция → +2761R real (multi-shot)
- Если дедупаешь по entry → ~+1240R real (÷2.23)

См. [[multi-shot-detector-2.3x-inflation]].

## Почему 1.1.2 даёт больший uplift чем 1.1.1

| | 1.1.1 | 1.1.2 |
|---|---:|---:|
| Baseline WR | 45% | 42% |
| Floating uplift | +9-39% per symbol | +18-41% per symbol |
| SWEPT filter | YES | NO |

1.1.2 без SWEPT даёт больше weak setups, которые fixed RR не успевает
закрыть с прибылью. Floating ловит их moментум-разворот. Edge floating
тем сильнее, чем слабее quality фильтрация на entry.

## Live-конфиг

```python
FLOATING_TP_CONFIG_112 = {
    "BTCUSDT": {"R_cap": 4.5, "threshold": 0.0, "confirm": 2},
    "ETHUSDT": {"R_cap": 4.5, "threshold": 0.0, "confirm": 2},
    "SOLUSDT": {"R_cap": 4.5, "threshold": 0.0, "confirm": 2},
}
MAX_HOLD_DAYS = 7
```

Universal config — никакого per-symbol тюнинга в отличие от 1.1.1.

## Файлы

- `research/elements_study/etap_109_floating_112.py` — 1.1.2 floating TP test
- `research/elements_study/etap_110_112_signals_audit.py` — funnel breakdown
- `strategies/strategy_1_1_2.py` — base detector (унаследовано от 1.1.1)

## Связи

- [[4-indicator-momentum-score]]
- [[floating-tp-only-helps-low-wr-strategies]]
- [[strategy-1-1-1-floating-tp-final]]
- [[multi-shot-detector-2.3x-inflation]]
