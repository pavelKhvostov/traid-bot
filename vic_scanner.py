"""VIC live-сканер: WS на 1m/15m/1d + расчёт maxV + детект на closing 15m.

Изолирован от существующего Scanner: своя WS-сессия, свои подписки
(VIC_NATIVE_TFS), свой bootstrap с ограниченным горизонтом
(VIC_1M_LOOKBACK_DAYS / VIC_15M_LOOKBACK_DAYS — чтобы не фетчить 4+ года
1m свечей с HISTORY_START_DATE)."""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone

import pandas as pd
import websockets

from config import (
    SYMBOLS,
    VIC_15M_LOOKBACK_DAYS,
    VIC_1M_LOOKBACK_DAYS,
    VIC_LTF_MINUTES,
    VIC_NATIVE_TFS,
)
from data_manager import (
    fetch_klines_range,
    load_df,
    save_df,
    tf_to_ms,
    update_df_incrementally,
)
from state import (
    load_vic_level,
    log_event,
    mark_sent,
    save_last_signal,
    save_vic_level,
    was_sent,
)
from strategies.vic_evot import detect_vic_evot
from telegram_bot import broadcast_signal
from vic_levels import calculate_vic_d

BINANCE_WS_BASE = "wss://stream.binance.com:9443/stream"


def _today_utc() -> pd.Timestamp:
    today = pd.Timestamp.utcnow().normalize()
    if today.tz is None:
        today = today.tz_localize("UTC")
    return today


