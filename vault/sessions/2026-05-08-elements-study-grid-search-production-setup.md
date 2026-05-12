---
tags: [session, research, smc, ob, fvg, rdrb, fractal, grid-search, production]
date: 2026-05-08
---

# Сессия 2026-05-08 — изучение SMC-элементов + grid search + production setup

Большая исследовательская сессия. Цель — методично изучить каждый SMC-примитив
(OB, FVG, RDRB, FH/FL) на BTC за 6 лет, найти закономерности и
скомбинировать в production-стратегию с задачей **WR>=55%, RR=2,
1-2 сделки/неделю** на фьючерсах (min SL 1%).

## Этапы и результаты

### Этап 0 — догрузка истории
Догружен BTCUSDT с 2020-01-01 для 1m, 15m, 1h, 2h, 4h, 6h, 12h, 1d.
Coverage 99-100% на старших ТФ, 79% на 1m/15m (gaps в ранний 2020).
Скрипт: [research/elements_study/etap_0_fetch_history.py](../../research/elements_study/etap_0_fetch_history.py)

### Этапы 1-4 — глубокое изучение каждого элемента

| Элемент | n (1h) | size % | bounce_1x | bounce_3x | sl_first | max_R |
|---|---:|---:|---:|---:|---:|---:|
| **OB** | 14k | 0.39 | 92% | 71% | 44% | 5.6× |
| **FVG** | 10k | 0.18 | 96% | 83% | 62% | 13× |
| **RDRB** | 7k | 0.07 | 99% | 96% | 78% | 35× |
| **Fractal** | 15k | n/a (level) | 89% | 53% | 44% | 3.2 ATR |

Полные отчёты:
- [research/elements_study/output/ob_report.md](../../research/elements_study/output/ob_report.md)
- [research/elements_study/output/ob_context_report.md](../../research/elements_study/output/ob_context_report.md)
- [research/elements_study/output/fvg_report.md](../../research/elements_study/output/fvg_report.md)
- [research/elements_study/output/rdrb_report.md](../../research/elements_study/output/rdrb_report.md)
- [research/elements_study/output/fractals_report.md](../../research/elements_study/output/fractals_report.md)

**Главный паттерн:** чем компактнее зона — тем выше bounce% и тем выше variance.

### Этап 5 — 5 связок (А-Д) — все опровергнуты кроме одной

Пытался придумать связки из общей логики. Реальный backtest показал:
- **Только Б работает**: FVG-1d + sweep fractal-1h → +17R / 67 сделок / R/tr +0.254
- В/Г/Д — отрицательно
- **Triple-confluence (В) — миф**: −7R / R/tr −0.37

**Главный урок:** «гипотезы из общих идей» хуже **наблюдений из real backtest**.

### Этапы 6-8 — single-element setups + RR sweep

WR≥70% при RR≥1.5 на одиночном элементе **недостижим** на BTC за 6 лет.
Лучшее: ~33-36% WR при RR=2 (около break-even).

**Ключевой инсайт:** `bounce_1x = 99% НЕ означает WR=99% при RR=2`.
Bounce-метрики из этапов 1-4 измеряли «дотягивает ли цена до 1×zone хоть
когда-то», что не равно «дойдёт ли до TP до выноса SL».

→ см. [[bounce-1x-не-равно-wr-при-rr]]

### Этап 9 — Grid search 114 комбинаций

Перебрал single-element + pairs (HTF zone × LTF zone того же direction
в зоне HTF) × 3 RR. Результат:

**4 проходят WR≥55% и n/week≥0.5:**
1. **[OB-1d small] + [FVG-1h]** RR=1.0 → WR 60.7% / R/tr +0.214 / 0.74/нед
2. [OB-4h small] + [FVG-1h] RR=1.0 → WR 60.5% / R/tr +0.211 / 0.81/нед
3. [RDRB-1d] + [RDRB-1h] RR=1.0 → WR 58.9% / R/tr +0.178 / 0.88/нед
4. [FVG-1d] + [FVG-1h] RR=1.0 → WR 56.2% / R/tr +0.123 / 0.68/нед

### Этап 10 — Deep-dive winner

Multi-counting проблема: 65 unique OB-1d → 420 setups (median 4 FVG/OB,
max 36!).

**С дедупом (one-FVG-per-OB):**
- WR 66.0%, R/tr +0.320 (vs WR 57.7% без дедупа)
- но n=50 closed (~10/год) — мало для частоты

