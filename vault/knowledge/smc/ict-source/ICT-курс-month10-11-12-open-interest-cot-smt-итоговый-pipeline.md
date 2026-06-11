---
type: external-source
source_file: "Month10-june + Month11-july + Month12-august study notes"
source_pages: "201 + 52 + 101"
course: "ICT Monthly Mentorship 2016-2017"
month: "10-12 / Июнь-Август 2017 (финал курса)"
author: "Michael J. Huddleston (ICT)"
ingested: 2026-06-10
tags: [ict, smc, course, open-interest, smt, external]
---

# ICT-курс · Month 10-12 (июнь-август 2017) — Open Interest, COT, SMT + итоговый pipeline

Завершающие три месяца. Углубление в order flow (Open Interest, COT) и **синтез всей методологии в единый decision pipeline** (Month12).

## Month10 (июнь) — Open Interest, SMT, FOMC

**Open Interest (OI)** — число открытых контрактов; измеряет приток денег (volume = интенсивность, OI = поток денег). Правила OI:

- Uptrend + OI растёт → **bullish** (новые продавцы вытесняются, лонги крепнут).
- Uptrend + OI падает → **bearish** (smart money лонги фиксируют прибыль).
- Downtrend + OI растёт → **bearish**; Downtrend + OI падает → **bullish** (шорты-smart money крывают; «когда запас лузеров иссяк — тренд кончается»).
- Consolidation + OI растёт → bearish; + OI падает → bullish.
- Применять на **HTF у Discount/Premium Array**: цена у HTF support + OI падает → bullish upswing.

⚠️ **OI — фьючерсный концепт.** Для крипты есть аналог: **Open Interest на перпетуалах/фьючах (Binance Futures OI, funding rate)**. У нас бот на **Spot** ([[почему binance а не bybit]]), OI не используется. 🔗 **Кандидат:** добавить Futures OI / funding как confluence-фильтр (но это против минимализма — отдельный data source).

- **SMT divergence (Index SMT on Highs/Lows)** — расхождение коррелированных инструментов на хаях/лоях = подсказка разворота. «Rely on Time Of Day» + FOMC как драйвер. 🔗 = cross-asset divergence; у нас BTC/ETH/SOL — можно проверять SMT между ними (когда BTC делает HH, а ETH — LH = bearish divergence). **Дешёвый кандидат на наших данных.**

## Month11 (июль) — Fundamental Screen (forex-специфика)

Воронка фундамента: USDX relative strength, two currency leaders, quarterly earnings, seasonal tendency (spring/summer), bond market in discount, hunt interest rate SMT, «Fall Highs Then Short Term Trading Begins», «Wait For HTF Institutional PDA».

⚠️ Почти всё **forex/equities-специфично** (earnings, currency leaders, bonds). Для крипты неприменимо. Takeaway только концептуальный: ждать HTF institutional PDA перед входом (= наш каскад).

## Month12 (август) — ⭐ итоговый Decision Pipeline (синтез курса)

Финал собирает ВСЁ в единую воронку анализа (top-down):

```
Seasonal Tendency → Quarterly Shifts → Interest Rate Differentials
  → Intermarket Analysis → Market Structure → Market Profile
  → PD Array Matrix → Key Price Levels
  → Monthly Bias Defined → Weekly Bias Defined
  + Relative Strength + Commitment Of Traders (COT) + Market Sentiment
```

Логика: от макро/сезонности → через intermarket → к структуре и PD Array Matrix → к bias на Monthly, затем Weekly → исполнение на LTF. **COT (Commitment of Traders)** — позиции крупных игроков как подтверждение.

🔗 **Для нашего проекта** релевантная (крипто-применимая) часть pipeline:
`Market Structure → PD Array Matrix → Key Price Levels → Monthly/Weekly Bias → execution на 1H`.
Это РОВНО наш multi-TF каскад + empirical calibrator ([[traid-bot-ml-pivot]]). Неприменимое (forex/equities): Seasonal, Interest Rate Differentials, Intermarket, COT (хотя крипто-COT-аналог = Futures OI/funding).

## Итоговые выводы по всему ICT-курсу (12 месяцев)

**Что подтвердило наш подход:**
- Multi-TF top-down каскад HTF→1H execution ([[expert-opinion-multi-tf-cascade-methodology]]).
- Mid-entry = Mean Threshold (50% OB).
- pro-trend + Premium/Discount bias = наш тренд-фильтр.
- OB/FVG определения совпадают с каноном ([[универсальные определения OB и FVG]]).

**Новые крипто-применимые кандидаты (по убыванию дешевизны проверки):**
1. **SMT divergence** между BTC/ETH/SOL (cross-asset на хаях/лоях).
2. **Day-of-week / weekly profile** (low-of-week в Mon-Wed) — [[ICT-курс-month07-08-09-time-price-killzones-weekly-profile-accumulation]].
3. **3 недостающих элемента зон:** Rejection Block, Breaker, Mitigation Block — [[ICT-курс-month05-06-intermarket-и-PD-arrays-иерархия-зон]].
4. **Futures OI / funding** как confluence (дороже — новый data source, против минимализма).
5. **Accumulation/Distribution фазы** ↔ Money Hands ([[money-hands-asvk]]).

**Не переносим (forex/equities):** Interest Rate Triads, Intermarket Analysis, COT, currency leaders, earnings, killzones-сессии (крипта 24/7).

⚠️ Весь курс — **методология/нарратив без статистики** (и forex-ориентирован). Любую идею — через [[7-criteria-of-good-strategy]] + проверка lookahead [[known-pitfalls]].

Предыдущий: [[ICT-курс-month07-08-09-time-price-killzones-weekly-profile-accumulation]]. Каталог: [[ICT-source-индекс]].
