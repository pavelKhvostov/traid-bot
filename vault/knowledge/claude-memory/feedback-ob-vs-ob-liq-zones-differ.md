---
name: feedback-ob-vs-ob-liq-zones-differ
description: "ob_liq намеренно имеет собственную (узкую) зону интереса, отличную от ob — не \"выравнивать\" автоматически"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: c2a93cd3-276b-4637-ad17-ca05219a1dfa
---

`ob_liq` имеет **свою** зону интереса, отличную от `ob` — это by design, не баг.

Текущие зоны (на 2026-05-24):
- `ob.zone` (LONG) = `[min(prev.low, cur.low), cur.close]` — полная (включает breaker block + drop area), совпадает с `block_orders` (1,1)
- `ob_liq.zone` (LONG) = `[min(prev.low, cur.low), prev.open]` — узкая (только drop area, без breaker block)

**Why:** `ob_liq` — composite с маркером ликвидности на `prev`, и логика входа там опирается на отвергнутый wick `prev.low` ↔ `prev.open` (отдельный сетап, не "OB + ликвидность как украшение"). Подтверждено пользователем 2026-05-24 после правки `ob` (добавили breaker block).

**How to apply:** При правках `ob` НЕ синхронизировать зону в `ob_liq` автоматически. Если возникает inconsistency-замечание — упомянуть, но не править без явного запроса. См. [[smc-lib-location]].
