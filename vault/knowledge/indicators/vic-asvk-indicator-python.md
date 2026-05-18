---
tags: [indicator, vic-asvk, volume, smc]
date: 2026-05-13
---

# ViC ASVK — Volume in Candle (Python реализация)

Python-перевод Pine-индикатора `Volume in Candle (ViC ASVK)` от ASVK.

## Что считает

Для каждого HTF бара вычисляет:
1. **maxV** — close LTF-свечи с максимальным dirVolume (volume-based S/R level)
2. **bullV** — суммарный volume где LTF close > open
3. **bearV** — суммарный volume где LTF close < open
4. **delta** = bullV - bearV (net imbalance)
5. **norm** = delta / total_volume (нормализованный, -1..+1)

## Pine settings (auto=true, mlt=100, prem=false)

LTF выбирается автоматически по формуле:
```
tfC = HTF в секундах
rs_raw = tfC / mlt
rs = max(60, rs_raw)  # non-premium минимум 60 секунд
LTF = timeframe.from_seconds(min(tfC, rs))  # closest valid TF
```

| HTF chart | tfC | rs_raw | rs (non-prem) | LTF |
|-----------|-----|--------|---------------|-----|
| 1h | 3600 | 36 | 60 | **1m** |
| 4h | 14400 | 144 | 144 | ~3m |
| 1d | 86400 | 864 | 864 | **15m** |

## Эталонная сверка с TradingView

BTC daily, auto=true, mlt=100, non-premium:
| Дата | TV maxV | Python (LTF=15m) | Diff |
|------|---------|------------------|------|
| 2026-05-11 | 81080 | 81079.06 | -0.94 ✓ |
| 2026-05-12 | 80290 | 80290.00 | **0.00** ✓ |

Реализация **корректна**.

## Каноничная функция

```python
# vic_levels.py
def calculate_vic_d(df_1m, day, ltf_minutes=15) -> float | None:
    """maxV для дня `day` — close LTF-свечи с макс dirVolume.

    ltf_minutes соответствует Pine LTF для конкретного HTF chart.
    Для D-chart с mlt=100 → ltf_minutes=15.
    """
    ...
```

## Применение в стратегиях

См. [[vic-asvk-as-filter-for-cascade-strategies]].

Главная находка: **|maxV-1d distance| > 1 ATR-1h** для 1.1.4 BFJK:
- WR 70.6% vs 64.3% baseline (+6.3pp)
- avg R/trade +1.12 vs +0.93 baseline
- Frac kept 59%

Используется как quality filter — entry далеко от dominant volume zone = меньше "застревания" в institutional pin.

## Дополнительные ViC фичи для filters

- **delta sign alignment** с trade direction
- **norm magnitude** (U-shape — extremes лучше mid)
- **divergence** на prev bar (bull bar с negative delta, или bear bar с positive delta) — слабый сигнал направления

## Файлы

- Реализация: [vic_levels.py](../../../../vic_levels.py)
- Demo на 1h BTC: [research/elements_study/etap_89_vic_indicator_1h.py](../../../../research/elements_study/etap_89_vic_indicator_1h.py)
- D-chart сверка с TV: [etap_90_vic_daily.py](../../../../research/elements_study/etap_90_vic_daily.py)
- Forensic на 1.1.4: [etap_91_vic_forensic.py](../../../../research/elements_study/etap_91_vic_forensic.py)
- Filter combos: [etap_92_vic_filters_audit.py](../../../../research/elements_study/etap_92_vic_filters_audit.py)
- Original Pine: [research/asvk_vic/](../../../../research/asvk_vic/) (для справки)

## Связи

- [[vic-asvk-as-filter-for-cascade-strategies]]
- [[vic-maxv-расходился-с-pine-индикатором-из-за-1m-вместо-15m]] — pitfall про LTF
- [[2026-05-13-live-bot-vic-ifvg-strategies-117-118]] — session
