---
tags: [home, tradingview, mcp, инфраструктура, читать-в-начале-сессии]
date: 2026-06-11
priority: high
---

# 🖥️ TradingView MCP — как запускать (читать в начале сессии если нужен график)

Подключён MCP-сервер `tradingview-mcp` (tradesdontlie) — Claude читает/управляет ЖИВЫМ графиком TradingView Desktop через CDP (порт 9222). 78 инструментов: читать индикаторы, OHLCV, рисовать зоны, скриншоты, Pine.

**Главное применение:** сверять Python-индикаторы (smc-lib) с TradingView (закрывает грабли про Pine-расхождения), размечать зоны на графике, читать значения индикаторов.

## Установка (уже сделана, 2026-06-11)

- Репо: `~/tradingview-mcp` (npm install выполнен, 94 пакета).
- Подключён глобально: `claude mcp add tradingview --scope user -- node ~/tradingview-mcp/src/server.js` → в `~/.claude.json`.
- TradingView Desktop 3.1.0 установлен (`/Applications/TradingView.app`).

## ⚠️ ЗАПУСК TradingView с debug-портом (КРИТИЧНО)

MCP не работает без TradingView, запущенного с CDP на порту 9222. Запускать ТАК:

```bash
pkill -9 -f "TradingView"; sleep 2
env -u ELECTRON_RUN_AS_NODE nohup /Applications/TradingView.app/Contents/MacOS/TradingView --remote-debugging-port=9222 > /tmp/tv-cdp.log 2>&1 &
disown
# проверка (должен вернуть Browser/Chrome):
curl -s http://localhost:9222/json/version
```

**ПОЧЕМУ `env -u ELECTRON_RUN_AS_NODE`:** окружение Claude выставляет `ELECTRON_RUN_AS_NODE=1`, из-за чего бинарник TradingView стартует как Node.js (не Electron) и отвергает флаг `--remote-debugging-port` с `bad option`. Убрав переменную — Electron стартует нормально, CDP поднимается за ~2 сек.
**ПОЧЕМУ `pkill -9` (не -f без -9):** SIGTERM приложение перехватывает; single-instance lock передаёт активацию старому инстансу без флага. Нужен SIGKILL.
**Штатный скрипт `~/tradingview-mcp/scripts/launch_tv_debug_mac.sh` НЕ работает** из окружения Claude (наследует ELECTRON_RUN_AS_NODE + использует pkill -f). Запускать командой выше.

## Проверка связи в начале сессии

MCP-инструменты подгружаются при старте сессии. Проверить: `tv_health_check` → должен вернуть `cdp_connected: true` + текущий символ.

## Известные баги MCP (обход)

- `draw_clear` / `draw_list` / `draw_remove_one` → **сломаны** (`getChartApi is not defined`).
  Обход для очистки графика: `ui_evaluate` →
  `window.TradingViewApi.activeChart().removeAllShapes()`.
- Твои индикаторы (Hull/ViC/RSI/Money Hands) рисуются через line.new/защищённые методы → `data_get_study_values` их НЕ отдаёт (только WICK.ED). Зоны считать Python-кодом проекта (smc-lib), а не читать с графика.

## Твой график (layout XnWnFhZo)

OKX/BINANCE:BTCUSDT, 12h, индикаторы: Trend Line ASVK (Hull), Custom RSI ASVK, Money Hands ASVK, Volume in Candle (ViC), EVoT, WICK.ED, All Chart Patterns, VWAPs, Mean Deviation Index. Для анализа по методологии проекта → переключать на **BINANCE** (весь проект на Binance Spot, OKX даёт другие фитили).

## Разметка зон

Скрипт `research/elements_study/tv_mark_zones.py` — считает зоны (фракталы/FVG/OB/sweep) по канону проекта на 12h-данных, выводит вокруг цены. Рисовать на график через `draw_shape` (rectangle для зон, horizontal_line для уровней). FVG считать по канону c1-c3 (см. known-pitfalls).
