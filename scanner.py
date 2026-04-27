"""Live-сканер: bootstrap + WS-поток закрытых свечей + диспатч в стратегии."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import pandas as pd
import websockets

from config import SYMBOLS, TIMEFRAMES_COMPOSED, TIMEFRAMES_NATIVE
from data_manager import compose_from_base, load_df, save_df, update_df_incrementally
from state import (
    log_event,
    mark_sent,
    save_last_signal,
    was_sent,
)
from strategies import fractal, fvg, hammer, marubozu, ob_htf, obx4, rdrb
from strategies.ob1h_core import find_first_confirmation_in_zone
from strategies.obx4 import to_ref_format
from telegram_bot import broadcast_signal

BINANCE_WS_BASE = "wss://stream.binance.com:9443/stream"

# ТФ для поиска зон. Применяется ко ВСЕМ стратегиям без исключения.
# Если добавишь новую стратегию — НЕ задавай ей собственный список,
# используй STRATEGY_TFS.
STRATEGY_TFS = ["12h", "1d", "2d", "3d"]

STRATEGY_MAP = {
    "OBX4":     (obx4.detect_zones,     STRATEGY_TFS),
    "FVG":      (fvg.detect_zones,      STRATEGY_TFS),
    "OB_HTF":   (ob_htf.detect_zones,   STRATEGY_TFS),
    "RDRB":     (rdrb.detect_zones,     STRATEGY_TFS),
    "FRACTAL":  (fractal.detect_zones,  STRATEGY_TFS),
    "MARUBOZU": (marubozu.detect_zones, STRATEGY_TFS),
    "HAMMER":   (hammer.detect_zones,   STRATEGY_TFS),
}


def _sig_key_str(strategy: str, symbol: str, source_tf: str, direction: str, confirm_iso: str) -> str:
    return f"{strategy}|{symbol}|{source_tf}|{direction}|{confirm_iso}"


class Scanner:
    def __init__(self) -> None:
        self.strategy_map = STRATEGY_MAP

    # ---------------- startup ----------------

    async def startup(self) -> None:
        """Только догружаем свежие свечи (инкремент), пересобираем составные.
        НИЧЕГО не детектируем, НИЧЕГО не помечаем как sent. Бот реагирует
        только на свежие закрытия WS-свечей + 7-дневный re-scan в 1h."""
        log_event("INFO", "startup: fetching latest candles")
        for symbol in SYMBOLS:
            for tf in TIMEFRAMES_NATIVE:
                await asyncio.to_thread(update_df_incrementally, symbol, tf)
            for tf, base_tf in TIMEFRAMES_COMPOSED.items():
                base = load_df(symbol, base_tf)
                composed = compose_from_base(base, tf)
                if not composed.empty:
                    save_df(composed, symbol, tf)
        log_event("INFO", "startup: data ready")

        await asyncio.to_thread(self._prefill_today_signals)

    def _prefill_today_signals(self) -> None:
        today_start = pd.Timestamp.utcnow().floor("D")
        if today_start.tz is None:
            today_start = today_start.tz_localize("UTC")
        log_event("INFO", f"prefill: scanning signals since {today_start.isoformat()}")

        cutoff = pd.Timestamp.utcnow() - pd.Timedelta(hours=48)
        if cutoff.tz is None:
            cutoff = cutoff.tz_localize("UTC")

        filled = 0
        for symbol in SYMBOLS:
            df_1h = to_ref_format(load_df(symbol, "1h"))
            if df_1h.empty:
                continue
            df_1h_recent = df_1h[
                pd.to_datetime(df_1h["Open time"], utc=True) >= cutoff
            ].reset_index(drop=True)
            if df_1h_recent.empty:
                continue
            for strat_name, (detect_fn, tfs) in self.strategy_map.items():
                for stf in tfs:
                    df_stf = load_df(symbol, stf)
                    if df_stf.empty:
                        continue
                    # load_df -> DatetimeIndex; режем по индексу
                    if isinstance(df_stf.index, pd.DatetimeIndex):
                        df_stf_recent = df_stf[df_stf.index >= cutoff]
                    else:
                        df_stf_recent = df_stf[
                            pd.to_datetime(df_stf["Open time"], utc=True) >= cutoff
                        ]
                    if df_stf_recent.empty or len(df_stf_recent) < 5:
                        continue
                    zones = detect_fn(df_stf_recent, symbol, stf)
                    today_zones = [
                        z for z in zones
                        if pd.to_datetime(z.trigger_time, utc=True) >= today_start
                    ]
                    for z in today_zones:
                        confirmation = find_first_confirmation_in_zone(z, df_1h_recent)
                        if confirmation is None:
                            continue
                        confirm_time = confirmation["confirm_time"]
                        if confirm_time < today_start:
                            continue
                        confirm_iso = confirm_time.isoformat()
                        key = _sig_key_str(strat_name, symbol, stf, z.direction, confirm_iso)
                        if was_sent(key):
                            continue
                        mark_sent(key, {
                            "source": "prefill_silent",
                            "strategy": strat_name,
                            "symbol": symbol,
                            "source_tf": stf,
                            "direction": z.direction,
                            "confirm_type": confirmation["type"],
                            "confirm_time": confirm_iso,
                            "marked_at": datetime.now(timezone.utc).isoformat(),
                        })
                        filled += 1
        log_event("INFO", f"prefill: marked {filled} today signals as sent (no broadcast)")

    # ---------------- live dispatch ----------------

    def on_closed_native_candle(self, symbol: str, tf: str) -> None:
        """Вызывается когда native-свеча закрылась. Данные уже в CSV."""
        # пересобрать составные, которые зависят от этого native
        if tf == "1h":
            self._recompose(symbol, "3h")
        if tf == "1d":
            self._recompose(symbol, "2d")

        df_1h = to_ref_format(load_df(symbol, "1h"))
        if df_1h.empty:
            log_event("WARN", f"on_closed: empty 1h for {symbol}")
            return

        # если это 1h — re-scan по всем source_tf за текущий UTC-день
        # (консистентно с _prefill_today_signals — иначе старые недельные
        # зоны могут отстрелить OB и прилететь подписчикам как "свежие").
        full_rescan = (tf == "1h")
        today_start = pd.Timestamp.utcnow().floor("D")
        if today_start.tz is None:
            today_start = today_start.tz_localize("UTC")

        for name, (detect, applicable_tfs) in self.strategy_map.items():
            if full_rescan:
                for stf in applicable_tfs:
                    self._dispatch_strategy(
                        name, detect, symbol, stf, df_1h, cutoff=today_start,
                    )
            else:
                if tf in applicable_tfs:
                    self._dispatch_strategy(
                        name, detect, symbol, tf, df_1h, cutoff=None,
                    )

    def _recompose(self, symbol: str, composed_tf: str) -> None:
        base_tf = TIMEFRAMES_COMPOSED.get(composed_tf)
        if not base_tf:
            return
        base = load_df(symbol, base_tf)
        composed = compose_from_base(base, composed_tf)
        if not composed.empty:
            save_df(composed, symbol, composed_tf)

    def _dispatch_strategy(
        self, name: str, detect, symbol: str, tf: str,
        df_1h: pd.DataFrame, cutoff: "pd.Timestamp | None",
    ) -> None:
        df_htf = load_df(symbol, tf)
        if df_htf.empty:
            return
        zones = detect(df_htf, symbol, tf)
        if cutoff is not None:
            zones = [z for z in zones if pd.to_datetime(z.trigger_time, utc=True) >= cutoff]
        if not zones:
            return

        if cutoff is None:
            # по одному tf-событию — хватит только последней зоны
            zones = sorted(zones, key=lambda z: pd.to_datetime(z.trigger_time, utc=True))[-1:]

        last_1h_open = pd.to_datetime(df_1h.iloc[-1]["Open time"], utc=True)
        for z in zones:
            confirmation = find_first_confirmation_in_zone(z, df_1h)
            if confirmation is None:
                continue

            confirm_time = confirmation["confirm_time"]
            # Главное правило: подтверждающая свеча = последняя закрытая 1h.
            if confirm_time != last_1h_open:
                continue
            if cutoff is not None and confirm_time < cutoff:
                continue

            confirm_iso = confirm_time.isoformat()
            sig_data = {
                "strategy": z.strategy,
                "symbol": z.symbol,
                "timeframe": "1h",
                "direction": z.direction,
                "source_tf": z.source_tf,
                "price": float(confirmation["confirm_close"]),
                "confirm_time_iso": confirm_iso,
                "zone_bottom": float(z.zone_bottom),
                "zone_top": float(z.zone_top),
                "confirm_type": confirmation["type"],
                "confirm_zone_bottom": float(confirmation["confirm_zone_bottom"]),
                "confirm_zone_top": float(confirmation["confirm_zone_top"]),
            }

            k = _sig_key_str(z.strategy, z.symbol, z.source_tf, z.direction, confirm_iso)
            if was_sent(k):
                continue
            try:
                result = broadcast_signal(sig_data)
                payload = {
                    "strategy": z.strategy,
                    "symbol": z.symbol,
                    "timeframe": "1h",
                    "direction": z.direction,
                    "confirm_time": confirm_iso,
                    "price": float(confirmation["confirm_close"]),
                    "sent_at": datetime.now(timezone.utc).isoformat(),
                    "sig": sig_data,
                    "broadcast_result": {
                        "ok": result.get("ok"), "failed": result.get("failed"),
                        "total": result.get("total"),
                    },
                }
                mark_sent(k, payload)
                save_last_signal(payload)
                log_event(
                    "SIGNAL",
                    f"{z.strategy} {z.symbol} {z.source_tf} {z.direction} "
                    f"via {confirmation['type']} "
                    f"sent to {result.get('ok', 0)} users "
                    f"(confirm_time={confirm_iso})",
                )
            except Exception as e:
                log_event("ERROR", f"broadcast failed for {k}: {e!r}")

    # ---------------- websocket ----------------

    def _stream_names(self) -> list[str]:
        return [
            f"{sym.lower()}@kline_{tf}"
            for sym in SYMBOLS
            for tf in TIMEFRAMES_NATIVE
        ]

    async def ws_loop(self) -> None:
        streams = "/".join(self._stream_names())
        url = f"{BINANCE_WS_BASE}?streams={streams}"
        log_event("INFO", f"ws_loop: {len(self._stream_names())} streams")

        while True:
            try:
                async with websockets.connect(url, ping_interval=30, ping_timeout=15) as ws:
                    log_event("INFO", "ws connected")
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
                        if not symbol or tf not in TIMEFRAMES_NATIVE:
                            continue
                        try:
                            await asyncio.to_thread(update_df_incrementally, symbol, tf)
                            await asyncio.to_thread(self.on_closed_native_candle, symbol, tf)
                        except Exception as e:
                            log_event("ERROR", f"on_closed {symbol} {tf}: {e!r}")
            except Exception as e:
                log_event("ERROR", f"ws disconnect: {e!r}")
                await asyncio.sleep(5)
