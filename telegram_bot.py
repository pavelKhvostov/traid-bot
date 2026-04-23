"""Тонкая обёртка над Telegram Bot API: send, broadcast, long-polling команд."""
from __future__ import annotations

import json
import html
from pathlib import Path

import requests

from config import STATE_DIR, TELEGRAM_BOT_TOKEN
from state import (
    load_last_signal,
    load_users,
    save_users,
)

API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
LAST_UPDATE_PATH = STATE_DIR / "last_update_id.json"


def _api(method: str, **params):
    url = f"{API_BASE}/{method}"
    r = requests.post(url, data=params, timeout=30)
    # не поднимаем исключение сразу — отдадим json для диагностики
    try:
        return r.json()
    except ValueError:
        return {"ok": False, "status_code": r.status_code, "text": r.text}


def send_message(text: str, chat_id: int) -> dict:
    return _api(
        "sendMessage",
        chat_id=chat_id,
        text=text,
        parse_mode="HTML",
        disable_web_page_preview="true",
    )


def broadcast(text: str) -> dict:
    users = load_users()
    ok, failed = 0, 0
    errors: list[tuple[int, str]] = []
    for uid in users:
        try:
            resp = send_message(text, uid)
            if resp.get("ok"):
                ok += 1
            else:
                failed += 1
                errors.append((uid, str(resp.get("description", resp))))
        except Exception as e:  # сеть/timeout — не роняем рассылку
            failed += 1
            errors.append((uid, repr(e)))
    return {"ok": ok, "failed": failed, "errors": errors, "total": len(users)}


# ---- polling ----

def _load_last_update_id() -> int:
    if not LAST_UPDATE_PATH.exists():
        return 0
    try:
        return int(json.loads(LAST_UPDATE_PATH.read_text()).get("last_update_id", 0))
    except (ValueError, OSError, json.JSONDecodeError):
        return 0


def _save_last_update_id(uid: int) -> None:
    LAST_UPDATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    LAST_UPDATE_PATH.write_text(json.dumps({"last_update_id": int(uid)}))


def _handle_command(chat_id: int, text: str) -> None:
    cmd = text.strip().split()[0].lower()
    # срезаем возможный @botname
    if "@" in cmd:
        cmd = cmd.split("@", 1)[0]

    users = load_users()

    if cmd == "/start":
        if chat_id not in users:
            users.append(chat_id)
            save_users(users)
        send_message(
            "Привет! Ты подписан на сигналы.\n"
            "Команды: /stop, /status, /lastsignal, /whoami",
            chat_id,
        )
    elif cmd == "/stop":
        if chat_id in users:
            users = [u for u in users if u != chat_id]
            save_users(users)
            send_message("Отписан.", chat_id)
        else:
            send_message("Ты и так не подписан.", chat_id)
    elif cmd == "/status":
        send_message("Подписан ✅" if chat_id in users else "Не подписан ❌", chat_id)
    elif cmd == "/lastsignal":
        payload = load_last_signal()
        if not payload:
            send_message("Сигналов пока не было.", chat_id)
        else:
            pretty = json.dumps(payload, ensure_ascii=False, indent=2)
            send_message(f"<pre>{html.escape(pretty)}</pre>", chat_id)
    elif cmd == "/whoami":
        send_message(f"chat_id: <code>{chat_id}</code>", chat_id)
    else:
        send_message("Неизвестная команда. Доступно: /start /stop /status /lastsignal /whoami", chat_id)


def check_updates(timeout: int = 0) -> int:
    """Разовый опрос getUpdates. Возвращает количество обработанных апдейтов."""
    offset = _load_last_update_id() + 1
    resp = _api("getUpdates", offset=offset, timeout=timeout)
    if not resp.get("ok"):
        print(f"[TG] getUpdates error: {resp}")
        return 0
    updates = resp.get("result", [])
    processed = 0
    max_id = offset - 1
    for upd in updates:
        uid = int(upd["update_id"])
        max_id = max(max_id, uid)
        msg = upd.get("message") or upd.get("edited_message")
        if not msg:
            continue
        chat_id = int(msg["chat"]["id"])
        text = msg.get("text", "")
        if not text:
            continue
        try:
            _handle_command(chat_id, text)
            processed += 1
        except Exception as e:
            print(f"[TG] handle error chat={chat_id}: {e!r}")
    if max_id >= offset:
        _save_last_update_id(max_id)
    return processed
