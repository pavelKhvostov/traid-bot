# Живой рынок

> **Главная концепция:** рынок — живой organism. Не статичный объект, не алгоритм для обыгрывания. У него есть собственный язык, грамматика, поведение и память. **ML должна научиться читать этот язык.**

**Создан:** 2026-06-15.  
**Машина:** PC2 (i5-14600KF + RTX 4070 + 32GB).  
**Аксиома:** только 14 элементов SMC × 8 TF. Никаких внешних индикаторов, макро, MA-family.

## Спека

Подробная спецификация концепции, action taxonomy, event vocabulary, ground truth, ML архитектура и validation: [`spec.md`](spec.md).

## Структура

```
живой-рынок/
├── README.md           — главная концепция
├── spec.md             — полная спецификация
├── события/            — Этап 1: event detector + chronological log
├── состояния/          — Этап 2: per-event state snapshots
├── продолжения/        — Этап 3: forward outcome (sequence ground truth)
├── ml/                 — Этап 4-5: multi-task ML pipeline
├── анализ/             — Этап 6: vocabulary discovery + transition patterns
├── data/               — parquet артефакты
└── sessions/           — discussion logs
```

## Связи

- Канон элементов: `~/smc-lib/elements/`
- Правило 2 (mitigation models): `~/smc-lib/rules.md`
- Правило 8 (движение цены — liquidity ↔ inefficiency): `~/smc-lib/rules.md`

## Параллельно

- **Прометей** живёт своим путём на **PC1** (RTX 5070 Ti). Отдельный pipeline, отдельный mindset.
- **Живой рынок** — на **PC2**. Эта концепция.
