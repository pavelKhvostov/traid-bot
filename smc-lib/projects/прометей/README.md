# Проект «Прометей»

**Path:** `~/smc-lib/projects/прометей/`
**Started:** 2026-06-14
**Author:** Vadim + Claude (co-development)

## Vision

Научить ML определять **сильный уровень дня** и **направление движения цены далее** — используя **ТОЛЬКО зоны интереса (SMC элементы)** с canon-aware mitigation tracking.

User explicit (2026-06-14):
> «Элементы с канонами и правилами — самое ценное что есть в проекте. Я делаю WR не прибегая даже к другим фитчам.»

То есть SMC — **primary signal**, не secondary поверх MA/macro/Lopez. Все остальные feature groups deprecated в рамках этого проекта.

## Scope (narrow by design)

**Что входит:**
- 16 SMC элементов из `~/smc-lib/elements/` × 8 TF
- Canon-aware mitigation tracking (через `~/smc-lib/elements/_mitigation.py`)
- Role inversion (OB → Breaker)
- Active vs consumed vs breaker classification
- Williams fractals + sweep tracking
- Confluence detection (multi-element overlap)

**Что НЕ входит:**
- Lopez microstructure (Amihud, VPIN, etc.)
- MA/EMA/HMA periods
- Macro features (USDT.D, TOTALES, SPX/BTC)
- Sessions, funding, volume profile
- Candle anatomy, VSA, Nison patterns
- Bulkowski, divergences

Это всё может быть добавлено как Phase 2+ если SMC-only baseline не достигнет целевой производительности. Но **изначальный фокус — pure SMC**.

## Targets (что предсказываем)

1. **Strong level of the day** — какой из active SMC уровней рынок выберет для реакции
   - Output: ranked list of active zones with probability of being "the level"
2. **Direction after touching strong level** — куда пойдёт цена после касания
   - Output: P(LONG reversal) vs P(SHORT continuation) vs P(no clear reaction)
3. **Magnitude of move** (опционально) — q10/q50/q90 ожидаемого хода

## Architecture (TBD)

Initial proposal — 2-stage pipeline:
- **Stage A: Level scoring** — rank active SMC zones by «вероятность быть сильным уровнем сегодня»
- **Stage B: Direction prediction** — given «strong level X selected», P(reversal / continuation)

Alternative: single multi-head model. Lock in spec.md после первой проверки.

## Inputs / data

- BTC 1h cadence (24 snapshot/день), TF panel: 15m → 1w
- Все SMC elements detected с mitigation chain applied
- Per snapshot: список active levels + features per level + market state

## Goals quantified

- Identify «strong level» с precision >= 70% (top-1 prediction = actual reaction zone)
- Direction prediction AUC >= 0.75
- Walk-forward 2020-2024 train, 2025-2026 holdout (per [[project-vc-daily-forecast]] split)

## Workflow rules

**Перед каждым action в проекте Прометей:**
1. **Канон first** — прочитать `~/smc-lib/elements/zone_of_interest.md` + конкретный element's definition.md
2. **Apply mitigation** — никогда не использовать raw detector output без `apply_mitigation()`
3. **Distinguish mit-test vs passage** (per [[feedback-smc-canon-checklist]])
4. **Track role inversion** (Breaker block)
5. **Не добавлять non-SMC фичи** до подтверждения SMC baseline

## Structure

```
прометей/
├── README.md       — этот файл
├── spec.md         — features, targets, methodology (Phase 0)
├── decisions.md    — log of locked decisions
├── detectors/      — canon-aware SMC detection per element
├── features/       — SMC feature engineering (primary)
├── labels/         — strong level + direction targets
├── training/       — model training
├── analysis/       — chart-based learning sessions
├── sessions/       — joint Vadim+Claude session logs
└── results/        — saved models, predictions, metrics
```

## Predecessors / related

- **`[[пример-анализа-рынка]]`** — session-01 (2026-06-14) с canon-learnings → база для Прометея
- **`[[project-vc-daily-forecast]]`** — broader project; Прометей это narrow «pure-SMC» подпроект; если успешен — SMC features уйдут в vc-daily-forecast как primary group
- **`[[reference-andrey-12h-branch]]`** — Andrey pipeline (NOT applicable — он смешивал SMC с Lopez/VSA, Прометей принципиально SMC-only)

## Memory triggers

«Прометей», «strong level of day», «SMC primary», «zone-only features» → читать этот README.
