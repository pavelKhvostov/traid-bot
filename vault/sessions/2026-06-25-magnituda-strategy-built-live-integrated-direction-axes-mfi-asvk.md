---
tags: [session, magnituda, reversal, catboost, direction-axes, microstructure, mfi, asvk, live-integration]
date: 2026-06-25
---

# Сессия 2026-06-25 — Магнитуда (reversal CatBoost) построена + заведена в live + оси направления + MFI×ASVK исчерпан

Длинная сессия. TV-разметка → оси направления → самокритика контролей → стратегия «Магнитуда» (создана, названа юзером,
доведена, выгружена, заведена в live ADMIN-only) → исследование связки MFI×ASVK (исчерпано).

## 1. TV-разметка (начало)
Нарисовал на BTC примеры HTF-breaker и текущий анализ (зоны 59–67k, сценарии). Правило [[feedback_analysis_draw_on_tv]].
Баг direction в примере breaker: edge = **fade** флипа (signed-return), `d==1→LONG`. TF flips (1H/8h/12h) — глюк долгоживущего TV-MCP.

## 2. Оси направления ортогональные цене — ВСЕ coin/неторгуемо
Юзер: «протестируй оси для улучшения НАПРАВЛЕНИЯ». `research/direction_axes/`. Стены: own-AR baseline + block-OOS + null + год + cross.
- **Cross-asset lead-lag** (ETH/SOL/USDT.D/TOTAL/BTC1!): дневка cross над own-AR **−0.028**, null p=0.82. Интрадей ~52% = собств. AR BTC, не cross. KILL.
- **Funding** (дотянут с Binance fapi): над own-AR −0.011, null p=0.71. KILL.
- **Signed order flow** (delta/CVD): +0.005 null p=0.000 год-стаб, НО per-bar +0.007% ≪ косты → экономически мёртв.
- Data-blocked: OI(30д)/ликвидации/on-chain. Оси не ортогональны — они ФУНКЦИИ цены. [[project_direction_axes_tested]] (память).

## 3. Самокритика killer-контролей (юзер: «боты→инфа в OHLCV»)
Признал 2 дыры (false-negative): горизонт (тестил ≥1h) + бедность фич. Патч `micro_direction.py` (rich-OHLCV 5m/15m, purged WF, two-cost):
**НАЙДЕН реальный сигнал, скрытый ≥1h: 15m acc 0.534, топ-conviction 0.6145, null p=0.000, год-стаб.** Но flow над geometry +0.0003 (бот-«поток» bar-rule не помог); **gross 0.38bps ≪ даже maker 2bps** → conviction-фильтр: топ-1% переходит maker лишь +0.37bps, adverse-selection съедает. **Уточнение стены: направление предсказуемо в OHLCV до ~61% на топ-conviction, но edge ≤ транзакц-пола → слой ЛИКВИДНОСТИ, не сигнала.** [[direction-axes-and-microstructure-sub-cost]]

## 4. ⭐ Стратегия «МАГНИТУДА» — главный итог (юзер дал имя)
CatBoost reversal-детектор. Label юзера: от close +3% РАНЬШЕ пробоя своего low (long)/high (short). АСИММ → не монетка-по-построению.
`research/reversal_cb/`. Полная программа в [[magnituda-reversal-strategy]] (решение) + [[magnituda]] (стратегия) + [[project_reversal_catboost_3pct]] (память).
- **Навык классификации РЕАЛЕН** (precision lift 1.4-1.9×, null=base, cross-asset) — но net-R≈0 (вола-RR-конфаунд: уверенность=вола→+3% чаще, но стоп далёкий→RR≈1).
- EV-rescue + ATR-стоп **провалились** (ATR сплющивает натуральный RR=бета — методологич. ошибка, **юзер поймал**: «отсеянные несли RR»).
- **На натуральном барьере + средне-RR отбор → 2 РОБАСТНЫЕ ячейки** (perm-null+год+OOS+cross): ① 8h LONG RR2.5-4 (net+0.25, OOS+0.24, cross3/3), ② 12h SHORT RR1.5-4 (net+0.09, BTC p0.002/SOL p0.004).
- **Помесячно** комбо +2.43R/мес, Sharpe 1.28, НО профит **концентрирован 2025-26** (2023-24 флэт).
- **Регим:** edge в низкой воле/ренже; long платит в быке, short в медведе → **тренд-хеджированы**.
- **corr≈0 с боевой корзиной → ДИВЕРСИФИКАТОР** (Sharpe 3.82→4.30, DD↓). Это главная ценность, не standalone.
- Улучшения: вола-гейт ❌ (все режимы +EV), фаза-гейт ❌ (own-equity не предсказывает, гейт ломает диверсификацию), **maker-исполнение ✅** (Sharpe 1.28→1.68; поймал lookahead-баг fill-vs-bracket → [[execution-sim-lookahead-fill-vs-bracket]]).

## 5. Live-интеграция Магнитуды (ADMIN-only, за флагом)
- Модели `models/magnitude_{long_8h,short_12h}.cbm` + config; детектор `strategies/magnitude.py` (фичи вендорены, сверка с каноном); **7 тестов**.
- `magnitude_scanner.py` (WS 8h/12h) + проводка в `main.py` за `MAGNITUDE_ENABLED` (OFF).
- **Юзер: «аналитика каждый час авто-стартует, добавь туда»** → `magnitude_hourly.py` + 1 вызов в `etap_227_live_dashboard_bot.py main()` за тем же флагом. ADMIN-only через `DASHBOARD_BOT_TOKEN` (мимо recipients() где Павел), prefill silent.
- Выгружено на git `andrey` (коммит 2fecfd1) + `MAGNITUDA_REPRODUCE.md` (для Claude Вадима).

## 6. MFI×ASVK связка — ИСЧЕРПАНА
Взял above/below RSI-ASVK + MFI. Reversal-детектор: Cohen's d ~0.1 (**в 10× слабее Магнитуды**), **сигнал ПЕРЕВЁРНУТ** — OB(перекупл)→long работает (моментум, +3% продолжение), OS(перепродан)→long = ловля ножа (net −0.26). TF-sweep индикатора 1h-12h × сложные связки (spring/дивергенция/squeeze/deep-turn) — **ВСЕ провалились**, выжил только тривиальный momentum-OB-12h (+0.08, cross3/3), который Магнитуда уже захватывает. Осциллятор не таймит развороты — стена подтверждена.

## Сквозной урок сессии
Стена «направление/развороты в точке = монетка» уточнена и закалена на экзогенных данных + микроструктуре: предсказуемое есть, но ≤ cost-floor (слой ликвидности). Магнитуда = первый монетизируемый reversal-кусок, но скромный/режим-зависимый → роль **~15% некорр. диверсификатор**, не машина. Юзер дважды поймал мои ошибки (RR-сплющивание ATR; и горизонт в контролях) — оба раза признал и исправил.
