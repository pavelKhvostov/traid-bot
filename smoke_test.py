"""Одноразовая проверка инфраструктуры: данные + телеграм."""
from __future__ import annotations

import time

from config import ADMIN_CHAT_ID, TELEGRAM_BOT_TOKEN
from data_manager import fetch_klines_range, tf_to_ms
from telegram_bot import send_message


def main() -> None:
    symbol, tf = "BTCUSDT", "1h"
    step = tf_to_ms(tf)
    now_ms = int(time.time() * 1000)
    end_ms = (now_ms // step) * step
    start_ms = end_ms - 100 * step

    print(f"[SMOKE] fetching {symbol} {tf}: last 100 candles...")
    df = fetch_klines_range(symbol, tf, start_ms, end_ms)
    if df.empty:
        raise RuntimeError("Binance вернул пустой ответ")

    first_row = df.iloc[0]
    last_row = df.iloc[-1]
    print(f"[SMOKE] got {len(df)} candles")
    print(f"[SMOKE] first: {df.index[0].isoformat()} O={first_row['open']} H={first_row['high']} "
          f"L={first_row['low']} C={first_row['close']} V={first_row['volume']}")
    print(f"[SMOKE] last:  {df.index[-1].isoformat()} O={last_row['open']} H={last_row['high']} "
          f"L={last_row['low']} C={last_row['close']} V={last_row['volume']}")

    last_ts = df.index[-1].isoformat()
    last_close = last_row["close"]
    text = (
        f"<b>Smoke test OK</b>: {symbol} {tf}, {len(df)} свечей, "
        f"последняя — <code>{last_ts}</code> @ <b>{last_close}</b>"
    )

    if not TELEGRAM_BOT_TOKEN or not ADMIN_CHAT_ID:
        raise RuntimeError("TELEGRAM_BOT_TOKEN / ADMIN_CHAT_ID не прочитаны из .env")

    print(f"[SMOKE] sending test message to admin {ADMIN_CHAT_ID}...")
    resp = send_message(text, ADMIN_CHAT_ID)
    if not resp.get("ok"):
        raise RuntimeError(f"Telegram sendMessage failed: {resp}")
    print("[SMOKE] done ✅")


if __name__ == "__main__":
    main()
