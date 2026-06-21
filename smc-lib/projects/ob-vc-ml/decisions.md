# Decisions Log — vc-ml-predictor

Все архитектурные / эмпирические решения с указанием даты и обоснования.

## 2026-06-12 — Project initialized

| # | Decision | Reason | Locked? |
|---|---|---|---|
| 1 | Separate project (not branch of skolzyashie) | User explicit: «не упрощать жизнь, экспериментировать как сегодня» | ✅ |
| 2 | Two entry types = n_FVG=1 + n_FVG≥2 | User: «мы определили ранее» (T1-T16 canon) | ✅ |
| 3 | 1h + 2h combined first, separate later | User: «логика не сильно отличаться. Потом отдельно посчитаем» | ✅ |
| 4 | BTC + ETH from 2020-01-01 | User direct | ✅ |
| 5 | Same canon as skolzyashie (v4 TCN+FT+regime feat, 60d labels) | User: «настройки как сегодня» | ✅ |
| 6 | Add VWAPs ASVK feature group | User direct addition | ✅ |
| 7 | Add Money Hands ASVK feature group | User direct addition | ✅ |
| 8 | NOT inherit conclusions from skolzyashie | User: «эксперементировать как сегодня» — independent experiment | ✅ |
| 9 | Phase 1 = rule-based baseline before ML | Need floor reference (без ML what ob_vc dает?) | ✅ |
| 10 | LIVE HMA per TF mandatory | Canon [[feedback-hma-live-per-tf-at-entry]] | ✅ |

## Pending decisions (will be made empirically)

| # | Decision | When decided |
|---|---|---|
| P1 | One model with `n_FVG` feature vs two routing models | Phase 2 — test both |
| P2 | Sliding vs anchored walk-forward | Phase 3 — test both |
| P3 | 60d vs 7d strict labels | Phase 3 — test 60d first, 7d if 60d works |
| P4 | n_folds = 6 vs 12 | Phase 3 |
| P5 | Apply CPCV (C variant)? | Phase 3 — last optional |
| P6 | Add SOL? | After BTC+ETH validation |
| P7 | Predict only LONG_3 or all 6 heads? | Train all 6, decide best target later |

## 2026-06-12 (evening) — Critical correction: Entry ≠ Detection

| # | Decision | Locked? |
|---|---|---|
| 14 | Entry happens AFTER ob_vc formation (wait window between) | ✅ User correction |
| 15 | **Entry trigger learned by ML** (не зашиваем туда правило A/B/C/D) | ✅ User: «пусть обучение определит» |
| 16 | **Wait timeout learned by ML** (не зашиваем) | ✅ User: «пусть обучение определит» |
| 17 | Initial max wait window cap = **48 hours** (generous, чтобы model discovered optimum) | ✅ Initial bound |
| 18 | Each 1h bar in wait window = ML sample (candidate entry) | ✅ Implementation |
| 19 | One entry per setup at production (cluster picks peak-P within window) | ✅ User: «один вход только возможен» |
| 20 | **All MA/EMA/SMA/HMA recomputed at ENTRY moment** (LIVE per TF) | ✅ Canon |
| 21 | **Wait window features mandatory** per [[feedback-wait-window-before-entry-analyzed]] | ✅ Canon |

### Implications:

- Sample count balloon: 4-8k setups × 48 candidate entries ≈ **200-400k samples per asset**
- BTC + ETH combined: **~400-800k training samples**
- This is **larger** dataset than skolzyashie (112k) — sparser per-bar feature dense per-event
- Model learns: which (hour-since-formation, wait-state, market-condition) = best entry
- In production: cluster strategy picks 1 peak-P within each setup's wait window

## Hypotheses to test (will mark ✅/❌ as decided)

| # | Hypothesis | Status |
|---|---|---|
| H1 | n_FVG≥2 has higher baseline WR than n_FVG=1 | 🟡 to test Phase 1 |
| H2 | ML adds value over rule-based (top-1% WR > baseline + 5pp) | 🟡 Phase 2 |
| H3 | Regime feature helps (как в skolzyashie) | 🟡 Phase 2 |
| H4 | TCN sequence channel helps (как в skolzyashie) | 🟡 Phase 2 |
| H5 | VWAPs ASVK appears in permutation importance | 🟡 Phase 4 (analysis) |
| H6 | Money Hands ASVK appears in permutation importance | 🟡 Phase 4 |
| H7 | Multi-TF MA dominates importance (как в skolzyashie) | 🟡 Phase 4 |
| H8 | n_FVG=1 events require ML more than n_FVG≥2 | 🟡 Phase 2 |

## Code reuse policy

✅ **Can reuse:**
- Architecture code (`models/ft_transformer.py`, `tcn.py`, `fusion.py`) — копировать или symlink
- TBM labeling (`labels/triple_barrier.py`) — same canon
- Regime classifier (`features/compute_regime.py`) — same canon
- Sequence cache builder (`features/precompute_sequences.py`) — adapt for event timestamps
- Walk-forward modules (`training/walk_forward_v2.py`) — same canon
- Ensemble compute (`training/compute_ensemble.py`) — with new prefix
- Cluster/cooldown analysis scripts — same canon

❌ **Must rewrite:**
- ob_vc detector (specific to this project)
- Event combining logic
- VWAPs ASVK feature computer (new)
- Money Hands ASVK feature computer (new)
- Event meta features
- Training script (uses event timestamps, not 1h grid)

⚠ **Must adapt (modify, not reuse blindly):**
- Existing feature computers — re-index on event timestamps
- Walk-forward — purge/embargo on event index instead of time gap (different sparseness)
- Test holdout — different timestamps (only ob_vc events in test period)

## Independence checklist

To prevent bias from skolzyashie findings:

- [x] Separate project directory
- [x] Own data symlinks (not direct paths to ma-rr-predictor/data)
- [x] Own scripts (даже если код 95% same as skolzyashie)
- [x] Own results directory
- [x] Own canonical conclusions (написать свои findings.md when ready)
- [x] Don't pre-set thresholds (cluster strategy ≠ skolzyashie's automatically — re-discover)
- [ ] Run permutation importance from scratch — DON'T assume MA dominance
- [ ] Test both 1-model-with-feature AND 2-models-routing — don't presume one wins
- [ ] Don't apply hybrid strategy from skolzyashie — find own optimum

## Next session start protocol

When resuming work on vc-ml-predictor:
1. Read `README.md` for current state
2. Read latest `decisions.md` entries for what's been decided
3. Check `results/` for completed runs
4. Check tasks queue for in-progress work
5. Don't apply skolzyashie conclusions без re-validation на vc-ml-predictor data
