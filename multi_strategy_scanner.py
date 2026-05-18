"""Общий live-сканер для Strategy 1.1.2, 1.1.3, 1.1.6.

Параметризован через detector function. Без confluence (это 1.1.1-only).
Триггер: закрытие 1h свечи на BTCUSDT. На каждом 1h close:
  1. Обновляем native CSV (1m, 15m, 1h, 4h, 1d).
  2. Composes 12h, 6h, 2h, 20m.
  3. Запускаем detector_fn на recent window.
  4. Каждый новый сигнал (через dedup) → broadcast.

Формат signal dict (требуется от detector_fn):
  signal_time, direction (LONG/SHORT), entry, sl, ob_htf_tf, fvg_tf,
  top_tf, fvg_zone, ob_htf_zone
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Callable

import pandas as pd
import websockets

from config import SYMBOLS
from data_manager import compose_from_base, load_df, update_df_incrementally
from state import log_event, mark_sent, save_last_signal, was_sent
from telegram_bot import broadcast

BINANCE_WS_BASE = "wss://stream.binance.com:9443/stream"
NATIVE_TFS = ["1m", "15m", "1h", "4h", "1d"]
HISTORY_DAYS = 30

# Минуты в каждом entry TF — для расчёта c2_close = c2_open + tf_minutes.
FVG_TF_MINUTES = {"15m": 15, "20m": 20, "1h": 60, "2h": 120}


# Detector_fn должен принимать: df_1d, df_12h, df_4h, df_6h, df_1h, df_2h,
# df_15m (опц), df_20m (опц) — и возвращать list[dict] сигналов.

class MultiStrategyScanner:
    """Параметризованный live-сканер.

    Args:
        strategy_id: короткий ID (e.g., "S112", "S113", "S116") — для дедуп-ключа и лог-префикса.
        strategy_name: человекочитаемое имя (e.g., "1.1.2", "1.1.3", "1.1.6").
        detector_fn: callable(df_1d, df_12h, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m, **opts) -> list[dict]
        needs_ltf: если True — передаём df_15m, df_20m в detector_fn (для 1.1.2, нужны).
                   Для 1.1.3, 1.1.6 — False (entry FVG того же ТФ что OB-htf).
        detector_kwargs: дополнительные опции в detector_fn (например fvg_variant="v1").
    """

    def __init__(self, *, strategy_id: str, strategy_name: str,
                  detector_fn: Callable, needs_ltf: bool = True,
                  detector_kwargs: dict | None = None,
                  entry_pct: float = 0.70, sl_pct: float = 0.35,
                  rr: float = 2.2):
        self.sid = strategy_id
        self.name = strategy_name
        self.detector = detector_fn
        self.needs_ltf = needs_ltf
        self.kwargs = detector_kwargs or {}
        # Утверждённые торговые параметры (entry/SL/TP в сообщении).
        # SL формула: между OB-htf edge и FVG entry edge (1.1.2/1.1.3/1.1.6 spec).
        self.entry_pct = entry_pct
        self.sl_pct = sl_pct
        self.rr = rr

    def apply_user_params(self, sig: dict) -> dict:
        """Пересчитывает entry/sl/tp по утверждённым параметрам.

        Формула:
          entry_LONG = fvg_b + entry_pct * (fvg_t - fvg_b)
          sl_LONG    = obh_b + sl_pct    * (fvg_b - obh_b)
          entry_SHORT= fvg_t - entry_pct * (fvg_t - fvg_b)
          sl_SHORT   = obh_t - sl_pct    * (obh_t - fvg_t)
          tp = entry +/- rr * |entry - sl|
        """
        fvg_b, fvg_t = sig["fvg_zone"]
        obh_b, obh_t = sig["ob_htf_zone"]
        direction = sig["direction"]
        fw = fvg_t - fvg_b
        if direction == "LONG":
            entry = fvg_b + self.entry_pct * fw
            sl = obh_b + self.sl_pct * (fvg_b - obh_b)
            if sl >= entry:
                return None
            risk = entry - sl
            tp = entry + self.rr * risk
        else:
            entry = fvg_t - self.entry_pct * fw
            sl = obh_t - self.sl_pct * (obh_t - fvg_t)
            if sl <= entry:
                return None
            risk = sl - entry
            tp = entry - self.rr * risk
        sig = dict(sig)  # don't mutate input
        sig["entry"] = float(entry)
        sig["sl"] = float(sl)
        sig["tp"] = float(tp)
        sig["risk"] = float(risk)
        return sig

    async def startup(self) -> None:
        log_event("INFO", f"{self.sid}_startup: bootstrap data")
        for symbol in SYMBOLS:
            for tf in NATIVE_TFS:
                await asyncio.to_thread(update_df_incrementally, symbol, tf)
        log_event("INFO", f"{self.sid}_startup: data ready")
        await asyncio.to_thread(self._prefill_silent)
        log_event("INFO", f"{self.sid}_startup: prefill silent done")

    def _prefill_silent(self) -> None:
        for symbol in SYMBOLS:
            try:
                signals = self._collect_signals(symbol)
            except Exception as e:
                log_event("WARN", f"{self.sid}_prefill {symbol}: {e!r}")
                continue
            for sig in signals:
                key = self._dedup_key(symbol, sig)
                if not was_sent(key):
                    sig_time = pd.Timestamp(sig["signal_time"])
                    if sig_time.tz is None:
                        sig_time = sig_time.tz_localize("UTC")
                    mark_sent(key, {"prefill": True, "signal_time": sig_time.isoformat()})

    def _dedup_key(self, symbol: str, sig: dict) -> str:
        sig_time = pd.Timestamp(sig["signal_time"])
        if sig_time.tz is None:
            sig_time = sig_time.tz_localize("UTC")
        entry_r = round(float(sig["entry"]), 8)
        return f"{self.sid}|{symbol}|{sig['direction']}|{sig_time.isoformat()}|{entry_r}"

    def _collect_signals(self, symbol: str) -> list[dict]:
        df_1d = load_df(symbol, "1d")
        df_4h = load_df(symbol, "4h")
        df_1h = load_df(symbol, "1h")
        if any(df.empty for df in (df_1d, df_4h, df_1h)):
            return []

        now = pd.Timestamp.now(tz="UTC")
        cutoff = now - pd.Timedelta(days=HISTORY_DAYS + 2)
        df_1d = df_1d[df_1d.index >= cutoff]
        df_4h = df_4h[df_4h.index >= cutoff]
        df_1h = df_1h[df_1h.index >= cutoff]

        df_12h = compose_from_base(df_1h, "12h")
        df_6h = compose_from_base(df_1h, "6h")
        df_2h = compose_from_base(df_1h, "2h")

        if self.needs_ltf:
            df_15m = load_df(symbol, "15m")
            df_1m = load_df(symbol, "1m")
            if df_15m.empty or df_1m.empty:
                return []
            df_15m = df_15m[df_15m.index >= cutoff]
            df_1m = df_1m[df_1m.index >= cutoff]
            df_20m = compose_from_base(df_1m, "20m")
            return self.detector(
                df_1d, df_12h, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m,
                verbose=False, **self.kwargs,
            )
        else:
            return self.detector(
                df_1d, df_12h, df_4h, df_6h, df_1h, df_2h,
                verbose=False, **self.kwargs,
            )

    def _format_message(self, symbol: str, sig: dict) -> str:
        """Простое сообщение без confluence. sig уже после apply_user_params."""
        sig_time = pd.Timestamp(sig["signal_time"])
        if sig_time.tz is None:
            sig_time = sig_time.tz_localize("UTC")
        dir_icon = "📈" if sig["direction"] == "LONG" else "📉"
        fvg_b, fvg_t = sig["fvg_zone"]
        tp = sig.get("tp")
        risk_pct = abs(sig["entry"] - sig["sl"]) / sig["entry"] * 100
        return (
            f"₿ <b>{symbol}</b> · 🔬 Strategy <b>{self.name}</b>\n"
            f"{dir_icon} <b>{sig['direction']}</b> · "
            f"{sig.get('top_tf', '?')} → {sig.get('ob_htf_tf', '?')} → "
            f"FVG-{sig.get('fvg_tf', '?')}\n"
            f"\n"
            f"Вход:    <b>{float(sig['entry']):.2f}</b>\n"
            f"SL:      <b>{float(sig['sl']):.2f}</b> ({risk_pct:.2f}%)\n"
            + (f"TP:      <b>{float(tp):.2f}</b> (RR={self.rr})\n" if tp else "")
            + f"FVG:     {fvg_b:.2f} – {fvg_t:.2f}\n"
            f"Время:   {sig_time.strftime('%Y-%m-%d %H:%M')} UTC"
        )

    def on_closed_1h(self, symbol: str) -> None:
        for tf in NATIVE_TFS:
            try:
                update_df_incrementally(symbol, tf)
            except Exception as e:
                log_event("WARN", f"{self.sid} force_update {symbol} {tf}: {e!r}")

        try:
            signals = self._collect_signals(symbol)
        except Exception as e:
            log_event("ERROR", f"{self.sid} detect {symbol}: {e!r}")
            return

        # Фильтр "current hour only": сигнал считается актуальным только если
        # его entry FVG c2 закрылся в текущем 1h окне.
        # c2_close = c2_open + tf_duration; current_hour_close = now.floor('h').
        # Окно валидности: (current_hour_close - 1h, current_hour_close].
        current_hour_close = pd.Timestamp.now(tz="UTC").floor("h")
        prev_hour_close = current_hour_close - pd.Timedelta(hours=1)

        for sig in signals:
            key = self._dedup_key(symbol, sig)
            if was_sent(key):
                continue

            sig_time = pd.Timestamp(sig["signal_time"])
            if sig_time.tz is None:
                sig_time = sig_time.tz_localize("UTC")

            # Вычисляем c2_close сигнала (момент когда entry FVG стал актуален).
            fvg_tf = sig.get("fvg_tf", "15m")
            tf_min = FVG_TF_MINUTES.get(fvg_tf, 15)
            signal_close = sig_time + pd.Timedelta(minutes=tf_min)

            # Проверяем что c2_close попадает в текущий 1h-час.
            if not (prev_hour_close < signal_close <= current_hour_close):
                mark_sent(key, {
                    "stale_outside_current_hour": True,
                    "signal_time": sig_time.isoformat(),
                    "signal_close": signal_close.isoformat(),
                    "current_hour_close": current_hour_close.isoformat(),
                })
                log_event("INFO",
                    f"{self.sid} {symbol} {sig['direction']} "
                    f"c2_close={signal_close.strftime('%Y-%m-%d %H:%M')} "
                    f"not in current hour ({prev_hour_close.strftime('%H:%M')}, "
                    f"{current_hour_close.strftime('%H:%M')}] — silenced")
                continue

            # Применяем утверждённые торговые параметры (entry/SL/TP).
            sig = self.apply_user_params(sig)
            if sig is None:
                log_event("WARN", f"{self.sid} {symbol} {key} invalid SL/TP geom — skipped")
                mark_sent(key, {"invalid_geom": True})
                continue

            text = self._format_message(symbol, sig)
            try:
                result = broadcast(text)
                payload = {
                    "strategy": self.sid,
                    "strategy_name": self.name,
                    "symbol": symbol,
                    "direction": sig["direction"],
                    "signal_time": sig_time.isoformat(),
                    "entry": float(sig["entry"]),
                    "sl": float(sig["sl"]),
                    "tp": float(sig.get("tp", 0.0)),
                    "rr": float(self.rr),
                    "ob_htf_tf": sig.get("ob_htf_tf"),
                    "fvg_tf": sig.get("fvg_tf"),
                    "top_tf": sig.get("top_tf"),
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
                    f"{self.sid} {symbol} {sig['direction']} "
                    f"sent to {result.get('ok', 0)} users",
                )
            except Exception as e:
                log_event("ERROR", f"{self.sid} broadcast {key}: {e!r}")

    def _stream_names(self) -> list[str]:
        return [f"{sym.lower()}@kline_{tf}" for sym in SYMBOLS for tf in NATIVE_TFS]

    async def ws_loop(self) -> None:
        streams = "/".join(self._stream_names())
        url = f"{BINANCE_WS_BASE}?streams={streams}"
        log_event("INFO", f"{self.sid}_ws_loop: {len(self._stream_names())} streams")

        while True:
            try:
                async with websockets.connect(url, ping_interval=30, ping_timeout=15) as ws:
                    log_event("INFO", f"{self.sid}_ws connected")
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
                            if tf == "1h":
                                await asyncio.to_thread(self.on_closed_1h, symbol)
                        except Exception as e:
                            log_event("ERROR", f"{self.sid} on_closed {symbol} {tf}: {e!r}")
            except Exception as e:
                log_event("ERROR", f"{self.sid}_ws disconnect: {e!r}")
                await asyncio.sleep(5)
