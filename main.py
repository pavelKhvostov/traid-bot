"""Точка входа: startup -> ws_loop + polling_loop.

Live-режим: 6 стратегий 1.1.x параллельно через MultiStrategyScanner.
  S111_SWEPT, S112, S113_V1, S113_V2, S114_V1, S114_V2

См. multi_strategy_scanner.py для конфига и логики.
Confluence/TV-refresh убраны 2026-05-06 (кружки декоративные, edge нет).
"""
from __future__ import annotations

import asyncio

from config import TELEGRAM_BOT_TOKEN, load_admins
from multi_strategy_scanner import STRATEGIES, MultiStrategyScanner
from state import load_users, log_event
from telegram_bot import polling_loop, send_message


async def main() -> None:
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "replace_me_with_real_bot_token":
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан в .env")

    log_event("INFO", "bot starting (6 strategies via MultiStrategyScanner)")

    # Разовая миграция: today-store отменён, файл удаляем если есть.
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

    from config import SYMBOLS
    strategy_names = ", ".join(s.name for s in STRATEGIES)
    startup_msg = (
        "🤖 <b>Бот запущен</b>\n"
        f"Стратегии: <b>{len(STRATEGIES)}</b> ({strategy_names})\n"
        f"Символы: {', '.join(SYMBOLS)}\n"
        f"Подписчиков: <b>{users_count}</b>"
    )
    for admin_id in admins:
        try:
            send_message(startup_msg, admin_id)
        except Exception as e:
            log_event("WARN", f"admin notify failed ({admin_id}): {e!r}")

    log_event("INFO", f"multi_scanner ready, users={users_count}, "
                      f"admins={len(admins)}, strategies={len(STRATEGIES)}")

    await asyncio.gather(
        scanner.ws_loop(),  # Binance WS — autoupdate BTC свечей + 1h trigger
        polling_loop(),     # Telegram bot polling
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log_event("INFO", "bot stopped by KeyboardInterrupt")
