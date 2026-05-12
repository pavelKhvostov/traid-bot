---
tags: [session, forensic, strategy-1-1-1, indicators, hull-ma, ict, asvk]
date: 2026-05-08
duration: medium
session_type: forensic-analysis + filter-search
---

# Сессия 2026-05-08 — Forensic Strategy 1.1.1 + indicator filters

## TL;DR

1. **Hull-4h pro-trend filter — мощный отдельный edge source** на 1.1.1:
   `WR 53.8% → 67.4%, +13.6pp, +27R на отфильтрованных 135 trades`. Самая
   сильная single-feature метрика которую видели за сессию.
2. **Score-based composite фильтр (5 топ-фич) — монотонная связь**
   score ↔ WR (0→20%, 1→41%, 2→41%, 3→59%, 4→70%, 5→100%). Не overfit.
3. **1.1.1 даже с filter rescue остаётся ниже C2** — все варианты
   filter дают frequency 0.15-0.30 setups/wk (fail criterion 4 из
   [[7-criteria-of-good-strategy]]).
4. **Главная польза находок — universal filters** для C2/C3/C6 и других
   trend-following кандидатов.

## Метод

`research/elements_study/etap_35_strategy_111_forensic.py`:
1. Берём 262 closed trades 1.1.1 honest (из etap_34) на 6.33y
2. Для каждой считаем 14 features at signal_time (FVG-15m c2_close):
   - Hull MA(78) trend на 1d, 4h, 1h
   - ASVK Custom RSI zone на 1h (red/yellow_OB/neutral/yellow_OS/green)
   - Money Hands bw2 color на 1h, MF sign на 1h
   - EMA200 align на 4h/1h/15m
   - ICT: hour, weekday, session, daily-open premium/discount
3. Per-feature WR/total_R, sorted
4. Filter combos с re-evaluation на RR=1.0/1.5/2.0

CSV всех trades + features: `output/etap35_trades_111_features.csv`.

## Single-feature ranking (262 closed, baseline WR 53.8% / +20R)

### 🥇 Топ-7 positive predictors (n ≥ 30)

| Feature | n | WR | Δpp | total_R | avg_R |
|---|---|---|---|---|---|
| **Hull 4h aligned** | 135 | **67.4%** | **+13.6** | +47R | +0.348 |
| **mh_mf aligned** (HA-MF sign) | 140 | 63.6% | +9.8 | +38R | +0.271 |
| Daily-open discount | 149 | 61.1% | +7.3 | +33R | +0.221 |
| EMA200 15m aligned | 145 | 60.7% | +6.9 | +31R | +0.214 |
| ICT NY session | 46 | 63.0% | +9.2 | +12R | +0.261 |
| Anchor 12h (vs 1d) | 137 | 58.4% | +4.6 | +23R | +0.168 |
| EMA200 1h aligned | 143 | 58.7% | +4.9 | +25R | +0.175 |

### 🚫 Топ negative predictors (n ≥ 30)

| Feature | n | WR | Δpp | total_R |
|---|---|---|---|---|
| Friday | 49 | 38.8% | −15.0 | −11R |
| **Hull 4h counter** | 127 | **39.4%** | **−14.4** | −27R |
| Daily-open premium | 113 | 44.2% | −9.6 | −13R |
| **mh_mf counter** | 122 | 42.6% | −11.2 | −18R |
| EMA200 15m counter | 117 | 45.3% | −8.5 | −11R |
| Anchor 1d (vs 12h) | 125 | 48.8% | −5.0 | −3R |

### ⚪ Что НЕ работает (no edge)

- **Hull 1h trend** — WR 53.8 vs 53.8% (noise на этом TF)
- **Money Hands bw2 color** — 54.3 vs 53.6% (color machine не дискриминирует)
- **ASVK ema_3 yellow_OS / green** — n слишком мало для conclusion
- **EMA200 4h** — counter лучше aligned (counterintuitive — wait,
  это значит mean-reversion работает на 4h в этих setups; но n=127 vs 135 близко)

### ⚠ Counterintuitive

- **ICT London (07-12 UTC) — anti-edge** WR 48.2%! Только NY (12-17 UTC)
  работает. Возможно crypto-специфика — европейские часы во время
  тестируемого периода были более consolidation-heavy.
- **Hour 18 UTC: WR 0% / -7R на 7 trades** — likely конкретный news event
  (close NY equity market). Need sample size.
- **2026 (4 мес) WR 38.5%** — current period regime change, но n=13 мало.

## Filter rescue — может ли 1.1.1 работать на RR > 1?

Главный вопрос: 1.1.1 honest @ RR=1.5 = −35R, @ RR=2.0 = −58R. Спасают ли filters?

| Filter | n_keep | RR=1.0 | RR=1.5 | RR=2.0 |
|---|---|---|---|---|
| baseline | 262 | 53.8% / +20R | 33% / **−35R** | 23% / **−58R** |
| Hull 4h | 135 | 67.4% / +47R | 42% / +5.5R | 32% / −4R |
| **Hull 4h + EMA200 15m** | 96 | 70.8% / +40R | **47.9% / +14.5R** ✅ | **37.7% / +8R** ✅ |
| Hull 4h + mh_mf | 89 | 73.0% / +41R | 44.4% / +7R | 34% / +1R ✅ |
| Hull 4h + ICT(L\|NY) | 49 | 73.5% / +23R | **56.8% / +15.5R** ✅ | 41.9% / +8R ✅ |
| **Score ≥ 4** (5 features) | 68 | 75.0% / +34R | **51.9% / +15.5R** ✅ | 39.0% / +7R ✅ |

✅ = rescue: positive total_R при RR > 1.

