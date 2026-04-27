---
tags: [strategy, s1]
date: 2026-04-22
status: phase-1
related: [[что такое обx4 цепочка]], [[правило первого OB после возврата]], [[что такое order block]]
---

# s1 obx4 + ob1h

## Триггер старшего ТФ

**OBx4-цепочка** на любом ТФ из диапазона **[1h, 2h, 3h, 4h, 6h, 8h, 12h, 1d, 2d, 3d]**.

Определение: 5 последовательных свечей, где:

**Bullish:**
- c1: красная (close < open)
- c2: зелёная (close > open)
- c3: красная
- c4: зелёная, и `c4.close > c1.open`
- c5: любая, но между c3 и c5 есть bullish FVG: `c5.low > c3.high`
- `body(c1) > body(c2) OR body(c1) > body(c3)` (хотя бы одно)
- Пересечение тел c1, c2, c3, c4 не пусто (`common_top > common_bottom`)

**Bearish:** зеркально (green-red-green-red + bearish FVG + `c4.close < c1.open`).

## Зона

Границы зоны = общее пересечение тел 4 первых свечей:
- `ob_top = min(body_top(c1..c4))`
- `ob_bottom = max(body_bottom(c1..c4))`

## Триггер младшего ТФ

**1h.** Правило — [[правило первого OB после возврата]]. Один источник истины на s1/s2/s3/s5.

## Stop-условие

Закрытие 1h свечи за границей зоны:
- Bullish: `close_1h < ob_bottom` → INVALID
- Bearish: `close_1h > ob_top` → INVALID

## Формат сигнала в Telegram

```
🟢 OBx4 + OB1h | BULLISH | BTCUSDT
TF зоны: 4h
Зона: 66500.2 – 67000.5
OBx4 сформирован: 2025-04-20 16:00 UTC
Возврат в зону: 2025-04-22 08:00 UTC
OB1h: свечи 09:00 → 10:00 UTC
```

## Источник в существующем коде

- `obxxx.py:detect_obx4_bullish` / `detect_obx4_bearish` — детектор.
- `obxxx.py:find_ob1h_in_obx4_zone` — логика возврата + первого OB1h.

Обе функции переезжают в новый проект с минимальными правками:
- `detect_obx4_*` → `src/detectors/obx4.py`
- `find_ob1h_in_obx4_zone` → `src/strategies/_shared/zone_first_ob.py` (общая для s1/s2/s3/s5)

## Известные исторические сетапы (для fixture-тестов)

*(заполнится при работе над Phase 1)*

## Открытые вопросы

*(пока нет)*

## Связи

- Детектор зоны: [[что такое обx4 цепочка]]
- Детектор триггера: [[что такое order block]]
- Правило: [[правило первого OB после возврата]]
