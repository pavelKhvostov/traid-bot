import asyncio
import json
import os
from pathlib import Path
from typing import Dict, Tuple

import pandas as pd
import requests
import websockets

from datetime import datetime, timedelta


# =========================================================
# CONFIG
# =========================================================
SUBS_FILE = "subscriptions.json"
LAST_SIGNAL_FILE = "last_signal.json"

ADMIN_IDS = [
    901107007  # твой telegram chat_id
]

USERS_FILE = "users.json"


def load_subscriptions():
    if not os.path.exists(SUBS_FILE):
        return {}
    return json.load(open(SUBS_FILE))


def save_subscriptions(subs):
    json.dump(subs, open(SUBS_FILE, "w"), indent=2)


def load_users():
    if not os.path.exists(USERS_FILE):
        return []
    return json.load(open(USERS_FILE))


def save_users(users):
    json.dump(users, open(USERS_FILE, "w"), indent=2)


def save_last_signal(signal):
    json.dump(signal, open(LAST_SIGNAL_FILE, "w"), indent=2)


def load_last_signal():
    if not os.path.exists(LAST_SIGNAL_FILE):
        return None
    return json.load(open(LAST_SIGNAL_FILE))

BINANCE_REST_BASE = "https://api.binance.com"
BINANCE_WS_BASE = "wss://stream.binance.com:9443/stream"

# Telegram
# Можно оставить так и задать через переменные окружения:
# set TELEGRAM_BOT_TOKEN=...
# set TELEGRAM_CHAT_ID=...
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "replace_me_with_real_bot_token")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "@ASVK_Power_Zone")
# Для публичного канала можно использовать username канала вида @ASVK_Power_Zone,
# если бот добавлен туда админом.
# Для приватного канала лучше использовать chat_id вида -1001234567890

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

# Целевые таймфреймы
TARGET_TFS = ["1h", "2h", "3h", "4h", "6h", "8h", "12h", "1d", "2d", "3d"]

# Нативные спот-ТФ Binance
NATIVE_TFS = ["1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d"]

# Составные ТФ
COMPOSED_TFS = {
    "3h": {"base_tf": "1h"},
    "2d": {"base_tf": "1d"},
}

DATA_DIR = Path("./data_obx4")
STATE_DIR = Path("./state_obx4")

REST_TIMEOUT = 20
BOOTSTRAP_LIMIT = 500
# Сколько свечей максимум храним в одном CSV.
# 100 000 покрывает ~11 лет 1h, ~274 года 1d — с запасом, чтобы инкрементальная
# докачка с 2022-01-01 не обрезала старые бары.
CSV_KEEP_LAST = 100000
WS_RECONNECT_DELAY = 5


# =========================================================
# PATHS / STATE
# =========================================================

def ensure_dirs():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def csv_path(symbol: str, tf: str) -> Path:
    return DATA_DIR / f"{symbol}_{tf}.csv"


def sent_state_path() -> Path:
    return STATE_DIR / "sent_signals.json"


def load_sent_state() -> dict:
    path = sent_state_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_sent_state(state: dict):
    sent_state_path().write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# =========================================================
# TIMEFRAME HELPERS
# =========================================================

def tf_to_pandas_rule(tf: str) -> str:
    mapping = {
        "1h": "1h",
        "2h": "2h",
        "3h": "3h",
        "4h": "4h",
        "6h": "6h",
        "8h": "8h",
        "12h": "12h",
        "1d": "1D",
        "2d": "2D",
        "3d": "3D",
    }
    return mapping[tf]


def tf_to_ms(tf: str) -> int:
    mapping = {
        "1h": 60 * 60 * 1000,
        "2h": 2 * 60 * 60 * 1000,
        "3h": 3 * 60 * 60 * 1000,
        "4h": 4 * 60 * 60 * 1000,
        "6h": 6 * 60 * 60 * 1000,
        "8h": 8 * 60 * 60 * 1000,
        "12h": 12 * 60 * 60 * 1000,
        "1d": 24 * 60 * 60 * 1000,
        "2d": 2 * 24 * 60 * 60 * 1000,
        "3d": 3 * 24 * 60 * 60 * 1000,
    }
    return mapping[tf]


# =========================================================
# DATAFRAME HELPERS
# =========================================================

def normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=[
            "Open time", "Open", "High", "Low", "Close", "Volume", "Close time"
        ])

    out = df.copy()

    out["Open time"] = pd.to_datetime(out["Open time"], utc=True, errors="coerce")
    out["Close time"] = pd.to_datetime(out["Close time"], utc=True, errors="coerce")

    for col in ["Open", "High", "Low", "Close", "Volume"]:
        out[col] = pd.to_numeric(out[col], errors="coerce")

    out = out.dropna(subset=["Open time", "Open", "High", "Low", "Close"])
    out = out.sort_values("Open time")
    out = out.drop_duplicates(subset=["Open time"], keep="last")
    out = out.reset_index(drop=True)

    return out


def load_df(symbol: str, tf: str) -> pd.DataFrame:
    path = csv_path(symbol, tf)
    if not path.exists():
        return normalize_df(pd.DataFrame())
    return normalize_df(pd.read_csv(path))


def save_df(symbol: str, tf: str, df: pd.DataFrame):
    out = normalize_df(df).tail(CSV_KEEP_LAST)
    out.to_csv(csv_path(symbol, tf), index=False)


# =========================================================
# BINANCE REST
# =========================================================

def fetch_klines(symbol: str, interval: str, limit: int = 500) -> pd.DataFrame:
    url = f"{BINANCE_REST_BASE}/api/v3/klines"
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit,
    }
    resp = requests.get(url, params=params, timeout=REST_TIMEOUT)
    resp.raise_for_status()
    raw = resp.json()

    rows = []
    for k in raw:
        rows.append({
            "Open time": pd.to_datetime(k[0], unit="ms", utc=True),
            "Open": float(k[1]),
            "High": float(k[2]),
            "Low": float(k[3]),
            "Close": float(k[4]),
            "Volume": float(k[5]),
            "Close time": pd.to_datetime(k[6], unit="ms", utc=True),
        })

    df = normalize_df(pd.DataFrame(rows))
    if df.empty:
        return df

    now_utc = pd.Timestamp.utcnow().tz_localize("UTC") if pd.Timestamp.utcnow().tzinfo is None else pd.Timestamp.utcnow()

    # Оставляем только реально закрытые бары
    df = df[df["Close time"] <= now_utc].copy()

    return normalize_df(df)


# =========================================================
# COMPOSED TIMEFRAMES
# =========================================================

def compose_from_base(df_base: pd.DataFrame, target_tf: str) -> pd.DataFrame:
    if df_base.empty:
        return normalize_df(pd.DataFrame())

    df = normalize_df(df_base).copy()
    df = df.set_index("Open time")

    rule = tf_to_pandas_rule(target_tf)

    expected_count = {
        "3h": 3,   # 3 свечи по 1h
        "2d": 2,   # 2 свечи по 1d
    }.get(target_tf)

    agg_dict = {
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Volume": "sum",
        "Close time": "last",
    }

    agg = df.resample(
        rule,
        label="left",
        closed="left",
        origin="epoch",
    ).agg(agg_dict)

    if expected_count is not None:
        counts = df["Close"].resample(
            rule,
            label="left",
            closed="left",
            origin="epoch",
        ).count()
        agg["bar_count"] = counts

        # оставляем только полностью собранные бары
        agg = agg[agg["bar_count"] == expected_count].copy()
        agg = agg.drop(columns=["bar_count"])

    agg = agg.dropna(subset=["Open", "High", "Low", "Close"]).reset_index()
    return normalize_df(agg)

# =========================================================
# HISTORICAL DOWNLOAD
# =========================================================

BINANCE_MAX_LIMIT = 1000


def interval_to_binance(tf: str) -> str:
    return tf


def fetch_klines_range(symbol: str, interval: str, start_time_ms: int, end_time_ms: int | None = None, limit: int = 1000) -> pd.DataFrame:
    url = f"{BINANCE_REST_BASE}/api/v3/klines"
    params = {
        "symbol": symbol,
        "interval": interval,
        "startTime": start_time_ms,
        "limit": min(limit, BINANCE_MAX_LIMIT),
    }
    if end_time_ms is not None:
        params["endTime"] = end_time_ms

    resp = requests.get(url, params=params, timeout=REST_TIMEOUT)
    resp.raise_for_status()
    raw = resp.json()

    rows = []
    for k in raw:
        rows.append({
            "Open time": pd.to_datetime(k[0], unit="ms", utc=True),
            "Open": float(k[1]),
            "High": float(k[2]),
            "Low": float(k[3]),
            "Close": float(k[4]),
            "Volume": float(k[5]),
            "Close time": pd.to_datetime(k[6], unit="ms", utc=True),
        })

    return normalize_df(pd.DataFrame(rows))