class VicScanner:
    # ---------------- startup ----------------

    async def startup(self) -> None:
        """Bootstrap 1m / 15m с ограниченным горизонтом + предрасчёт maxV(D-1)."""
        log_event("INFO", "vic_startup: fetching candles")
        for symbol in SYMBOLS:
            await asyncio.to_thread(
                self._bootstrap_recent, symbol, "1m", VIC_1M_LOOKBACK_DAYS,
            )
            await asyncio.to_thread(
                self._bootstrap_recent, symbol, "15m", VIC_15M_LOOKBACK_DAYS,
            )
            # 1d уже в TIMEFRAMES_NATIVE — существующий Scanner.startup догонит,
            # но дублируем здесь на случай если VicScanner стартует первым.
            await asyncio.to_thread(update_df_incrementally, symbol, "1d")
        log_event("INFO", "vic_startup: data ready")

        await asyncio.to_thread(self._prefill_vic_levels)
        log_event("INFO", "vic_startup: maxV cache filled")

    @staticmethod
    def _bootstrap_recent(symbol: str, tf: str, lookback_days: int) -> None:
        """update_df_incrementally с ограниченным начальным горизонтом.

        Если CSV пуст или последняя свеча старше горизонта — фетчим только
        последние lookback_days дней, не от HISTORY_START_DATE."""
        df = load_df(symbol, tf)
        now_ms = int(time.time() * 1000)
        step = tf_to_ms(tf)
        end_ms = (now_ms // step) * step
        horizon_start_ms = end_ms - lookback_days * 24 * 60 * 60 * 1000

        if df.empty or int(df.index[-1].timestamp() * 1000) < horizon_start_ms:
            start_ms = horizon_start_ms
        else:
            start_ms = int(df.index[-1].timestamp() * 1000) + step

        if start_ms >= end_ms:
            return

        new_rows = fetch_klines_range(symbol, tf, start_ms, end_ms)
        if new_rows.empty:
            return

        # отрезать незакрытую свечу, если попала
        last_open_ms = int(new_rows.index[-1].timestamp() * 1000)
        if last_open_ms + step > now_ms:
            new_rows = new_rows.iloc[:-1]
        if new_rows.empty:
            return

        if df.empty:
            fresh = new_rows
        else:
            fresh = pd.concat([df, new_rows])
            fresh = fresh[~fresh.index.duplicated(keep="last")].sort_index()
        save_df(fresh, symbol, tf)

    def _prefill_vic_levels(self) -> None:
        """Посчитать maxV(D-1) для каждого символа, если ещё не в кэше."""
        d_minus_1 = _today_utc() - pd.Timedelta(days=1)
        for symbol in SYMBOLS:
            if load_vic_level(symbol, d_minus_1) is not None:
                continue
            df_1m = load_df(symbol, "1m")
            if df_1m.empty:
                log_event("WARN", f"vic_prefill: пустой 1m для {symbol}")
                continue
            level = calculate_vic_d(df_1m, d_minus_1, ltf_minutes=VIC_LTF_MINUTES)
            if level is None:
                log_event("WARN", f"vic_prefill: maxV=None для {symbol} {d_minus_1.date()}")
                continue
            save_vic_level(symbol, d_minus_1, level)
            log_event("INFO", f"vic_prefill: {symbol} maxV({d_minus_1.date()})={level}")

    # ---------------- live dispatch ----------------

    def on_closed_1d(self, symbol: str) -> None:
        """Закрылась дневная свеча. Пересчитать maxV для только что закрывшегося дня."""
        d_minus_1 = _today_utc() - pd.Timedelta(days=1)
        df_1m = load_df(symbol, "1m")
        if df_1m.empty:
            log_event("WARN", f"vic_on_1d: пустой 1m для {symbol}")
            return
        level = calculate_vic_d(df_1m, d_minus_1, ltf_minutes=VIC_LTF_MINUTES)
        if level is None:
            log_event("WARN", f"vic_on_1d: maxV=None для {symbol} {d_minus_1.date()}")
            return
        save_vic_level(symbol, d_minus_1, level)
        log_event("INFO", f"vic_on_1d: {symbol} maxV({d_minus_1.date()})={level}")

    def on_closed_15m(self, symbol: str, last_15m_open_ms: int) -> None:
        """Закрылась 15m свеча — main hot path стратегии VIC_EVOT."""
        today = _today_utc()
        d_minus_1 = today - pd.Timedelta(days=1)

        vic = load_vic_level(symbol, d_minus_1)
        if vic is None:
            return  # уровень не посчитан — нечего детектить

        df_1d = load_df(symbol, "1d")
        if df_1d.empty:
            return
        # последняя дневная свеча должна быть D-1 (UTC); иначе 1d ещё не догнал WS.
        if pd.to_datetime(df_1d.index[-1], utc=True) != d_minus_1:
            return

        df_15m_full = load_df(symbol, "15m")
        if df_15m_full.empty:
            return
        df_15m_today = df_15m_full[df_15m_full.index >= today]
        if len(df_15m_today) < 5:
            return

        last_15m_open_time = pd.Timestamp(last_15m_open_ms, unit="ms", tz="UTC")
        # Контракт detect_vic_evot: df_15m.iloc[-1] == last_closed_15m.
        if pd.to_datetime(df_15m_today.index[-1], utc=True) != last_15m_open_time:
            log_event(
                "WARN",
                f"vic_on_15m: {symbol} csv_last={df_15m_today.index[-1]} "
                f"ws_last={last_15m_open_time}",
            )
            return

        sig = detect_vic_evot(df_15m_today, df_1d, vic, symbol, last_15m_open_time)
        if sig is None:
            return

        confirm_iso = sig.confirm_time.isoformat()
        # Дедуп: source_tf="1d/15m" — для ясности при ручном анализе sent_signals.
        dedup_key = f"VIC_EVOT|{symbol}|1d/15m|{sig.direction}|{confirm_iso}"
        if was_sent(dedup_key):
            return

        # sig_data["source_tf"]="15m" — для signal_inline_kb / TradingView ссылки.
        sig_data = {
            "strategy": "VIC_EVOT",
            "symbol": symbol,
            "direction": sig.direction,
            "source_tf": "15m",
            "price": float(sig.price),
            "level_price": float(sig.level.price),
            "level_day_iso": sig.level.day.isoformat(),
            "confirm_time_iso": confirm_iso,
            "confirm_type": sig.meta.get("confirm_type", "FVG-15m + LL-фрактал"),
        }

        try:
            result = broadcast_signal(sig_data)
            payload = {
                "strategy": "VIC_EVOT",
                "symbol": symbol,
                "timeframe": "15m",
                "source_tf": "1d/15m",
                "direction": sig.direction,
                "confirm_time": confirm_iso,
                "price": float(sig.price),
                "level_price": float(sig.level.price),
                "level_day": sig.level.day.isoformat(),
                "fractal_time": sig.meta.get("fractal_time"),
                "vic_level": float(sig.level.price),
                "sent_at": datetime.now(timezone.utc).isoformat(),
                "sig": sig_data,
                "broadcast_result": {
                    "ok": result.get("ok"),
                    "failed": result.get("failed"),
                    "total": result.get("total"),
                },
            }
            mark_sent(dedup_key, payload)
            save_last_signal(payload)
            log_event(
                "SIGNAL",
                f"VIC_EVOT {symbol} 1d/15m {sig.direction} "
                f"sent to {result.get('ok', 0)} users (confirm_time={confirm_iso})",
            )
        except Exception as e:
            log_event("ERROR", f"vic broadcast failed for {dedup_key}: {e!r}")

    # ---------------- websocket ----------------

    def _stream_names(self) -> list[str]:
        return [
            f"{sym.lower()}@kline_{tf}"
            for sym in SYMBOLS
            for tf in VIC_NATIVE_TFS
        ]

    async def ws_loop(self) -> None:
        streams = "/".join(self._stream_names())
        url = f"{BINANCE_WS_BASE}?streams={streams}"
        log_event("INFO", f"vic_ws_loop: {len(self._stream_names())} streams")

        while True:
            try:
                async with websockets.connect(url, ping_interval=30, ping_timeout=15) as ws:
                    log_event("INFO", "vic_ws connected")
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
                        open_ms = k.get("t")
                        if not symbol or tf not in VIC_NATIVE_TFS:
                            continue
                        try:
                            await asyncio.to_thread(update_df_incrementally, symbol, tf)
                            if tf == "1d":
                                await asyncio.to_thread(self.on_closed_1d, symbol)
                            elif tf == "15m":
                                await asyncio.to_thread(
                                    self.on_closed_15m, symbol, int(open_ms),
                                )
                            # 1m close: только обновляем CSV для следующего расчёта maxV
                        except Exception as e:
                            log_event("ERROR", f"vic on_closed {symbol} {tf}: {e!r}")
            except Exception as e:
                log_event("ERROR", f"vic_ws disconnect: {e!r}")
                await asyncio.sleep(5)
