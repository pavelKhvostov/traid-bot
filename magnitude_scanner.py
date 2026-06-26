"""Live-сканер стратегии «Магнитуда» — ADMIN-ONLY (тест-контур, БЕЗ рассылки подписчикам).

Триггер: закрытие 8h свечи -> long-детектор; закрытие 12h свечи -> short-детектор; по BTC/ETH/SOL.
Отправка ТОЛЬКО ADMIN через DASHBOARD_BOT_TOKEN (бот @new_edge_neiro_bot), НЕ через прод-токен, НЕ broadcast.
Включается флагом MAGNITUDE_ENABLED в main.py (по умолчанию OFF).

Модель/детектор: strategies/magnitude.py (persisted models/magnitude_*.cbm). Спека: research/reversal_cb/MAGNITUDA_REPRODUCE.md.
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone

import pandas as pd
import requests
import websockets

from config import load_admins
from data_manager import load_df, update_df_incrementally
from state import log_event, mark_sent, save_last_signal, was_sent
from strategies.magnitude import detect_magnitude_signals, _load

BINANCE_WS_BASE = "wss://stream.binance.com:9443/stream"
MAG_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]   # cross-asset (ядро стратегии); независимо от глобального SYMBOLS
TF_DIRECTION = {"8h": "long", "12h": "short"}
HISTORY_BARS = 400                                 # достаточно для rolling-окон фич (нужно >=110)
DASHBOARD_BOT_TOKEN = os.getenv("DASHBOARD_BOT_TOKEN", "")


class MagnitudeScanner:
    """ADMIN-only сканер Магнитуды. Сигналы идут только админам (analytics-бот), не подписчикам."""

    def __init__(self) -> None:
        self.sid = "MAG"
        self.token = DASHBOARD_BOT_TOKEN

    # ---- отправка ТОЛЬКО админам (dashboard-канал) ----
    def _send_admin(self, text: str) -> dict:
        admins = load_admins()
        if not self.token:
            log_event("WARN", "MAG: DASHBOARD_BOT_TOKEN не задан — сигнал НЕ отправлен (ADMIN-only)")
            return {"ok": False, "skipped": "no_token"}
        if not admins:
            log_event("WARN", "MAG: нет админов в admins.json — сигнал не отправлен")
            return {"ok": False, "skipped": "no_admins"}
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        ok = 0
        for chat_id in admins:
            try:
                r = requests.post(url, data={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                                             "disable_web_page_preview": "true"}, timeout=30)
                if r.json().get("ok"):
                    ok += 1
            except Exception as e:
                log_event("ERROR", f"MAG send admin={chat_id}: {e!r}")
        return {"ok": ok > 0, "sent": ok, "total": len(admins)}

    # ---- startup ----
    async def startup(self) -> None:
        log_event("INFO", "MAG_startup: bootstrap 8h/12h (ADMIN-only режим)")
        for sym in MAG_SYMBOLS:
            for tf in ("8h", "12h"):
                try:
                    await asyncio.to_thread(update_df_incrementally, sym, tf)
                except Exception as e:
                    log_event("WARN", f"MAG bootstrap {sym} {tf}: {e!r}")
        try:
            await asyncio.to_thread(_load)            # прогрев CatBoost-моделей
        except Exception as e:
            log_event("ERROR", f"MAG model load: {e!r}")
        await asyncio.to_thread(self._prefill_silent)
        log_event("INFO", "MAG_startup: prefill silent done (ADMIN-only)")

    def _dedup_key(self, symbol: str, sig: dict) -> str:
        t = pd.Timestamp(sig["signal_time"])
        if t.tz is None:
            t = t.tz_localize("UTC")
        return f"Magnitude|{symbol}|{sig['direction']}|{t.isoformat()}|{round(float(sig['entry']), 8)}"

    def _collect(self, symbol: str, tf: str) -> list[dict]:
        df = load_df(symbol, tf)
        if df is None or df.empty or len(df) < 120:
            return []
        return detect_magnitude_signals(df.tail(HISTORY_BARS), TF_DIRECTION[tf], n_recent=3)

    def _prefill_silent(self) -> None:
        for sym in MAG_SYMBOLS:
            for tf in ("8h", "12h"):
                try:
                    sigs = self._collect(sym, tf)
                except Exception as e:
                    log_event("WARN", f"MAG_prefill {sym} {tf}: {e!r}")
                    continue
                for sig in sigs:
                    key = self._dedup_key(sym, sig)
                    if not was_sent(key):
                        t = pd.Timestamp(sig["signal_time"])
                        if t.tz is None:
                            t = t.tz_localize("UTC")
                        mark_sent(key, {"prefill": True, "signal_time": t.isoformat()})

    def _format(self, symbol: str, sig: dict) -> str:
        t = pd.Timestamp(sig["signal_time"])
        if t.tz is None:
            t = t.tz_localize("UTC")
        icon = "📈" if sig["direction"] == "LONG" else "📉"
        risk_pct = abs(sig["entry"] - sig["sl"]) / sig["entry"] * 100
        return (
            f"🧲 <b>{symbol}</b> · <b>Магнитуда</b> · ADMIN-only тест\n"
            f"{icon} <b>{sig['direction']}</b> · reversal {sig['tf']}\n"
            f"\n"
            f"Вход:  <b>{sig['entry']:.2f}</b>\n"
            f"SL:    <b>{sig['sl']:.2f}</b> ({risk_pct:.2f}%)\n"
            f"TP:    <b>{sig['tp']:.2f}</b> (RR={sig['rr']})\n"
            f"reversal-likelihood p={sig['p']}\n"
            f"Время: {t.strftime('%Y-%m-%d %H:%M')} UTC\n"
            f"⚠️ кандидат на обкатке (~33% WR / высокий RR, режим-зависимо). НЕ финсовет, НЕ рассылка."
        )

    def on_closed(self, symbol: str, tf: str) -> None:
        try:
            update_df_incrementally(symbol, tf)
            sigs = self._collect(symbol, tf)
        except Exception as e:
            log_event("ERROR", f"MAG detect {symbol} {tf}: {e!r}")
            return
        now = pd.Timestamp.now(tz="UTC")
        fresh_cut = now - pd.Timedelta(hours=int(tf[:-1]) * 1.5)   # только только-что закрытый бар
        for sig in sigs:
            key = self._dedup_key(symbol, sig)
            if was_sent(key):
                continue
            t = pd.Timestamp(sig["signal_time"])
            if t.tz is None:
                t = t.tz_localize("UTC")
            if t < fresh_cut:
                mark_sent(key, {"stale_outside_window": True, "signal_time": t.isoformat()})
                continue
            res = self._send_admin(self._format(symbol, sig))
            payload = {
                "strategy": "Magnitude", "symbol": symbol, "direction": sig["direction"],
                "tf": sig["tf"], "signal_time": t.isoformat(), "entry": float(sig["entry"]),
                "sl": float(sig["sl"]), "tp": float(sig["tp"]), "rr": float(sig["rr"]),
                "p": float(sig["p"]), "admin_only": True, "send_ok": bool(res.get("ok")),
                "sent_at": datetime.now(timezone.utc).isoformat(),
            }
            mark_sent(key, payload)
            save_last_signal(payload)
            log_event("SIGNAL", f"MAG {symbol} {sig['direction']} {sig['tf']} -> ADMIN ok={res.get('ok')}")

    def _streams(self) -> list[str]:
        return [f"{s.lower()}@kline_{tf}" for s in MAG_SYMBOLS for tf in ("8h", "12h")]

    async def ws_loop(self) -> None:
        url = f"{BINANCE_WS_BASE}?streams={'/'.join(self._streams())}"
        log_event("INFO", f"MAG_ws_loop: {len(self._streams())} streams (ADMIN-only)")
        while True:
            try:
                async with websockets.connect(url, ping_interval=30, ping_timeout=15) as ws:
                    log_event("INFO", "MAG_ws connected")
                    async for raw in ws:
                        try:
                            msg = json.loads(raw)
                        except ValueError:
                            continue
                        data = msg.get("data") or msg
                        k = data.get("k")
                        if not k or not k.get("x"):
                            continue
                        symbol = data.get("s") or k.get("s")
                        tf = k.get("i")
                        if not symbol or tf not in ("8h", "12h"):
                            continue
                        try:
                            await asyncio.to_thread(self.on_closed, symbol, tf)
                        except Exception as e:
                            log_event("ERROR", f"MAG on_closed {symbol} {tf}: {e!r}")
            except Exception as e:
                log_event("ERROR", f"MAG_ws disconnect: {e!r}")
                await asyncio.sleep(5)