def fetch_full_history(symbol: str, tf: str, start_date: str = "2022-01-01") -> pd.DataFrame:
    """
    Качает всю историю по symbol/tf начиная с указанной даты.
    """
    start_ts = pd.Timestamp(start_date, tz="UTC")
    now_ts = pd.Timestamp.utcnow()

    all_parts = []
    current_ms = int(start_ts.timestamp() * 1000)

    while True:
        part = fetch_klines_range(
            symbol=symbol,
            interval=interval_to_binance(tf),
            start_time_ms=current_ms,
            end_time_ms=int(now_ts.timestamp() * 1000),
            limit=BINANCE_MAX_LIMIT,
        )

        if part.empty:
            break

        all_parts.append(part)

        last_open_time = pd.to_datetime(part["Open time"].max(), utc=True)
        next_open_time = last_open_time + pd.to_timedelta(tf_to_ms(tf), unit="ms")
        next_ms = int(next_open_time.timestamp() * 1000)

        if next_ms <= current_ms:
            break

        current_ms = next_ms

        print(f"[HISTORY] {symbol} {tf} loaded up to {last_open_time}")

        if len(part) < BINANCE_MAX_LIMIT:
            break

    if not all_parts:
        return normalize_df(pd.DataFrame())

    df = pd.concat(all_parts, ignore_index=True)
    df = normalize_df(df)

    # Только реально закрытые свечи
    now_utc = pd.Timestamp.utcnow()
    df = df[df["Close time"] <= now_utc].copy()

    return normalize_df(df)


def update_df_incrementally(
    symbol: str,
    tf: str,
    start_date_fallback: str = "2022-01-01",
) -> pd.DataFrame:
    """
    Инкрементальная докачка:
      - если CSV пуст/нет  -> качает всю историю с start_date_fallback;
      - если CSV уже есть  -> качает только свечи после последнего сохранённого бара.

    Все данные в UTC (как отдаёт Binance). Выравнивание свечей на Binance spot:
      1h/2h/4h/6h/8h/12h/1d       -> по UTC 00:00
      3h, 2d                      -> составные, пересобираются отдельно.
    Фильтруются только закрытые свечи (Close time <= now_utc).
    """
    ensure_dirs()

    df_existing = load_df(symbol, tf)

    now_ts = pd.Timestamp.utcnow()
    now_ms = int(now_ts.timestamp() * 1000)

    # 1) Если данных нет — полная загрузка
    if df_existing.empty:
        print(f"[INCR] {symbol} {tf}: CSV пуст, полная загрузка с {start_date_fallback}")
        df_full = fetch_full_history(symbol, tf, start_date=start_date_fallback)
        if not df_full.empty:
            save_df(symbol, tf, df_full)
            print(f"[INCR] {symbol} {tf}: загружено {len(df_full)} свечей")
        return df_full

    # 2) Данные есть — качаем только хвост
    last_open_time = pd.to_datetime(df_existing["Open time"].max(), utc=True)
    last_open_ms = int(last_open_time.timestamp() * 1000)
    next_open_ms = last_open_ms + tf_to_ms(tf)

    # Если следующий бар ещё даже не начался — ничего не качаем
    if next_open_ms >= now_ms:
        print(
            f"[INCR] {symbol} {tf}: up-to-date "
            f"(last closed bar open={last_open_time.isoformat()})"
        )
        return df_existing

    print(
        f"[INCR] {symbol} {tf}: докачиваю с "
        f"{pd.to_datetime(next_open_ms, unit='ms', utc=True).isoformat()}"
    )

    parts = [df_existing]
    current_ms = next_open_ms

    while True:
        part = fetch_klines_range(
            symbol=symbol,
            interval=interval_to_binance(tf),
            start_time_ms=current_ms,
            end_time_ms=now_ms,
            limit=BINANCE_MAX_LIMIT,
        )

        if part.empty:
            break

        parts.append(part)

        last_part_open = pd.to_datetime(part["Open time"].max(), utc=True)
        next_current_ms = int(last_part_open.timestamp() * 1000) + tf_to_ms(tf)

        if next_current_ms <= current_ms:
            break
        current_ms = next_current_ms

        if len(part) < BINANCE_MAX_LIMIT:
            break

    combined = pd.concat(parts, ignore_index=True)
    combined = normalize_df(combined)  # дедуп по Open time + сортировка

    # Оставляем только реально закрытые свечи
    now_utc = pd.Timestamp.utcnow()
    combined = combined[combined["Close time"] <= now_utc].copy()
    combined = normalize_df(combined)

    added = len(combined) - len(df_existing)
    if added < 0:
        # теоретически возможно, если CSV_KEEP_LAST обрезал старые бары — не пугаемся
        added = 0

    save_df(symbol, tf, combined)
    print(
        f"[INCR] {symbol} {tf}: +{added} новых свечей, "
        f"всего в CSV {len(combined)}, last={combined['Open time'].max()}"
    )
    return combined


