---
name: feedback-marubozu-canon-pine-wicked
description: Canon marubozu в smc-lib = Pine WICK.ED (open на экстремуме); старый канон body/range ≥ 0.95 deprecated
metadata: 
  node_type: memory
  type: feedback
  originSessionId: c2a93cd3-276b-4637-ad17-ca05219a1dfa
---

Canon **marubozu** в `~/smc-lib/elements/marubozu/` зафиксирован 2026-05-24 по Pine-индикатору **WICK.ED — ASVK**:

- **LONG**: `open == low AND close > open` (нет нижнего фитиля, верхний — любой длины)
- **SHORT**: `open == high AND close < open` (нет верхнего фитиля, нижний — любой длины)

Зона интереса = тело свечи `[body_bottom, body_top]`.

**DEPRECATED**: старый канон `body / range ≥ 0.95` из `~/traid-bot/vault/knowledge/strategies/marubozu тело 95 процентов.md` и `~/traid-bot/strategies/marubozu.py:12`. **Не использовать** в новой логике поверх smc-lib.

**Why:** Пользователь явно выбрал Pine WICK.ED после сравнения двух определений. Pine-условие сильно слабее (на BTC 90m 6 лет: 893 hit под Pine vs ~10× меньше под 95 %-rule). Импульс с открытием на экстремуме важнее минимизации противоположного фитиля.

**How to apply:**
- При любых запросах "найди marubozu", "посчитай marubozu", "детектор marubozu" — использовать **только** `elements/marubozu/code.py::detect_marubozu` (или Pine-эквивалент).
- Если видишь код, проверяющий `body / range >= 0.95` для marubozu — это deprecated, флагнуть пользователю.
- Vault-заметка `marubozu тело 95 процентов.md` остаётся как историческая reference, но не как canon.

См. [[smc-lib-location]], [[charts-output-location]].
