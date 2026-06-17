"""etap_228 — бот ПОСТОЯННЫХ кнопок (@new_edge_neiro_bot): BTC / ETH / SOL / ТОТАЛ.

Нижняя reply-клавиатура (всегда видна). Нажатие → последний часовой расклад из кэша
(в 16:48 придёт версия от 16:00). Кэш пишет etap_227 (раз в час); если нет — генерит на лету.
🌐 ТОТАЛ — рыночная карта TOTAL/TOTALES + метрики (etap_229).

Долгоживущий процесс (long-polling). Запусти и держи запущенным.
Запуск: venv/Scripts/python.exe research/daily_engine/etap_228_dashboard_buttons_bot.py
"""
import os, sys, json
from pathlib import Path
import requests
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent.parent))
try:
    from dotenv import load_dotenv
    load_dotenv(HERE.parent.parent / ".env")
except Exception:
    pass
import etap_227_live_dashboard_bot as G
import etap_229_market as MK
import etap_230_market_index as MI

TOKEN = os.getenv("DASHBOARD_BOT_TOKEN", "")
API = f"https://api.telegram.org/bot{TOKEN}"
STATE = HERE.parent.parent / "state" / "live_dashboard"; STATE.mkdir(parents=True, exist_ok=True)
OFF = STATE / "bot_offset.json"
# ПОСТОЯННАЯ нижняя клавиатура
KB = json.dumps({"keyboard": [["₿ BTC", "Ξ ETH", "◎ SOL"], ["🌐 ТОТАЛ (рынок)", "ℹ️ Справка"]],
                 "resize_keyboard": True, "is_persistent": True})

HELP = (
    "ℹ️ <b>КАК ЧИТАТЬ СИГНАЛ</b>\n\n"
    "<b>1) Заголовок — главное за 5 секунд</b>\n"
    "Режим (какой сегодня день):\n"
    "🟢 <b>растущий</b> · 🔴 <b>падающий</b> · ⚪ <b>боковик</b> · ⚫ <b>рано</b> (день не определился)\n"
    "Сигнал: <b>LONG</b> (вверх) / <b>SHORT</b> (вниз) / <b>HOLD</b> (ждать).\n"
    "<b>Шанс роста</b> — насколько день «лёг» в плюс: 50% = непонятно, 90% = уверенно вверх. "
    "Это текущее состояние, <b>не обещание</b>.\n\n"
    "<b>2) Строка «Что делать»</b>\n"
    "• растущий день → лонги от опор на откате (не вдогонку)\n"
    "• падающий день → шорты от сопротивлений (не лови дно)\n"
    "• боковик → от границ к центру или пропусти\n"
    "• «вдогонку поздно» = цена уже прошла почти весь обычный дневной путь\n\n"
    "<b>3) Картинка — 3 части</b>\n"
    "① <b>Цена</b>: свечи + «утренний коридор» (пунктир). ФОН: зелёный=растёт, серый=боковик, красный=падает.\n"
    "② <b>Шанс роста</b> по часам. Серая полоса = «зона ожидания» (не дёргаемся). Точки: зелёная=лонг, красная=шорт, серая=ждать.\n"
    "③ <b>Сколько дневного хода пройдено</b>: 1.0 = как в обычный день; выше — ход почти выбран, входить поздно.\n\n"
    "<b>4) Смен мнения</b>: 0–1 = сигнал устойчивый; много = день рваный, осторожно.\n\n"
    "<b>🌐 ТОТАЛ</b> — то же по всему рынку (TOTAL/TOTALES из TradingView) + BTC.D, Fear&amp;Greed и пр.\n\n"
    "<i>Главное: это карта состояния рынка, а НЕ прогноз будущего. Вход — твоё решение.</i>")
_M = None


def model():
    global _M
    if _M is None:
        _M = G.fit_model()
    return _M


def api(method, **kw):
    try:
        return requests.post(f"{API}/{method}", timeout=60, **kw).json()
    except Exception as e:
        print("[dash-bot] api err", repr(e)); return {}


def greet(chat):
    api("sendMessage", data={"chat_id": chat, "parse_mode": "HTML", "reply_markup": KB,
        "text": "Жми монету — пришлю <b>актуальный расклад</b>.\n«🌐 ТОТАЛ» — обзор всего рынка.\n<i>Обновляется каждый час.</i>"})


def _send_png(chat, png, cap):
    with open(png, "rb") as f:
        api("sendPhoto", data={"chat_id": chat, "caption": cap, "parse_mode": "HTML", "reply_markup": KB},
            files={"photo": f})


def send_dash(chat, sym):
    try:
        meta = STATE / f"{sym}.json"
        if not meta.exists():
            G.generate(sym, G.D.fetch(G.SRC[sym]), model())
        m = json.loads(meta.read_text(encoding="utf-8"))
        if not Path(m["png"]).exists():
            G.generate(sym, G.D.fetch(G.SRC[sym]), model()); m = json.loads(meta.read_text(encoding="utf-8"))
        _send_png(chat, m["png"], m["caption"])
    except Exception as e:
        api("sendMessage", data={"chat_id": chat, "text": f"{sym}: не удалось ({e!r})"})


def _send_cached(chat, name, gen):
    meta = STATE / f"{name}.json"
    if not meta.exists():
        gen()
    m = json.loads(meta.read_text(encoding="utf-8"))
    if not Path(m["png"]).exists():
        gen(); m = json.loads(meta.read_text(encoding="utf-8"))
    _send_png(chat, m["png"], m["caption"])


def send_market(chat):
    # свежие TOTAL/TOTALES из TradingView на момент нажатия (тянет ~15 сек, кратко двигает график)
    api("sendMessage", data={"chat_id": chat, "text": "Собираю TOTAL / TOTALES из TradingView… (~15 сек)"})
    try:
        MI.generate_total_totales()
    except Exception as e:
        api("sendMessage", data={"chat_id": chat, "text": f"TV недоступен, использую запасной индекс ({e!r})"})
    for name, gen in [("TOTALIDX", MI.generate_total_totales),
                      ("TOTALESIDX", MI.generate_total_totales),
                      ("MARKET", MK.generate_market)]:
        try:
            _send_cached(chat, name, gen)
        except Exception as e:
            api("sendMessage", data={"chat_id": chat, "text": f"{name}: не удалось ({e!r})"})


def send_help(chat):
    api("sendMessage", data={"chat_id": chat, "parse_mode": "HTML", "reply_markup": KB, "text": HELP})


def route(chat, text):
    t = (text or "").upper()
    if "СПРАВ" in t or "ПОМОЩ" in t or "/HELP" in t: send_help(chat)
    elif "BTC" in t: send_dash(chat, "BTC")
    elif "ETH" in t: send_dash(chat, "ETH")
    elif "SOL" in t: send_dash(chat, "SOL")
    elif "ТОТАЛ" in t or "TOTAL" in t or "РЫНОК" in t: send_market(chat)
    else: greet(chat)


def main():
    if not TOKEN:
        raise SystemExit("DASHBOARD_BOT_TOKEN не задан в .env")
    offset = json.loads(OFF.read_text()) if OFF.exists() else 0
    print("[dash-bot] запущен, слушаю кнопки @new_edge_neiro_bot ...")
    while True:
        r = api("getUpdates", data={"offset": offset + 1, "timeout": 50})
        for u in r.get("result", []):
            offset = u["update_id"]
            msg = u.get("message") or u.get("edited_message")
            if msg and "text" in msg:
                route(msg["chat"]["id"], msg["text"])
        OFF.write_text(json.dumps(offset))


if __name__ == "__main__":
    main()
