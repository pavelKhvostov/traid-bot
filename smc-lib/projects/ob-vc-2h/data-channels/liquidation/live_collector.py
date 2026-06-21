"""Live liquidation collector — Binance Futures WebSocket forceOrder feed.

⚠ Реальность: исторических liquidation данных в публичном free доступе нет:
   - Binance allForceOrders endpoint — DECOMMISSIONED (2023+)
   - Coinglass historical — требует API key (free tier exists)
   - Coinalyze historical — требует API key (free tier exists)
   - Tardis.dev — платная подписка

Этот скрипт собирает liquidations в real-time с публичного Binance WebSocket
и записывает в дневные parquet файлы. Запустить как daemon: после 3-6 месяцев
накопится история для v2 ML training.

Endpoint: wss://fstream.binance.com/ws/!forceOrder@arr
Public, no auth. Streams все liquidations со всех perp пар.

Output: ~/smc-lib/projects/ob-vc/data-channels/liquidation/live/{YYYY-MM-DD}.parquet
  columns: ts_ms, symbol, side, price, qty, usd_value

Запуск:
  python3 live_collector.py
  # или как daemon: nohup python3 live_collector.py > collector.log 2>&1 &
"""
from __future__ import annotations
import asyncio
import json
import pathlib
from datetime import datetime, timezone

import pandas as pd


try:
    import websockets
except ImportError:
    raise SystemExit("pip install websockets")


URL = "wss://fstream.binance.com/ws/!forceOrder@arr"
OUT_DIR = pathlib.Path(__file__).resolve().parent / "live"
OUT_DIR.mkdir(exist_ok=True)
BUFFER: list[dict] = []
FLUSH_INTERVAL_SEC = 60  # flush every minute


def event_to_row(o: dict) -> dict:
    """Binance forceOrder payload:
       {"E": event_time, "o": {
           "s": symbol, "S": side (BUY/SELL), "ap": avg_price,
           "q": qty, "T": trade_time, "ot": order_type, ...}}
    """
    body = o.get("o", {})
    price = float(body.get("ap", 0))
    qty   = float(body.get("q", 0))
    return {
        "ts_ms": int(body.get("T", o.get("E", 0))),
        "symbol": body.get("s", ""),
        "side":   body.get("S", ""),
        "price":  price,
        "qty":    qty,
        "usd_value": price * qty,
    }


def flush_buffer() -> None:
    global BUFFER
    if not BUFFER:
        return
    df = pd.DataFrame(BUFFER)
    # Group by date and append
    df["date"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True).dt.date.astype(str)
    for date, chunk in df.groupby("date"):
        out = OUT_DIR / f"{date}.parquet"
        if out.exists():
            existing = pd.read_parquet(out)
            chunk_combined = pd.concat([existing, chunk.drop(columns=["date"])], ignore_index=True)
        else:
            chunk_combined = chunk.drop(columns=["date"])
        chunk_combined = chunk_combined.drop_duplicates(subset=["ts_ms","symbol","side","qty"])
        chunk_combined.to_parquet(out, index=False)
        print(f"  [flush] {date}: +{len(chunk)} rows (total {len(chunk_combined):,})")
    BUFFER = []


async def collector():
    print(f"[liq-live] connecting to {URL}")
    print(f"[liq-live] output -> {OUT_DIR}")
    print(f"[liq-live] flush interval: {FLUSH_INTERVAL_SEC}s")
    last_flush = asyncio.get_event_loop().time()
    while True:
        try:
            async with websockets.connect(URL, ping_interval=20) as ws:
                print("[liq-live] connected")
                async for msg in ws:
                    try:
                        data = json.loads(msg)
                        BUFFER.append(event_to_row(data))
                    except Exception as e:
                        print(f"[liq-live] parse error: {e}")
                    now = asyncio.get_event_loop().time()
                    if now - last_flush >= FLUSH_INTERVAL_SEC:
                        flush_buffer()
                        last_flush = now
        except Exception as e:
            print(f"[liq-live] connection error: {e} — reconnecting in 10s")
            flush_buffer()
            await asyncio.sleep(10)


if __name__ == "__main__":
    try:
        asyncio.run(collector())
    except KeyboardInterrupt:
        print("\n[liq-live] stopping, final flush...")
        flush_buffer()
        print("[liq-live] done")
