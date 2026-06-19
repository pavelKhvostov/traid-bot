# Mitigation Block

**Зона, в которую цена возвращается ПОСЛЕ полного пробоя бывшего OB с закреплением (Правило 1).** Институциональные участники, оказавшиеся в убытке после пробоя их зоны, mitigate (закрывают) убыточные позиции при возврате цены — отсюда название.

Канон 2026-06-14: переписан с старого ABC/MSS подхода на canonical «broken OB + Правило 1».

## Условие формирования

1. **Существует canon-OB** (LONG или SHORT) — см. `elements/ob/definition.md`
2. **Полный пробой OB.zone** в обратную сторону:
   - LONG OB: `close < ob.zone_low` (= drop_low)
   - SHORT OB: `close > ob.zone_high` (= rally_high)
3. **Закрепление по Правилу 1** (`~/smc-lib/rules.md` §1): пробойная свеча + 3 последующие подтверждающие свечи, у каждой из 3 — **И open, И close** за пробитым уровнем.

Минимум — 4 свечи цепочкой: 1 пробойная + 3 подтверждающие.

## Геометрия зоны

**Mitigation Block ZoI = OB.zone** (геометрия наследуется БЕЗ изменений):
- Bearish MB (LONG OB пробит вниз): ZoI = `[drop_low, prev.open]` = бывшая drop area
- Bullish MB (SHORT OB пробит вверх): ZoI = `[prev.open, rally_high]` = бывшая rally area

После закрепления — роль зоны **flipped**:
- бывший support (LONG OB) → resistance (Bearish MB) при возврате цены сверху
- бывший resistance (SHORT OB) → support (Bullish MB) при возврате цены снизу

## Семантика

Institutional участники, открывшие позиции в OB.zone (LONG OB = накопление лонгов), оказались в убытке после полного пробоя. На возврате цены к бывшей OB.zone они **закрывают убыточные позиции в безубыток** (mitigation of loss) → ожидается продолжение движения в новом направлении.

## Mitigation модель

**wick-fill** (Правило 2 модель 1) — наследуется от OB:
- Bearish MB: касание сверху wick'ом, low ≤ zone_hi → зона сжимается; low ≤ zone_lo → CONSUMED
- Bullish MB: касание снизу wick'ом, high ≥ zone_lo → сжимается; high ≥ zone_hi → CONSUMED

## Отличие от Breaker Block

| Аспект | Breaker Block | Mitigation Block |
|---|---|---|
| Trigger | BOS (одно закрытие за зоной OB) | **Полный пробой + Закрепление Правило 1** (4 свечи) |
| ZoI | проткнутый фитиль prev (узкая) | бывшая OB.zone (вся area) |
| Confirmation | 1 close-cross | 4 свечи (1 пробойная + 3 подтверждающих) |
| Семантика | flip-zone после structural break | mitigation of loss + role flip |

## Параметры детекции

| Параметр | Значение | Описание |
|---|---|---|
| `max_bars_to_breakout` | 30 | максимум баров от формирования OB до пробойной свечи; иначе MB не формируется |

## Алгоритм детекции (псевдокод)

```python
def detect_mitigation_block(ob, post_bars):
    broken_level = ob.zone[0] if ob.direction == "long" else ob.zone[1]
    target_side = "below" if ob.direction == "long" else "above"

    for i in range(min(30, len(post_bars))):
        bar = post_bars[i]
        if not bar.close is at target_side of broken_level:
            continue  # not yet broken

        # Found breakout candle at i. Need 3 confirming.
        if i + 3 >= len(post_bars):
            return None  # insufficient bars

        for j in range(i+1, i+4):
            c = post_bars[j]
            if not (c.open is at target_side AND c.close is at target_side):
                return None  # confirmation failed

        # All 4 conditions met → MB armed
        return MitigationBlock(ob, breakout_idx=i, confirm_idxs=(i+1, i+2, i+3), ...)

    return None  # breakout not found in window
```

## Эталонные примеры

### Bearish MB (LONG OB пробит вниз)

LONG OB: prev (bear) O=100, H=102, L=95, C=96; cur (bull) O=96, H=105, L=94, C=104
→ OB.zone = drop area = [94, 100]

Post-bars:
- bar 1 (пробойная): O=95, H=96, L=88, C=89 (close 89 < drop_low 94 ✓)
- bar 2: O=89, H=91, L=85, C=87 (open 89 < 94 ✓, close 87 < 94 ✓)
- bar 3: O=87, H=89, L=83, C=85 (open 87 < 94 ✓, close 85 < 94 ✓)
- bar 4: O=85, H=87, L=82, C=86 (open 85 < 94 ✓, close 86 < 94 ✓)

→ MB armed at bar 4. ZoI = [94, 100], role = resistance.

### Bullish MB (SHORT OB пробит вверх) — зеркально

SHORT OB: prev (bull) O=100, H=105, L=98, C=104; cur (bear) O=104, H=106, L=95, C=96
→ OB.zone = rally area = [100, 106]

Post-bars:
- bar 1 (пробойная): close > rally_high 106
- bar 2-4: open И close > 106

→ MB armed. ZoI = [100, 106], role = support.

## Связанные элементы

- **`ob`** — необходимое prerequisite (MB строится поверх OB)
- **`breaker_block`** — родственный flip-zone, но другая trigger logic (BOS vs Rule 1)
- **Правило 1** — закрепление цены за уровнем
- **Правило 2** — mitigation модель wick-fill

## Источники

- pavel-notes ICT Month04 (старый ABC/MSS подход — deprecated 2026-06-14)
- User canon 2026-06-14: переход на canonical «broken OB + Rule 1» через session 2026-06-14
- Memory: `feedback-mitigation-block-canon`
