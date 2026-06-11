---
type: external-source
source_file: Month03-november_notes.pdf
source_pages: 71
course: "ICT Monthly Mentorship 2016-2017"
month: "03 / Ноябрь 2016"
author: "Michael J. Huddleston (ICT)"
ingested: 2026-06-10
tags: [ict, smc, course, timeframes, external]
---

# ICT-курс · Month 03 (ноябрь 2016) — выбор таймфрейма и top-down анализ

Третий месяц. Тема — **как выбрать таймфрейм под свою модель** и top-down подход (Monthly → Weekly → Daily → LTF). Прямо релевантно нашей multi-TF каскадной методологии.

## Таймфрейм ↔ тип трейдинга

- **Monthly** → Position Trading (свинги на сотни пипсов, формируются месяцами).
- **Weekly** → Swing Trading (недели).
- **Daily** → Short Term Trading (1–3 недели, 50–300 пипсов).
- **4H и меньше** → Day Trading.

## Типы трейдеров (определи свою модель)

1. **Trend Trader** — только по направлению Monthly+Weekly.
2. **Swing Trader** — Daily, среднесрок.
3. **Contrarian** — развороты на экстремумах.
4. **Short Term** — недельные диапазоны, 1–5 дней.
5. **Day Trader** — интрадей, выход к 14:00 NY.

## Top-down логика (ядро месяца)

Анализ сверху вниз: на Monthly определить долгосрочный swing и «куда цена пойдёт дальше / что под этим уровнем» (ликвидность) → перенести на Weekly → Daily. На каждом шаге ищем те же reference points: **Orderblocks, Stop Runs, Liquidity Voids**. Торговать в направлении самого свежего HTF-сетапа = low risk / high reward.

## Выводы для проекта (⚡сильное совпадение)

- Это **методологическое обоснование нашего multi-TF каскада**: HTF задаёт направление и зону, LTF уточняет вход с меньшим стопом. Ровно то, что у нас в [[expert-opinion-multi-tf-cascade-methodology]] и в семействе 1.1.x (OB-{1d,12h} → ... → OB-{1h,2h}).
- **Mapping на наши TF:** ICT Monthly/Weekly/Daily/4H ≈ наши макро-якоря 1d/12h → промежуточные 4h/6h → entry 1h/2h. Концептуально та же иерархия, что в [[три типа подтверждения 1h ob fvg rdrb]].
- **«Trade in direction of HTF setup»** = наш **pro-trend** фильтр в C2 ([[strategy-c2-ob-6h-fvg-2h-pro-rr1]]) и Hull-1d тренд-фильтр ([[c2-ema-or-hull6h-trend-filter-winner]]).
- **Осторожно:** forex-пипсы и сессии; крипта 24/7. Концепция top-down переносится, конкретные TF — наша эмпирика (FVG-12h > FVG-1d, см. [[fvg-12h-сильнее-fvg-1d-как-макро-якорь]]) уже точнее «дефолта Daily».

Предыдущий: [[ICT-курс-month02-октябрь-rr-money-management-mean-threshold]]. Следующий: [[ICT-курс-month04-декабрь]]. Каталог: [[ICT-source-индекс]].
