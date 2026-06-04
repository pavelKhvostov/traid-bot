---
name: feedback-vic-maxv-absolute-not-sided
description: "ViC ASVK maxV = close of ABSOLUTE max-volume LTF bar (any direction), NOT sided/dominant group bar. Verified 2026-06-04 with user values."
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 935dc13c-ff07-4b9a-8e0d-e35a63c1d0be
---

# ViC ASVK maxV — absolute, not sided

**Правило (canon Pine ViC ASVK indicator):**

`maxV = close LTF-бара с АБСОЛЮТНЫМ максимальным объёмом` среди ВСЕХ LTF-баров в HTF-свече, независимо от bull/bear направления.

## Why this canon (verified 2026-06-04)

User-validated values:

| D candle | LTF | Max-vol bar | Dir | V | maxV (close) | User said |
|---|---|---|---|---|---|---|
| 2026-02-06 (mlt=45) | 32m | 03:00 MSK | bear | 11,906 | **61,734** | ✓ 61,734 |
| 2026-03-29 (mlt=45) | 32m | 01:24 MSK | bear | 1,843 | **65,688** | ≈ 65,685 (Δ=3) |

## Bug в текущем коде

`~/smc-lib/indicators/vic_asvk.py:calculate_vic_bar()` использует НЕВЕРНОЕ определение:

```python
# WRONG (current):
bullV = sum(b.volume for b in ltf_bars if b.close > b.open)
bearV = sum(b.volume for b in ltf_bars if b.close < b.open)
dom = "bull" if bullV >= bearV else "bear"
maxV = close of max-vol bar in `dom` group

# CORRECT (Pine canon):
max_bar = max(ltf_bars, key=lambda b: b.volume)
maxV = max_bar.close
```

## Применение

- **Все формулы и стратегии** где используется maxV должны использовать absolute max-vol определение
- Bull/bear/dom могут оставаться как separate features (для `norm` = bullV-bearV / total), но maxV — НЕ зависит от направления
- Текущая стратегия 12h фрактал (`[[12h-fractal-prediction-final-strategy]]`) и `[[force-model-v3-architecture]]` использовали неверный maxV — требуют ре-валидации

## Импликации для прошлых backtest-ов

- All in-sample результаты ViC C1 (sweep maxV) в C1-C7 basket — **на неверном maxV**
- Cluster grid searches (ViC heatmap, multi-TF maxV cluster) — **на неверном maxV**
- Возможно правильный maxV даст другие результаты (better edge или нет)

## Связи

- `[[feedback-pine-ltf-d-chart-integer-rule]]` — LTF определение
- `[[vc-volume-confirmation-definition]]` — VC использует ViC LTF
- `[[12h-fractal-prediction-final-strategy]]` — strategy с C1 sweep maxV
- vault: `vic-asvk-indicator-python.md` — оригинальный canon
- `~/smc-lib/indicators/vic_asvk.py` — code requires fix
