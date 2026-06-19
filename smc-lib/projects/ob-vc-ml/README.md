# VC-ML-Predictor

ML модель **на ob_vc детектированных событиях** (вместо каждого 1h close).
Отдельная экспериментальная ветка от [[skolzyashie]] — изолированный pipeline.

## Гипотеза

ML rank-фильтр поверх ob_vc rule-based detector даст:
- **меньше сигналов** (только структурно-валидные)
- **выше WR** (отбираем institutional confluence)
- **production sniper-grade** (1-5 trades/мес at 65%+ WR ожидаем)

## Setup

| Aspect | Value |
|---|---|
| **Entry detector** | ob_vc canon (strict timing per [[feedback-ob-vc-strict-detection-timing]]) |
| **TFs** | 1h + 2h combined (potом separate analysis) |
| **Two entry types** | n_FVG=1 (single zone) vs n_FVG≥2 (multi-FVG confluence) |
| **Assets** | BTC + ETH from 2020-01-01 |
| **Labels** | 60d triple-barrier, TP=3/4/5%, SL=1% (same as skolzyashie) |
| **Architecture** | v4 TCN + FT + regime feature (same canon) |
| **Live rules** | HMA partial-bar update per TF at entry (MANDATORY canon [[feedback-hma-live-per-tf-at-entry]]) |
| **Additional features** | VWAPs ASVK + Money Hands ASVK |

## Зачем отдельный проект (не как часть skolzyashie)

✅ Ничего не предполагаем заранее из skolzyashie findings
✅ Не наследуем conclusions (regime feature was breakthrough? может для ob_vc другое)
✅ Тестируем все walk-forward варианты на ob_vc data заново
✅ Тестируем все label horizons
✅ Тестируем 1-model-with-feature vs 2-models routing независимо

## Файлы спеки

- [spec.md](spec.md) — full spec с decisions log
- [entry-detection-rules.md](entry-detection-rules.md) — ob_vc canon applied
- [feature-catalog.md](feature-catalog.md) — все features (existing + VWAPs + Money Hands)
- [pipeline.md](pipeline.md) — data flow CSV → ensemble
- [decisions.md](decisions.md) — будет логом всех экспериментов

## Status

🟡 **Phase 0: Spec & Detector** (current)
- [x] Project skeleton
- [ ] ob_vc detector script (1h + 2h grid)
- [ ] VWAPs ASVK + Money Hands ASVK feature computers
- [ ] Labels recompute on ob_vc timestamps

🔵 **Phase 1: Baseline (rules-based)**
- [ ] Compute baseline WR per (TF, n_FVG, Type) — what does ob_vc alone give?

🔵 **Phase 2: ML training**
- [ ] First ML experiment (v4+regime-feat, ob_vc events only)
- [ ] 4-seed ensemble
- [ ] Compare to baseline

🔵 **Phase 3: Architecture experiments**
- [ ] 1-model + n_FVG feature vs 2-models routing
- [ ] Walk-forward variants (sliding/anchored/12-fold/CPCV)
- [ ] Label horizon variants

🔵 **Phase 4: Cluster/cooldown analysis** — same canon as skolzyashie
🔵 **Phase 5: Holdout audit** — test 2026-04→06
🔵 **Phase 6: Live paper trading + production decision**

## Связи

- [[skolzyashie]] — родительский raincheck/canon (за reference architecture)
- [[project-ob-vc]] — base ob_vc canon (entry detection rules)
- [[feedback-ob-vc-canon-7-relaxed]] — relaxed FVG criteria (применяем)
- [[feedback-hma-live-per-tf-at-entry]] — live HMA rule (MANDATORY)
- [[feedback-ob-vc-strict-detection-timing]] — strict timing для detection
- [[feedback-anchored-vwap-from-fractals]] — VWAPs ASVK recipe
- [[mh-screening-best-config-not-lazybear]] — Money Hands ASVK config
- [[ob-vc-2h-types-T1-T16]] — type classification (используем как мета-фичу)
- [[ob-vc-2h-24-types-wick-ratio]] — extended classification (с wick ratio)
