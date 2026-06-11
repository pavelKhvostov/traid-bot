---
type: external-source
source_file: "screencapture-medium-ziad-francis-automating-fair-value-gaps-fvg-in-python.pdf"
source_pages: 8
author: "Ziad Francis, PhD (Medium / CodeTrading)"
ingested: 2026-06-10
tags: [fvg, smc, python, code, external]
---

# Medium: FVG-детектор на Python — сверка с нашим `fvg`

Конспект статьи Ziad Francis «Automating Fair Value Gaps (FVG) in Python». Содержит **рабочий код FVG-детектора** — прямой объект для сверки с нашим каноном [[что такое fvg]] и `smc-lib/fvg`.

## Определение FVG (3-свечной паттерн)

- **Candle 1 (i-2):** референс — high и low.
- **Candle 2 (i-1):** momentum-свеча — сильное тело (displacement).
- **Candle 3 (i):** референс — оставляет gap относительно Candle 1.
- **Bullish FVG:** `third_low > first_high` (low 3-й свечи выше high 1-й). Зона = [first_high, third_low].
- **Bearish FVG:** `third_high < first_low`. Зона = [first_low, third_high].

## Их код (ключевая логика)

```python
def detect_fvg(data, lookback_period=10, body_multiplier=1.5):
    fvg_list = [None, None]
    for i in range(2, len(data)):
        first_high  = data['High'].iloc[i-2]
        first_low   = data['Low'].iloc[i-2]
        middle_open = data['Open'].iloc[i-1]
        middle_close= data['Close'].iloc[i-1]
        third_low   = data['Low'].iloc[i]
        third_high  = data['High'].iloc[i]
        # средний модуль тела за lookback
        prev_bodies = (data['Close'].iloc[max(0,i-1-lookback_period):i-1] -
                       data['Open'].iloc[max(0,i-1-lookback_period):i-1]).abs()
        avg_body_size = prev_bodies.mean() or 0.001
        middle_body = abs(middle_close - middle_open)
        if third_low > first_high and middle_body > avg_body_size * body_multiplier:
            fvg_list.append(('bullish', first_high, third_low, i))
        elif third_high < first_low and middle_body > avg_body_size * body_multiplier:
            fvg_list.append(('bearish', first_low, third_high, i))
        else:
            fvg_list.append(None)
    return fvg_list
```

## ⚡ Сверка с нашим FVG (важные отличия)

1. **Фильтр силы momentum-свечи:** у них middle_body > `avg_body(lookback=10) × 1.5`. То есть FVG засчитывается только если средняя свеча крупнее средней за 10 баров в 1.5×. 🔗 У нас в `smc-lib/fvg` — нужно проверить, есть ли такой фильтр размера тела. Если нет — это **дешёвое улучшение качества FVG** (отсекает слабые гэпы). Кандидат на эксперимент.
2. **Gap по wicks (High/Low), не по телам.** Их условие `third_low > first_high` — по теням. Наш канон [[что такое fvg]] это подтверждает (FVG между тенями 1-й и 3-й). ОК, совпадает.
3. **Замечание из комментариев к статье (важное):** существование price imbalance у FVG_Top vs FVG_Bottom (тела свечей не перекрываются) сильно влияет на определение FVG. 🔗 Это РОВНО наш `i_fvg` (inverse/imbalance FVG) и различие efficiency/inefficiency. Подтверждает, что наш более тонкий канон ([[три класса зон ликвидность эффективность неэффективность]]) правильнее наивного FVG.

## Честный вывод автора (совпадает с нашими законами)

> «no signal is perfect. While price often revisits these gap zones, it can either bounce from them or break straight through. There's no reliable way to predict direction solely from the FVG itself, which is why relying only on these levels isn't a practical trading approach.»

🔗 = НАШ эмпирический закон: FVG сам по себе не даёт edge, нужен каскад/confluence ([[traid-bot-empirical-laws]], [[expert-opinion-multi-tf-cascade-methodology]]). И «только backtest покажет» = наш [[7-criteria-of-good-strategy]]. Автор не приводит статистики → нарратив, гнать через backtest.

## Action items для проекта

- ☐ Сверить `smc-lib/fvg` с этим определением — есть ли у нас **body_multiplier фильтр** (middle_body > avg×1.5)? Если нет — проверить как фильтр качества.
- Их детектор примитивнее нашего (нет HTF, нет mitigation, нет i_fvg) — мы дальше продвинуты. Ценность только в body-size фильтре.

Каталог: [[ICT-source-индекс]]. Канон: [[что такое fvg]], [[универсальные определения OB и FVG]].
