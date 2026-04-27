import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

TIMEFRAMES_NATIVE = ["1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d"]
TIMEFRAMES_COMPOSED = {"3h": "1h", "2d": "1d"}
ALL_TIMEFRAMES = TIMEFRAMES_NATIVE + list(TIMEFRAMES_COMPOSED.keys())

# VIC_EVOT (стратегия №8) — отдельная WS-подписка, чтобы существующий
# Scanner не дёргал 1m/15m REST-обновления (1440+96 closes/сутки на символ).
# 1d входит в обе подписки; close_1d приходит в оба сканера (раз в сутки —
# дубликат REST-апдейта тривиален).
VIC_TFS = ["1d"]
VIC_NATIVE_TFS = ["1m", "15m", "1d"]
VIC_1M_LOOKBACK_DAYS = 3
VIC_15M_LOOKBACK_DAYS = 7

DATA_DIR = Path("./data")
STATE_DIR = Path("./state")
SIGNALS_DIR = Path("./signals")

HISTORY_START_DATE = "2022-01-01"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

ADMINS_PATH = STATE_DIR / "admins.json"


def ensure_dirs():
    for d in (DATA_DIR, STATE_DIR, SIGNALS_DIR):
        d.mkdir(parents=True, exist_ok=True)


ensure_dirs()


def load_admins() -> list[int]:
    if not ADMINS_PATH.exists():
        ADMINS_PATH.write_text("[]", encoding="utf-8")
        return []
    try:
        return [int(x) for x in json.loads(ADMINS_PATH.read_text(encoding="utf-8"))]
    except (ValueError, json.JSONDecodeError, OSError):
        return []


def save_admins(admins: list[int]) -> None:
    ADMINS_PATH.write_text(
        json.dumps(sorted(set(int(a) for a in admins)), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def is_admin(chat_id: int) -> bool:
    return int(chat_id) in load_admins()
