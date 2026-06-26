"""Точка входа: startup -> ws_loop + polling_loop.

Live-режим: Strategy 1.1.1 (с confluence) + 1.1.2 + 1.1.3 + 1.1.6 (без confluence).
Старый Scanner (7 классических) и VicScanner отключены, сохранены в коде.

Утверждённые параметры live-сканеров:
  1.1.1: entry=0.80, sl=0.35 sym, RR=2.2, SWEPT ON (через 1.1.1 detector + confluence)
  1.1.2: entry=0.70, sl=0.35 sym, RR=2.2, NO SWEPT
  1.1.3: entry=0.70, sl=0.35 sym, RR=2.2, OB-macro (untouched)
  1.1.6: entry=0.70, sl=0.35 sym, RR=2.2, FVG-macro + immediate FVG-htf entry
"""
from __future__ import annotations

import asyncio
import os

from config import TELEGRAM_BOT_TOKEN, load_admins
from state import load_users, log_event
from strategy_1_1_1_scanner import Strategy111Scanner
from telegram_bot import polling_loop, send_message

from multi_strategy_scanner import MultiStrategyScanner
from strategies.strategy_1_1_2 import detect_strategy_1_1_2_signals
from strategies.strategy_1_1_3 import detect_strategy_1_1_3_signals
from strategies.strategy_1_1_6 import detect_strategy_1_1_6_signals


async def main() -> None:
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "replace_me_with_real_bot_token":
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан в .env")

    log_event("INFO", "bot starting (1.1.1 + 1.1.2 + 1.1.3 + 1.1.6)")

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
    s112 = MultiStrategyScanner(
        strategy_id="S112", strategy_name="1.1.2",
        detector_fn=detect_strategy_1_1_2_signals, needs_ltf=True,
        entry_pct=0.70, sl_pct=0.35, rr=2.2,
    )
    s113 = MultiStrategyScanner(
        strategy_id="S113", strategy_name="1.1.3",
        detector_fn=detect_strategy_1_1_3_signals, needs_ltf=False,
        detector_kwargs={"fvg_variant": "v1", "macro_mode": "untouched"},
        entry_pct=0.70, sl_pct=0.35, rr=2.2,
    )
    s116 = MultiStrategyScanner(
        strategy_id="S116", strategy_name="1.1.6",
        detector_fn=detect_strategy_1_1_6_signals, needs_ltf=False,
        detector_kwargs={"fvg_variant": "v1"},
        entry_pct=0.70, sl_pct=0.35, rr=2.2,
    )

    await s111.startup()
    await s112.startup()
    await s113.startup()
    await s116.startup()

    # Стратегия «Магнитуда» — ADMIN-only, за флагом MAGNITUDE_ENABLED (по умолчанию OFF).
    # Сигналы идут ТОЛЬКО админам через DASHBOARD_BOT_TOKEN, НЕ подписчикам. Подписка на 8h/12h по BTC/ETH/SOL.
    mag_on = os.getenv("MAGNITUDE_ENABLED", "").lower() in ("1", "true", "yes", "on")
    s_mag = None
    if mag_on:
        from magnitude_scanner import MagnitudeScanner
        s_mag = MagnitudeScanner()
        await s_mag.startup()
        log_event("INFO", "Magnitude scanner ENABLED (ADMIN-only, 8h/12h, BTC/ETH/SOL)")

    users_count = len(load_users())
    admins = load_admins()

    from config import SYMBOLS
    startup_msg = (
        "🤖 <b>Бот запущен</b>\n"
        "Стратегии: <b>1.1.1, 1.1.2, 1.1.3, 1.1.6</b>\n"
        f"Символы: {', '.join(SYMBOLS)}\n"
        f"Подписчиков: <b>{users_count}</b>\n"
        "1.1.1 — с confluence (BTC1!/TOTALES/USDT.D)\n"
        "1.1.2/1.1.3/1.1.6 — без confluence, RR=2.2 в сообщении"
        + ("\n🧲 Магнитуда: ВКЛ (ADMIN-only тест, 8h/12h)" if mag_on else "")
    )
    for admin_id in admins:
        try:
            send_message(startup_msg, admin_id)
        except Exception as e:
            log_event("WARN", f"admin notify failed ({admin_id}): {e!r}")

    log_event("INFO", f"all scanners ready, users={users_count}, admins={len(admins)}")

    coros = [
        s111.ws_loop(),         # Binance WS — 1.1.1 detection
        s111.tv_refresh_loop(), # TV REST — confluence data
        s112.ws_loop(),         # 1.1.2 own WS session
        s113.ws_loop(),         # 1.1.3 own WS session
        s116.ws_loop(),         # 1.1.6 own WS session
        polling_loop(),         # Telegram bot polling
    ]
    if s_mag is not None:
        coros.append(s_mag.ws_loop())  # Магнитуда own WS (8h/12h), ADMIN-only

    await asyncio.gather(*coros)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log_event("INFO", "bot stopped by KeyboardInterrupt")
