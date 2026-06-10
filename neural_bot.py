"""neural_bot.py — отдельный Telegram-бот под нейросеть оценки сигналов (ветка pavel).

Самодостаточный (НЕ конфликтует с основным telegram_bot.py): свой токен, своё
состояние в state/neural_bot/. Стиль проекта: requests + long-polling, JSON,
без БД/фреймворков (CLAUDE.md).

Назначение: рассылать подписчикам сигналы стратегий 1.1.x с ОЦЕНКОЙ КАЧЕСТВА
1-5 от нейросети (etap_178/179): 1=плохой (не брать), 5=идеал. По умолчанию
шлёт только сигналы с классом >= NEURAL_MIN_GRADE.

Команды:
  /start  — подписаться
  /stop   — отписаться
  /status — подписан/нет + текущий порог
  /grade N — установить мин. класс сигнала (1-5), напр. /grade 4
  /test   — прислать пример сигнала (проверка связи)

Запуск standalone:        python neural_bot.py
Отправка сигнала из кода:  from neural_bot import broadcast_neural_signal
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

# --- токен: ТОЛЬКО из окружения / .env (секрет не хранится в коде) ---
import os
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except Exception:
    pass
TOKEN = os.environ.get("NEURAL_BOT_TOKEN", "")
if not TOKEN:
    raise SystemExit(
        "NEURAL_BOT_TOKEN не задан. Добавь в .env строку:\n"
        "  NEURAL_BOT_TOKEN=<твой токен>\n"
        "или экспортируй переменную окружения перед запуском.")
API_BASE = f"https://api.telegram.org/bot{TOKEN}"

# --- состояние (отдельная папка, не пересекается с основным ботом) ---
STATE_DIR = Path(__file__).resolve().parent / "state" / "neural_bot"
STATE_DIR.mkdir(parents=True, exist_ok=True)
USERS_PATH = STATE_DIR / "users.json"
OFFSET_PATH = STATE_DIR / "last_update_id.json"
SENT_PATH = STATE_DIR / "sent_signals.json"

DEFAULT_MIN_GRADE = 4   # по умолчанию шлём только сигналы класса >= 4 (взял TP)

GRADE_LABEL = {
    1: "⛔ 1/5 — плохой, не брать",
    2: "⚠️ 2/5 — слабый",
    3: "🟡 3/5 — средний",
    4: "✅ 4/5 — хороший (цель TP)",
    5: "🔥 5/5 — идеал",
}
GRADE_EMOJI = {1: "⛔", 2: "⚠️", 3: "🟡", 4: "✅", 5: "🔥"}


# ============================================================
# Telegram API
# ============================================================
def _api(method: str, **params) -> dict:
    try:
        r = requests.post(f"{API_BASE}/{method}", data=params, timeout=35)
    except requests.RequestException as e:
        print(f"[neural_bot] {method} network error: {e!r}")
        return {"ok": False, "error": repr(e)}
    try:
        return r.json()
    except ValueError:
        return {"ok": False, "status_code": r.status_code, "text": r.text}


def send_message(chat_id: int, text: str, reply_markup: dict | None = None) -> dict:
    params = {"chat_id": chat_id, "text": text, "parse_mode": "HTML",
              "disable_web_page_preview": "true"}
    if reply_markup is not None:
        params["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
    resp = _api("sendMessage", **params)
    if not resp.get("ok"):
        print(f"[neural_bot] send to {chat_id} failed: {resp.get('description', resp)}")
    return resp


# ============================================================
# Состояние (JSON)
# ============================================================
def _load(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _save(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_users() -> list[dict]:
    return _load(USERS_PATH, [])


def save_users(users: list[dict]) -> None:
    _save(USERS_PATH, users)


def _find_user(users: list[dict], chat_id: int) -> dict | None:
    for u in users:
        if u.get("chat_id") == chat_id:
            return u
    return None


def subscribe(chat_id: int, username: str | None, first_name: str | None) -> None:
    users = load_users()
    u = _find_user(users, chat_id)
    now = datetime.now(timezone.utc).isoformat()
    if u is None:
        users.append({"chat_id": chat_id, "username": username, "first_name": first_name,
                      "active": True, "min_grade": DEFAULT_MIN_GRADE,
                      "subscribed_at": now})
    else:
        u["active"] = True
        u["username"] = username or u.get("username")
        u.setdefault("min_grade", DEFAULT_MIN_GRADE)
    save_users(users)


def unsubscribe(chat_id: int) -> None:
    users = load_users()
    u = _find_user(users, chat_id)
    if u:
        u["active"] = False
        save_users(users)


def set_min_grade(chat_id: int, grade: int) -> None:
    users = load_users()
    u = _find_user(users, chat_id)
    if u:
        u["min_grade"] = max(1, min(5, grade))
        save_users(users)


def active_users() -> list[dict]:
    return [u for u in load_users() if u.get("active")]


# ============================================================
# Форматирование сигнала с оценкой нейросети
# ============================================================
def format_neural_signal(sig: dict) -> str:
    """sig: {strategy, symbol, direction, entry, sl, tp, grade, score, time, zone}."""
    g = int(sig.get("grade", 0))
    emoji = GRADE_EMOJI.get(g, "❔")
    dir_emoji = "📈" if sig.get("direction") == "LONG" else "📉"
    score = sig.get("score")
    score_str = f" (score {score:.2f})" if isinstance(score, (int, float)) else ""
    lines = [
        f"{emoji} <b>{sig.get('symbol','?')}</b> · {sig.get('strategy','?')}",
        f"{dir_emoji} <b>{sig.get('direction','?')}</b>",
        f"🧠 Оценка нейросети: <b>{GRADE_LABEL.get(g, str(g))}</b>{score_str}",
        "",
    ]
    if sig.get("entry") is not None:
        lines.append(f"Вход:  <code>{sig['entry']}</code>")
    if sig.get("sl") is not None:
        lines.append(f"SL:    <code>{sig['sl']}</code>")
    if sig.get("tp") is not None:
        lines.append(f"TP:    <code>{sig['tp']}</code>")
    if sig.get("zone"):
        lines.append(f"Зона:  {sig['zone']}")
    if sig.get("time"):
        lines.append(f"Время: {sig['time']} UTC")
    return "\n".join(lines)


def _sig_key(sig: dict) -> str:
    return f"{sig.get('strategy')}|{sig.get('symbol')}|{sig.get('direction')}|{sig.get('time')}"


def broadcast_neural_signal(sig: dict) -> dict:
    """Разослать сигнал активным подписчикам с учётом их min_grade. Дедуп по ключу."""
    sent = _load(SENT_PATH, [])
    key = _sig_key(sig)
    if key in sent:
        return {"ok": True, "skipped": "duplicate"}
    g = int(sig.get("grade", 0))
    text = format_neural_signal(sig)
    delivered = 0
    for u in active_users():
        if g >= int(u.get("min_grade", DEFAULT_MIN_GRADE)):
            if send_message(u["chat_id"], text).get("ok"):
                delivered += 1
    sent.append(key)
    _save(SENT_PATH, sent[-5000:])   # ограничиваем рост
    return {"ok": True, "delivered": delivered, "grade": g}


# ============================================================
# Обработка команд
# ============================================================
def _handle(msg: dict) -> None:
    chat = msg.get("chat", {})
    chat_id = chat.get("id")
    if chat_id is None:
        return
    text = (msg.get("text") or "").strip()
    username = chat.get("username")
    first = chat.get("first_name")

    if text.startswith("/start"):
        subscribe(chat_id, username, first)
        send_message(chat_id,
            "🧠 <b>Neural Signals Bot</b>\n\n"
            "Ты подписан. Будешь получать сигналы стратегий с оценкой качества "
            "<b>1-5</b> от нейросети (1=плохой, 5=идеал).\n\n"
            f"Сейчас порог: <b>≥{DEFAULT_MIN_GRADE}</b> (только хорошие сигналы).\n"
            "Команды: /status /grade N /stop /test")
    elif text.startswith("/stop"):
        unsubscribe(chat_id)
        send_message(chat_id, "Отписка выполнена. /start — подписаться снова.")
    elif text.startswith("/grade"):
        parts = text.split()
        if len(parts) >= 2 and parts[1].isdigit() and 1 <= int(parts[1]) <= 5:
            set_min_grade(chat_id, int(parts[1]))
            send_message(chat_id, f"Готово. Минимальный класс сигнала: <b>≥{parts[1]}</b>.")
        else:
            send_message(chat_id, "Формат: <code>/grade N</code>, где N от 1 до 5.\n"
                                  "Напр. <code>/grade 4</code> — только сигналы класса 4-5.")
    elif text.startswith("/status"):
        u = _find_user(load_users(), chat_id)
        if u and u.get("active"):
            send_message(chat_id, f"✅ Подписан. Порог: <b>≥{u.get('min_grade', DEFAULT_MIN_GRADE)}</b>.")
        else:
            send_message(chat_id, "❌ Не подписан. /start — подписаться.")
    elif text.startswith("/test"):
        demo = {"strategy": "1.1.1", "symbol": "BTCUSDT", "direction": "LONG",
                "entry": 65432.1, "sl": 64800.0, "tp": 66800.0, "grade": 5,
                "score": 4.7, "zone": "OB-12h × FVG-2h",
                "time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")}
        send_message(chat_id, "Пример сигнала:\n\n" + format_neural_signal(demo))
    else:
        send_message(chat_id, "Команды: /start /status /grade N /stop /test")


# ============================================================
# Long-polling
# ============================================================
def _offset() -> int:
    return int(_load(OFFSET_PATH, {"id": 0}).get("id", 0))


def _set_offset(uid: int) -> None:
    _save(OFFSET_PATH, {"id": uid})


def check_updates(timeout: int = 25) -> int:
    resp = _api("getUpdates", offset=_offset() + 1, timeout=timeout)
    if not resp.get("ok"):
        print(f"[neural_bot] getUpdates failed: {resp}")
        return 0
    n = 0
    max_id = _offset()
    for upd in resp.get("result", []):
        uid = int(upd["update_id"]); max_id = max(max_id, uid)
        m = upd.get("message") or upd.get("edited_message")
        if not m:
            continue
        try:
            _handle(m); n += 1
        except Exception as e:
            print(f"[neural_bot] handle error: {e!r}")
    if max_id > _offset():
        _set_offset(max_id)
    return n


def run() -> None:
    me = _api("getMe")
    if me.get("ok"):
        print(f"[neural_bot] запущен как @{me['result'].get('username')}")
    else:
        print(f"[neural_bot] getMe failed: {me} — проверь токен")
        return
    print("[neural_bot] long-polling... Ctrl+C для остановки")
    while True:
        try:
            check_updates(25)
        except KeyboardInterrupt:
            print("\n[neural_bot] остановлен")
            break
        except Exception as e:
            print(f"[neural_bot] loop error: {e!r}")
            time.sleep(3)


if __name__ == "__main__":
    run()
