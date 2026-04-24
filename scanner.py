"""Live-сканер: bootstrap + WS-поток закрытых свечей + диспатч в стратегии."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

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
from strategies import fractal, fvg, ob_htf, obx4, rdrb
from strategies.base import Signal, signal_key
from strategies.ob1h_core import find_first_ob1h_in_zone, scan_zones_to_signals
from strategies.obx4 import to_ref_format
from telegram_bot import broadcast_signal

BINANCE_WS_BASE = "wss://stream.binance.com:9443/stream"

STRATEGY_MAP = {
    "OBX4":    (obx4.detect_zones,    ["1h", "2h", "3h", "4h", "6h", "8h", "12h", "1d", "2d", "3d"]),
    "FVG":     (fvg.detect_zones,     ["2h", "3h", "4h", "6h", "8h", "12h", "1d", "2d", "3d"]),
    "OB_HTF":  (ob_htf.detect_zones,  ["2h", "3h", "4h", "6h", "8h", "12h", "1d", "2d", "3d"]),
    "RDRB":    (rdrb.detect_zones,    ["2h", "3h", "4h", "6h", "8h", "12h", "1d", "2d", "3d"]),
    "FRACTAL": (fractal.detect_zones, ["2h", "3h", "4h", "6h", "8h", "12h", "1d", "2d", "3d"]),
}


def _sig_to_dict(s: Signal) -> dict:
    return {
        "strategy": s.strategy,
        "symbol": s.symbol,
        "timeframe": s.timeframe,
        "direction": s.direction,
        "source_tf": s.meta["source_tf"],
        "price": float(s.price),
        "confirm_time_iso": s.confirm_time.isoformat() if hasattr(s.confirm_time, "isoformat") else str(s.confirm_time),
        "zone_bottom": float(s.meta["zone_bottom"]),
        "zone_top": float(s.meta["zone_top"]),
    }


def _signal_payload(s: Signal) -> dict:
    return {
        "strategy": s.strategy,
        "symbol": s.symbol,
        "timeframe": s.timeframe,
        "direction": s.direction,
        "confirm_time": s.confirm_time.isoformat() if hasattr(s.confirm_time, "isoformat") else str(s.confirm_time),
        "price": s.price,
        "sent_at": datetime.now(timezone.utc).isoformat(),
        "meta": s.meta,
    }


def _sig_key(s: Signal) -> str:
    return f"{s.strategy}|{s.symbol}|{s.meta['source_tf']}|{s.direction}|{s.meta['ob1h_cur_time']}"


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

    def _build_signal(self, strat_name: str, z, hit: dict, source_tf: str) -> Signal:
        meta = {
            "source_tf": source_tf,
            "zone_bottom": float(z.zone_bottom),
            "zone_top": float(z.zone_top),
            "trigger_time": pd.to_datetime(z.trigger_time, utc=True).isoformat(),
            "first_return_time": hit["first_return_time"].isoformat(),
            "ob1h_prev_time": hit["ob1h_prev_time"].isoformat(),
            "ob1h_cur_time": hit["ob1h_cur_time"].isoformat(),
            "ob1h_cur_close": hit["ob1h_cur_close"],
        }
        for k, v in (z.meta or {}).items():
            meta.setdefault(k, v)
        return Signal(
            strategy=strat_name,
            symbol=z.symbol,
            timeframe="1h",
            direction=z.direction,
            confirm_time=hit["ob1h_cur_time"],
            price=hit["ob1h_cur_close"],
            meta=meta,
        )

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
                        hit = find_first_ob1h_in_zone(z, df_1h_recent)
                        if hit is None:
                            continue
                        ob_time = pd.to_datetime(hit["ob1h_cur_time"], utc=True)
                        if ob_time < today_start:
                            continue
                        sig = self._build_signal(strat_name, z, hit, stf)
                        key = _sig_key(sig)
                        if was_sent(key):
                            continue
                        mark_sent(key, {
                            "source": "prefill_silent",
                            "strategy": sig.strategy,
                            "symbol": sig.symbol,
                            "source_tf": sig.meta["source_tf"],
                            "direction": sig.direction,
                            "ob1h_cur_time": sig.meta["ob1h_cur_time"],
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

        signals = scan_zones_to_signals(zones, df_1h)
        last_1h_open = pd.to_datetime(df_1h.iloc[-1]["Open time"], utc=True)
        for s in signals:
            ob_time = pd.to_datetime(s.meta["ob1h_cur_time"], utc=True)
            # Главное правило: шлём только если OB на последней закрытой 1h-свече.
            if ob_time != last_1h_open:
                continue
            # re-scan ветка: OB также должен быть сегодня (подстраховка, обычно уже
            # выполнено предыдущей проверкой).
            if cutoff is not None and ob_time < cutoff:
                continue
            k = _sig_key(s)
            if was_sent(k):
                continue
            try:
                sig_data = _sig_to_dict(s)
                result = broadcast_signal(sig_data)
                payload = _signal_payload(s)
                payload["sig"] = sig_data
                payload["broadcast_result"] = {
                    "ok": result.get("ok"), "failed": result.get("failed"),
                    "total": result.get("total"),
                }
                mark_sent(k, payload)
                save_last_signal(payload)
                log_event(
                    "SIGNAL",
                    f"{s.strategy} {s.symbol} {s.meta['source_tf']} {s.direction} "
                    f"sent to {result.get('ok', 0)} users "
                    f"(ob1h_cur_time={s.meta['ob1h_cur_time']})",
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
