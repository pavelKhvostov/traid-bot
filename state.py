"""Плоский JSON-стейт: подписчики, дедуп-ключи, последний сигнал, bot.log."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from config import STATE_DIR

USERS_PATH = STATE_DIR / "users.json"
SENT_PATH = STATE_DIR / "sent_signals.json"
LAST_SIGNAL_PATH = STATE_DIR / "last_signal.json"
LOG_PATH = STATE_DIR / "bot.log"
LOG_ROTATE_BYTES = 5 * 1024 * 1024  # 5 MB


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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---- users ----

def load_users() -> list[dict]:
    data = _read_json(USERS_PATH, [])
    # миграция: если вдруг старый формат list[int], конвертируем
    out: list[dict] = []
    for x in data:
        if isinstance(x, int):
            out.append({
                "id": int(x), "username": None, "first_name": None,
                "joined_at": _now_iso(), "last_active": _now_iso(),
            })
        elif isinstance(x, dict) and "id" in x:
            u = dict(x)
            u["id"] = int(u["id"])
            out.append(u)
    return out


def save_users(users: list[dict]) -> None:
    seen: dict[int, dict] = {}
    for u in users:
        seen[int(u["id"])] = {
            "id": int(u["id"]),
            "username": u.get("username"),
            "first_name": u.get("first_name"),
            "joined_at": u.get("joined_at") or _now_iso(),
            "last_active": u.get("last_active") or _now_iso(),
        }
    _write_json(USERS_PATH, sorted(seen.values(), key=lambda x: x["id"]))


def get_user(id: int) -> dict | None:
    for u in load_users():
        if u["id"] == int(id):
            return u
    return None


def is_subscribed(id: int) -> bool:
    return get_user(id) is not None


def upsert_user(id: int, username: str | None, first_name: str | None) -> dict:
    users = load_users()
    now = _now_iso()
    found = None
    for u in users:
        if u["id"] == int(id):
            found = u
            break
    if found is None:
        found = {
            "id": int(id),
            "username": username,
            "first_name": first_name,
            "joined_at": now,
            "last_active": now,
        }
        users.append(found)
    else:
        if username is not None:
            found["username"] = username
        if first_name is not None:
            found["first_name"] = first_name
        found["last_active"] = now
    save_users(users)
    return found


def remove_user(id: int) -> bool:
    users = load_users()
    new = [u for u in users if u["id"] != int(id)]
    if len(new) == len(users):
        return False
    save_users(new)
    return True


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


# ---- bot.log ----

def _rotate_log_if_needed() -> None:
    try:
        if LOG_PATH.exists() and LOG_PATH.stat().st_size > LOG_ROTATE_BYTES:
            backup = LOG_PATH.with_suffix(".log.1")
            if backup.exists():
                backup.unlink()
            LOG_PATH.rename(backup)
    except OSError:
        pass


def log_event(level: str, msg: str) -> None:
    level_up = (level or "INFO").upper()
    if level_up not in ("INFO", "SIGNAL", "WARN", "ERROR"):
        level_up = "INFO"
    line = f"{_now_iso()} [{level_up}] {msg}\n"
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        _rotate_log_if_needed()
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass
    print(line.rstrip())
