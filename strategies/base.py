"""Общие примитивы: Signal, Zone, дедуп-ключи, форматирование."""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

STRATEGY_ICONS = {
    "OBX4": "⚡",
    "OB_HTF": "🟣",
    "FVG": "🎯",
    "FRACTAL": "🔱",
    "RDRB": "⚪",
}

DIRECTION_EMOJI = {
    "LONG": "🟢",
    "SHORT": "🔴",
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


def signal_key(s: Signal) -> str:
    return f"{s.strategy}|{s.symbol}|{s.timeframe}|{s.direction}|{s.confirm_time.isoformat()}"


def zone_key(z: Zone) -> str:
    return f"{z.strategy}|{z.symbol}|{z.source_tf}|{z.direction}|{z.trigger_time.isoformat()}"


def format_signal_telegram(s: Signal) -> str:
    icon = STRATEGY_ICONS.get(s.strategy, "•")
    demoji = DIRECTION_EMOJI.get(s.direction, "")
    confirm_str = s.confirm_time.strftime("%Y-%m-%d %H:%M UTC")
    m = s.meta or {}

    # Общий формат для сигналов, прошедших через ob1h-ядро
    # (meta содержит source_tf + zone_bottom + zone_top).
    if "zone_bottom" in m and "zone_top" in m and "source_tf" in m:
        return "\n".join([
            f"{icon} <b>{s.strategy}</b> — <b>{s.symbol}</b> (зона {m['source_tf']})",
            f"{demoji} <b>{s.direction}</b>",
            f"Зона: {float(m['zone_bottom']):.4f} – {float(m['zone_top']):.4f}",
            f"OB 1h закрылся: {confirm_str}",
            f"Цена входа: {s.price}",
        ])

    # Fallback (старый формат / OBX4-detail на сырой зоне).
    lines = [
        f"{icon} <b>{s.strategy}</b> — <b>{s.symbol}</b> ({s.timeframe})",
        f"{demoji} <b>{s.direction}</b>",
        f"Время подтверждения: {confirm_str}",
        f"Цена: {s.price}",
    ]
    if s.strategy == "OBX4":
        if "ob_top" in m and "ob_bottom" in m:
            lines.append(f"Зона OB: {float(m['ob_bottom']):.4f} – {float(m['ob_top']):.4f}")
        if "fvg_top" in m and "fvg_bottom" in m:
            lines.append(f"FVG: {float(m['fvg_bottom']):.4f} – {float(m['fvg_top']):.4f}")
    return "\n".join(lines)
