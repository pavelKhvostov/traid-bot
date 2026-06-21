# OB-VC — Project

**Цель:** зарабатывать на ob_vc сетапах. Найти HTF/LTF комбинацию (или их подмножество)
с устойчивым edge и построить strategy с PF ≥ 2 / R ≥ +100R на 6y BTC.

Canon ob_vc: `~/smc-lib/elements/ob_vc/definition.md` (2026-05-29).

## Scope

Полный canon HTF→LTF table:

| HTF (OB) | LTF (FVG) |
|---|---|
| 3D, 2D | 12h |
| 1D, 12h | 4h, 6h |
| 6h, 4h | 1h, 90m, 2h |
| 2h, 1h | 15m, 20m |

8 HTF × ~2.5 LTF = ~20 HTF×LTF комбинаций для оценки edge.

## Условия детекции (canon #1-#9)

1. ⚠ `ob.dir == fvg.dir`
2. HTF OB на supported TF
3. LTF FVG на allowed LTF (per таблице)
4. `fvg.zone ∩ drop_area/rally_area ≠ ∅` (drop = `[min(prev.low,cur.low), prev.open]`, rally = mirror)
5. `fvg.zone ⊆ [low_ob_vc, first_opposite_Williams_N2_fractal_level]`
6. OB actionable (не consumed wick-fill)
7. `fvg.c1.open_time ≥ ob.cur.open_time`
8. `fvg.c3.close_time ≤ first_fractal.confirmation_time`
9. FVG not consumed by FH confirmation (1m wick-fill check)

## Phase plan

### Phase 1 — Detection & Characterization
- [ ] `scripts/phase1_detect_all_htf.py` — детектор по canon #1-#8 на всех 8 HTF (6y BTC)
- [ ] `scripts/phase1_with_cond9.py` — добавить #9 (1m wick-fill check)
- [ ] Stats per HTF×LTF combo: count, lifetime distribution, touch rate, P(close-through)
- [ ] Deliverable: таблица 20 combos × {count, P_active, mean_TTL, mean_width_pct}

### Phase 2 — Reaction & Edge measurement
- [ ] Per combo: P(touch) within K bars, P(bounce ≥ X%), P(close-through)
- [ ] Туточно ли ob_vc > обычный OB (lift)? И > чем obычный OB на mit-touch?
- [ ] Time-to-mit distribution
- [ ] Deliverable: rank HTF×LTF по P(profitable_reaction|touch)

### Phase 3 — Backtest (strict)
- [ ] Trade rules: entry on touch (zone-edge / mid / close), SL за wick, TP-grid
- [ ] Strict timing: detection completes at fvg.c3.close + actionable check
- [ ] Walk-forward 6y (2020-2026), no lookahead
- [ ] Compare:
  - Single combo
  - Best top-3 combos blended
  - vs Strategy 1.1.1 floating baseline (+196R PF 2.20)
- [ ] Deliverable: PF/R/Win% per top-5 combos

### Phase 4 — ML edge layer
- [ ] Features: HTF×LTF type, n_components, TTL, drop/rally width, position in OB.zone,
      regime (HMM/cascade), confluence с другими ZoI, distance to nearest fractal cluster
- [ ] Target: P(touch_succeeds_R≥1)
- [ ] Walk-forward CV (purged K-fold, embargo=14)
- [ ] Decision rule: gating Phase 3 entries
- [ ] Deliverable: AUC, lift, R improvement над baseline

### Phase 5 — Production
- [ ] Live detector (1m streaming, all 8 HTF)
- [ ] Alerts (active ob_vc + ML score)
- [ ] Daily chart в формате `chart_format.md` canonical

## Memory cross-refs

- [[ob-vc-canon-reference]] — pointer на element library
- [[12h-fractal-prediction-final-strategy]] — для confluence в Phase 4
- [[prediction-algo-final-results]] — методология walk-forward
- [[feedback-p4zr-entry-fill-lookahead]] — избегать entry-fill bias в Phase 3
- [[feedback-phase4-zone-precompute-must-chunk]] — chunking при snapshot_from_events
- [[feedback-always-fetch-1m-before-chart]] — fetch перед любым live chart

## Out of scope (для V1)

- Альты (ETH/SOL) — после BTC устаканится
- Funding rate integration — Phase 4+ если базовый edge будет
- Real-time execution latency modeling — Phase 5
