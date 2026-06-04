---
name: feedback-pine-ltf-d-chart-integer-rule
description: "Pine `timeframe.from_seconds()` на D-chart: rs/60 integer → exact ceil(rs/60) custom TF; rs/60 non-integer → closest valid from {1,3,5,10,15,30,45,60,...}. Уточнение к 12h-rule."
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 935dc13c-ff07-4b9a-8e0d-e35a63c1d0be
---

# Pine ViC LTF — refined rule (D-chart, 2026-06-04)

Уточнение к [[pine-ltf-12h-chart-ceil-round-up-to-integer-minutes]] (vault).

## Правило (универсальное)

Pine `timeframe.from_seconds(s)` где `s = max(60, tfC/mlt)` (auto LTF):

| Случай | Что возвращает Pine |
|---|---|
| **`rs/60` IS integer** (например 1920/60=32) | **exact `ceil(rs/60)` custom TF (32m)** |
| **`rs/60` NOT integer** (например 864/60=14.4) | **closest valid** из {1, 3, 5, 10, 15, 30, 45, 60, 120, 180, 240, 360, 480, 720, 1440} |

## Примеры на D-chart (tfC=86400s)

| mlt | rs(s) | rs/60 | integer? | LTF (Pine) |
|---|---|---|---|---|
| 30 | 2880 | 48 | ✓ | **48m** |
| **45** | **1920** | **32** | ✓ | **32m** ← важно для текущей стратегии |
| 50 | 1728 | 28.8 | ✗ | closest valid = 30m |
| 100 | 864 | 14.4 | ✗ | closest valid = 15m (default) |
| 144 | 600 | 10 | ✓ | **10m** |
| 200 | 432 | 7.2 | ✗ | closest valid = 5m or 10m (closer) |

## Примеры на 12h-chart (tfC=43200s)

Все из set: rs/60 редко integer для нестандартных mlt, поэтому `ceil` rule доминирует.

| mlt | rs(s) | LTF |
|---|---|---|
| 45 | 960 | 16m (ceil rule) |
| 100 | 432 | 8m (ceil rule) |

## Verification 2026-06-04

D-candle 2026-03-29 BTC (mlt=45 → LTF=32m, anchor=D-start):
- bullV=4645 / bearV=5407 → dominant **bear**
- Max-vol bear LTF bar: 01:24 MSK, V=1843
- maxV (close) = **65,688** (user reading 65,685, Δ=3 — display rounding)

## How to apply

В `vic_asvk.py` функция `auto_ltf_minutes` должна:
1. Compute `rs = max(60, tfC/mlt)`
2. Check if `rs % 60 == 0`:
   - YES → return `rs // 60` (exact integer minutes)
   - NO → return closest valid from VALID_LTF_SECONDS // 60

Текущий код использует только closest-valid → **багует для integer cases** на D-chart.

## Связи

- [[vc-volume-confirmation-definition]] — VC использует ViC LTF
- [[12h-fractal-prediction-final-strategy]] — strategy с mlt=45 на 12h (LTF=16m)
- vault: `pine-ltf-12h-chart-ceil-round-up-to-integer-minutes.md` — 12h-chart canon
- vault: `vic-maxv-расходился-с-pine-индикатором-из-за-1m-вместо-15m.md` — D-chart non-integer case