def update_composed_from_base(symbol: str):
    """
    Пересобирает составные ТФ (3h из 1h, 2d из 1d) из уже обновлённых базовых.
    compose_from_base использует origin='epoch', поэтому баров выровнены по UTC.
    """
    df_1h = load_df(symbol, "1h")
    df_1d = load_df(symbol, "1d")

    df_3h = compose_from_base(df_1h, "3h")
    df_2d = compose_from_base(df_1d, "2d")

    save_df(symbol, "3h", df_3h)
    save_df(symbol, "2d", df_2d)

    print(f"[COMPOSED] {symbol} 3h: {len(df_3h)}, 2d: {len(df_2d)}")


# =========================================================
# OBX4 LOGIC
# =========================================================

def is_bearish(c) -> bool:
    return c["Close"] < c["Open"]

def body_size(c) -> float:
    return abs(c["Close"] - c["Open"])


def is_bullish(c) -> bool:
    return c["Close"] > c["Open"]


def body_top(c) -> float:
    return max(c["Open"], c["Close"])


def body_bottom(c) -> float:
    return min(c["Open"], c["Close"])


def has_common_body_intersection(c1, c2, c3, c4):
    common_top = min(
        body_top(c1),
        body_top(c2),
        body_top(c3),
        body_top(c4),
    )
    common_bottom = max(
        body_bottom(c1),
        body_bottom(c2),
        body_bottom(c3),
        body_bottom(c4),
    )
    return common_bottom < common_top, common_bottom, common_top


def detect_obx4_bullish(df: pd.DataFrame) -> pd.DataFrame:
    results = []
    if len(df) < 5:
        return pd.DataFrame(results)

    for i in range(len(df) - 4):
        c1 = df.iloc[i]
        c2 = df.iloc[i + 1]
        c3 = df.iloc[i + 2]
        c4 = df.iloc[i + 3]
        c5 = df.iloc[i + 4]

        # red -> green -> red -> green
        if not (
            is_bearish(c1) and
            is_bullish(c2) and
            is_bearish(c3) and
            is_bullish(c4)
        ):
            continue

        # body c1 должно быть больше body c2
        if body_size(c1) <= body_size(c2) and body_size(c1) <= body_size(c3):
            continue

        # 4-я зеленая закрывается выше открытия 1-й красной
        if c4["Close"] <= c1["Open"]:
            continue

        # bullish FVG
        if c5["Low"] <= c3["High"]:
            continue

        # общее пересечение по телам
        ok, ob_bottom, ob_top = has_common_body_intersection(c1, c2, c3, c4)
        if not ok:
            continue

        results.append({
            "pattern_time": c1["Open time"],
            "direction": "bullish",
            "ob_top": float(ob_top),
            "ob_bottom": float(ob_bottom),
            "fvg_top": float(c5["Low"]),
            "fvg_bottom": float(c3["High"]),
            "c1_time": c1["Open time"],
            "c2_time": c2["Open time"],
            "c3_time": c3["Open time"],
            "c4_time": c4["Open time"],
            "c5_time": c5["Open time"],
        })

    return pd.DataFrame(results)


def detect_obx4_bearish(df: pd.DataFrame) -> pd.DataFrame:
    results = []
    if len(df) < 5:
        return pd.DataFrame(results)

    for i in range(len(df) - 4):
        c1 = df.iloc[i]
        c2 = df.iloc[i + 1]
        c3 = df.iloc[i + 2]
        c4 = df.iloc[i + 3]
        c5 = df.iloc[i + 4]

        # green -> red -> green -> red
        if not (
            is_bullish(c1) and
            is_bearish(c2) and
            is_bullish(c3) and
            is_bearish(c4)
        ):
            continue

        # body c1 должно быть больше body c2
        if body_size(c1) <= body_size(c2) and body_size(c1) <= body_size(c3):
            continue

        # 4-я красная закрывается ниже открытия 1-й зеленой
        if c4["Close"] >= c1["Open"]:
            continue

        # bearish FVG
        if c5["High"] >= c3["Low"]:
            continue

        # общее пересечение по телам
        ok, ob_bottom, ob_top = has_common_body_intersection(c1, c2, c3, c4)
        if not ok:
            continue

        results.append({
            "pattern_time": c1["Open time"],
            "direction": "bearish",
            "ob_top": float(ob_top),
            "ob_bottom": float(ob_bottom),
            "fvg_top": float(c3["Low"]),
            "fvg_bottom": float(c5["High"]),
            "c1_time": c1["Open time"],
            "c2_time": c2["Open time"],
            "c3_time": c3["Open time"],
            "c4_time": c4["Open time"],
            "c5_time": c5["Open time"],
        })

    return pd.DataFrame(results)


