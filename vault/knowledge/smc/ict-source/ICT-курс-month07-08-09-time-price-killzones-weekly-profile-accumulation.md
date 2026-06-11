---
type: external-source
source_file: "Month07-march + Month08-april + Month09-may study notes"
source_pages: "133 + 85 + 106"
course: "ICT Monthly Mentorship 2016-2017"
month: "07-09 / Март-Май 2017"
author: "Michael J. Huddleston (ICT)"
ingested: 2026-06-10
tags: [ict, smc, course, time-price, killzones, external]
---

# ICT-курс · Month 07-09 (март-май 2017) — Time & Price, Killzones, недельный профиль, Accumulation/Distribution

Три месяца про **применение PD Arrays через время**: добавляется ось ВРЕМЕНИ к оси ЦЕНЫ. (Month07 = дубль `(1)`, читался один.)

## Month07 (март) — Time & Price Theory + недельный профиль

- **PD Array каскад до execution:** Monthly → Weekly → Daily → 4Hour → **1Hour (Execution)**. На каждом TF делим на **Premium / Discount** относительно equilibrium. Вход исполняется на 1H. 🔗 = РОВНО наш каскад с confirm на 1h ([[три типа подтверждения 1h ob fvg rdrb]])! ICT тоже завершает на 1H execution.
- **Premium Array / Discount Array + Killzone** — зоны премиум/дисконт, привязанные к killzone-времени.
- **Недельный профиль (Time):**
  - Каждую неделю рынок ходит от одного PD Array к другому, из квадранта в квадрант по пути наименьшего сопротивления (Premium↔Discount).
  - **Low/High of the Week обычно формируется Mon-Tue-Wed (MTW).** Weekly range на 30-50% завершается внутри Mon→Wed.
  - Когда пробивается Mon-Wed High → цена агрессивно расширяется к Monthly/Weekly Premium Array.
  - Wednesday/Thursday reversals могут формировать месячный профиль.
- **Институциональная подсказка:** «Wednesday breaks short-term high then finds institutional sponsorship on +OBs» — среда часто даёт вход на бычьих OB.

🔗 **Для крипты:** недельный профиль (день недели) — у нас НЕ используется как фильтр. Крипта 24/7, но day-of-week сезонность может существовать. **Кандидат на проверку:** есть ли у BTC статистика «low of week в Mon-Wed»? Дёшево проверить на наших данных.

## Month08 (апрель) — PD Array Matrix + Time & Price

- **PD Array Matrix** — сводная матрица: все PD Arrays (из [[ICT-курс-month05-06-intermarket-и-PD-arrays-иерархия-зон]]) × все TF, наложенные на Time & Price Theory.
- «Too Large» / «Close» — про **отбор OB по размеру**: слишком крупные орблоки отбраковываются (нужен компактный OB для приемлемого стопа). 🔗 = наш sl=max(15%·OB,1%): крупный OB → большой стоп → хуже R. Совпадает с идеей «избегать too large OB».

## Month09 (май) — Accumulation / Distribution (Wyckoff-подобные фазы)

Фазы институционального набора/разгрузки:
- **Buy Program:** Offset → Accumulation → Reaccumulation → (рост).
- **Sell Program:** Offset → Distribution → Redistribution → (падение).

🔗 Это Wyckoff-логика накопления/распределения. У нас как явный детектор фаз НЕ оформлено. Концептуально близко к consolidation-фазе ([[ICT-курс-month01-сентябрь-основы-price-action]]) и Money Hands индикатору ([[money-hands-asvk]], [[traid-bot-ml-pivot]] — MH ML pipeline). MH как раз про «руки» (smart money) — возможна связь.

## Выводы для проекта

- **Подтверждает наш каскад HTF→1H execution** (ICT тоже завершает на 1H).
- **Новые кандидаты на проверку (дёшево, на наших данных):**
  1. **Day-of-week профиль** — low/high недели в Mon-Wed? (Time-фильтр)
  2. **OB size filter** — отбраковка «too large» OB (у нас частично через sl-cap).
  3. **Accumulation/Distribution фазы** — связь с Money Hands ([[money-hands-asvk]]).
- **PD Array Matrix** = концепт «все зоны × все TF» — у нас реализован как multi-TF scan + empirical calibrator.
- ⚠️ Killzones/сессии — forex-время; для крипты 24/7 проверять отдельно.

Предыдущий: [[ICT-курс-month05-06-intermarket-и-PD-arrays-иерархия-зон]]. Следующий: [[ICT-курс-month10-11-12]]. Каталог: [[ICT-source-индекс]].
