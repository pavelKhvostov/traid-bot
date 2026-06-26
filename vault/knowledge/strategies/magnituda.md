---
tags: [strategy, magnituda, reversal, catboost, live, admin-only]
date: 2026-06-25
---

# Стратегия «Магнитуда» — live-спека и интеграция

ML reversal-стратегия. Решение/обоснование: [[magnituda-reversal-strategy]]. Память: [[project_reversal_catboost_3pct]].
Воспроизведение один-в-один: `research/reversal_cb/MAGNITUDA_REPRODUCE.md` (git ветка `andrey`, коммит 2fecfd1).

## Спека
- **① LONG** на закрытых **8h** барах, RR-бакет **[2.5,4)**; **② SHORT** на **12h**, RR-бакет **[1.5,4)**.
- Селектор = reversal-likelihood (CatBoost, top-30% уверенности, per-asset порог).
- Label/сделка: вход=close, **стоп=свой low/high, TP=±3%**. RR=3%/риск (натуральный барьер — НЕ ATR, иначе сплющивается RR).
- Косты: maker-исполнение (лимит-вход ~0.10% + TP лимиткой, стоп market) — даёт Sharpe 1.28→1.68.
- Cross-asset BTC/ETH/SOL. Роль: **~15% некорр. диверсификатор** к корзине (corr≈0), не standalone.

## Артефакты (live)
- Модели: `models/magnitude_long_8h.cbm`, `models/magnitude_short_12h.cbm`, `models/magnitude_config.json` (FEATS 22, THR 0.03, CAP 120, flag_thr per-dir).
- Детектор: `strategies/magnitude.py` — `detect_magnitude_signals(df, direction)`, фичи вендорены из канона (тест `tests/test_magnitude.py` сверяет дрейф, 7/7 зелёных).
- Обучение/персист: `research/reversal_cb/train_persist.py`.

## Live-интеграция — ADMIN-ONLY, за флагом `MAGNITUDE_ENABLED` (по умолч. OFF)
Два пути (один флаг). **Для текущего сетапа активен путь аналитики** (она авто-стартует ежечасно):
1. **Почасовая аналитика (основной):** `magnitude_hourly.py` (свежие klines Binance → детект → ADMIN-only через `DASHBOARD_BOT_TOKEN`,
   мимо `recipients()` где Павел; дедуп `state/magnitude_hourly_sent.json`; первый запуск = prefill silent). Вызывается из
   `research/daily_engine/etap_227_live_dashboard_bot.py` `main()` за флагом.
2. **Сигнальный бот (если крутится `main.py`):** `magnitude_scanner.py` (WS 8h/12h), за тем же флагом. ⚠️ НЕ включать оба одновременно (дубли — разные дедуп-хранилища).

**Активация:** в `.env` `MAGNITUDE_ENABLED=true` (DASHBOARD_BOT_TOKEN у аналитики уже есть). Выключить — убрать.
**Безопасность:** ADMIN-only (admins.json=[901107007]), НЕ подписчикам, НЕ прод-токен, OFF по умолчанию, сбой обёрнут в try/except.

## Кавеаты для эксплуатации
- Скромный/режим-зависимый edge (низкая вола/ренж; в высоковола-быке флэтует — это норма, его подменяют каскады).
- Профит исторически концентрирован 2025-26; готовность к флэт-периоду. Малый сайз.
- Модель затухает → нужен периодич. walk-forward переобуч (`train_persist.py`).
- `catboost` в окружении бота обязателен; `models/` не в .gitignore (нужны для деплоя).
