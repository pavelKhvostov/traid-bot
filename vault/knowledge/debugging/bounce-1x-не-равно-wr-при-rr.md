---
tags: [debugging, pitfall, metrics, smc]
date: 2026-05-08
session: [[2026-05-08-elements-study-grid-search-production-setup]]
---

# Bounce_1x ≠ realistic WR при RR-стратегии

## Что было

В этапе 1 (research/elements_study) я считал метрику `bounce_1x` для
каждой зоны (OB / FVG / RDRB) и фрактала: «доходила ли цена до
`entry + 1×zone_size` хоть когда-то в окне 50 баров».

Результаты были впечатляющими:
- OB-1h: 92% bounce_1x
- FVG-1h: 96%
- **RDRB-1h: 99%**

И я сделал вывод: «бери small RDRB / small FVG / wick-touch — там WR
почти 100%».

## Симптом

При **realistic backtest** с фьючерсным SL и фиксированным RR (1.0-2.0)
ВСЕ топ-сегменты дали **WR 33-36%** — то есть на грани break-even при RR=2.

Edge испарился. Метафора: «обещали 99% побед, вышло 33%».

## Причина

`bounce_1x` и `WR при RR=N` — это **разные** метрики, измеряющие разные события.

### bounce_1x (как я считал)

«Доходила ли цена до 1× zone_size в нашу сторону **хоть в каком-то моменте**
окна 50 баров после первого касания зоны».

Не учитывает: **порядок** между движением вверх и вниз. Если цена сначала
выбила SL, потом вернулась и достигла +1×zone — `bounce_1x = True`.

### WR при RR=N

«Дойдёт ли цена до `entry + N×risk` **до того как** выбьет SL».

Учитывает порядок строго.

### Численная иллюстрация

На RDRB-1h:
- zone_size median = 0.07% от цены
- ATR(14) на 1h ≈ 0.6% от цены
- При расширенном SL (за trigger + 0.5·ATR) → risk ≈ 0.5·ATR ≈ 10×zone_size
- Чтобы достичь TP при RR=2 → цене нужно пройти 1·ATR = **20×zone_size**
- 1× zone_size = 0.07% — крохотное движение
- 20× zone_size = 1.4% — уже значительное

Цена `bounce_1x` = 99% (легко проскочить 0.07% wick'ом),
но **не успевает** дойти до 20× до того как откатывает на SL.

## Правило избегания

1. **Любую bounce_X% метрику в zone-units не использовать как прокси WR.**
   В отчётах писать ATR-units или absolute-pct moves.

2. **Перед делом implementation, сделать realistic backtest с RR-формулой**
   на маленьком sample. Если WR падает с 99% до 33% — формула SL/TP
   не соответствует bounce-метрике.

3. **Для оценки edge mean-reversion стратегии:**
   - Считать `realistic_wr_at_rr` (с симуляцией SL/TP first-hit) на 1m
   - Считать `R/trade` ≈ `WR × RR − (1−WR)`, не зависящий от zone_size
   - Сравнивать с benchmark = WR при random entry / тот же RR (≈ 1/(1+RR) для случайного)

4. **Bounce-метрики полезны** для:
   - Ranking зон по «упорству» рынка
   - Понимания распределения движения (не WR strategy)
   - Поиска «mean potential» при unbounded TP

## Источник

[[2026-05-08-elements-study-grid-search-production-setup]] — этапы 1-4
(metrics) vs этапы 6-8 (realistic backtest) дали разрыв 99% vs 33%.

## Связи

- [[strategy-ob-4h-fvg-1h-pro-trend]]
- [[универсальные определения OB и FVG]]
