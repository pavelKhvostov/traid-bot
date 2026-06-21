# [ARCHIVED] Правило 3 — VC (Volume Confirmation)

> ⚠ **Архивировано 2026-06-14** решением пользователя. Перенесено из `~/smc-lib/rules.md`.
>
> Концепция VC как самостоятельного предикат-правила deprecated. Зональная реализация остаётся как элемент `elements/ob_vc/` (со своим расширенным каноном); standalone VC predicate (`vc/`) — historical artifact.

---

**Принцип.** HTF-зона (canonically OB) считается «подтверждённой» (volume-confirmed), если её направлению **сопутствует displacement** (FVG того же направления). Displacement может быть выражен двумя способами: **spatial** (FVG внутри HTF OB) или **temporal** (FVG сразу после OB на том же TF).

> ⚠️ **VC — предикат, не зона.** Сама зона остаётся за HTF-элементом. VC лишь сигнализирует, что HTF-зона валидирована displacement'ом.
>
> ⚠️ **Vestigial name.** Объём не используется напрямую — расчёт чисто геометрический (FVG = displacement-signature).

Canon-код: `vc/definition.md`, `vc/code.py` (API: `has_vc(ob, fvg) → bool`).

> **Зональная реализация** этой концепции — элемент `ob_vc` (см. `elements/ob_vc/definition.md`). `vc/` = предикат (bool), `ob_vc/` = зона как самостоятельный элемент библиотеки с расширенной HTF/LTF-таблицей (3D/2D ↔ 12h, D/12h ↔ 4h/6h, 4h/6h ↔ 1h/90m/2h, 1h/2h ↔ 15m/20m) и **partial overlap** условием вместо строгого containment.

### Три канонических варианта

| Variant | HTF (OB) | LTF (FVG) | Геометрия | Direction |
|---|---|---|---|---|
| **1** *(spatial)* | 1h, 2h | 15m, 20m | `FVG.zone ⊆ OB.zone` (containment) | aligned |
| **2** *(spatial)* | 4h, 6h | 1h, 90m, 2h | `FVG.zone ⊆ OB.zone` (containment) | aligned |
| **3** *(temporal)* | 1h, 2h | **same TF as OB** (1h, 2h) | `FVG.c1 = OB.cur+1` (sequential, **НЕ** требует containment) | aligned |

**Direction**: во всех вариантах — **aligned** (`OB.direction == FVG.direction`).

### Семантика

- **Variants 1, 2 (spatial containment)** — внутри HTF OB лежит LTF FVG того же направления. Институциональная зона подтверждена displacement'ом «изнутри».
- **Variant 3 (temporal sequence)** — OB сформировалась, на следующей же свече начинается FVG того же направления (FVG обычно ВНЕ OB.zone — displacement выводит цену из зоны). OB сработала как launchpad → импульс → gap.

### Что VC даёт

- Boolean predicate над HTF-зоной (актуально для всех вариантов).
- Усиливает приоритет HTF OB в ranking / выборе entry (см. [[Правило 4]]).
- Используется в [[Правило 5]] как ключевое подтверждение в основной стратегии ASVK.

### Mitigation

VC сам не mitigated — это предикат. Mitigated может быть HTF-зона (по [[Правило 2]]) или LTF FVG обеспечивающая VC (wick-fill); после consumption LTF FVG предикат снимается (если нет других обеспечивающих FVG).