def detect_all_obx4(df: pd.DataFrame) -> pd.DataFrame:
    bull = detect_obx4_bullish(df)
    bear = detect_obx4_bearish(df)
    out = pd.concat([bull, bear], ignore_index=True)
    if not out.empty:
        out = out.sort_values("pattern_time").reset_index(drop=True)
    return out


def newest_signal_only(df: pd.DataFrame) -> pd.DataFrame:
    """
    Берем только сигналы, подтвержденные на самой последней закрытой c5-свече.
    Так мы не пересылаем старые исторические паттерны на каждом пересчете.
    """
    if df.empty:
        return df
    last_c5_time = df["c5_time"].max()
    return df[df["c5_time"] == last_c5_time].copy()


# =========================================================
# DETECTION на последнем закрытом баре
# =========================================================

def detect_signal_on_last_closed_candle(df: pd.DataFrame):
    """
    Проверяем только один паттерн:
    последние 5 закрытых свечей, где 5-я свеча = последняя свеча в df.
    """
    df = normalize_df(df)

    if len(df) < 5:
        return None

    last5 = df.iloc[-5:].reset_index(drop=True)

    bull = detect_obx4_bullish(last5)
    if not bull.empty:
        row = bull.iloc[-1].copy()

        # Дополнительная защита:
        # c5_time паттерна должен совпадать с open time последней свечи в df
        if pd.to_datetime(row["c5_time"]) == pd.to_datetime(df.iloc[-1]["Open time"]):
            return row

    bear = detect_obx4_bearish(last5)
    if not bear.empty:
        row = bear.iloc[-1].copy()

        if pd.to_datetime(row["c5_time"]) == pd.to_datetime(df.iloc[-1]["Open time"]):
            return row

    return None


# =========================================================
# SIGNAL EXPORT (бэктест по истории)
# =========================================================

SIGNALS_DIR = Path("./signals_by_tf")


def ensure_signal_dir():
    SIGNALS_DIR.mkdir(parents=True, exist_ok=True)


def tf_signal_csv_path(tf: str) -> Path:
    return SIGNALS_DIR / f"obx4_{tf}_signals.csv"


def build_signals_df_for_symbol_tf(symbol: str, tf: str, df: pd.DataFrame) -> pd.DataFrame:
    signals = detect_all_obx4(df)

    if signals.empty:
        return pd.DataFrame(columns=[
            "symbol",
            "tf",
            "pattern_time",
            "direction",
            "ob_top",
            "ob_bottom",
            "fvg_top",
            "fvg_bottom",
            "c1_time",
            "c2_time",
            "c3_time",
            "c4_time",
            "c5_time",
            "zone_low_c1_c5",
            "zone_high_c1_c5",
        ])

    zone_lows = []
    zone_highs = []

    for _, row in signals.iterrows():
        c_times = [
            pd.to_datetime(row["c1_time"], utc=True),
            pd.to_datetime(row["c2_time"], utc=True),
            pd.to_datetime(row["c3_time"], utc=True),
            pd.to_datetime(row["c4_time"], utc=True),
            pd.to_datetime(row["c5_time"], utc=True),
        ]

        c_df = df[df["Open time"].isin(c_times)].copy()

        if len(c_df) == 5:
            zone_lows.append(float(c_df["Low"].min()))
            zone_highs.append(float(c_df["High"].max()))
        else:
            zone_lows.append(None)
            zone_highs.append(None)

    signals = signals.copy()
    signals.insert(0, "tf", tf)
    signals.insert(0, "symbol", symbol)
    signals["zone_low_c1_c5"] = zone_lows
    signals["zone_high_c1_c5"] = zone_highs

    signals = signals.sort_values(["c5_time", "symbol"]).reset_index(drop=True)
    return signals