**FVG pro-trend** добавляет +10 п.п. WR (62.8% vs 52.1% counter).

**Стабильность по годам тревожная:** 2020-2023 ~ 65% WR, **2024-2025 ~ 50%**.

### Этапы 11-12 — фьючерсный SL (min 1%)

Узкий ATR-only SL (median 0.34%) недопустим для фьючерсов.
С min_sl=1% от entry edge падает но остаётся:
- [OB-4h] + [FVG-1h pro] + RR=1.5 + min_sl=1% → WR 55.2% / R/tr +0.380 / 0.50/нед

### Этап 13 — переосмысление size-фильтра

**Шок-открытие:** size-фильтр был ошибкой. Без size-фильтра total return лучше:

| Size | n/wk | WR | R/tr | total R |
|---|---:|---:|---:|---:|
| **ALL** | 3.43 | 56.9% | +0.138 | **+116R** |
| medium | 2.61 | 56.9% | +0.138 | +88R |
| small | 0.50 | 58.4% | +0.168 | +21R |
| large | 0.32 | 54.4% | +0.089 | +7R |

(все с pro-trend FVG, RR=1.0, min_sl=1%)

**Pro-trend = главный фильтр.** Size — слабый при правильном SL/RR.

## 🏆 Production-кандидат (финал сессии)

```
ВХОД:
1. На 4h детектируется ЛЮБОЙ OB (без size-фильтра)
2. Внутри 5 дней после OB на 1h формируется
   ПЕРВАЯ FVG того же направления, чья зона
   пересекается с OB-4h
3. ФИЛЬТР: FVG pro-trend (close_1h > EMA200_1h для LONG / < для SHORT)

ENTRY: limit на mid(FVG-1h)

STOP LOSS:
   sl = max(FVG_далекая_граница − 0.3·ATR_1h, entry − 1% от entry)

TAKE PROFIT: tp = entry + 1.0 × risk (RR=1.0)

TIMEOUT: 14 дней
```

**Цифры на BTCUSDT 2020-2026:**
- 1130 setups → 3.43/неделю
- WR 56.9%, R/tr +0.138
- Total +116R за 6 лет ≈ **+18R/год**
- Median risk 1% от entry (фьючерс-friendly)
- При риске 1%/trade: ~+18%/год; при 2%: +36%/год

См. [[strategy-ob-4h-fvg-1h-pro-trend]]

## Главные уроки сессии

1. **Multi-counting легко исказить картину** в 1.5-2× — обязательно делать дедуп.
2. **Bounce-метрики ≠ realistic WR** — изначально я обманывался, mistakenly выбрав small.
3. **Pro-trend filter > size filter** на pair-сетапах при правильном SL.
4. **Size-фильтр для HTF zone — слабая идея** при включенном min_sl%.
5. **WR≥70% при RR=2 на BTC за 6 лет — недостижим** на любых element-комбинациях.
   Реалистичный таргет: WR 55-60% при RR=1.0.
6. **Grid search > intuitive hypotheses.** 4 из 5 связок «по логике» опровергнуты;
   реальный winner найден перебором 114 комбинаций.

## Открытые вопросы

1. **Стабильность 2024-2025**: WR в эти годы ниже 60-65% baseline'а 2020-2023.
   Edge выгорает или временный режимный сдвиг?
2. **Out-of-sample**: проверить production-кандидат на ETH/SOL.
3. **Walk-forward**: разделить выборку на train/test и проверить устойчивость
   найденного setup'а.
4. **Live integration**: оформить как `strategies/strategy_X_X.py` с тестами
   и Telegram-сигналами.

## Файлы сессии

В `research/elements_study/`:
- 13 этапов скриптов (`etap_0_*.py` → `etap_13_*.py`)
- output/ — все CSV-сводки и report-md (5 элементов × 8 ТФ + grid search +
  production trial)

## Связи

- [[asvk-custom-rsi]], [[money-hands-asvk]] — индикаторы (другая сессия)
- [[универсальные определения OB и FVG]], [[что такое rdrb]],
  [[фракталы билла уильямса]] — canon-определения
- [[strategy-ob-4h-fvg-1h-pro-trend]] — production-кандидат (новая)
- [[bounce-1x-не-равно-wr-при-rr]] — pitfall (новая)
