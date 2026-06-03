# Формирование экспертного заключения

Воспроизводимый pipeline для построения мнения о направлении движения цены на основе зон из `elements/`, классов зон ([[zone-class-liquidity-inefficiency-block]]) и магнит-логики ([[feedback-untraded-area-is-magnet]]).

> **Главное правило.** Экспертное заключение строится как **multi-TF top-down каскад**: W → D → 12h → 4h → 1h → 15m. Не на одном ТФ. См. [[feedback-expert-opinion-is-multi-tf-cascade]].

> **Назначение.** Когда пользователь спрашивает "куда пойдёт цена", "что сейчас на графике", "дай мнение" — выполнять каскад по шагам, не пропуская ТФ.

## Каскад ТФ — что каждый отвечает

| ТФ | Вопрос | Window context |
|---|---|---|
| **W** (Mon-anchor) | Доминирующий трейд года; macro magnets | 1-2 года |
| **D** | Текущая swing-структура (месяцы); primary reaction zones | 3-6 месяцев |
| **12h** | Intermediate confluence (недели) | 1-2 месяца |
| **4h** | Setup zones, working area | 2-4 недели |
| **1h** | Entry context, confirmation zones | 1-2 недели |
| **15m** | Precision triggers, execution | 2-5 дней |

## Принципы каскада

1. **HTF priority** — при конфликте HTF побеждает. HTF wick "проглатывает" LTF события (см. [[feedback-fractal-liquidity-strength-and-sweep]]).
2. **Top-down narrative** — мнение от W (макро) к 15m (микро). Не наоборот.
3. **Confluence** — высокая вероятность setup'a там, где зоны нескольких ТФ выравниваются (D FL + 4h FVG + 1h OB в одной области).
4. **LTF не разрушает HTF** — "пробой" 15m FH внутри 4h wick не отменяет 4h setup.

## Когда применять

- "Дай мнение, куда цена двинется"
- "Что сейчас на графике"
- "Какой setup активен"
- При создании trade plan / review-чеклиста

## Pipeline — 10 шагов (выполняются НА КАЖДОМ ТФ каскада)

### Шаг 1. Сбор данных + каскад

- Источник: `~/traid-bot/data/BTCUSDT_1m_vic_vadim.csv` + докачка через `scripts/fetch_btc_1m_missing.py`.
- Агрегация: для каждого ТФ каскада через epoch-anchor (W — **Mon-anchor** [[weekly-tf-anchor-monday]]).
- Окно: per-TF lookback (см. таблицу выше).
- Forming bar текущего ТФ — **отделять** от закрытых, отмечать явно.

### Шаг 2. Detection scan по 11 элементам (per TF)

Прогнать все детекторы из `elements/` на окне каждого ТФ:
ob, block_orders, ob_liq, rb, fvg, i_fvg, rdrb, i_rdrb, i_rdrb_fvg, marubozu, fractal.

### Шаг 3. Position assessment (per TF)

Для каждой зоны определить позицию текущей цены: **above / below / INSIDE**.
Фильтр: ±5 % от current close на target-TF, ±10-15 % для HTF (W/D — больше радиус).

### Шаг 4. Классификация (per TF)

Распределить зоны на три класса:
- **Блок** — OB, block_orders, ob_liq, RDRB-family
- **Inefficiency** 🧲 — FVG, i_FVG, marubozu
- **Liquidity** 🧲 — fractal, rb, ob_liq.liq_zone

### Шаг 5. Magnets (per TF)

Untraded inefficiency + unswept liquidity рядом с ценой = магниты. Отметить HTF магниты особо — они доминируют над LTF.

### Шаг 6. Structure reading (per TF)

Sequence FH/FL → trend на каждом ТФ:
- HH + HL = uptrend
- LH + LL = downtrend
- LH + HL = consolidation / contraction
- HH + LL = expansion / volatility break

### Шаг 7. Cascade integration (КЛЮЧЕВОЙ ШАГ)

Свести анализ всех ТФ в одну картину:

#### 7a. Trend cascade

```
W trend  → определяет dominant bias года
D trend  → определяет тактический bias на недели
12h-4h   → определяют активную фазу (impulse / pullback / consolidation)
1h-15m   → определяют immediate execution context
```