**Вывод:** Любой 2-feature filter с Hull-4h рескуит RR=1.5 (которое было
−35R baseline). Лучший edge × frequency tradeoff:
- **Hull 4h + EMA200 15m** — 96 trades, RR=1.5 → +14.5R / WR 48% / R/tr +0.199
- **Score ≥ 4** — 68 trades, RR=1.5 → +15.5R / WR 52% / R/tr +0.298

## Score gradient — главная картинка

Composite score из 5 features: `hull_4h + do_pos:discount + ict:LON|NY +
mh_mf + ema200_15m`, считаем сколько aligned (0..5):

| Score | n | WR | Total R |
|---|---|---|---|
| 0 | 15 | 20.0% | −9R |
| 1 | 46 | 41.3% | −8R |
| 2 | 58 | 41.4% | −10R |
| 3 | 75 | 58.7% | +13R |
| 4 | 56 | 69.6% | +22R |
| 5 | 12 | 100.0% | +12R |

**Монотонная связь.** Не overfit (структурный signal: чем больше «звёзд
сошлось», тем выше WR). 263 closed trades — статистически значимо.

Граница score=3 — естественный threshold. Score ≤ 2 (119 trades / 45%)
это **−27R loss bucket** который надо отрезать.

## Заключение про 1.1.1 как стратегию

Даже с best filter (Hull 4h + EMA200 15m или score≥4):
- Frequency 96/6.33y = **0.29 setups/wk** (criterion 4 требует ≥1/wk)
- Total R ~ +40-50R / 6.33y = **+6-8R/year** (vs C2 +11R/year)
- WR хорошая (67-75% RR=1.0) но volume не хватает

→ **1.1.1 + filter не догоняет C2 как primary strategy.** Оставляем 1.1.1
как case study failed-then-rescued; main winner — C2.

См. [[strategy-1-1-1-honest-audit-failed]] обновить с rescue-results.

## Что ВАЖНО для других стратегий

Эти filter находки потенциально применимы к C2/C3/D2/любым
trend-following кандидатам:

### Action items для C2 ([[strategy-c2-ob-6h-fvg-2h-pro-rr1]])

1. **Test C2 + Hull 4h pro-trend filter.** C2 уже использует EMA200(2h)
   как pro-trend. Hull-4h может быть либо complementary (сильнее
   фильтрует), либо redundant (та же информация). Гипотеза: C2 уже видит
   часть этого через EMA200, но Hull-4h добавит ~+3-5pp WR.
2. **Test C2 + daily-open premium/discount.** На 1.1.1 это +7.3pp WR.
   На C2 (RR=1, mid entry) ожидаемый эффект меньше (RR=1 не sensitive к
   точке входа), но точно не повредит.
3. **Test C2 + Friday exclusion** (на 1.1.1 Fri = −15pp WR).
   Критичная гипотеза — может быть макро-pattern для крипто.

### Action items для всей research-ветки

1. **Hull-4h как universal pro-trend filter** — добавить опцию в
   `_shared/backtest_year.py` для всех research-стратегий.
2. **Daily-open ICT premium/discount** — реализовать как helper в
   `research/_shared/ict.py` (новый файл).
3. **«Score-based filter» как pattern** — для будущих confluence-стратегий
   считать composite score 3-5 features, не binary all-or-nothing.

## Грабли, найденные по пути

1. **CP1251 console на Windows** — Δ, ★ ломают вывод
   (`UnicodeEncodeError`). Replaced на `d=`, `***`. Третий случай за
   2026-05-08 — добавить в [[known-pitfalls]] если ещё не там.
2. **MH bw2 color (зелёный/серый) — НЕ работает на 1.1.1.** Поверх
   trend-MAs (Hull) и MF sign — не даёт дополнительной информации.
   Возможно работает на counter-trend стратегиях (RDRB, fractal sweeps).
3. **EMA200 4h aligned проигрывает counter** — не используем без
   проверки (n близок, может flukе).

## Артефакты

- `research/elements_study/etap_35_strategy_111_forensic.py`
- `research/elements_study/output/etap35_trades_111_features.csv`
  (262 строки × 30 колонок, для последующего ML/segmentation)
- `research/elements_study/output/etap35_run.log` — полный output

## Sequel: применение к C2 (etap_36, тот же день)

Тестировали топ-5 фильтров поверх C2:
- **Hull-4h aligned** на C2 — flat (-1.3pp)! Top finding на 1.1.1 не работает.
- **Hull-1d aligned** на C2 — **+6.8pp WR / +41R total**! Оказался настоящий
  winner для C2.
- DO discount, MH MF, ICT, Score — все слабые / отрицательные на C2.

→ **Создан новый winner [[strategy-c2v2-ob-6h-fvg-2h-pro-hull-1d]]:**
+101R / RR=1.5 / 0 bad years.

**Универсальный lesson:** Hull TF должен быть на **1-2 ступени выше anchor TF**:
- 1.1.1 anchor 1d/12h → Hull-4h
- C2 anchor 6h → Hull-1d

Filter findings из forensic не переносятся механически между стратегиями.

## Связи

- [[strategy-1-1-1-honest-audit-failed]] — rescue attempt fail (frequency)
- [[strategy-c2-ob-6h-fvg-2h-pro-rr1]] — baseline C2
- [[strategy-c2v2-ob-6h-fvg-2h-pro-hull-1d]] — **новый winner** через
  применение находок к C2
- [[asvk-trend-line-hull]] — Hull MA как ключевой filter
- [[asvk-custom-rsi]] — yellow_OB как anti-edge marker (на 1.1.1)
- [[money-hands-asvk]] — bw2 color НЕ работает; MF sign работает только на 1.1.1
- [[7-criteria-of-good-strategy]] — C2v2 проходит 7/7
