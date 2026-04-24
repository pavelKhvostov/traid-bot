"""Точка входа: startup -> ws_loop + polling_loop."""
from __future__ import annotations

import asyncio

from config import TELEGRAM_BOT_TOKEN, load_admins
from scanner import Scanner
from state import load_users, log_event
from telegram_bot import polling_loop, send_message


async def main() -> None:
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "replace_me_with_real_bot_token":
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан в .env")

    log_event("INFO", "bot starting")

    # Разовая миграция формата signals_today.json (был "text", стал "sig").
    try:
        import state as _state
        p = _state.SIGNALS_TODAY_PATH
        if p.exists():
            p.unlink()
            log_event("INFO", "signals_today.json cleared for new format")
    except Exception as e:
        log_event("WARN", f"signals_today cleanup failed: {e!r}")

    scanner = Scanner()
    await scanner.startup()

    users_count = len(load_users())
    admins = load_admins()

    startup_msg = (
        "🤖 <b>Бот запущен</b>\n"
        "Стратегии: OBX4, FVG, OB_HTF, RDRB, FRACTAL\n"
        "Символы: BTCUSDT, ETHUSDT, SOLUSDT\n"
        f"Подписчиков: <b>{users_count}</b>\n"
        "Шлём только НОВЫЕ сигналы на только что закрывшихся свечах."
    )
    for admin_id in admins:
        try:
            send_message(startup_msg, admin_id)
        except Exception as e:
            log_event("WARN", f"admin notify failed ({admin_id}): {e!r}")

    log_event("INFO", f"scanner ready, users={users_count}, admins={len(admins)}")

    await asyncio.gather(
        scanner.ws_loop(),
        polling_loop(),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log_event("INFO", "bot stopped by KeyboardInterrupt")
