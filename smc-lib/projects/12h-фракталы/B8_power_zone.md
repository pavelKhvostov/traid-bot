# B8 — Power Zone

Был **C9** в старом каноне → B9 → **B8** (swap 2026-06-06).

## Идея

«Power Zone» — зона **экстремальной концентрации силы** (multi-TF force balance), являющаяся **contrarian-сигналом** на pivot.

Когда сила рынка максимально смещена в одну сторону через все TFs одновременно, это указывает на **исчерпание стороны** (exhaustion) и грядущий разворот:
- На FL (bottom): экстремальный seller bias → selling exhaustion → bullish reversal
- На FH (top): экстремальный buyer bias → buyer exhaustion → bearish reversal

## Sub-conditions

### B8C1 — Reverse Force Divergence (∪3)

«Reverse» = разворот цены **против** доминирующей силы (force divergence vs price direction).

Внутренняя логика — OR-union из 3 параллельных условий по multi-TF force:

```
buyer_total = Σ buyer_tf  по TFs ∈ {1h, 2h, 4h, 6h, 8h, 12h, 1d, 2d, 3d}
seller_total = Σ seller_tf по тем же TFs
net = buyer_total - seller_total
net_w2 = net(i) + net(i-1)   ← rolling 2-bar

c9a: direction = "low"  AND  net ≤ -1000      (FL seller exhaustion)
c9b: direction = "high" AND  net ≥ +500       (FH buyer exhaustion)
c9c: direction = "low"  AND  net_w2 ≤ -2000   (FL strong 2-bar seller bias)

B8C1 = c9a ∨ c9b ∨ c9c
```

`buyer_tf` / `seller_tf` — per-TF force scores из `force_opinion.py` (Phase 4 SMC framework).

**Causality:** ✅ net и net_w2 на баре i используют forces, рассчитанные на close of i и i-1 (past). Per [[feedback-b-series-strict-causal-i]]. Требуется аудит, что force_opinion.py не peek'ает в i+1 на HTF (особенно 3D на 12h-баре).

**Цифры (на A4-baseline 1356, canonical 2026-06-06):**
n = 63 · conf = 52 · **WR 82.54%** · Δ +33.94 pp

## Асимметрия порогов (важно!)

| | FL (selling exhaustion) | FH (buyer exhaustion) |
|---|---|---|
| Single-bar threshold | net ≤ **-1000** (строго) | net ≥ **+500** (мягче) |
| Cumulative threshold | net_w2 ≤ **-2000** | — *(нет аналога)* |
| Кол-во условий | **2** (c9a + c9c) | **1** (c9b) |

Эмпирическая асимметрия: на BTC seller exhaustion @ bottom более надёжный сигнал, чем buyer exhaustion @ top. Связано с долгосрочной бычьей премией крипты (HTF bias up) → bottoms ярче, tops размытые.

## Канон / код

- **Источник логики:** `~/smc-lib/scripts/basket_andrey_magnitude.py` (lines 30-42)
- **Force opinion framework:** `~/smc-lib/prediction-algo/force_opinion.py` (Phase 4)
- **Force per-bar dataset:** `~/Desktop/force_all_bars_per_tf.parquet`
- **Trigger:** [[feedback-expert-force-opinion-trigger]] — «экспертное заключение по силе» → force_opinion.py

## Связанные memories

- [[feedback-expert-force-opinion-trigger]] — Phase 4 framework
- [[force-model-v3-architecture]] — current v3 (regions + directional Williams + monotonic TF weights)
- [[force-rank-inverted-vs-williams]] — strong force = lower P(W) standalone (1-axis ML); B8C1 = OR-comb с extreme thresholds, а не linear model
- [[feedback-12h-fractal-c9-reverse-force]] — старая memory (название «C9», обновить → B8C1)
- [[feedback-b-series-strict-causal-i]] — strict causality для B-серии

## TODO

- Пересчитать B8C1 (с разбивкой по компонентам c9a/c9b/c9c) на A4-baseline 1356 (окно 2020-01-01 → now)
- Causality-аудит force_opinion.py на HTF (3D, 2D на 12h baseline)
- Возможные B8Cx (расширение Power Zone семейства):
  - **B8C2** — FH с net_w2 ≥ +1000 (зеркальный c9c — buyer exhaustion 2-bar)
  - **B8C3** — n_TFs_buyer_wins extreme (≥8 или ≤1 из 9 TFs) → uniform bias через все TFs
  - **B8C4** — 3D-only dominance (без размывания на LTF) — institutional bias
  - **B8C5** — HTF vs LTF divergence (HTF buyer + LTF seller @ pivot, или наоборот)
  - **B8C6** — force_w3 / force_w5 (более длинные windows для seller exhaustion)
