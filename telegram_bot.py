"""Telegram: send, broadcast, polling + кнопки + админские команды."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime

import requests

from config import STATE_DIR, TELEGRAM_BOT_TOKEN, is_admin, load_admins, save_admins
from state import (
    get_user,
    is_subscribed,
    load_users,
    log_event,
    remove_user,
    upsert_user,
)
from strategies.base import render_signal_from_dict, tradingview_url

API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
LAST_UPDATE_PATH = STATE_DIR / "last_update_id.json"

# ---- reply keyboards ----

USER_KB = {
    "keyboard": [
        [{"text": "📊 Статус"}, {"text": "🛑 Отписаться"}],
    ],
    "resize_keyboard": True,
    "is_persistent": True,
}

UNSUBSCRIBED_KB = {
    "keyboard": [[{"text": "▶️ Подписаться"}]],
    "resize_keyboard": True,
    "is_persistent": True,
}


def _api(method: str, **params):
    url = f"{API_BASE}/{method}"
    try:
        r = requests.post(url, data=params, timeout=30)
    except requests.RequestException as e:
        log_event("ERROR", f"telegram {method} network: {e!r}")
        return {"ok": False, "error": repr(e)}
    try:
        return r.json()
    except ValueError:
        return {"ok": False, "status_code": r.status_code, "text": r.text}


def send_message(text: str, chat_id: int, reply_markup: dict | None = None) -> dict:
    params = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }
    if reply_markup is not None:
        params["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
    resp = _api("sendMessage", **params)
    if not resp.get("ok"):
        log_event("WARN", f"send_message chat={chat_id} failed: {resp.get('description', resp)}")
    return resp


def _kb_for(chat_id: int) -> dict:
    return USER_KB if is_subscribed(chat_id) else UNSUBSCRIBED_KB


def signal_inline_kb(symbol: str, tf: str) -> dict:
    return {
        "inline_keyboard": [[
            {"text": "📊 TradingView", "url": tradingview_url(symbol, tf)}
        ]]
    }


def send_signal(sig_data: dict, chat_id: int) -> dict:
    text = render_signal_from_dict(sig_data)
    kb = signal_inline_kb(sig_data["symbol"], sig_data["source_tf"])
    return send_message(text, chat_id, reply_markup=kb)


def broadcast_signal(sig_data: dict) -> dict:
    users = load_users()
    ids = [u["id"] for u in users]
    ok, failed = 0, 0
    errors: list[tuple[int, str]] = []
    for uid in ids:
        try:
            resp = send_signal(sig_data, uid)
            if resp.get("ok"):
                ok += 1
            else:
                failed += 1
                errors.append((uid, str(resp.get("description", resp))))
        except Exception as e:
            failed += 1
            errors.append((uid, repr(e)))
    log_event("INFO", f"broadcast_signal: ok={ok} failed={failed} total={len(ids)}")
    return {"ok": ok, "failed": failed, "errors": errors, "total": len(ids)}


def broadcast(text: str) -> dict:
    """Текстовая рассылка (для админского /broadcast)."""
    users = load_users()
    ids = [u["id"] for u in users]
    ok, failed = 0, 0
    errors: list[tuple[int, str]] = []
    for uid in ids:
        try:
            resp = send_message(text, uid, reply_markup=USER_KB)
            if resp.get("ok"):
                ok += 1
            else:
                failed += 1
                errors.append((uid, str(resp.get("description", resp))))
        except Exception as e:
            failed += 1
            errors.append((uid, repr(e)))
    log_event("INFO", f"broadcast: ok={ok} failed={failed} total={len(ids)}")
    return {"ok": ok, "failed": failed, "errors": errors, "total": len(ids)}


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


def _fmt_user(chat_id: int) -> str:
    u = get_user(chat_id)
    if not u:
        return str(chat_id)
    tag = f"@{u['username']}" if u.get("username") else (u.get("first_name") or "")
    return f"{chat_id} ({tag})".strip()


def _fmt_dt(iso: str | None) -> str:
    if not iso:
        return "-"
    try:
        dt = datetime.fromisoformat(iso)
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        return iso


# ---- action handlers ----

WELCOME_UNSUBSCRIBED = (
    "👋 Привет! Это бот торговых сигналов Binance Spot.\n\n"
    "Отслеживаю паттерны на BTC, ETH и SOL, "
    "подтверждение через OB 1h.\n\n"
    "Нажми кнопку ниже, чтобы подписаться."
)


def _action_subscribe(chat_id: int, username: str | None, first_name: str | None) -> None:
    upsert_user(chat_id, username, first_name)
    log_event("INFO", f"subscribe from {_fmt_user(chat_id)}")
    send_message("Привет! Ты подписан на сигналы.", chat_id, reply_markup=USER_KB)


def _action_unsubscribe(chat_id: int) -> None:
    removed = remove_user(chat_id)
    log_event("INFO", f"unsubscribe from {_fmt_user(chat_id)} removed={removed}")
    text = "Вы отписаны." if removed else "Ты и так не подписан."
    send_message(text, chat_id, reply_markup=UNSUBSCRIBED_KB)


def _action_status(chat_id: int) -> None:
    u = get_user(chat_id)
    if not u:
        send_message(
            "❌ <b>Не подписан</b>\nНажмите «▶️ Подписаться»",
            chat_id,
            reply_markup=UNSUBSCRIBED_KB,
        )
        return
    total = len(load_users())
    send_message(
        "✅ <b>Подписка активна</b>\n"
        f"С: <code>{_fmt_dt(u.get('joined_at'))}</code>\n"
        f"Подписчиков всего: {total}",
        chat_id,
        reply_markup=USER_KB,
    )


def _action_whoami(chat_id: int) -> None:
    send_message(
        f"chat_id: <code>{chat_id}</code>\n"
        f"admin: <b>{'yes' if is_admin(chat_id) else 'no'}</b>",
        chat_id,
        reply_markup=_kb_for(chat_id),
    )


# маппинг «кнопка/слэш → действие»
BUTTON_TO_ACTION = {
    "/start": "subscribe",
    "▶️ подписаться": "subscribe",
    "/stop": "unsubscribe",
    "🛑 отписаться": "unsubscribe",
    "/status": "status",
    "📊 статус": "status",
    "/whoami": "whoami",
}

SUBSCRIBE_TRIGGERS = ("/start", "▶️ Подписаться")


def _handle_message(msg: dict) -> None:
    chat_id = int(msg["chat"]["id"])
    text = (msg.get("text") or "").strip()
    if not text:
        return

    # Неподписчикам — только приветствие + кнопка "Подписаться".
    if not is_subscribed(chat_id) and text not in SUBSCRIBE_TRIGGERS:
        send_message(WELCOME_UNSUBSCRIBED, chat_id, reply_markup=UNSUBSCRIBED_KB)
        return

    parts = text.split(maxsplit=1)
    first = parts[0]
    arg = parts[1] if len(parts) > 1 else ""
    head = first.lower()
    if "@" in head:
        head = head.split("@", 1)[0]

    frm = msg.get("from") or {}
    username = frm.get("username")
    first_name = frm.get("first_name")

    key = text.lower() if not text.startswith("/") else head
    action = BUTTON_TO_ACTION.get(key)

    if action and action not in ("subscribe", "unsubscribe") and is_subscribed(chat_id):
        upsert_user(chat_id, username, first_name)

    if action == "subscribe":
        _action_subscribe(chat_id, username, first_name)
        return
    if action == "unsubscribe":
        _action_unsubscribe(chat_id)
        return
    if action == "status":
        _action_status(chat_id)
        return
    if action == "whoami":
        _action_whoami(chat_id)
        return

    # ---- admin-only slash commands ----
    if head in ("/users", "/admin_add", "/admin_remove", "/broadcast"):
        if not is_admin(chat_id):
            send_message("Команда только для админов.", chat_id, reply_markup=_kb_for(chat_id))
            log_event("WARN", f"{head} denied for {_fmt_user(chat_id)}")
            return

        if head == "/users":
            users = load_users()
            send_message(f"Подписчиков: <b>{len(users)}</b>", chat_id, reply_markup=_kb_for(chat_id))
            log_event("INFO", f"/users by {_fmt_user(chat_id)}: {len(users)}")
            return

        if head == "/admin_add":
            try:
                new_id = int(arg.strip())
            except ValueError:
                send_message("Использование: /admin_add &lt;id&gt;", chat_id, reply_markup=_kb_for(chat_id))
                return
            admins = load_admins()
            if new_id in admins:
                send_message(f"{new_id} уже админ.", chat_id, reply_markup=_kb_for(chat_id))
            else:
                admins.append(new_id)
                save_admins(admins)
                send_message(f"Админ {new_id} добавлен.", chat_id, reply_markup=_kb_for(chat_id))
                log_event("INFO", f"admin_add {new_id} by {_fmt_user(chat_id)}")
            return

        if head == "/admin_remove":
            try:
                rm_id = int(arg.strip())
            except ValueError:
                send_message("Использование: /admin_remove &lt;id&gt;", chat_id, reply_markup=_kb_for(chat_id))
                return
            admins = load_admins()
            if rm_id not in admins:
                send_message(f"{rm_id} и так не админ.", chat_id, reply_markup=_kb_for(chat_id))
            else:
                admins = [a for a in admins if a != rm_id]
                save_admins(admins)
                send_message(f"Админ {rm_id} убран.", chat_id, reply_markup=_kb_for(chat_id))
                log_event("INFO", f"admin_remove {rm_id} by {_fmt_user(chat_id)}")
            return

        if head == "/broadcast":
            text_to_send = arg.strip()
            if not text_to_send:
                send_message("Использование: /broadcast &lt;text&gt;", chat_id, reply_markup=_kb_for(chat_id))
                return
            result = broadcast(text_to_send)
            send_message(
                f"Разослано: ok={result['ok']}, failed={result['failed']}, total={result['total']}",
                chat_id,
                reply_markup=_kb_for(chat_id),
            )
            log_event("INFO", f"/broadcast by {_fmt_user(chat_id)}: {result}")
            return

    send_message("Неизвестная команда.", chat_id, reply_markup=_kb_for(chat_id))


def check_updates(timeout: int = 0) -> int:
    offset = _load_last_update_id() + 1
    resp = _api("getUpdates", offset=offset, timeout=timeout)
    if not resp.get("ok"):
        log_event("ERROR", f"getUpdates: {resp}")
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
        try:
            _handle_message(msg)
            processed += 1
        except Exception as e:
            log_event("ERROR", f"handle_message: {e!r}")
    if max_id >= offset:
        _save_last_update_id(max_id)
    return processed


async def polling_loop(poll_interval: float = 2.0) -> None:
    log_event("INFO", "polling_loop started")
    while True:
        try:
            await asyncio.to_thread(check_updates, 0)
        except Exception as e:
            log_event("ERROR", f"polling_loop: {e!r}")
        await asyncio.sleep(poll_interval)
