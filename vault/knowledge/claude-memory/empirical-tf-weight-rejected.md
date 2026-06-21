---
name: empirical-tf-weight-rejected
description: "Empirical TF_WEIGHT через LR на next-bar Williams отвергнут (2026-06-03); методология сломана (StandardScaler нейтрализует naive 72×); канон naive (1,2,4,...,72) остаётся"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 436555f5-69d9-4434-ba35-f759547388d5
---

# Empirical TF_WEIGHT calibration — rejected

**Правило:** Канон naive TF_WEIGHT `{1h:1, 2h:2, 4h:4, 6h:6, 8h:8, 12h:12, 1d:24, 2d:48, 3d:72}` (линейные часы) **остаётся в силе** для HTF dominance. Empirical recalibration через ML на next-bar Williams = **методологически неверная задача**.

**Why:**
1. **Target wrong**: next-bar Williams n=2 — слишком granular timing event. HTF zones «всегда около цены», поэтому НЕ дискриминируют момент.
2. **Standardization neutralizes scaling**: в zone_strength() naive 72× уже baked in. StandardScaler (x-μ)/σ нормализует buyer_3d к z-score → 72× factor смыт.
3. **Model accuracy 45% < baseline 49.5%**: модель не учится → coefficients unreliable.
4. **User intuition correct**: HTF zones структурно важнее для price reactions (mitigation, magnet effect) — это НЕ та же задача что predict next-bar Williams.

**How to apply:**
- НЕ повторять empirical test с тем же target (next-bar)
- Если нужна fair HTF empirical validation: **per-zone-event labeling** (label = price reverses ≥ X% within Y bars after touch), train per zone-touch
- В zone_strength(), force_opinion и т.д. использовать naive TF_WEIGHT (canon)
- 3d coefficient в empirical std-space = 0.612 (low), в effective-space = 0.252 — оба отражают что 3d НЕ доминирует **для timing**, но это task-specific finding

**Files:** `~/Desktop/empirical_tf_weight_coefs.parquet` (saved coefficients для reference), `~/smc-lib/scripts/empirical_tf_weight_train.py` (broken script — для уроков, не для использования).

Связано с [[force-rank-inverted-vs-williams]], [[bb-model-phase4-negative-result]].
