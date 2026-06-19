# RDRBx — Extended RDRB with delayed activation

**Status:** Draft 2026-06-14 (session-01 совместного анализа с Vadim)
**Related:** [[rdrb]] (canonical 3-bar), [[fvg]] (underlying FVG structure)

## Concept

RDRBx = Reversal-Displacement-Reversal Block, **extended** version where activation candle (Cn) arrives **delayed** (через N+ баров после displacement). Builds on canonical FVG structure.

**Key difference from RDRB:**
- RDRB = strict 3-bar pattern (c1, c2, c3 consecutive, immediate trigger)
- RDRBx = c1, c2, c3 (canonical FVG triple) + delayed Cn (activation candle that fills FVG 100% and reacts from c1+c2 POI zone)

## Structure

```
SHORT RDRBx:
  c1 ┐
  c2 │  ← POI zone (c1's lower wick + body)
  c3 ┘  ← displacement bar, completes SHORT FVG (c1.low > c3.high)
   |
   | ... (N bars passes)
   |
  Cn   ← returns, fills FVG to 100%, rejects at POI → RDRBx active

LONG RDRBx: mirror
```

## Detection rules

### SHORT RDRBx

1. **Consecutive bars c1, c2, c3** form SHORT FVG (canonical FVG detector):
   - `c1.low > c3.high`
   - FVG zone = `[c3.high, c1.low]`

2. **POI zone (zone of interest)** = `[c1.low, c1.close]`
   - Lower bound = c1.low (top of FVG)
   - Upper bound = c1.close (bottom of c1's body, where displacement of c2 starts)
   - Rationale: this is c1's "rejection wick" zone — where a bullish attempt failed; institutional supply

3. **Activation candle Cn** (where n > 3) must satisfy:
   - `Cn.high >= c1.low` — **100% FVG fill** (top of FVG touched/breached)
   - `Cn.close < c1.low` — rejection (Cn closes BELOW the POI/FVG top)
   - User confirmed 2026-06-14: «Cn свеча перекрывает FVG на 100% и дает реакцию с зоны»

4. **Variant** (temporal classification):
   - `"near"` if `(Cn.index - c3.index) <= 5` bars
   - `"far"`  if `> 5` bars (user term: "RDRBx дальний")

### LONG RDRBx (mirror)

1. c1, c2, c3 form LONG FVG: `c1.high < c3.low`
2. POI = `[c1.open, c1.high]` (upper wick + body top)
3. Cn: `Cn.low <= c1.high` AND `Cn.close > c1.high`

## Invalidation

- **SHORT POI** invalidated if any bar **closes > c1.high** (full break above c1 wick top)
- **LONG POI**  invalidated if any bar **closes < c1.low**
- After Cn activation: POI consumed (one-shot RDRBx)

## To-experiment parameters

User указал (2026-06-14): **«размер фитиля low с1 важен — отдельный эксперимент»**.

Кандидаты на исследование:
- `c1_lower_wick_ratio` (SHORT) = (c1.body_bottom - c1.low) / c1.range
  - Гипотеза: больший wick = сильнее POI = выше precision RDRBx
- `c1_upper_wick_ratio` (LONG) = (c1.high - c1.body_top) / c1.range
- Минимальный threshold qualifier — TBD после ML-эксперимента

## Direction

Inherited from underlying FVG:
- SHORT FVG → SHORT RDRBx (rejection at POI from above)
- LONG FVG → LONG RDRBx (rejection at POI from below)

## Difference from related elements

| Element | c1-c3 | Активация | Direction logic |
|---|---|---|---|
| **FVG** | 3 bars, gap created | none (zone exists from c3 close) | gap direction |
| **iFVG** | 2 FVGs + untouched candles between | when 2nd FVG overlaps 1st | direction of 2nd FVG |
| **OB** | 2 bars (prev, cur), color-change | mitigation on touch | direction of cur after color change |
| **RDRB** | 3 bars strict, consecutive | immediate (at c3 close) | direction of c2 displacement |
| **RDRBx** | 3 bars FVG + delayed Cn | **on Cn (potentially many bars later)** | inherited from FVG direction |

## Implementation notes

```python
@dataclass(frozen=True)
class RDRBx:
    direction: Direction          # "long" | "short"
    c1: Candle
    c2: Candle
    c3: Candle
    cn: Candle                    # the activation candle
    n_bars_between_c3_cn: int     # temporal distance
    variant: Literal["near", "far"]
    fvg: FVG                      # underlying FVG (c1, c2, c3)
    poi: Interval                 # POI zone
    c1_wick_ratio: float          # для experimental filter (см. To-experiment)


def detect_rdrbx_at(
    c1: Candle, c2: Candle, c3: Candle,
    forward_bars: Sequence[Candle],
    near_far_threshold: int = 5,
) -> RDRBx | None:
    """Detect RDRBx given a candidate FVG triple (c1, c2, c3) + forward bars.

    Returns RDRBx if:
      - c1, c2, c3 form valid FVG
      - some Cn in forward_bars satisfies activation criteria
      - POI was not invalidated before Cn
    """
    ...
```

## User cite (workflow)

> «Тут важно учитывать размер фитиля low С1. Это можно рассмотреть в последующем как отдельный эксперимент. Сам пока додумай параметры. Cn свеча перекрывает FVG на 100% и дает реакцию с зоны»
>
> — Vadim, 2026-06-14, session-01 (~/smc-lib/projects/пример-анализа-рынка/sessions/2026-06-14-session-01.md)

## TODO

- [ ] Implement `detect_rdrbx_at()` in `code.py`
- [ ] Add to elements registry / SMC element panel of [[project-vc-daily-forecast]] (replace ob_sweep_liq_4candles? or add as new element 17?)
- [ ] Experiment c1_wick_ratio threshold (separate Phase 4 ablation)
- [ ] Define variant detection on production data (count "near" vs "far" RDRBx historically)
- [ ] Cross-reference with existing ob_vc canon — потенциально RDRBx может быть **более точным entry signal** чем raw ob_vc
