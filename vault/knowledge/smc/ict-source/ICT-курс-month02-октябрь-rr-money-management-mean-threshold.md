---
type: external-source
source_file: Month02-October_Notes.pdf
source_pages: 121
course: "ICT Monthly Mentorship 2016-2017"
month: "02 / Октябрь 2016"
author: "Michael J. Huddleston (ICT)"
ingested: 2026-06-10
tags: [ict, smc, course, risk-management, external]
---

# ICT-курс · Month 02 (октябрь 2016) — Reward/Risk, money management, Mean Threshold

Второй месяц. Главная тема — **математика R:R и управление капиталом** + защита от ловушек маркет-мейкера. Один важный технический концепт: **Mean Threshold**.

## Рост малого счёта без высокого риска

- Чего избегать: не гнаться за быстрыми крупными %, не открывать большой риск ради большой прибыли, не жертвовать капиталом из-за плохого планирования.
- К чему стремиться: реалистичный R:R, **уважать риск важнее награды**, искать сетапы ≥**3:1**, чтобы убытки слабо влияли на счёт.
- Пример «малых целей»: 20 пипсов/неделю, риск 1.5%, R:R 1:1 → стабильный compounding. 6%/мес достижимо на дневных орблоках.

## Технический приём: Mean Threshold (⚡ВАЖНО для нас)

- **Mean Threshold = 50% орблока** (его середина). Используется как:
  - точка входа на вторичном bullish OB,
  - уровень для размещения стопа.
- Bullish OB = down-свеча перед ралли (последняя противоположная свеча). High этого OB до open price = **Fair Value Gap / наиболее вероятный «support»**.
- 🔗 Это РОВНО наш **mid-entry единой зоны** в [[strategy-c2-ob-6h-fvg-2h-pro-rr1]] и приём «entry=mid OB+FVG». ICT называет середину орблока «mean threshold». Подтверждает выбранную нами механику входа.

## Loss recovery (мартингейл-лайт)

- После стопа (например −2%): войти повторно **½ размера позиции** (риск станет 1%). Митигирует исходный убыток, если цена ещё не пробила хай. ⚠️ Это усреднение/мартингейл-логика — у нас НЕ применяется и противоречит fixed-risk модели; фиксирую как «чужой подход, не переносить».

## Математика R:R (таблицы «Consider The Numbers»)

При R:R = 5:1 и риске 2%:
- WR 30% → +16%/мес; WR 40% → +28%; WR 50% → +28%... +.
- Вывод ICT: **при высоком R:R даже WR 30–40% прибыльны**. → 🔗 Прямо релевантно нашему спору про floating-TP и low-WR стратегии ([[floating-tp-only-helps-low-wr-strategies]]): высокий R:R компенсирует низкий WR. Но у нас C2 сознательно RR=1.0 с WR 55% — другая точка на кривой. Это не противоречие, а напоминание: WR без R:R бессмысленен (см. наш закон в [[traid-bot-empirical-laws]] про bounce≠WR).

## Market Maker Traps (паттерны-ловушки)

- **False Bull/Bear Flags** — не каждый флаг = продолжение; в зрелом тренде / на HTF distribution(accumulation) флаг разворачивается. Premium/Discount контекст помогает отличить.
- **False Breakouts** — на equilibrium рынок входит в range; breakout-трейдеры ставят заявки по краям; ММ выносит цену за range, чтобы снять стопы (выше range в bearish-рынке / ниже в bullish), затем разворот. 🔗 = liquidity sweep / stop-run; родственно нашему SWEPT-флагу в стратегиях 1.1.x.

## Структура «Secrets To High Reward» (анонс будущих месяцев)

1. Correlation Analysis (USDX SMT, correlated-pair SMT) ← **SMT divergence** — новый концепт.
2. Time & Price Theory (Quarterly/Monthly/Weekly/Daily range, Time of Day).
3. IPDA (Institutional Order Flow, Liquidity Seeking, Market Efficiency Paradigm).

## Выводы для проекта

- **Подтверждает наш Mean Threshold = mid-entry** (главная техническая ценность месяца).
- **R:R-математика** — напоминание, что edge = WR × R:R совместно; релевантно нашим спорам про floating-TP.
- **False breakout = stop-run** — наш SWEPT уже это ловит.
- **Не переносить:** loss-recovery усреднением (мартингейл) — против нашей fixed-risk модели.
- **Новое на будущее:** SMT divergence (корреляция активов) — у нас есть cross-asset (BTC/ETH/SOL) и confluence BTC1!/TOTALES/USDT.D в 1.1.1, но SMT как divergence-детектор не формализован → кандидат.

Предыдущий: [[ICT-курс-month01-сентябрь-основы-price-action]]. Следующий: [[ICT-курс-month03-ноябрь]]. Каталог: [[ICT-source-индекс]].
