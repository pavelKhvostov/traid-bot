---
tags: [strategy, cascade, grid, cross-asset, robust, overnight, anti-overfit]
date: 2026-06-19
status: исследовано — 12 робастных cross-asset конфигов, кандидаты на live-скелет-тест
related: [[i-rdrb-fvg-cross-asset-live-candidate]], [[rdrb-htf-1-1-1-high-conviction-subset]], [[strategy-1-1-7-ifvg-continuation]]
---

# Cascade grid 64 — cross-asset робастный шорт-лист (ночной прогон)

Ночной перебор пространства 1.1.x-скелета с анти-оверфит гейтами.
Движок: `research/cascade_grid/grid.py` (Stage 1) + `stage2_validate.py` (Stage 2).
Sanity пройден до запуска (каркас 1.1.1 воспроизводит edge).

## Метод

Скелет: L1 top(1d,12h) → L2 macro(4h,6h) → L3 htf(1h,2h)[+swept] → L4 entry(15/20m или same-tf FVG).
Оси: top{OB,FVG} × macro{OB,FVG,iFVG,RDRB} × htf{OB,RDRB} × entry{deep,sametf} × swept{0,1} = **64 конфига**.
Геометрия унифицирована (entry=mid entry-FVG, SL=внутрь top-зоны OB_SL_DEPTH, TP=RR·risk). **RR=2.0 фикс** для гейтинга (без cherry-pick).

**Stage 1 гейты (совместно — мульти-тестинг отсекается):** min_n + cross-asset(≥2/3) + two-sided BTC + year(≥5/N) + OOS(обе половины). → **15/64 прошли**.
**Stage 2 (адверсарно):** per-trade>0 на ВСЕХ 3 символах + permutation-null 2000 (random-time) <0.05 + RR-кривая 1.5-3.0. → **12/15 робастны**.

## ⚠️ Честный кавеат по числам
Абсолютные ΣR **завышены** (PER_TOP_CAP=3 + генерик-коллектор → счёт в 2-6× больше live-семейства).
**Доверяй: per-trade expectancy (PTT), cross-asset перенос, год-стабильность, null — НЕ абсолютному ΣR.**
+246R здесь ≠ live 1.1.2 +101R. Ранжируем по min-PTT (нормализовано по объёму).

## 12 робастных конфигов (по min per-trade по 3 символам)

| Конфиг | minPTT | null_p | BTC PTT | ETH PTT | SOL PTT | лет B/E/S |
|---|---|---|---|---|---|---|
| topOB-macRDRB-htfOB-**sametf** | +0.217 | 0.035 | +0.27 | +0.43 | +0.22 | 6/7/4 |
| **topFVG-macOB-htfOB-deep** | +0.203 | 0.000 | +0.23 | +0.28 | +0.20 | 5/7/5 |
| topOB-macOB-htfOB-**sametf** | +0.190 | 0.009 | +0.19 | +0.43 | +0.29 | 5/7/6 |
| topFVG-macOB-htfOB-deep-SW | +0.173 | 0.001 | +0.28 | +0.17 | +0.22 | 7/5/4 |
| topFVG-macFVG-htfOB-deep-SW | +0.169 | 0.002 | +0.18 | +0.20 | +0.17 | 6/6/6 |
| **topFVG-macFVG-htfRDRB-deep** | +0.148 | 0.003 | +0.15 | +0.19 | **+0.45** | 6/7/7 |
| **topOB-macOB-htfRDRB-deep** | +0.148 | 0.001 | +0.15 | +0.25 | +0.19 | 6/7/7 |
| topFVG-macFVG-htfOB-deep | +0.141 | 0.000 | +0.14 | +0.24 | +0.18 | 6/7/6 |
| topOB-macFVG-htfOB-deep (≈1.1.1) | +0.101 | 0.000 | +0.19 | +0.26 | +0.10 | 6/7/6 |
| topOB-macOB-htfOB-deep (≈1.1.2) | +0.088 | 0.000 | +0.15 | +0.22 | +0.09 | 7/6/7 |
| topOB-macRDRB-htfOB-deep | +0.063 | 0.015 | +0.11 | +0.22 | +0.06 | 6/6/5 |
| topFVG-maciFVG-htfOB-deep-SW | +0.033 | 0.025 | +0.22 | +0.18 | +0.03 | 6/5/3 |

Отсеялись на Stage 2: all-OB+SWEPT (SOL PTT −0.043, 1/7), macFVG-sametf (null 0.103), maciFVG-deep (null 0.050, SOL 2/7).

## Выводы (честно)

