"""MultiStrategyScanner — параллельный live-сканер 4 стратегий 1.1.1/1.1.2/1.1.3/1.1.4.

На каждом 1h close для каждого символа из SYMBOLS:
  1. force_update всех native TFs (1d, 4h, 1h, 15m, 1m)
  2. compose composed TFs (12h, 6h, 2h, 20m)
  3. detect_*_signals по каждой из 4 стратегий
  4. dedup через state/sent_signals.json (ключ {strategy}|{symbol}|{dir}|{time}|{entry})
  5. age-фильтр (>2h) — silenced
  6. broadcast в Telegram (общий формат, без confluence)

Параметры (по Андрея vault):
  S111: entry=0.80, sl=0.35 sym, RR=2.2 (SWEPT не применяем — он в analyze)
  S112: entry=0.70, sl=0.35 sym, RR=2.2
  S113: entry=0.70, sl=0.35 sym, RR=2.2, macro_mode=untouched
  S114: entry=0.70, sl=0.35 asym (LONG 0.35 / SHORT 0.65), RR=2.0
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

import pandas as pd

from config import HISTORY_START_DATE, SYMBOLS
from data_manager import (
    compose_from_base, fetch_full_history, load_df, update_df_incrementally,
)
from state import (
    log_event, mark_sent, was_sent,
)
from strategies.strategy_1_1_1 import detect_strategy_1_1_1_signals
from strategies.strategy_1_1_2 import detect_strategy_1_1_2_signals
from strategies.strategy_1_1_3 import detect_strategy_1_1_3_signals
from strategies.strategy_1_1_4 import detect_strategy_1_1_4_signals
from telegram_bot import broadcast

# Native TFs для WS-сканера. Composed (12h/6h/2h/20m) собираются runtime.
BINANCE_WS_BASE = "wss://stream.binance.com:9443/stream"
NATIVE_TFS = ["1d", "4h", "1h", "15m", "1m"]

# Window для детектора. Должен быть >= top_tf_hours (24h для 1d) + buffer.
HISTORY_DAYS = 60

# Старые сигналы старше N часов — silenced.
MAX_SIGNAL_AGE_HOURS = 2


@dataclass
class StrategyConfig:
    """Конфиг одной стратегии в live."""
    name: str                          # "S111", "S112", ...
    detector: Callable                 # detect_strategy_*_signals
    detector_kwargs: dict              # kwargs для детектора (macro_mode, etc)
    entry_pct: float                   # 0.70 или 0.80 inside FVG-entry
    sl_pct: float                      # 0.35 (symmetric)
    sl_asym_short: float | None        # для 1.1.4: 0.65 для SHORT, иначе None
    rr: float                          # 2.2 / 2.0

    def compute_entry_sl_tp(self, sig: dict) -> tuple[float, float, float] | None:
        """Применяем entry_pct / sl_pct поверх сигнала детектора.

        Сигнал даёт fvg_zone (entry) и ob_htf_zone (SL якорь).
        Возвращает (entry, sl, tp) или None если risk <= 0.
        """
        fvg_b, fvg_t = sig["fvg_zone"]
        ob_b, ob_t = sig["ob_htf_zone"]
        d = sig["direction"]
        if d == "LONG":
            entry = fvg_b + self.entry_pct * (fvg_t - fvg_b)
            sl = ob_b + self.sl_pct * (fvg_b - ob_b)
            if sl >= entry:
                return None
            tp = entry + self.rr * (entry - sl)
        else:
            entry = fvg_t - self.entry_pct * (fvg_t - fvg_b)
            sl_pct = self.sl_asym_short if self.sl_asym_short is not None else self.sl_pct
            sl = ob_t - sl_pct * (ob_t - fvg_t)
            if sl <= entry:
                return None
            tp = entry - self.rr * (sl - entry)
        return float(entry), float(sl), float(tp)


# Конфигурации всех 4 стратегий (по Andrew vault)
STRATEGIES: list[StrategyConfig] = [
    StrategyConfig("S111", detect_strategy_1_1_1_signals, {},
                   entry_pct=0.80, sl_pct=0.35, sl_asym_short=None, rr=2.2),
    StrategyConfig("S112", detect_strategy_1_1_2_signals, {},
                   entry_pct=0.70, sl_pct=0.35, sl_asym_short=None, rr=2.2),
    StrategyConfig("S113", detect_strategy_1_1_3_signals,
                   {"fvg_variant": "v1", "macro_mode": "untouched"},
                   entry_pct=0.70, sl_pct=0.35, sl_asym_short=None, rr=2.2),
    StrategyConfig("S114", detect_strategy_1_1_4_signals, {},
                   entry_pct=0.70, sl_pct=0.35, sl_asym_short=0.65, rr=2.0),
]


def format_signal_message(strategy: str, symbol: str, sig: dict,
                           entry: float, sl: float, tp: float) -> str:
    """Общий формат сигнала для всех 4 стратегий — без confluence."""
    sig_time = pd.Timestamp(sig["signal_time"])
    if sig_time.tz is None:
        sig_time = sig_time.tz_localize("UTC")
    msk_time = (sig_time + pd.Timedelta(hours=3)).strftime("%Y-%m-%d %H:%M")

    icon = "📈" if sig["direction"] == "LONG" else "📉"
    sym_short = symbol.replace("USDT", "")

    return (
        f"{icon} <b>{sym_short} — {sig['direction']}</b>\n"
        f"🎯 Стратегия: <b>{strategy}</b>\n"
        f"\n"
        f"💰 Вход:  <code>{entry:,.2f}</code>\n"
        f"🛑 Стоп:  <code>{sl:,.2f}</code>\n"
        f"🎯 Цель:  <code>{tp:,.2f}</code>\n"
        f"\n"
        f"📊 Время: {msk_time} МСК\n"
        f"📦 OB-htf: {sig.get('ob_htf_tf', '?')}  "
        f"FVG: {sig.get('fvg_tf', '?')}"
    )


class MultiStrategyScanner:
    """Параллельный сканер всех 4 стратегий."""

    def __init__(self):
        self.last_processed_1h: dict[str, pd.Timestamp] = {}

    async def startup(self) -> None:
        """Bootstrap истории для всех символов и TFs."""
        log_event("INFO", "MultiStrategyScanner startup")
        for symbol in SYMBOLS:
            for tf in NATIVE_TFS:
                df = load_df(symbol, tf)
                if df.empty:
                    log_event("INFO", f"bootstrap {symbol} {tf} from {HISTORY_START_DATE}")
                    fetch_full_history(symbol, tf, HISTORY_START_DATE)
        self._prefill_silent()

    def _prefill_silent(self) -> None:
        """Маркируем сегодняшние сигналы как sent (без рассылки)."""
        now = pd.Timestamp.now(tz="UTC")
        today_start = now.normalize()
        marked = 0
        for symbol in SYMBOLS:
            for cfg in STRATEGIES:
                try:
                    sigs = self._collect_for_strategy(symbol, cfg)
                except Exception as e:
                    log_event("WARN", f"prefill {cfg.name} {symbol}: {e!r}")
                    continue
                for sig in sigs:
                    sig_time = pd.Timestamp(sig["signal_time"])
                    if sig_time.tz is None:
                        sig_time = sig_time.tz_localize("UTC")
                    if sig_time < today_start:
                        continue
                    setup = cfg.compute_entry_sl_tp(sig)
                    if setup is None:
                        continue
                    entry, sl, tp = setup
                    key = self._dedup_key(cfg.name, symbol, sig, entry)
                    if not was_sent(key):
                        mark_sent(key, {
                            "prefill": True,
                            "strategy": cfg.name,
                            "signal_time": sig_time.isoformat(),
                        })
                        marked += 1
        log_event("INFO", f"prefill_silent: {marked} signals marked")

    @staticmethod
    def _dedup_key(strategy: str, symbol: str, sig: dict, entry: float) -> str:
        sig_time = pd.Timestamp(sig["signal_time"])
        if sig_time.tz is None:
            sig_time = sig_time.tz_localize("UTC")
        entry_r = round(entry, 2)
        return f"{strategy}|{symbol}|{sig['direction']}|{sig_time.isoformat()}|{entry_r}"

    def _load_data(self, symbol: str):
        """Загружает все TFs нужные для всех 4 стратегий."""
        df_1d = load_df(symbol, "1d")
        df_4h = load_df(symbol, "4h")
        df_1h = load_df(symbol, "1h")
        df_15m = load_df(symbol, "15m")
        df_1m = load_df(symbol, "1m")
        if any(df.empty for df in (df_1d, df_4h, df_1h, df_15m, df_1m)):
            return None

        # Recent window для performance
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

        return {
            "1d": df_1d, "12h": df_12h, "4h": df_4h, "6h": df_6h,
            "1h": df_1h, "2h": df_2h, "15m": df_15m, "20m": df_20m,
        }

    def _collect_for_strategy(self, symbol: str, cfg: StrategyConfig) -> list[dict]:
        """Вызов детектора одной стратегии с правильным kwargs."""
        data = self._load_data(symbol)
        if data is None:
            return []

        # Все 4 стратегии принимают одинаковый набор df: 1d, 12h, 4h, 6h, 1h, 2h, 15m, 20m
        # (детектор 1.1.3 не использует 15m/20m, но игнорирует их без ошибки).
        if cfg.name == "S113":
            # 1.1.3 принимает df_1d, df_12h, df_4h, df_6h, df_1h, df_2h (без 15m/20m)
            return cfg.detector(
                data["1d"], data["12h"], data["4h"], data["6h"],
                data["1h"], data["2h"],
                verbose=False, **cfg.detector_kwargs,
            )
        return cfg.detector(
            data["1d"], data["12h"], data["4h"], data["6h"],
            data["1h"], data["2h"], data["15m"], data["20m"],
            verbose=False, **cfg.detector_kwargs,
        )

    def on_closed_1h(self, symbol: str) -> None:
        """Главный handler — на каждом 1h close."""
        # Force-update всех native TFs (WS не гарантирует порядок доставки)
        for tf in NATIVE_TFS:
            try:
                update_df_incrementally(symbol, tf)
            except Exception as e:
                log_event("WARN", f"force_update {symbol} {tf}: {e!r}")

        for cfg in STRATEGIES:
            try:
                signals = self._collect_for_strategy(symbol, cfg)
            except Exception as e:
                log_event("ERROR", f"{cfg.name} detect {symbol}: {e!r}")
                continue

            for sig in signals:
                setup = cfg.compute_entry_sl_tp(sig)
                if setup is None:
                    continue
                entry, sl, tp = setup

                key = self._dedup_key(cfg.name, symbol, sig, entry)
                if was_sent(key):
                    continue

                sig_time = pd.Timestamp(sig["signal_time"])
                if sig_time.tz is None:
                    sig_time = sig_time.tz_localize("UTC")

                # Age-filter
                age = pd.Timestamp.now(tz="UTC") - sig_time
                if age > pd.Timedelta(hours=MAX_SIGNAL_AGE_HOURS):
                    mark_sent(key, {
                        "stale": True,
                        "strategy": cfg.name,
                        "signal_time": sig_time.isoformat(),
                        "age_hours": round(age.total_seconds() / 3600, 1),
                    })
                    log_event(
                        "INFO",
                        f"{cfg.name} {symbol} {sig['direction']} stale "
                        f"(age {age.total_seconds() / 3600:.1f}h) — silenced",
                    )
                    continue

                text = format_signal_message(cfg.name, symbol, sig, entry, sl, tp)
                try:
                    broadcast(text)
                    mark_sent(key, {
                        "strategy": cfg.name,
                        "symbol": symbol,
                        "direction": sig["direction"],
                        "signal_time": sig_time.isoformat(),
                        "entry": entry,
                        "sl": sl,
                        "tp": tp,
                        "sent_at": datetime.now(timezone.utc).isoformat(),
                    })
                    log_event("INFO", f"{cfg.name} {symbol} {sig['direction']} sent")
                except Exception as e:
                    log_event("ERROR", f"{cfg.name} broadcast {symbol}: {e!r}")

    async def ws_loop(self) -> None:
        """Подписка на Binance WebSocket для всех символов и TFs.

        Паттерн идентичный Strategy111Scanner.ws_loop:
        - update_df_incrementally на закрытии candle
        - триггер on_closed_1h только для tf="1h"
        """
        import websockets

        streams = "/".join(
            f"{sym.lower()}@kline_{tf}"
            for sym in SYMBOLS
            for tf in NATIVE_TFS
        )
        url = f"{BINANCE_WS_BASE}?streams={streams}"
        log_event("INFO", f"MultiStrategyScanner WS subscribe ({len(SYMBOLS) * len(NATIVE_TFS)} streams)")

        while True:
            try:
                async with websockets.connect(url, ping_interval=30, ping_timeout=15) as ws:
                    log_event("INFO", "MultiStrategyScanner WS connected")
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
                            # Триггер детекции на 1h close (покрывает 1h
                            # и composed 2h случаи)
                            if tf == "1h":
                                await asyncio.to_thread(self.on_closed_1h, symbol)
                        except Exception as e:
                            log_event(
                                "ERROR",
                                f"MultiScanner on_closed {symbol} {tf}: {e!r}",
                            )
            except Exception as e:
                log_event("ERROR", f"MultiScanner WS disconnect: {e!r}")
                await asyncio.sleep(5)
