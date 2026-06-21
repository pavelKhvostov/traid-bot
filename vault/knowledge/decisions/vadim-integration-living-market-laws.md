---
tags: [decision, integration, vadim, living-market, ta-laws, confluence, convergence]
date: 2026-06-21
---

# Интеграция ветки Vadim: «живой рынок» ↔ наши TA-законы

2026-06-21. Внедрены наработки Vadim из `origin/Vadim` (merge-base `1fba632`, 5 коммитов) в наш проект
БЕЗ потери контекста сессии. Метод: не checkout/merge ветки (риск нашим несохранённым ta_laws/cascade/
i_rdrb/level_engine), а **выборочный перенос его файлов** через `git checkout origin/Vadim -- <path>` —
чисто аддитивно. Перенесено: **87 vault-файлов** (Обсидиан) + **651 smc-lib** (канон+код). Вне vault/smc-lib
он ничего не менял. Orphan: `smc-lib/zone_of_interest.md` (он заменил каноном, у нас остался — безвреден).

## Что внедрено

**Законы рынка (принципы «живой-рынок»):** [[FRESH_LOOK_PRINCIPLE]], [[REALISTIC_TARGET_PRINCIPLE]], [[DIRECTIONS]].
**ML-наработки:** [[force-model-v3-architecture]] (сила зон→reversal force, 5 LR, 344 коэф.),
[[2026-06-19-живой-рынок-B8-series-confluence-principles]] (B8 TWB-MEM физика цены, 24h HIGH MAE 0.74% + confluence-фичи),
[[12h-fractal-prediction-final-strategy]] (sweep∩maxV → 82% HH/73% LL/6y).
**Канон:** [[2026-06-14-canon-refactor-session]] (13 элементов + breaker/mitigation/choch_bos), zone-taxonomy
[[zone-class-liquidity-inefficiency-block]] (liquidity/inefficiency/block), VIC maxV=абсолютный, [[feedback-untraded-area-is-magnet]].
**~55 memory-заметок** в `vault/knowledge/claude-memory/` + его сессии 05-30…06-19. Код в `smc-lib/`.

## ✦ КОНВЕРГЕНЦИИ (его законы = наши, доказано независимо двумя путями)

1. **Realistic Target ≡ наш закон дальности.** Его [[REALISTIC_TARGET_PRINCIPLE]]: предсказывать «первый
   значимый пик с откатом» (достижимое трейдером), а не физический max — «дельта недоступности». НАШ
   [[ta-pattern-taxonomy-direction-vs-extent]]: учебный measured-move 1× завышен, реальная медиана ~0.49×
   высоты. **Два независимых маршрута к одному закону** → высокая уверенность: цели надо резать к
   достижимым. Его кейс B8.1 (HIGH $65.7k vs физ. $67k = «realistic TP») — буквально наш «крупн 0.24×».

2. **Fresh Look ≡ наш «направление=контекст + инвалидация».** Его [[FRESH_LOOK_PRINCIPLE]]: план=гипотеза,
   ✗-метка при расхождении в ПЕРВОЙ зоне → полный сброс/свежий взгляд. НАШ результат: голая форма=монетка,
   **edge=форма+контекст**, ломается при сломе контекста; pullback в тренд работает, против — fade.
   Его «цепочка строится от первой проверенной точки» = наша иерархия mtf-контекста.

3. **Force-model (сила зон) ≡ наш confluence-lift.** Его [[force-model-v3-architecture]]: сила мульти-ТФ зон →
   reversal force на свече. НАШ `confluence_lift.py`/`futures_tradeability.py`: **аналитика (мульти-ТФ контекст)
   = несущая часть edge** — та же форма без контекста −0.071R, с контекстом +0.164R. Его force-model — это
   наш «слой аналитики» в обучаемом виде; его 5 принципов Phase 4 (strength/force-aggregation/liquidity-charge/
   HTF-magnets/3D-dominance) = кандидаты-фичи для нашего level_engine [[level-strength-engine-описательный-предиктив-kill]].

4. **Его lookahead-уроки ≡ наша shuffle/null-дисциплина.** [[ob-vc-hma-features-lookahead-fix]]: canon v3.3
   (AUC 0.79) оказался lookahead → реал 0.54. [[ml-snapshot-not-trajectory]]: tabular ML видит snapshot, не
   траекторию. Сходится с нашим: чистый OOS AUC ~0.54-0.70 только под shuffle; AUC>0.65 на directional crypto =
   подозревать. Добавлено в [[known-pitfalls]].

## ⚖️ КОМПЛЕМЕНТАРНОСТЬ / расхождения (что взять осторожно)

- Vadim сильнее в **предиктивном ML** (B8 физика цены, force-model, pred12h) и **каноне SMC-элементов**;
  мы — в **фальсификации форм** (фольклор vs закон) и **нетто-торговоспособности** (косты/null/cross-asset).
- Его pred12h «82% HH» = precision по Williams-пивотам, НЕ PnL — как наш «barrier-R ≠ нетто-edge». Перед
  деньгами прогнать через наш harness (entry/stop/TP+косты+random-null).
