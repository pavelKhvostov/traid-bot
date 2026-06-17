"""Confluence-проверка для Strategy 1.1.1 на BTC.

При срабатывании 1.1.1 на BTC проверяем — есть ли независимый 1.1.1-сетап
на BTC1! (CME futures), TOTALES, USDT.D в окне ±N часов.

Правила направления:
  - BTC1! (CME)  : same direction (BTC LONG → BTC1 LONG)
  - TOTALES      : same direction (рост рынка ↔ рост капитализации)
  - USDT.D       : mirror direction (BTC LONG → USDT.D SHORT, т.к. USDT
                   доминирование зеркально движению крипты)

Данные для confluence-источников лежат в data/<SYM>_<TF>.csv и обновляются
скриптом fetch_tv_data.py (вручную или по cron).

Ограничения:
  - У USDT.D / TOTALES / BTC1 нет 1m, поэтому 20m FVG отсутствует. Используется
    только 15m entry FVG.
  - Глубина 15m у CRYPTOCAP-тикеров ограничена TV (~17-52 дня), но для live
    проверки текущего сигнала это достаточно — нужна свежая history.
"""
from __future__ import annotations

import pandas as pd

from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_1 import detect_strategy_1_1_1_signals

# Источники confluence: (symbol_in_data_dir, "same"|"mirror", display_label)
CONFLUENCE_SOURCES = [
    ("BTC1",    "same",   "BTC1!"),
    ("TOTALES", "same",   "TOTALES"),
    ("USDT_D",  "mirror", "USDT.D"),
]

# Окно ±N часов вокруг BTC signal_time для матча.
SYNC_WINDOW_HOURS = 24


def _empty_ohlc() -> pd.DataFrame:
    df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df.index = pd.DatetimeIndex([], tz="UTC", name="open_time")
    return df


def _detect_signals_for(symbol: str) -> list[dict]:
    """Прогон 1.1.1-детектора на confluence-источнике (без 1m → без 20m)."""
    df_1d = load_df(symbol, "1d")
    df_4h = load_df(symbol, "4h")
    df_1h = load_df(symbol, "1h")
    df_15m = load_df(symbol, "15m")
    if any(df.empty for df in (df_1d, df_4h, df_1h, df_15m)):
        return []
    df_12h = compose_from_base(df_1h, "12h")
    df_6h = compose_from_base(df_1h, "6h")
    df_2h = compose_from_base(df_1h, "2h")
    df_20m = _empty_ohlc()  # нет 1m для CRYPTOCAP/CME → 20m недоступна
    return detect_strategy_1_1_1_signals(
        df_1d, df_12h, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m,
        verbose=False,
    )


def check_confluence(
    btc_signal_time: pd.Timestamp,
    btc_direction: str,
    window_hours: int = SYNC_WINDOW_HOURS,
) -> dict:
    """Проверка confluence — возвращает dict с матчами.

    Returns:
        {
            "matches": ["BTC1!", "TOTALES"],   # список совпавших источников
            "count": 2,                         # 0-3
            "details": {                        # отладка
                "BTC1": {"matched": True, "target_direction": "LONG", "found_at": <ts>},
                "TOTALES": {...},
                "USDT.D": {"matched": False, ...},
            }
        }
    """
    btc_t = btc_signal_time
    if btc_t.tz is None:
        btc_t = btc_t.tz_localize("UTC")
    win = pd.Timedelta(hours=window_hours)

    matches: list[str] = []
    details: dict = {}

    for symbol, mode, label in CONFLUENCE_SOURCES:
        target_dir = (
            btc_direction if mode == "same"
            else ("SHORT" if btc_direction == "LONG" else "LONG")
        )
        try:
            sigs = _detect_signals_for(symbol)
        except Exception as e:
            details[label] = {"matched": False, "error": repr(e)}
            continue

        found_at = None
        for s in sigs:
            if s["direction"] != target_dir:
                continue
            t = pd.Timestamp(s["signal_time"])
            if t.tz is None:
                t = t.tz_localize("UTC")
            if abs(t - btc_t) <= win:
                found_at = t
                break

        details[label] = {
            "matched": found_at is not None,
            "target_direction": target_dir,
            "found_at": found_at.isoformat() if found_at is not None else None,
        }
        if found_at is not None:
            matches.append(label)

    return {
        "matches": matches,
        "count": len(matches),
        "details": details,
    }


def format_signal_message(symbol: str, sig: dict, confluence: dict) -> str:
    """Формирует Telegram-сообщение для BTC-сигнала с confluence.

    Формат:
        BTC - LONG 🟢🟢🟢
        POI: Daily OB + 4h FVG
        Volume confirmation: 2h OB + 20m FVG
    """
    # Strip USDT suffix для отображения: BTCUSDT → BTC
    sym_short = symbol.replace("USDT", "") if symbol.endswith("USDT") else symbol

    color = "🟢" if sig["direction"] == "LONG" else "🔴"
    circles = color * confluence["count"]

    # Маппинг top_tf для отображения
    top_tf = sig.get("top_tf", "1d")
    top_label = "Daily" if top_tf == "1d" else top_tf  # "12h" остаётся как есть

    msg = (
        f"{sym_short} - {sig['direction']} {circles}\n"
        f"POI: {top_label} OB + {sig['fvg_macro_tf']} FVG\n"
        f"Volume confirmation: {sig['ob_htf_tf']} OB + {sig['fvg_tf']} FVG"
    )

    # Авто-контекст рынка (тип дня + confluence + зоны/цели/магниты).
    # Изолирован try/except внутри build_context — сбой → пустая строка,
    # сам сигнал не страдает. См. signal_context.py.
    try:
        from signal_context import build_context
        ctx = build_context(symbol, sig)
        if ctx:
            msg = msg + "\n" + ctx
    except Exception:
        pass

    return msg
