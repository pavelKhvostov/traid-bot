"""Общие примитивы: Signal, Zone, дедуп-ключи, форматирование."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

ASSET_ICONS = {
    "BTCUSDT": "₿",
    "ETHUSDT": "Ξ",
    "SOLUSDT": "◎",
}

STRATEGY_ICONS = {
    "OBX4": "⚡",
    "FVG": "〰️",
    "OB_HTF": "📦",
    "RDRB": "↩️",
    "FRACTAL": "❄️",
    "MARUBOZU": "🟩",
    "HAMMER": "🔨",
    "VIC_EVOT": "🎯",
}

DIRECTION_EMOJI = {
    "LONG": "📈",
    "SHORT": "📉",
}

TF_TO_TV = {
    "1h": "60", "2h": "120", "3h": "180", "4h": "240",
    "6h": "360", "8h": "480", "12h": "720",
    "1d": "D", "2d": "2D", "3d": "3D",
}


@dataclass
class Signal:
    strategy: str
    symbol: str
    timeframe: str
    direction: str
    confirm_time: pd.Timestamp
    price: float
    meta: dict = field(default_factory=dict)
    zone: "Zone | None" = None
    level: "Level | None" = None


@dataclass
class Zone:
    strategy: str
    symbol: str
    source_tf: str
    direction: str
    zone_bottom: float
    zone_top: float
    trigger_time: pd.Timestamp
    meta: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Level:
    price: float
    day: pd.Timestamp
    source: str = "VIC"


def signal_key(s: Signal) -> str:
    return f"{s.strategy}|{s.symbol}|{s.timeframe}|{s.direction}|{s.confirm_time.isoformat()}"


def zone_key(z: Zone) -> str:
    return f"{z.strategy}|{z.symbol}|{z.source_tf}|{z.direction}|{z.trigger_time.isoformat()}"


def tradingview_url(symbol: str, tf: str) -> str:
    interval = TF_TO_TV.get(tf, "240")
    return f"https://www.tradingview.com/chart/?symbol=BINANCE:{symbol}&interval={interval}"


def _fmt_price(x: float) -> str:
    v = float(x)
    s = f"{v:.2f}" if abs(v) >= 1000 else f"{v:.4f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def _fmt_confirm(iso_or_ts) -> str:
    if isinstance(iso_or_ts, str):
        try:
            dt = datetime.fromisoformat(iso_or_ts)
        except ValueError:
            return iso_or_ts
    else:
        try:
            dt = pd.to_datetime(iso_or_ts, utc=True).to_pydatetime()
        except Exception:
            return str(iso_or_ts)
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def _render(
    strategy: str, symbol: str, direction: str, source_tf: str,
    price: float,
    zone_bottom: float | None = None, zone_top: float | None = None,
    level_price: float | None = None, level_day: pd.Timestamp | None = None,
    confirm_iso_or_ts=None,
    confirm_type: str = "OB-1h",
) -> str:
    asset_icon = ASSET_ICONS.get(symbol, "")
    strat_icon = STRATEGY_ICONS.get(strategy, "•")
    dir_icon = DIRECTION_EMOJI.get(direction, "")
    confirm_str = _fmt_confirm(confirm_iso_or_ts)

    price_s = _fmt_price(price)

    if level_price is not None:
        # Level-режим: одна горизонтальная цена вместо диапазона зоны.
        lp_s = _fmt_price(level_price)
        labels = ["Вход:", "Уровень:", "Время:"]
        vals = [price_s, lp_s, confirm_str]
        day_str = pd.Timestamp(level_day).strftime("%Y-%m-%d") if level_day is not None else ""
        head2 = f"{dir_icon} <b>{direction}</b> · уровень maxV({day_str})"
    else:
        zb_s = _fmt_price(zone_bottom)
        zt_s = _fmt_price(zone_top)
        labels = ["Вход:", "Зона:", "Время:"]
        vals = [price_s, f"{zb_s} – {zt_s}", confirm_str]
        head2 = f"{dir_icon} <b>{direction}</b> · зона {source_tf}"

    width = max(len(lb) for lb in labels)
    code_lines = [f"{lb:<{width}} {v}" for lb, v in zip(labels, vals)]
    code_block = "<code>" + "\n".join(code_lines) + "</code>"

    head1_left = f"{asset_icon} <b>{symbol}</b>".lstrip()
    head1 = f"{head1_left} · {strat_icon} <b>{strategy}</b>"
    head3 = f"Подтверждение: <b>{confirm_type}</b>"

    return "\n".join([head1, head2, head3, "", code_block])


def format_signal_telegram(s: Signal) -> str:
    m = s.meta or {}
    source_tf = m.get("source_tf") or s.timeframe

    if s.level is not None:
        return _render(
            strategy=s.strategy,
            symbol=s.symbol,
            direction=s.direction,
            source_tf=source_tf,
            price=float(s.price),
            level_price=float(s.level.price),
            level_day=s.level.day,
            confirm_iso_or_ts=s.confirm_time,
            confirm_type=m.get("confirm_type", "FVG-15m + LL-фрактал"),
        )

    zb = m.get("zone_bottom")
    zt = m.get("zone_top")
    return _render(
        strategy=s.strategy,
        symbol=s.symbol,
        direction=s.direction,
        source_tf=source_tf,
        price=float(s.price),
        zone_bottom=float(zb) if zb is not None else float(s.price),
        zone_top=float(zt) if zt is not None else float(s.price),
        confirm_iso_or_ts=s.confirm_time,
        confirm_type=m.get("confirm_type", "OB-1h"),
    )


def render_signal_from_dict(sig: dict) -> str:
    if sig.get("level_price") is not None:
        level_day_iso = sig.get("level_day_iso")
        level_day = pd.to_datetime(level_day_iso, utc=True) if level_day_iso else None
        return _render(
            strategy=sig["strategy"],
            symbol=sig["symbol"],
            direction=sig["direction"],
            source_tf=sig.get("source_tf") or sig.get("timeframe", ""),
            price=float(sig["price"]),
            level_price=float(sig["level_price"]),
            level_day=level_day,
            confirm_iso_or_ts=sig["confirm_time_iso"],
            confirm_type=sig.get("confirm_type", "FVG-15m + LL-фрактал"),
        )
    return _render(
        strategy=sig["strategy"],
        symbol=sig["symbol"],
        direction=sig["direction"],
        source_tf=sig.get("source_tf") or sig.get("timeframe", ""),
        price=float(sig["price"]),
        zone_bottom=float(sig["zone_bottom"]),
        zone_top=float(sig["zone_top"]),
        confirm_iso_or_ts=sig["confirm_time_iso"],
        confirm_type=sig.get("confirm_type", "OB-1h"),
    )
