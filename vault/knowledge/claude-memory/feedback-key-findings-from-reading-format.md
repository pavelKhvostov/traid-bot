---
name: feedback-key-findings-from-reading-format
description: При запросе «ключевые выводы из чтения / изучи книги» — формат action-oriented findings под каждую книгу с emoji + направление применения + таблица или bullet list
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 935dc13c-ff07-4b9a-8e0d-e35a63c1d0be
---

# Канонический формат «Ключевые выводы из чтения»

При триггерах **«изучи книги»**, **«ключевые выводы из чтения»**, **«что применить из X»**, **«прочитай и сделай выводы»** — использовать строго фиксированный format **action-oriented findings**.

Полный canon — Правило 13 в `~/smc-lib/rules.md`.

## Why

Пользователь хочет actionable items, не литературные summary. Цель — сразу видеть **что брать в работу** из книги, привязанное к нашему коду. Will work с этими findings — поэтому формат должен быть structured для referencing.

## Формат (короткая memo)

```
## Ключевые выводы из чтения

### <emoji> <Автор/Книга> — <направление применения>

| Глава | Что применять |
|---|---|
| Ch X — <название> | <конкретный action в нашем коде> |
```

Или bullet list (для VSA-detectors / patterns):

```
### <emoji> <Книга> → расширение <module>

N novel primitives candidates:
- `slug_1` — детектор short definition
- `slug_2` — ...

**<их концепт> = <наш концепт>** — те же концепции, разная терминология
```

## Emoji guide

- 🎯 ML / quant / инфраструктура (Lopez de Prado)
- 📊 volume / orderflow / microstructure (Williams VSA)
- 🕯 candlestick / price action (Nison)
- 📈 chart patterns / classic TA (Bulkowski)

## Что обязательно

- ✓ Стрелка `→ направление применения` в заголовке
- ✓ Каждый action item указывает на наш конкретный файл/модуль
- ✓ Приоритет ⭐⭐⭐ → ⭐ виден
- ✓ Cross-references через `~/smc-lib/...` paths

## Что нельзя

- ❌ Длинный summary книги (это для `notes_<book>.md`)
- ❌ Биография автора
- ❌ Концепции без привязки к нашему коду

## How to apply

При следующих просьбах от пользователя «изучи / выводы / что применить» — выводить именно в этом формате. Полные summary остаются в `~/smc-lib/literature/notes_<book>.md`.

## Связи

- Правило 13 в `~/smc-lib/rules.md` (полный canon)
- `[[feedback-elements-library-output-format]]` — родственный формат для «элементов библиотеки» (Правило 10)
- `~/smc-lib/literature/` — раздел литература где живут полные notes
