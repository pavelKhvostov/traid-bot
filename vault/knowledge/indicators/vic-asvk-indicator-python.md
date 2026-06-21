---
tags: [indicator, vic-asvk, volume, smc]
date: 2026-05-13
last_updated: 2026-06-04
---

# ViC ASVK — Volume in Candle (Python реализация)

Python-перевод Pine-индикатора `Volume in Candle (ViC ASVK)` от ASVK.

## Что считает

Для каждого HTF бара вычисляет:
1. **maxV** ⭐ — close LTF-бара с **АБСОЛЮТНЫМ максимумом объёма** среди всех LTF-баров в HTF candle (независимо от bull/bear направления)
2. **bullV** — суммарный volume где LTF close > open
3. **bearV** — суммарный volume где LTF close < open
4. **delta** = bullV - bearV (net imbalance)
5. **norm** = delta / total_volume (нормализованный, -1..+1)

⚠️ **2026-06-04 fix:** maxV = ABSOLUTE max-vol bar, NOT "max-vol bar in dominant (bull or bear) group". Раньше в `vic_asvk.py:calculate_vic_bar()` была ошибка (использовался sided max). Verified 2026-06-04 на 3 D-свечах:
- 2026-02-06: bear bar V=11906, close=61,734 (user ✓ 61,733)
- 2026-02-24: bear bar V=1904, close=62,966 (user ✓ 62,962, Δ=4)
- 2026-02-28: bear bar V=2009, close=63,264 (user ✓ 63,266, Δ=2)

```python
# CORRECT:
max_bar = max(ltf_bars, key=lambda b: b.volume)
maxV = max_bar.close

# WRONG (legacy bug in vic_asvk.py):
# dom = "bull" if bullV >= bearV else "bear"
# max_bar = max((b for b in ltf_bars if dir_matches(b, dom)), key=lambda b: b.volume)
```

## Pine settings (auto=true, mlt=N, prem=false)

LTF выбирается автоматически по формуле:
```
tfC = HTF в секундах
rs_raw = tfC / mlt
rs = max(60, rs_raw)  # non-premium минимум 60 секунд
LTF = timeframe.from_seconds(min(tfC, rs))
```

### Refined LTF rule (verified 2026-06-04)

`timeframe.from_seconds(s)` поведение:

| Условие | Что возвращает |
|---|---|
| **`s/60` IS integer** | exact `s/60` minute custom TF |
| **`s/60` NOT integer** | closest valid TF из {1, 3, 5, 10, 15, 30, 45, 60, 120, 180, 240, 360, 480, 720, 1440}m |

### Примеры

| HTF chart | mlt | tfC | rs | rs/60 | integer? | LTF |
|---|---|---|---|---|---|---|
| 1h | 100 | 3600 | 60 | 1 | ✓ | **1m** |
| 4h | 100 | 14400 | 144 | 2.4 | ✗ | 3m (closest) |
| 12h | 100 | 43200 | 432 | 7.2 | ✗ | 8m? но Pine ceil → 8m custom |
| 12h | 45 | 43200 | 960 | 16 | ✓ | **16m** (используется в стратегии) |
| 1d | 100 | 86400 | 864 | 14.4 | ✗ | 15m (closest, default) |
| **1d** | **45** | **86400** | **1920** | **32** | **✓** | **32m** ⭐ |
| 1d | 144 | 86400 | 600 | 10 | ✓ | **10m** |

⭐ **mlt=45 + D-chart → LTF=32m** — критично для C1 condition в pred12h.

См. [[pine-ltf-12h-chart-ceil-round-up-to-integer-minutes]] для деталей.

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
- [[pine-ltf-12h-chart-ceil-round-up-to-integer-minutes]] — 12h-chart canon + D-chart integer rule (refined 2026-06-04)
- [[2026-05-13-live-bot-vic-ifvg-strategies-117-118]] — session

## Pitfalls

1. **maxV ≠ sided/dominant max** — это absolute max (fix 2026-06-04, см. выше)
2. **LTF integer rule** — для mlt=45 + D → 32m (не 30m closest!)
3. **LTF anchor** — `request.security_lower_tf` aligns LTF к HTF bar start, не epoch (для custom TFs типа 32m, 16m где не делит сутки чисто)
