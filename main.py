"""Точка входа: startup -> MultiStrategyScanner (4 стратегии) + Telegram polling.

Live-режим: 4 стратегии 1.1.x параллельно через MultiStrategyScanner.
  S111  — entry=0.80, sl=0.35 sym, RR=2.2
  S112  — entry=0.70, sl=0.35 sym, RR=2.2
  S113  — entry=0.70, sl=0.35 sym, RR=2.2, macro_mode=untouched
  S114  — entry=0.70, sl=0.35/0.65 asym, RR=2.0

Без confluence — общий формат сигнала для всех 4.
"""
from __future__ import annotations

import asyncio

from config import TELEGRAM_BOT_TOKEN, load_admins, SYMBOLS
from state import load_users, log_event
from multi_strategy_scanner import MultiStrategyScanner, STRATEGIES
from telegram_bot import polling_loop, send_message


async def main() -> None:
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "replace_me_with_real_bot_token":
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан в .env")

    log_event("INFO", f"bot starting ({len(STRATEGIES)} strategies via MultiStrategyScanner)")

    # Разовая миграция: today-store отменён.
    try:
        from pathlib import Path
        p = Path("state/signals_today.json")
        if p.exists():
            p.unlink()
            log_event("INFO", "signals_today.json removed (today-store retired)")
    except Exception:
        pass

    scanner = MultiStrategyScanner()
    await scanner.startup()

    users_count = len(load_users())
    admins = load_admins()

    strategy_names = ", ".join(s.name for s in STRATEGIES)
    startup_msg = (
        "🤖 <b>Бот запущен</b>\n"
        f"Стратегии ({len(STRATEGIES)}): <b>{strategy_names}</b>\n"
        f"Символы: {', '.join(SYMBOLS)}\n"
        f"Подписчиков: <b>{users_count}</b>"
    )
    for admin_id in admins:
        try:
            send_message(startup_msg, admin_id)
        except Exception as e:
            log_event("WARN", f"admin notify failed ({admin_id}): {e!r}")

    log_event("INFO", f"MultiStrategyScanner ready, users={users_count}, admins={len(admins)}")

    await asyncio.gather(
        scanner.ws_loop(),    # Binance WS — все 4 стратегии на каждом 1h close
        polling_loop(),       # Telegram bot polling
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log_event("INFO", "bot stopped by KeyboardInterrupt")
