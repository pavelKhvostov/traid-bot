"""Live-сканер Strategy 1.1.1.

Триггер: закрытие 1h свечи. На каждом 1h close:
  1. Обновляем native CSV (1m, 15m, 1h, 4h, 1d).
  2. Composes 12h, 6h, 2h, 20m из native.
  3. Запускаем detect_strategy_1_1_1_signals на recent window.
  4. Каждый новый сигнал (через dedup) → broadcast «BTCUSDT 1.1.1 LONG/SHORT».

OB-htf cur close — 1h каждый час, 2h на чётных часах. На 1h close после
обновления df_1h можно сразу детектить и 1h, и 2h случаи (composed df_2h
обновится из свежего df_1h).
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import pandas as pd
import websockets

from config import SYMBOLS
from data_manager import compose_from_base, load_df, update_df_incrementally
from state import log_event, mark_sent, save_last_signal, was_sent
from strategies.strategy_1_1_1 import detect_strategy_1_1_1_signals
from strategy_1_1_1_confluence import check_confluence, format_signal_message
from telegram_bot import broadcast

BINANCE_WS_BASE = "wss://stream.binance.com:9443/stream"

# Native TFs, на которые подписываемся (composed 12h/6h/2h/20m строятся из них).
NATIVE_TFS = ["1m", "15m", "1h", "4h", "1d"]

# Recent-window для детектора. Должен быть >= max(top_tf_hours) + buffer на formation.
# 30 дней покрывает любую top-OB → 4h/6h FVG → 1h/2h OB → 15m/20m FVG воронку.
HISTORY_DAYS = 30


class Strategy111Scanner:
    """Параллельный со Scanner/VicScanner — своя WS-сессия и dispatch."""

    async def startup(self) -> None:
        log_event("INFO", "s111_startup: bootstrap data")
        for symbol in SYMBOLS:
            for tf in NATIVE_TFS:
                await asyncio.to_thread(update_df_incrementally, symbol, tf)
        log_event("INFO", "s111_startup: data ready")

        # Prefill silent: помечаем сигналы за последний день как sent, чтобы
        # не разослать пачку при рестарте.
        await asyncio.to_thread(self._prefill_silent)
        log_event("INFO", "s111_startup: prefill silent done")

    def _prefill_silent(self) -> None:
        """Помечаем ВСЕ сигналы из window детектора как sent без рассылки.

        Иначе на первом же 1h close после рестарта повалились бы все
        исторические сигналы из последних HISTORY_DAYS дней. После prefill
        новый сигнал будет сгенерён только когда сработает 1h close с
        реально новым OB-htf cur.
        """
        for symbol in SYMBOLS:
            try:
                signals = self._collect_signals(symbol)
            except Exception as e:
                log_event("WARN", f"s111_prefill {symbol}: {e!r}")
                continue
            for sig in signals:
                key = self._dedup_key(symbol, sig)
                if not was_sent(key):
                    sig_time = pd.Timestamp(sig["signal_time"])
                    if sig_time.tz is None:
                        sig_time = sig_time.tz_localize("UTC")
                    mark_sent(key, {"prefill": True, "signal_time": sig_time.isoformat()})

    @staticmethod
    def _dedup_key(symbol: str, sig: dict) -> str:
        sig_time = pd.Timestamp(sig["signal_time"])
        if sig_time.tz is None:
            sig_time = sig_time.tz_localize("UTC")
        # Ключ включает entry round'ленный — стабильный across одинаковых сетапов
        # с разных top-TF (1d/12h дают одинаковый entry FVG, дедуп их склеит).
        entry_r = round(float(sig["entry"]), 8)
        return f"S111|{symbol}|{sig['direction']}|{sig_time.isoformat()}|{entry_r}"

    def _collect_signals(self, symbol: str) -> list[dict]:
        df_1d = load_df(symbol, "1d")
        df_4h = load_df(symbol, "4h")
        df_1h = load_df(symbol, "1h")
        df_15m = load_df(symbol, "15m")
        df_1m = load_df(symbol, "1m")
        if any(df.empty for df in (df_1d, df_4h, df_1h, df_15m, df_1m)):
            return []

        # Recent-window для performance.
        now = pd.Timestamp.now(tz="UTC")
        cutoff = now - pd.Timedelta(days=HISTORY_DAYS)
        df_1d = df_1d[df_1d.index >= cutoff - pd.Timedelta(days=2)]
        df_4h = df_4h[df_4h.index >= cutoff - pd.Timedelta(days=2)]
        df_1h = df_1h[df_1h.index >= cutoff - pd.Timedelta(days=2)]
        df_15m = df_15m[df_15m.index >= cutoff - pd.Timedelta(days=2)]
        df_1m = df_1m[df_1m.index >= cutoff - pd.Timedelta(days=2)]

        df_12h = compose_from_base(df_1h, "12h")
        df_6h = compose_from_base(df_1h, "6h")
        df_2h = compose_from_base(df_1h, "2h")
        df_20m = compose_from_base(df_1m, "20m")

        return detect_strategy_1_1_1_signals(
            df_1d, df_12h, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m,
            verbose=False,
        )

    def on_closed_1h(self, symbol: str) -> None:
        # На закрытии 1h одновременно закрываются 15m и 1m candles.
        # WS не гарантирует порядок их доставки, поэтому force-update всех
        # native TFs перед детекцией — иначе df_15m/df_1m могут быть на 1
        # бар отстать и мы пропустим entry FVG c2 в текущей итерации.
        for tf in NATIVE_TFS:
            try:
                update_df_incrementally(symbol, tf)
            except Exception as e:
                log_event("WARN", f"s111 force_update {symbol} {tf}: {e!r}")

        try:
            signals = self._collect_signals(symbol)
        except Exception as e:
            log_event("ERROR", f"s111 detect {symbol}: {e!r}")
            return

        for sig in signals:
            key = self._dedup_key(symbol, sig)
            if was_sent(key):
                continue

            sig_time = pd.Timestamp(sig["signal_time"])
            if sig_time.tz is None:
                sig_time = sig_time.tz_localize("UTC")

            # Confluence-проверка с BTC1!, TOTALES, USDT.D
            try:
                confluence = check_confluence(sig_time, sig["direction"])
            except Exception as e:
                log_event("WARN", f"s111 confluence check {symbol}: {e!r}")
                confluence = {"matches": [], "count": 0, "details": {}}

            text = format_signal_message(symbol, sig, confluence)

            try:
                result = broadcast(text)
                payload = {
                    "strategy": "S111",
                    "symbol": symbol,
                    "direction": sig["direction"],
                    "signal_time": sig_time.isoformat(),
                    "entry": float(sig["entry"]),
                    "sl": float(sig["sl"]),
                    "ob_htf_tf": sig["ob_htf_tf"],
                    "fvg_tf": sig["fvg_tf"],
                    "fvg_macro_tf": sig["fvg_macro_tf"],
                    "top_tf": sig.get("top_tf", "1d"),
                    "confluence_count": confluence["count"],
                    "confluence_matches": confluence["matches"],
                    "sent_at": datetime.now(timezone.utc).isoformat(),
                    "broadcast_result": {
                        "ok": result.get("ok"),
                        "failed": result.get("failed"),
                        "total": result.get("total"),
                    },
                }
                mark_sent(key, payload)
                save_last_signal(payload)
                log_event(
                    "SIGNAL",
                    f"S111 {symbol} {sig['direction']} sync={confluence['count']}/3 "
                    f"({','.join(confluence['matches']) or 'none'}) "
                    f"sent to {result.get('ok', 0)} users",
                )
            except Exception as e:
                log_event("ERROR", f"s111 broadcast {key}: {e!r}")

    def _stream_names(self) -> list[str]:
        return [f"{sym.lower()}@kline_{tf}" for sym in SYMBOLS for tf in NATIVE_TFS]

    async def ws_loop(self) -> None:
        streams = "/".join(self._stream_names())
        url = f"{BINANCE_WS_BASE}?streams={streams}"
        log_event("INFO", f"s111_ws_loop: {len(self._stream_names())} streams")

        while True:
            try:
                async with websockets.connect(url, ping_interval=30, ping_timeout=15) as ws:
                    log_event("INFO", "s111_ws connected")
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
                        if not symbol or tf not in NATIVE_TFS:
                            continue
                        try:
                            await asyncio.to_thread(update_df_incrementally, symbol, tf)
                            # Триггер детекции — на 1h close (покрывает 1h и
                            # composed 2h случаи). Остальные TF — только обновляем CSV.
                            if tf == "1h":
                                await asyncio.to_thread(self.on_closed_1h, symbol)
                        except Exception as e:
                            log_event("ERROR", f"s111 on_closed {symbol} {tf}: {e!r}")
            except Exception as e:
                log_event("ERROR", f"s111_ws disconnect: {e!r}")
                await asyncio.sleep(5)
