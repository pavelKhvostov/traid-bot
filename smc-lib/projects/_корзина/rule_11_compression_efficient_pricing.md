# [ARCHIVED] Правило 11 — Компрессия (эффективное ценообразование) — *было в разработке*

> ⚠ **Архивировано 2026-06-14** решением пользователя. Перенесено из `~/smc-lib/rules.md`.
>
> Правило не было завершено (статус *в разработке*, 9 открытых вопросов). Концепция компрессии deprecated как самостоятельное правило справочника.

---

**Принцип.** **Компрессия = эффективное ценообразование.** Зона, в которой institutional accumulation/distribution прошёл аккуратно: сформирован стек OB разных ТФ, и все inefficiency (FVG) внутри стека отработаны.

### Структурное определение (зафиксировано пользователем 2026-05-29)

1. **Серия OB разных ТФ** в одной price zone (стек multi-TF институциональных уровней).
2. **Все LTF FVG 15m в зоне OB-стека заполнены ≥50%** (mitigation by wick-fill).

Если есть хотя бы одна FVG 15m с мит < 50% → **это НЕ компрессия** (есть остаточная inefficiency, рынок ещё не «дошёл» до efficient pricing).

### Класс зоны

**⛽ Liquidity** — фрактальная ликвидность (по решению пользователя). См. [[Правило 8]] таксономию.

Семантически: компрессия = «traded zone» — институционал торговался **fair** внутри стека, оставив stops розницы за границами компрессии. Sweep этих границ = Phase 1 цикла Правила 8.

### Контраст с `feedback-untraded-area-is-magnet`

| Тип зоны | Магнит-логика |
|---|---|
| **Untraded area (FVG, marubozu body)** | Магнит — цена возвращается заполнить |
| **Traded area (компрессия)** | **НЕ магнит** — заполнение уже произошло, зона «отработана» |

### Контраст с `ob_vc` ([[Правило 3 (ARCHIVED)]] зональная реализация)

| Элемент | FVG-статус |
|---|---|
| **ob_vc** | OB + **активная** (не отработанная) LTF FVG = displacement validator |
| **compression** | OB-стек + **отработанные** (≥50%) LTF FVG = efficient pricing |

**Взаимоисключающие** состояния для одного OB.

### Открытые вопросы (нерешённые)

1. **Минимум OB в стеке** — 2? 3? больше?
2. **HTF-набор** — на каких TF собираем OB (1h, 4h, 12h, 1d)?
3. **«В одной зоне»** — overlapping zones / общий midpoint ± толеранс / bounding box?
4. **Direction OB** — same direction (LONG-only / SHORT-only стек) или mixed допустим?
5. **FVG TF set** — только 15m или включая 20m?
6. **Формула «≥50% заполнен»** — `(hi - min_wick) / (hi - lo) ≥ 0.5` для LONG FVG?
7. **Геометрия компрессии-зоны** — union / intersection / bounding box / outer edges?
8. **Mitigation модель самой компрессии** — sweep? first-touch?
9. **Direction labels компрессии** — long/short / top/bottom / neutral?

### Связи

- [[Правило 2]] — wick-fill mitigation для проверки «≥50%»
- [[Правило 3 (ARCHIVED)]] — VC: компрессия = антипод ob_vc для одного OB
- [[Правило 8]] — Phase 0/preparation цикла; компрессия = накопленная liquidity
- `feedback-untraded-area-is-magnet` — антонимично: untraded = magnet, traded (компрессия) = не magnet
- `feedback-fractal-liquidity-strength-and-sweep` — сила liquidity = TF × age × cluster