Если все ТФ aligned → strong directional move. Если HTF up / LTF down → ожидаемый pullback в HTF up-структуре.

#### 7b. Multi-TF confluence zones

Найти ценовые области, где сходятся зоны 2+ ТФ. Это самые значимые setup-зоны.

Примеры:
- W FH + D RDRB block + 4h OB в одной области → strong SHORT setup
- D FL + 4h FVG + 1h OB-LONG → strong LONG setup (buy-side liquidity grab + entry)

#### 7c. HTF magnets

Top-3 ближайших HTF магнита (по W и D) — главные attraction-points для цены. LTF setup имеет смысл только если согласуется с HTF магнитом.

### Шаг 8. Scenario construction (с multi-TF триггерами)

Минимум 2 сценария (обычно 3):

| Сценарий | Trigger | Path (multi-TF) |
|---|---|---|
| **A** (main) | HTF/MTF условие | последовательность HTF→LTF магнитов |
| **B** (alt) | invalidation main | противоположное направление |
| **C** (extreme) | прямой пробой ключевых HTF уровней | extended HTF targets |

Каждый trigger ссылается на close ТФ (не intrabar).

### Шаг 9. Invalidation map (cross-TF)

Decision-tree триггеров, расставленных по ТФ:

| ТФ trigger | Action | Цель |
|---|---|---|
| 15m close > X | trigger LTF entry | 4h target |
| 1h close < Y | invalidate setup | 4h alt-target |
| 4h close > Z | shift bias | D target |
| D close < W-FL | invalidate trade direction | W extended target |

### Шаг 10. Time anchors + caveats

- Время закрытия forming-bar'а на каждом ТФ (особенно W и D — главные).
- Указать актуальность данных ("на N MSK").
- Caveats: intrabar = noise; HTF setup может выглядеть слабо на LTF до закрытия HTF бара.

## Формат финального ответа

1. **Текущая цена** + время data feed
2. **Cascade summary** (краткое summary по каждому ТФ: trend + ключевые зоны)
3. **Multi-TF confluence zones** (где сходятся 2+ ТФ)
4. **HTF magnets** (top-3 ближайших)
5. **Сценарии A / B / (C)** с вероятностями + multi-TF триггерами
6. **Invalidation map** (cross-TF таблица)
7. **Caveats** (forming bars, актуальность)
8. Опционально: предложение follow-up (entry levels, аналоги, графики)

## Что НЕ делать

- НЕ давать одно-TF мнение без явного указания "только TF X, остальные не учтены".
- НЕ опираться только на одну зону / один фрактал — мнение строится на multi-TF confluence.
- НЕ давать "прогнозную цифру" без сценариев и триггеров.
- НЕ игнорировать W / D structure (их игнорирование = торговля против дома).
- НЕ переинвертировать: LTF reversal-сигнал НЕ отменяет HTF trend — это retracement.
- НЕ давать % уверенности > 75 % без strong multi-TF confluence (3+ ТФ aligned).
- НЕ путать магнит-зоны (inefficiency / liquidity) с S/R (блок).

## Реализация

Reference-script: `scripts/expert_opinion.py` (поддерживает каскад).

Запуск каскада:
```bash
python3 scripts/expert_opinion.py --tfs W,D,12h,4h,1h,15m
```

Или отдельный ТФ для углублённого анализа:
```bash
python3 scripts/expert_opinion.py --tfs D --start 2026-04-04
```

Шаги 1–5 (детекция, позиция, магниты) выполняются скриптом автоматически per TF.
Шаги 6–10 (structure, cascade integration, scenarios, invalidation) — синтез ассистентом на основе output'а.

## Связи

- [[feedback-expert-opinion-is-multi-tf-cascade]] — главный принцип (multi-TF cascade).
- [[zone-class-liquidity-inefficiency-block]] — таксономия для Step 4.
- [[feedback-untraded-area-is-magnet]] — магнит-модель для Step 5.
- [[feedback-fractal-liquidity-strength-and-sweep]] — TF × age × cluster, HTF wick swallows LTF.
- [[feedback-marubozu-is-imbalance-not-support]] — interaction model для marubozu-зон.
- [[weekly-tf-anchor-monday]] — W = Mon-anchor.
- [[rules.md]] — Правило 1 (закрепление цены) для триггеров.
- [[zone_of_interest.md]] — справочник всех зон.
