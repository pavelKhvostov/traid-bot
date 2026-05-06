"""Live-сканер для 6 стратегий 1.1.x параллельно.

Заменяет Strategy111Scanner (single 1.1.1) на универсальный сканер
с конфигом списка стратегий. Все 6 версий слушают один WS, на каждом
1h close прогоняют каждый детектор независимо.

Конфиги (см. STRATEGIES):
  S111_SWEPT  — 1.1.1 со SWEPT-фильтром (отсекает 20% NOT-SWEPT мусора)
  S112        — 1.1.2 без SWEPT (NOT-SWEPT даёт лучше R/trade)
  S113_V1     — 1.1.3 fvg_variant=v1, macro_mode=untouched
  S113_V2     — 1.1.3 fvg_variant=v2
  S114_V1     — 1.1.4 fvg_variant=v1
  S114_V2     — 1.1.4 fvg_variant=v2

См. vault/sessions/2026-05-06-swept-cross-strategy-test.md и
vault/knowledge/decisions/swept-фильтр-применим-только-к-1-1-1.md.

Защита от старых сигналов:
  - prefill_silent помечает все сигналы из последних HISTORY_DAYS как sent
  - age-check на on_closed_1h: если age > MAX_SIGNAL_AGE_HOURS — silenced
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

import pandas as pd
import websockets

from config import SYMBOLS
from data_manager import compose_from_base, load_df, update_df_incrementally
from state import log_event, mark_sent, save_last_signal, was_sent
from strategies.strategy_1_1_1 import detect_strategy_1_1_1_signals
from strategies.strategy_1_1_2 import detect_strategy_1_1_2_signals
from strategies.strategy_1_1_3 import detect_strategy_1_1_3_signals
from strategies.strategy_1_1_4 import detect_strategy_1_1_4_signals
from telegram_bot import broadcast

BINANCE_WS_BASE = "wss://stream.binance.com:9443/stream"

# Native TFs, на которые подписываемся (composed 12h/6h/2h/20m из них).
NATIVE_TFS = ["1m", "15m", "1h", "4h", "1d"]

# Recent-window для детектора. >= max(top_tf_hours) + buffer на formation.
HISTORY_DAYS = 30

# Защита от устаревших сигналов: если signal_time старше N часов от
# текущего момента — не отправляем, помечаем как stale в дедуп.
# Уменьшено с 2h (было в Strategy111Scanner) до 1h: детектор триггерится
# на каждом 1h close, любой сигнал старше 1h = подозрительный.
MAX_SIGNAL_AGE_HOURS = 1


# ======================================================================
# Конфиг стратегий
# ======================================================================

@dataclass(frozen=True)
class StrategyConfig:
    """Конфиг одной стратегии для MultiStrategyScanner.

    name           — для дедуп-ключа в state/sent_signals.json
    detect_fn      — функция-детектор из strategies/
    detect_kwargs  — kwargs для detect_fn (fvg_variant, macro_mode)
    macro_pattern  — "FVG" или "OB" — для format_signal
    apply_swept    — применять ли SWEPT-фильтр на OB-htf
                     (по 2026-05-06 SWEPT работает только для 1.1.1)
    htf_tf_minutes — True если tf_minutes для отображения берётся из
                     ob_htf_tf (1.1.3/1.1.4), False если из fvg_tf (1.1.1/1.1.2)
    """
    name: str
    detect_fn: Callable[..., list[dict]]
    detect_kwargs: dict[str, Any] = field(default_factory=dict)
    macro_pattern: str = "FVG"
    apply_swept: bool = False
    htf_tf_minutes: bool = False


STRATEGIES: list[StrategyConfig] = [
    StrategyConfig(
        name="S111_SWEPT",
        detect_fn=detect_strategy_1_1_1_signals,
        detect_kwargs={},
        macro_pattern="FVG",
        apply_swept=True,
        htf_tf_minutes=False,
    ),
    StrategyConfig(
        name="S112",
        detect_fn=detect_strategy_1_1_2_signals,
        detect_kwargs={},
        macro_pattern="OB",
        apply_swept=False,
        htf_tf_minutes=False,
    ),
    StrategyConfig(
        name="S113_V1",
        detect_fn=detect_strategy_1_1_3_signals,
        detect_kwargs={"fvg_variant": "v1", "macro_mode": "untouched"},
        macro_pattern="OB",
        apply_swept=False,
        htf_tf_minutes=True,
    ),
    StrategyConfig(
        name="S113_V2",
        detect_fn=detect_strategy_1_1_3_signals,
        detect_kwargs={"fvg_variant": "v2", "macro_mode": "untouched"},
        macro_pattern="OB",
        apply_swept=False,
        htf_tf_minutes=True,
    ),
    StrategyConfig(
        name="S114_V1",
        detect_fn=detect_strategy_1_1_4_signals,
        detect_kwargs={"fvg_variant": "v1"},
        macro_pattern="FVG",
        apply_swept=False,
        htf_tf_minutes=True,
    ),
    StrategyConfig(
        name="S114_V2",
        detect_fn=detect_strategy_1_1_4_signals,
        detect_kwargs={"fvg_variant": "v2"},
        macro_pattern="FVG",
        apply_swept=False,
        htf_tf_minutes=True,
    ),
]


# ======================================================================
# SWEPT-чек (общий, копия из analyze_1_1_1_ob_swept.py)
# ======================================================================

def check_swept(sig: dict, df_1h: pd.DataFrame, df_2h: pd.DataFrame) -> bool | None:
    """SWEPT: OB-htf пара (c1=prev, c2=cur) против двух свечей слева.

    LONG:  min(c1.low, c2.low)   < min(prev1.low, prev2.low)
    SHORT: max(c1.high, c2.high) > max(prev1.high, prev2.high)

    Возвращает None если данных не хватает (нет prev_time/cur_time в df,
    или меньше 2 свечей до prev_idx).
    """
    df_top = df_1h if sig["ob_htf_tf"] == "1h" else df_2h
    cur_time = pd.Timestamp(sig["ob_htf_cur_time"])
    prev_time = pd.Timestamp(sig["ob_htf_prev_time"])
    if cur_time.tz is None: cur_time = cur_time.tz_localize("UTC")
    if prev_time.tz is None: prev_time = prev_time.tz_localize("UTC")
    if prev_time not in df_top.index or cur_time not in df_top.index:
        return None
    prev_idx = df_top.index.get_loc(prev_time)
    if prev_idx < 2:
        return None
    cur_idx = df_top.index.get_loc(cur_time)
    c1l = float(df_top.iloc[prev_idx]["low"])
    c2l = float(df_top.iloc[cur_idx]["low"])
    c1h = float(df_top.iloc[prev_idx]["high"])
    c2h = float(df_top.iloc[cur_idx]["high"])
    n1l = float(df_top.iloc[prev_idx - 1]["low"])
    n2l = float(df_top.iloc[prev_idx - 2]["low"])
    n1h = float(df_top.iloc[prev_idx - 1]["high"])
    n2h = float(df_top.iloc[prev_idx - 2]["high"])
    if sig["direction"] == "LONG":
        return min(c1l, c2l) < min(n1l, n2l)
    return max(c1h, c2h) > max(n1h, n2h)


# ======================================================================
# Format signal — универсальный, без кружков confluence
# ======================================================================

def format_signal(sig: dict, config: StrategyConfig) -> str:
    """Форматирует сигнал для Telegram, формат:

        BTC - LONG
        POI: Daily OB + 4h FVG
        Volume confirmation: 1h OB + 15m FVG

    Без кружков confluence (decision 2026-05-06).
    Без указания версии стратегии — все 6 выглядят одинаково
    (дедуп идёт по name, не по тексту сообщения).
    """
    symbol = sig.get("symbol", "BTCUSDT")
    sym_short = symbol.replace("USDT", "") if symbol.endswith("USDT") else symbol

    direction = sig["direction"]
    top_tf = sig.get("top_tf", "1d")
    top_label = "Daily" if top_tf == "1d" else top_tf

    # macro_tf берём в зависимости от паттерна:
    # 1.1.1, 1.1.4 → fvg_macro_tf  (macro=FVG)
    # 1.1.2, 1.1.3 → ob_macro_tf   (macro=OB)
    if config.macro_pattern == "FVG":
        macro_tf = sig.get("fvg_macro_tf") or sig.get("macro_tf", "?")
    else:  # "OB"
        macro_tf = sig.get("ob_macro_tf") or sig.get("macro_tf", "?")

    # entry_tf:
    # 1.1.1, 1.1.2 → fvg_tf (15m или 20m, младший ТФ)
    # 1.1.3, 1.1.4 → fvg_tf == ob_htf_tf (1h или 2h, тот же ТФ что OB-htf)
    htf_tf = sig["ob_htf_tf"]
    fvg_tf = sig.get("fvg_tf") or htf_tf

    return (
        f"{sym_short} - {direction}\n"
        f"POI: {top_label} OB + {macro_tf} {config.macro_pattern}\n"
        f"Volume confirmation: {htf_tf} OB + {fvg_tf} FVG"
    )


# ======================================================================
# MultiStrategyScanner
# ======================================================================

class MultiStrategyScanner:
    """Один WS, 6 параллельных детекторов на каждом 1h close.

    Каждый detect_fn запускается независимо, со своими kwargs. Сигналы
    дедуплятся по ключу включающему имя стратегии — поэтому одинаковый
    сетап от двух разных версий = два разных сообщения подписчику.
    """

    async def startup(self) -> None:
        log_event("INFO", f"multi_scanner_startup: bootstrap data, "
                          f"strategies={[s.name for s in STRATEGIES]}")
        for symbol in SYMBOLS:
            for tf in NATIVE_TFS:
                await asyncio.to_thread(update_df_incrementally, symbol, tf)
        log_event("INFO", "multi_scanner_startup: data ready")

        # Prefill silent: помечаем сигналы за последний месяц как sent
        # для каждой стратегии независимо. Иначе на первом же 1h close
        # после рестарта повалились бы все исторические сигналы.
        await asyncio.to_thread(self._prefill_silent)
        log_event("INFO", "multi_scanner_startup: prefill silent done")

    def _prefill_silent(self) -> None:
        """Помечаем ВСЕ сигналы из window каждого детектора как sent."""
        total = 0
        for symbol in SYMBOLS:
            df_pack = self._load_df_pack(symbol)
            if df_pack is None:
                continue
            for config in STRATEGIES:
                try:
                    signals = self._collect_signals(symbol, config, df_pack)
                except Exception as e:
                    log_event("WARN", f"prefill {config.name} {symbol}: {e!r}")
                    continue
                for sig in signals:
                    key = self._dedup_key(symbol, sig, config)
                    if not was_sent(key):
                        sig_time = self._sig_time_utc(sig)
                        mark_sent(key, {
                            "prefill": True,
                            "strategy": config.name,
                            "signal_time": sig_time.isoformat(),
                        })
                        total += 1
        log_event("INFO", f"prefill: marked {total} signals as sent across "
                          f"{len(STRATEGIES)} strategies")

    @staticmethod
    def _sig_time_utc(sig: dict) -> pd.Timestamp:
        sig_time = pd.Timestamp(sig["signal_time"])
        if sig_time.tz is None:
            sig_time = sig_time.tz_localize("UTC")
        return sig_time

    @staticmethod
    def _dedup_key(symbol: str, sig: dict, config: StrategyConfig) -> str:
        sig_time = MultiStrategyScanner._sig_time_utc(sig)
        entry_r = round(float(sig["entry"]), 8)
        return f"{config.name}|{symbol}|{sig['direction']}|{sig_time.isoformat()}|{entry_r}"

    def _load_df_pack(self, symbol: str) -> dict[str, pd.DataFrame] | None:
        """Загружает все нужные ТФ один раз (для всех 6 стратегий).

        Recent-window сразу применён.
        """
        df_1d = load_df(symbol, "1d")
        df_4h = load_df(symbol, "4h")
        df_1h = load_df(symbol, "1h")
        df_15m = load_df(symbol, "15m")
        df_1m = load_df(symbol, "1m")
        if any(df.empty for df in (df_1d, df_4h, df_1h, df_15m, df_1m)):
            return None

        now = pd.Timestamp.now(tz="UTC")
        cutoff = now - pd.Timedelta(days=HISTORY_DAYS + 2)
        df_1d = df_1d[df_1d.index >= cutoff]
        df_4h = df_4h[df_4h.index >= cutoff]
        df_1h = df_1h[df_1h.index >= cutoff]
        df_15m = df_15m[df_15m.index >= cutoff]
        df_1m = df_1m[df_1m.index >= cutoff]

        df_12h = compose_from_base(df_1h, "12h")
        df_6h = compose_from_base(df_1h, "6h")
        df_2h = compose_from_base(df_1h, "2h")
        df_20m = compose_from_base(df_1m, "20m")

        return {
            "1d": df_1d, "12h": df_12h, "4h": df_4h, "6h": df_6h,
            "1h": df_1h, "2h": df_2h, "15m": df_15m, "20m": df_20m, "1m": df_1m,
        }

    def _collect_signals(
        self, symbol: str, config: StrategyConfig,
        df_pack: dict[str, pd.DataFrame],
    ) -> list[dict]:
        """Detect для одной стратегии + опционально SWEPT-фильтр.

        Сигнатуры детекторов слегка различаются:
          1.1.1 / 1.1.2: (1d, 12h, 4h, 6h, 1h, 2h, 15m, 20m, **kwargs)
          1.1.3 / 1.1.4: (1d, 12h, 4h, 6h, 1h, 2h, **kwargs)  — без 15m/20m
        """
        df_1d = df_pack["1d"]
        df_12h = df_pack["12h"]
        df_4h = df_pack["4h"]
        df_6h = df_pack["6h"]
        df_1h = df_pack["1h"]
        df_2h = df_pack["2h"]

        # 1.1.1 и 1.1.2 принимают df_15m/df_20m (entry-FVG младшего ТФ).
        # 1.1.3 и 1.1.4 — только htf-уровень.
        if config.htf_tf_minutes:
            # 1.1.3 / 1.1.4 — без 15m/20m
            sigs = config.detect_fn(
                df_1d, df_12h, df_4h, df_6h, df_1h, df_2h,
                **config.detect_kwargs, verbose=False,
            )
        else:
            # 1.1.1 / 1.1.2 — с 15m/20m
            sigs = config.detect_fn(
                df_1d, df_12h, df_4h, df_6h, df_1h, df_2h,
                df_pack["15m"], df_pack["20m"],
                **config.detect_kwargs, verbose=False,
            )

        # SWEPT-фильтр (только для 1.1.1).
        if config.apply_swept:
            filtered = []
            for s in sigs:
                sw = check_swept(s, df_1h, df_2h)
                if sw:  # True
                    filtered.append(s)
            sigs = filtered

        # Добавим symbol в сигнал — нужен для format_signal.
        for s in sigs:
            s["symbol"] = symbol
        return sigs

    def on_closed_1h(self, symbol: str) -> None:
        """Триггер на закрытии 1h-свечи: прогон всех 6 стратегий."""
        # Force-update всех native TFs перед детекцией.
        # На закрытии 1h одновременно закрываются 15m и 1m.
        for tf in NATIVE_TFS:
            try:
                update_df_incrementally(symbol, tf)
            except Exception as e:
                log_event("WARN", f"force_update {symbol} {tf}: {e!r}")

        # Загружаем df-pack один раз для всех стратегий.
        df_pack = self._load_df_pack(symbol)
        if df_pack is None:
            log_event("WARN", f"on_closed_1h {symbol}: empty df pack, skip")
            return

        for config in STRATEGIES:
            try:
                signals = self._collect_signals(symbol, config, df_pack)
            except Exception as e:
                log_event("ERROR", f"detect {config.name} {symbol}: {e!r}")
                continue
            self._dispatch_signals(symbol, signals, config, df_pack)

    def _dispatch_signals(
        self, symbol: str, signals: list[dict], config: StrategyConfig,
        df_pack: dict[str, pd.DataFrame],
    ) -> None:
        """Для каждого сигнала: dedup → age-check → format → broadcast."""
        for sig in signals:
            key = self._dedup_key(symbol, sig, config)
            if was_sent(key):
                continue

            sig_time = self._sig_time_utc(sig)
            age = pd.Timestamp.now(tz="UTC") - sig_time

            # Age-check: глушим устаревшие сигналы тихо в дедуп.
            if age > pd.Timedelta(hours=MAX_SIGNAL_AGE_HOURS):
                mark_sent(key, {
                    "stale": True,
                    "strategy": config.name,
                    "signal_time": sig_time.isoformat(),
                    "age_hours": round(age.total_seconds() / 3600, 1),
                })
                log_event(
                    "INFO",
                    f"{config.name} {symbol} {sig['direction']} stale "
                    f"(age {age.total_seconds() / 3600:.1f}h) — silenced",
                )
                continue

            text = format_signal(sig, config)
            try:
                result = broadcast(text)
                payload = {
                    "strategy": config.name,
                    "symbol": symbol,
                    "direction": sig["direction"],
                    "signal_time": sig_time.isoformat(),
                    "entry": float(sig["entry"]),
                    "sl": float(sig["sl"]),
                    "ob_htf_tf": sig["ob_htf_tf"],
                    "fvg_tf": sig.get("fvg_tf") or sig["ob_htf_tf"],
                    "macro_tf": (
                        sig.get("fvg_macro_tf") or sig.get("ob_macro_tf")
                        or sig.get("macro_tf")
                    ),
                    "macro_pattern": config.macro_pattern,
                    "top_tf": sig.get("top_tf", "1d"),
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
                    f"{config.name} {symbol} {sig['direction']} "
                    f"sent to {result.get('ok', 0)} users",
                )
            except Exception as e:
                log_event("ERROR", f"broadcast {key}: {e!r}")

    # ------------------------------------------------------------------
    # WebSocket loop
    # ------------------------------------------------------------------

    def _stream_names(self) -> list[str]:
        return [f"{sym.lower()}@kline_{tf}" for sym in SYMBOLS for tf in NATIVE_TFS]

    async def ws_loop(self) -> None:
        streams = "/".join(self._stream_names())
        url = f"{BINANCE_WS_BASE}?streams={streams}"
        log_event("INFO", f"multi_scanner_ws_loop: {len(self._stream_names())} streams")

        while True:
            try:
                async with websockets.connect(
                    url, ping_interval=30, ping_timeout=15,
                ) as ws:
                    log_event("INFO", "multi_scanner_ws connected")
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
                            await asyncio.to_thread(
                                update_df_incrementally, symbol, tf,
                            )
                            # Триггер детекции — на 1h close.
                            if tf == "1h":
                                await asyncio.to_thread(self.on_closed_1h, symbol)
                        except Exception as e:
                            log_event(
                                "ERROR", f"on_closed {symbol} {tf}: {e!r}"
                            )
            except Exception as e:
                log_event("ERROR", f"multi_scanner_ws disconnect: {e!r}")
                await asyncio.sleep(5)
