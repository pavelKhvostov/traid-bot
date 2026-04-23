import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

TIMEFRAMES_NATIVE = ["1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d"]
TIMEFRAMES_COMPOSED = {"3h": "1h", "2d": "1d"}
ALL_TIMEFRAMES = TIMEFRAMES_NATIVE + list(TIMEFRAMES_COMPOSED.keys())

DATA_DIR = Path("./data")
STATE_DIR = Path("./state")
SIGNALS_DIR = Path("./signals")

HISTORY_START_DATE = "2022-01-01"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0") or 0)


def ensure_dirs():
    for d in (DATA_DIR, STATE_DIR, SIGNALS_DIR):
        d.mkdir(parents=True, exist_ok=True)


ensure_dirs()