1. **OB+FVG-каскад робастен cross-asset как СЕМЕЙСТВО** — 12 разных конфигов пережили адверсарную валидацию. Edge в архитектуре, не в одной ячейке. Грид сам переоткрыл, что all-OB(=1.1.2) — самый объёмный/универсальный (BTC+ETH+SOL, 7/6/7 лет).
2. **Новое за пределами live 1.1.x — топ-кандидаты на live-скелет-тест:**
   - **topOB-macOB-htfRDRB-deep** (= 1.1.2 с RDRB на htf): объём + cross-asset + 6/7/7 лет + null 0.001 + RR-робаст. Лучший all-round новый.
   - **topFVG-macOB-htfOB-deep** (FVG-якорь + OB-каскад): лучший per-trade (+0.20) при объёме, ETH 7/7, null 0.
   - **topFVG-macFVG-htfRDRB-deep** (чистый FVG + htf-RDRB): SOL-монстр (PTT +0.45, 7/7), все+.
3. **htf-RDRB** в гриде РОБАСТЕН (vs [[rdrb-htf-1-1-1-high-conviction-subset]] где он был high-PTT/low-freq) — в более свободном join даёт и объём, и cross-asset. Нюанс: строгий 1.1.1-скелет режет RDRB-htf сильнее; нужен честный live-скелет-тест.
4. **macro-iFVG** — самый слабый выживший (marginal, null≈0.05, SOL шум). Согласуется с [[strategy-1-1-7-ifvg-continuation]] (iFVG слаб/BTC-leaning).
5. **SWEPT** в генерик-скелете чаще вредит (all-OB-SW ломает SOL); пара FVG-SW выжили, но слабее non-SW.

## Артефакты
- `research/cascade_grid/grid.py` (движок+Stage1), `stage2_validate.py` (Stage2)
- `grid_results.csv` (все 64), `grid_report.txt` (Stage1), `stage2_report.txt` (Stage2 подробно)

## Топ-3 через СТРОГИЙ live-скелет (2026-06-19, честные объёмы)

`research/cascade_grid/live_skeleton_top3.py` — настоящий канон (collect_valid_macro_obs/fvgs с
инвалидацией, find_signal_in_htf с fractal-инвалидацией, ~1 сигнал на (top,macro), dedup).
**Сверка движка:** ref-1.1.1 = BTC 271/+62R/ptt+0.229 (в точности мой C-baseline); ref-1.1.2 = BTC +88R 7/7.
Строгий скелет срезал грид-числа в 2-6× (подтверждает кавеат выше).

| Конфиг | BTC closed/R/ptt | ETH closed/R/ptt | SOL closed/R/ptt | +лет B/E/S |
|---|---|---|---|---|
| ref-1.1.1 (OB/FVG/OB) | 271 +62 +0.23 | 262 +62 +0.24 | 251 +7 +0.03 | 6/6/3 |
| ref-1.1.2 (OB/OB/OB) | 770 +88 +0.11 | 692 +64 +0.09 | 670 −4 −0.01 | 7/5/4 |
| **cand2 FVG/OB/OB (FVG-якорь)** | **126 +54 +0.43** | **115 +38 +0.33** | **135 +33 +0.24** | 5/4/5 |
| cand1 OB/OB/RDRB (htf-RDRB) | 291 +57 +0.20 | 266 +64 +0.24 | 266 +16 +0.06 | 4/5/4 |
| cand3 FVG/FVG/RDRB | 106 +11 +0.10 | 115 +38 +0.33 | 83 +34 +0.41 | 5/5/5 |

**Вердикт (честно):**
- ✅ **cand2 = FVG-якорь (FVG-1d/12h top + OB-macro → OB-htf) — НОВЫЙ live-кандидат.** Самый высокий
  per-trade на ВСЕХ 3 символах (+0.43/+0.33/+0.24 — вдвое выше OB-top семейства), cross-asset, 5/4/5 лет,
  две стороны, ~115-135 сделок (умеренная частота). FVG-как-якорь — отдельный источник сигнала
  (диверсификация от OB-top). Кандидат на детектор+тесты+WS (как A).
- cand1 htf-RDRB: подтверждает [[rdrb-htf-1-1-1-high-conviction-subset]] — выше per-trade (+0.20 vs +0.11 у 1.1.2),
  но реже и хуже год-стабильность BTC (4/7 vs 7/7). Не замена 1.1.2 → роль грейд-бустера.
- cand3: ETH/SOL-leaning (BTC слаб +0.10). Не универсал.
- iFVG-macro: в строгий скелет не прошёл (был слабейшим в гриде).

→ Следующий шаг: cand2 (FVG-якорь) — полноценный детектор `strategies/` + тесты + cross-asset бэктест (как A).

## Связи
- [[i-rdrb-fvg-cross-asset-live-candidate]] — A (отдельный паттерн, не в этом гриде)
- [[грейд-как-правило-размера-pnl-и-непереносимость-на-1-1-2]] — risk-рычаг сверху
