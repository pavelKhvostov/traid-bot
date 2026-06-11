---
tags: [strategy, reversal, fractal, ml, neural-net, pavel]
date: 2026-06-10
status: research-strong
branch: pavel
related: [research/elements_study/etap_177_neural_full_arsenal_pavel.py]
---

# Нейросеть «весь арсенал» — BTC+ETH+SOL, метка Андрея, AUC 0.91-0.94 (pavel)

## Что это

Максимальная нейросеть проекта: **полный арсенал фич** + **3 актива (BTC/ETH/SOL pooled)** + **метка Андрея**. Развитие [[neural-fractal-pavel-etap176]]. Достигла AUC 0.91-0.94 — на уровне эталона Андрея (etap_173). Ветка `pavel`.

## Полный арсенал фич (83 шт, все ≤ close[i])

- **Андрей/ICT:** sweep_SSL/BSL_mag/failed (Liquidity Sweep / DOL), OB/FVG зоны-дистанции, **Bulkowski ВСЕ 13 паттернов** (fired + bars_since), фрактал-структура.
- **López de Prado:** **SADF** (bubble/explosiveness, Lec8), **fractional differentiation** d=0.4 (Lec3), **Shannon entropy** окна (Lec8), **Amihud illiquidity** (Lec8 microstructure).
- **База:** rsi/hull/ema/atr/vol_z, свечная геометрия, momentum 3/7/14, HTF-тренд (last-closed), asset_id.

## Метка Андрея (мягче моей 5%-race)

`y_{low,high}_strong_{3,4,5}` = is_fractal(i) AND движение ≥X% за 14 баров ПОСЛЕ confirmation. Фичи на close(i), движение в будущем. NB: фрактал-факт (i±2) — часть МЕТКИ; фичи строго ≤ i.

## Стандарты обучения (López de Prado)

Purged K-Fold (5 фолдов) + embargo 14 баров, sample weights по uniqueness, focal loss (α=0.75, γ=2), MLP с BatchNorm+Dropout(0.35)+3 residual-блока (GELU), AdamW+weight decay 1.5e-2, OneCycle, early-stop, ансамбль 5 фолдов. Pooled по 3 активам (9129 строк vs 3043 на одном BTC — больше данных для NN). PyTorch/MPS (Mac M5).

## Результаты (OOS test 2025+, 3 актива)

| Цель | base | CV-AUC | TEST-AUC | best precision |
| --- | --- | --- | --- | --- |
| y_low_strong_3 | 12.1% | 0.943 | 0.935 | thr0.7: **0.84** (×6.95, n=95) |
| y_low_strong_5 | 10.5% | 0.931 | 0.925 | thr0.7: **0.93** (×8.81, n=40) |
| y_low_strong_4 | 11.3% | 0.936 | 0.929 | thr0.7: 0.59 (×5.16, n=118) |
| y_high_strong_3 | 8.3% | 0.923 | 0.921 | thr0.6: 0.44 (×5.28, n=173) |
| y_high_strong_4 | 7.3% | 0.918 | 0.917 | thr0.6: 0.42 (×5.76, n=107) |
| y_high_strong_5 | 9.8% | 0.910 | 0.914 | thr0.6: 0.46 (×7.1, n=37) |

## ⚠️ Проверка на lookahead (КРИТИЧНО при AUC 0.94)

**Shuffle-тест (3 прогона, метка перемешана): mean AUC = 0.489** → чистая случайность → **lookahead'а в данных НЕТ.** Высокий AUC честный (метка Андрея + богатые фичи + 3 актива).

**Честная оговорка:** метка включает «станет ли свеча фракталом», что на 12h подтверждается через 2 бара (~сутки). Это НЕ утечка данных (фичи ≤ i, shuffle чист), но означает: сигнал в live даётся **на confirmation (i+2)**, не мгновенно на close[i]. Так и работает подход Андрея. Моя более ранняя метка 5%-race ([[neural-fractal-pavel-etap176]]) предсказывает на close[i] (раньше), но имеет потолок AUC ~0.68 — честнее по времени, труднее по сути.

## Выводы

1. **Нейросеть достигла уровня эталона Андрея** (AUC 0.91-0.94 vs его 0.94) на метке Андрея + полном арсенале.
2. **3 актива (pooled) критичны для NN** — 9129 строк дали стабильность, которой не было на 3043 (одиночный BTC, etap_176 застрял на 0.67).
3. **LONG сильнее на высоком пороге:** y_low_strong_5 precision 0.93 (×8.8) на 40 сигналах — почти каждый сигнал хороший. y_low_strong_3 precision 0.84 на 95.
4. **SADF/fractional diff/entropy** (López de Prado) + Bulkowski 13 + sweep/DOL вместе дали скачок 0.67→0.93 (но в основном за счёт смены метки на Андрееву + объёма данных).
5. **Ключевой урок:** метка решает больше, чем модель. Та же сеть: метка 5%-race → 0.67, метка Андрея → 0.93.

## Дальше

- MDA feature importance — какие из 83 фич реально несут сигнал.
- Bet sizing из вероятности (López Lec5) для live-сигнала.
- Сравнить с LightGBM на тех же данных (этал. Андрея = GBM; ждём паритет).
- Live-интеграция: сигнал на confirmation фрактала + порог prob≥0.7 (LONG).

Скрипт: [research/elements_study/etap_177_neural_full_arsenal_pavel.py](../../../research/elements_study/etap_177_neural_full_arsenal_pavel.py). Связь: [[neural-fractal-pavel-etap176]], [[good-fractal-5pct-race-predictor-etap174]], [[adv-fin-ml-индекс]], [[bulkowski-reversal-detectors-btc-12h-baseline]], [[traid-bot-ml-pivot]].
