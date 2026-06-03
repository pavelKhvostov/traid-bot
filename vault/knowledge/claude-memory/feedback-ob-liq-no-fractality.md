---
name: feedback-ob-liq-no-fractality
description: "ob_liq канон БЕЗ Williams-фрактальности (с 2026-05-27). Маркер = 2 условия (wick ≥ 3× wick cur + wick > body prev). 2-свечный паттерн (prev, cur). Понятие «фрактальность» к ob_liq НЕ применяется."
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 3af6f0d9-c3ee-48ba-ae08-4c05d8c82af3
---

# ob_liq канон БЕЗ Williams-фрактальности

Утверждено пользователем 2026-05-27. Изменение в каноне `~/smc-lib/elements/ob_liq/`.

## Что изменилось

| Аспект | До 2026-05-27 | После 2026-05-27 |
|---|---|---|
| Свечной паттерн | 5-свечный (prev-2, prev-1, prev, cur, cur+1) | **2-свечный** (prev, cur) |
| Условий маркера | 3 (wick ≥ 3× cur, wick > body, **prev = Williams 5-bar HH/LL**) | **2** (wick ≥ 3× cur, wick > body) |
| Зависимость от соседей | Да (Williams check) | **Нет** |
| `detect_ob_liq` signature | `(prev_minus2, prev_minus1, prev, cur, cur_plus1)` | `(prev, cur)` |

## How to apply

- При работе с `ob_liq` НЕ требовать Williams-фрактальность prev.
- При обсуждении `ob_liq` НЕ упоминать «фрактал» / «5-bar HH/LL».
- При написании кода вызывать `detect_ob_liq(prev, cur)` (2 аргумента).
- Старые скрипты с 5-аргументным вызовом обновлены 2026-05-27.

## Why

Williams-условие отрезало много визуально валидных ob_liq случаев. Пример который вскрыл проблему: BTC 12h 02-16 15:00 / 02-17 03:00 — структурно ob_liq (wick ratios passing), но prev.high < prev-2.high → Williams fail. Канон смягчён.

## Артефакты

- `~/smc-lib/elements/ob_liq/code.py` (упрощённая 2-арг функция)
- `~/smc-lib/elements/ob_liq/definition.md`
- `~/smc-lib/elements/ob_liq/tests/test_ob_liq.py` (6 tests pass)
- `~/smc-lib/zone_of_interest.md` (раздел 4)
- `~/smc-lib/README.md`

## Related

- [[feedback-ob-vs-ob-liq-zones-differ]] — зона ob_liq отличается от ob (не меняется, всё ещё актуально)
- [[smc-lib-location]]
