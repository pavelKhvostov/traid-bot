---
tags: [session, pred12h, c9, force, basket]
date: 2026-06-05
strategy: pred12h-fractal-prediction
status: c9-approved
---

# C9 утверждено: reverse force divergence (WR 84.2%)

Продолжение работы над OR-basket. После C8 (W-aligned VWAPs) — добавлено **C9 = reverse force divergence**.

## Контекст

Исследовали Phase 4 force framework (`~/smc-lib/prediction-algo/force_opinion.py`) на pred12h baseline 1275 events.

**Force = взвешенная магнитная сила SMC-зон** вокруг текущей цены:
- `strength(zone) = TF_weight × age × class × proximity × mitigation`
- `buyer = Σ strength(LONG zones)`, `seller = Σ strength(SHORT zones)`
- `net = buyer - seller`
- Cascade {1h, 2h, 4h, 6h, 8h, 12h, 1d, 2d, 3d}

## Что сделали

### 1. Cumulative force i, i+i-1, i+i-1+i-2

Sum net force across windows w1 (single), w2 (2 bars), w3 (3 bars).

### 2. Direction-matched grid (canon: FH→sellers, FL→buyers)

Все 4 missed (#14, #15, #48, NEW) имеют direction-matched cumulative force. Ranking:
- #14 net_w2 = #1 в окне 2026-02-01+ (FH cumulative top)
- #48 net_w1 = #2, net_w3 = #3
- #15 в top-30
- NEW в top-42

Но **WR direction-matched filter за 6 лет**: 37-54% (хуже baseline). Trend-continuation bars тоже имеют сильную direction-matched force.

### 3. Reverse-direction grid (force ПРОТИВ ожидаемого)

Открыты три **80%+ WR конфигурации**:

| Filter | Window | WR | n |
|--------|-------:|---:|--:|
| FL net ≤ -1000 (sellers at bottom) | w1 (1 bar) | **100%** | 12 |
| FH net ≥ +500 (buyers at top) | w1 (1 bar) | **82%** | 39 |
| FL net_w2 ≤ -2000 (sellers extended w2) | w2 (2 bars) | **86%** | 14 |

**Window w3 (3 bars) reverse — не достигает 80%** (max 57-59%).

### 4. C9 утверждено = union 3 reverse-force filters

```python
C9 = C9a ∪ C9b ∪ C9c
  C9a: (direction=FL) AND (net ≤ -1000)
  C9b: (direction=FH) AND (net ≥ +500)
  C9c: (direction=FL) AND (net_w2 ≤ -2000)
```

## Метрики итого

| | n | conf | WR | imp/18 |
|---|---:|---:|---:|---:|
| C9 standalone | 57 | 48 | **84.2%** | 0 |
| C9 unique (вне C1-C7 + C8) | **6** | 5 | **83.3%** | 0 |
| C1-C7 ∪ C8 ∪ C9 (full basket) | 676 | 449 | 66.4% | 15/18 |

## Семантика

**Reverse force = exhaustion / divergence pattern:**
- FL bar с sellers dominant = capitulation bottom (sellers max attack, exhaustion)
- FH bar с buyers dominant = distribution top (buyers max push, exhaustion)
- FL bar с extended w2 sellers = extended capitulation

Это противоположно «направление-силы-под-разворот» (canonical direction-match). Catches **divergence reversals**.

## 4 missed остаются

C9 НЕ catches {#14, #15, #48, NEW} — все 4 missed имеют **canonical direction-matched force**, не reverse. Это означает:
- В точках missed pivot'а sellers/buyers логично доминируют («магнит уже накопил силу»)
- C9 ловит обратный паттерн (вопреки force)
- Missed остаются открытыми для других track'ов

## Архитектурное

| C9 свойство | Значение |
|-------------|----------|
| WR | 84.2% (высокое) |
| Recall | 57 events / 6 лет ≈ 10/yr (узкий) |
| Marginal к C1-C7 | +6 unique events (83% WR) |
| Catches imp/missed | 0 |
| Назначение | high-precision confirmation, не recall expansion |

## Total basket after C9

```
Baseline F1∩F2∩F3 = 1275 events  P(W)=48.6%  18/18 imp
↓
C1∪C2∪C3∪C4∪C5∪C6∪C7 = 657  P(W)=66.7%  15/18 imp
↓
+ C8 (≥2 W-aligned swept) = +13 unique  →  670  P(W)=66.3%
↓
+ C9 (reverse force divergence) = +6 unique  →  676  P(W)=66.4%  15/18 imp
```

4 missed (#14, #15, #48, NEW) — открыто, требуют новых track'ов (multi-asset, micro-LTF, divergence).

## Артефакты

### Скрипты (новые)

- `~/smc-lib/scripts/missed_force_cumulative.py` — initial force cumulative analysis
- `~/smc-lib/scripts/missed_composite_grid.py` — close_pos / pre_3d / rva composite (failed)
- `~/smc-lib/scripts/missed_full_feature_audit.py` — full feature audit на 4 missed

### Data (already existed)

- `~/Desktop/force_all_bars_per_tf.parquet` — 4686 12h bars × 9 TFs × buyer/seller/net (precomputed)
- `~/Desktop/pred12h_baseline_c1c7.parquet` — basket с C1-C7 flags

## Открытые вопросы

- 4 missed (#14, #15, #48, NEW) — все имеют **direction-matched** force, не catches by C9
- Trying tracks: multi-asset USDT.D, micro-LTF 1m order flow, force divergence (force × price divergence)

## Связано

- [[2026-06-04-pred12h-c8-vwap-w-aligned-canon]] — C8 canon previous session
- [[feedback-12h-fractal-c9-reverse-force]] — C9 memory
- `~/smc-lib/projects/pred12h-fractal-three-candles.md` — canon basket с C9 строкой
- `~/smc-lib/prediction-algo/force_opinion.py` — Phase 4 force framework canon
