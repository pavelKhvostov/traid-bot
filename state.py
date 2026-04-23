"""Плоский JSON-стейт: подписчики, дедуп-ключи, последний сигнал."""
from __future__ import annotations

import json
from pathlib import Path

from config import STATE_DIR

USERS_PATH = STATE_DIR / "users.json"
SENT_PATH = STATE_DIR / "sent_signals.json"
LAST_SIGNAL_PATH = STATE_DIR / "last_signal.json"


def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ---- users ----

def load_users() -> list[int]:
    data = _read_json(USERS_PATH, [])
    return [int(x) for x in data]


def save_users(users: list[int]) -> None:
    _write_json(USERS_PATH, sorted(set(int(u) for u in users)))


# ---- sent signals ----

def load_sent_signals() -> dict:
    return _read_json(SENT_PATH, {})


def save_sent_signals(d: dict) -> None:
    _write_json(SENT_PATH, d)


def was_sent(key: str) -> bool:
    return key in load_sent_signals()


def mark_sent(key: str, payload: dict) -> None:
    d = load_sent_signals()
    d[key] = payload
    save_sent_signals(d)


# ---- last signal ----

def load_last_signal() -> dict:
    return _read_json(LAST_SIGNAL_PATH, {})


def save_last_signal(payload: dict) -> None:
    _write_json(LAST_SIGNAL_PATH, payload)
