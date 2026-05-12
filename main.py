"""Точка входа: startup -> ws_loop + polling_loop.

Live-режим: ТОЛЬКО Strategy 1.1.1. Другие стратегии (Scanner с 7 классическими
+ VicScanner) отключены и сохранены в коде, но не запускаются.
"""
from __future__ import annotations

import asyncio

from config import TELEGRAM_BOT_TOKEN, load_admins
from state import load_users, log_event
from strategy_1_1_1_scanner import Strategy111Scanner
from telegram_bot import polling_loop, send_message


async def main() -> None:
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "replace_me_with_real_bot_token":
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан в .env")

    log_event("INFO", "bot starting (Strategy 1.1.1 only)")

    # Разовая миграция: today-store отменён, файл удаляем если есть.
    try:
        from pathlib import Path
        p = Path("state/signals_today.json")
        if p.exists():
            p.unlink()
            log_event("INFO", "signals_today.json removed (today-store retired)")
    except Exception:
        pass

    s111 = Strategy111Scanner()
    await s111.startup()

    users_count = len(load_users())
    admins = load_admins()

    from config import SYMBOLS
    startup_msg = (
        "🤖 <b>Бот запущен</b>\n"
        "Стратегия: <b>Strategy 1.1.1</b>\n"
        f"Символы: {', '.join(SYMBOLS)}\n"
        f"Подписчиков: <b>{users_count}</b>\n"
        "Сигналы: формат с confluence (BTC1!/TOTALES/USDT.D)."
    )
    for admin_id in admins:
        try:
            send_message(startup_msg, admin_id)
        except Exception as e:
            log_event("WARN", f"admin notify failed ({admin_id}): {e!r}")

    log_event("INFO", f"s111 ready, users={users_count}, admins={len(admins)}")

    await asyncio.gather(
        s111.ws_loop(),         # Binance WS — autoupdate BTC/ETH/SOL свечей
        s111.tv_refresh_loop(), # TV REST — autoupdate USDT.D/TOTALES/BTC1 каждые 30 мин
        polling_loop(),         # Telegram bot polling
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log_event("INFO", "bot stopped by KeyboardInterrupt")
