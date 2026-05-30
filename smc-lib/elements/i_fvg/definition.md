# i-FVG (Inverse FVG)

Композитное событие: **FVG-B противоположного направления первой касается ранее untouched FVG-A** → роль зоны A инвертирует (support → resistance или resistance → support).

Canon из vault: `~/traid-bot/vault/knowledge/smc/inverse-fvg-definition.md` (2026-05-13).

> **Не путать с**:
> - `fvg` — одиночная 3-свечная зона (примитив, на котором строится i-FVG)
> - `i_rdrb_fvg` — другой композит (RDRB + FVG того же направления), не имеет отношения к инверсии

## Структура

Две FVG противоположного направления (примитив см. `elements/fvg/definition.md`):

- **FVG-A** — исходная, формируется первой. Должна оставаться untouched после `A.c2` до момента касания свечой `B.c2`.
- **FVG-B** — обратная по направлению, формируется позже. Её свечи (`B.c1, B.c2, B.c3`) первыми входят в зону A (first touch).

Свечи: `A.c1, A.c2, A.c3, …, B.c1, B.c2, B.c3` (между `A.c3` и `B.c1` может быть произвольное число untouched-баров).

## Условия

1. **FVG-A валидна** (детектор `detect_fvg` возвращает не-None).
2. **FVG-B валидна** и `B.direction != A.direction`.
3. **B сформирована позже A**: индекс `B.c1 > A.c3`.
4. **A осталась untouched** между `A.c3` и `B.c1` (включительно справа). "Touch" = wick любой свечи в окне `[A.c3+1, B.c1-1]` входит в зону A.
5. **B первой касается A**: хотя бы одна свеча из `(B.c1, B.c2, B.c3)` пробивает зону A (wick в A.zone).
6. **Зоны A и B пересекаются**: `intervals_overlap(A.zone, B.zone)` (длина пересечения > 0).

## Направление i-FVG

Определяется направлением FVG-B (направлением инверсии):

- **B bullish (LONG)** → bull→bear FVG-A инвертирована из resistance в support → итоговая LONG-зона
- **B bearish (SHORT)** → bear→bull FVG-A инвертирована из support в resistance → итоговая SHORT-зона

Wait — нет, проверим: A bullish изначально работала как support (gap up; цена возвращается снизу). Если B bearish первой касается → A становится resistance (цена пришла сверху, A не удержала, развернулась). Итоговое направление = направление B.

| FVG-A | FVG-B | Роль A до | Роль A после | i-FVG direction |
|---|---|---|---|---|
| bullish | bearish | support | resistance | SHORT |
| bearish | bullish | resistance | support | LONG |

## Зоны интереса

| Зона | Что это |
|---|---|
| **A.zone** | Зона исходной FVG-A. После i-FVG **меняет роль**, но геометрически неизменна |
| **B.zone** | Зона новой FVG-B (сам i-FVG как FVG) |
| **overlap** | `[max(A.bottom, B.bottom), min(A.top, B.top)]` — пересечение, основная зона i-FVG-события |

По умолчанию **«зона интереса i-FVG» = overlap** — это область, где одновременно сходятся обе зоны (двойная значимость).

## Геометрия

```python
# A bullish (LONG FVG): A.zone = [A.c1.high, A.c3.low]
# B bearish (SHORT FVG): B.zone = [B.c3.high, B.c1.low]
overlap = (max(A.zone[0], B.zone[0]), min(A.zone[1], B.zone[1]))
# валидно если overlap[0] < overlap[1]
```

## Эталонный пример — bull → bear i-FVG (synthetic)

| Свеча | O | H | L | C | Тип |
|---|---|---|---|---|---|
| A.c1 | 100 | 105 | 99 | 104 | bull |
| A.c2 | 104 | 120 | 103 | 119 | bull (displacement up) |
| A.c3 | 119 | 124 | 115 | 122 | bull |
| ... | ... | ... | ... | ... | untouched bars |
| B.c1 | 130 | 132 | 118 | 119 | bear |
| B.c2 | 119 | 120 | 102 | 104 | bear (displacement down, first touch A) |
| B.c3 | 104 | 108 | 100 | 105 | bear |

**Проверка**:
- FVG-A: `A.c1.high (105) < A.c3.low (115)` ✓ → bull
- FVG-B: `B.c1.low (118) > B.c3.high (108)` ✓ → bear
- A untouched между `A.c3` и `B.c1`: ✓ (нет промежуточных свечей в примере)
- B.c2 first-touches A: `B.c2.low (102) < A.zone.bottom (105)` — wick проходит через всю зону A ✓
- Overlap: `[max(105, 108), min(115, 118)] = [108, 115]` (h=7) ✓

**Зоны**:
- A.zone: `[105, 115]` (bullish, была support)
- B.zone: `[108, 118]` (bearish, the i-FVG)
- **overlap (зона интереса i-FVG)**: `[108, 115]`
- direction: **SHORT** (B bearish, A инвертирована в resistance)

## Связанные элементы

- `fvg` — примитив, на котором строится i-FVG (используется дважды для A и B)
- `i_rdrb_fvg` — другой композит c FVG (не путать)
