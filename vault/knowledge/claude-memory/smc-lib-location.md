---
name: smc-lib-location
description: "~/smc-lib — канонический источник определений и кода SMC-элементов (RDRB, i-RDRB, FVG, фракталы и т.д.)"
metadata: 
  node_type: memory
  type: reference
  originSessionId: 3cacc97d-b7e5-4c77-9746-69e316174b22
---

# smc-lib

Канонический источник правды для SMC-элементов пользователя. Расположение: `~/smc-lib/`.

## Структура

```
~/smc-lib/
  README.md             — обзор и список элементов
  candle.py             — общий dataclass Candle + intervals_overlap
  conftest.py           — pytest sys.path setup
  elements/
    <name>/
      definition.md     — формальное определение (предусловия, формулы, эталонный пример)
      code.py           — эталонная реализация (импортирует Candle из ~/smc-lib/candle.py)
      tests/
        test_<name>.py
        fixtures.json
```

## Соглашения

- Свеча: `body_top = max(open, close)`, `body_bottom = min(open, close)`, `upper_wick = [body_top, high]`, `lower_wick = [low, body_bottom]`.
- Зоны возвращаются как `(bottom, top)`.
- Время в данных — UTC; отображение — UTC+3 ([[display-time-in-utc-plus-3]]).
- Версии (V1, V2) — стабильные, не переписываются. Новая ревизия = новая папка.

## Как пользоваться

Перед любой работой с SMC-паттернами проверяй `~/smc-lib/elements/<name>/definition.md` — там актуальная формализация. Память `[[i-rdrb-v1-pattern]]` содержит стратегическо-бэктестовый контекст (фильтры, WR, R-метрики), но **терминология устарела**:

1. Это RDRB + FVG, а не "i-RDRB V1" в текущем словаре.
2. **Направления перевёрнуты**: в `i-rdrb-v1-pattern.md` описанный "5-candle bullish reversal" (C2 bear, C2.close < C1.low) под новой конвенцией = **SHORT**. Старый текст использует terminology "long для C2 bear" (направление цели/выхода), новая конвенция — "C2 определяет направление: bear → SHORT, bull → LONG".

Текущая таксономия:

- **RDRB** — 3 свечи. Направление = C2 (bear → SHORT, bull → LONG). Варианты V1/V2 по наличию liq.
- **i-RDRB** — 4 свечи (RDRB + displacement C4)
- 5-свечный паттерн с FVG из `[[i-rdrb-v1-pattern]]` = i-RDRB + C5 для построения FVG. Бэктест-метрики там по-прежнему валидны, но при интерпретации направлений умножай на -1.

## Запуск тестов

```bash
cd ~/smc-lib && python3 -m pytest elements/<name>/tests/ -v
```

Зависимости: `pytest` (установлен через `pip install --user pytest`).