- Его B8 «физика цены» (реконструкция уровней) = ОПИСАТЕЛЬНЫЙ слой — ближе к нашему «descriptive wins».
  Directional AUC 0.66 у него = наша стена (направление дня≈монетка). Согласованно.

## ✅ ТЕХНИЧЕСКАЯ ИНТЕГРАЦИЯ — выполнено + первый результат (2026-06-21)

**Способ переиспользования (найден, валиден):** `research/smc_adapter.py` мостит наш pandas ↔ его Candle/
zones-движок. Его архитектура 3 слоя: `candle.py` → `elements/` (16 канон-детекторов, тесты 150/150,
candle-level pure) → `поиск-элементов/event_detector_v11` (сканер+митигация) → `prediction-algo/zones.py`
(**уже pandas**: `precompute_zone_events`+`snapshot_from_events`, КАУЗАЛЬНО) → `force_model_v3`. Bar-выравнивание
СОВПАДАЕТ (он `bucket=ts−ts%tf_ms` = наш origin=epoch). Gotcha: ключи `_SCANNERS` регистрозависимы (OB/FVG/RDRB
заглавные). force_model target = 12h-Williams ≠ наш → берём его ФИЧИ/зоны, не цель.

**Эксперимент `zone_confluence_test.py` (362 arc-сетапа, его zone-движок как конфлюэнс-слой):**
- Его **сила зон НЕСЁТ робастный сигнал, но с ОБРАТНЫМ знаком** = подтверждение его же закона «untraded=магнит»:
  ZONE-high (плотность зон по направлению fade) → нетто **−0.169R** (цена идёт В магнит, fade провал);
  ZONE-low (путь чист) → **+0.180R** (год 6/7). Спред +0.35.
- **ЕГО СЛОЙ ДАЁТ ЛИФТ СВЕРХ НАШЕГО MTF:** MTF-aligned ВСЕ +0.182R (PF1.29) → **MTF-aligned ∩ ZONE-low
  (чистый путь) +0.309R (PF1.55, год 6/7)**. Два слоя комплементарны: наш mtf=направление, его zone-density=
  магнит/чистота пути. ZONE-high тащит вниз даже при mtf-aligned (+0.038R).
- Вывод: **его работа реально усиливает наш edge** (+0.182→+0.309R). Оговорки: лучшая ячейка n=79, sym 2/3
  (ETH слабее), это правило-скор (не его LR), нужен «clear-path» фактор (магнит-против) + полный harness.

## 🟢 ФАЗА 1 — ЕДИНОЕ ЯДРО `research/analytics_engine.py` (готово, тесты 13/13)

«Один движок — два потребителя»: `precompute(df_1m)` → `analyze_at(pc, ts)` → `AnalyticsState`
(контекст mtf/режим/ATR/позиция + зона-ландшафт Вадима каузально + его descriptive-законы + сетап-вердикт).
Переиспользуется и ботом, и harness → каждый живой вывод бэктест-валидируем, без дрейфа.
Законы внутри: **magnet_against** (= zone_confluence, зоны=магниты, корректный знак), **realistic_tp**
(ближайший магнит по направлению ≤ наш extent MAX_EXT_ATR), taxonomy-роли, mitigation (из его движка),
**fresh-look** (уровень инвалидации). Вердикт по валидир. правилу: mtf-aligned ∩ clear-path → ✅ (+0.309R-класс);
магнит против → ждать; против контекста → ⛔. Smoke BTC: контекст+25 зон+сетап+вердикт, каузально.
Кавеат: realistic_tp=ближайшая зона может дать низкий RR → нужен RR-фильтр (Фаза 2). Predictive (force-model)
ещё не подключён (за гейтом). `analyze_live(symbol)` = удобный вход (CSV/fetch).

## ▶ Практические следующие шаги (синтез двух модулей)

1. Подключить его **force-model/zone-strength** как обучаемый «слой аналитики-конфлюэнс» к нашим arc/fade/
   taxonomy-сетапам (мы доказали, что контекст-конфлюэнс переворачивает −0.071R→+0.164R).
2. Сверить его **realistic-target algo** (first significant peak, K%/RR) с нашим extent-законом (0.49×) —
   объединить в единый TP-калькулятор по категориям.
3. Внести **fresh-look инвалидацию** (✗-метка при сломе первой зоны) в live-разбор (`send_full_btc_report.py`).
4. Канон smc-lib (13 элементов) = единый источник детекторов для cascade/level_engine.

## Связи
[[ta-pattern-taxonomy-direction-vs-extent]] · [[ta-curved-patterns-arcs-and-data-discovered-shapes]] ·
[[ta-fade-law-deep-factors]] · [[level-strength-engine-описательный-предиктив-kill]] · [[FRESH_LOOK_PRINCIPLE]] ·
[[REALISTIC_TARGET_PRINCIPLE]] · [[force-model-v3-architecture]]
