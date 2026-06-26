"""Магнитуда — ПОЧАСОВАЯ проверка для аналитического процесса (вызывается из etap_227 main()).
ADMIN-ONLY: шлёт ТОЛЬКО админам (state/admins.json, по умолч. 901107007) через DASHBOARD_BOT_TOKEN,
НЕ через recipients() аналитики (там Павел), НЕ через прод-токен, НЕ рассылка.

Тянет свежие 8h/12h klines BTC/ETH/SOL с Binance, детектит reversal на последних закрытых барах
(strategies/magnitude.py + models/magnitude_*.cbm), шлёт новые сигналы. Дедуп: state/magnitude_hourly_sent.json.
Первый запуск = PREFILL silent (не дампит бэклог). Идемпотентно — безопасно звать каждый час.

Включение в аналитике контролируется флагом MAGNITUDE_ENABLED (см. вызов в etap_227).
"""
from __future__ import annotations
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from strategies.magnitude import detect_magnitude_signals  # noqa: E402

SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
TF_DIR = {"8h": "long", "12h": "short"}
STATE_FILE = ROOT / "state" / "magnitude_hourly_sent.json"
ADMINS_FILE = ROOT / "state" / "admins.json"
DEFAULT_ADMIN = 901107007


def _admins() -> list[int]:
    try:
        ids = [int(x) for x in json.loads(ADMINS_FILE.read_text(encoding="utf-8"))]
        return ids or [DEFAULT_ADMIN]
    except Exception:
        return [DEFAULT_ADMIN]


def _fetch(sym: str, interval: str, limit: int = 400) -> pd.DataFrame:
    u = f"https://api.binance.com/api/v3/klines?symbol={sym}&interval={interval}&limit={limit}"
    r = json.load(urllib.request.urlopen(u, timeout=20))
    rows = [(pd.to_datetime(k[0], unit="ms", utc=True), float(k[1]), float(k[2]),
             float(k[3]), float(k[4]), float(k[5])) for k in r]
    df = pd.DataFrame(rows, columns=["open_time", "open", "high", "low", "close", "volume"]).set_index("open_time")
    return df.iloc[:-1]  # отбросить незакрытый последний бар


def _load_sent():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8")), False
        except Exception:
            return {}, False
    return {}, True  # первый запуск -> prefill


def _save_sent(d: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def _key(sym: str, sig: dict) -> str:
    t = pd.Timestamp(sig["signal_time"])
    if t.tz is None:
        t = t.tz_localize("UTC")
    return f"Magnitude|{sym}|{sig['direction']}|{t.isoformat()}|{round(float(sig['entry']), 8)}"


def _fmt(sym: str, sig: dict) -> str:
    icon = "📈" if sig["direction"] == "LONG" else "📉"
    rp = abs(sig["entry"] - sig["sl"]) / sig["entry"] * 100
    t = pd.Timestamp(sig["signal_time"])
    return (f"🧲 <b>{sym}</b> · <b>Магнитуда</b> · ADMIN-only тест\n"
            f"{icon} <b>{sig['direction']}</b> · reversal {sig['tf']}\n\n"
            f"Вход:  <b>{sig['entry']:.2f}</b>\n"
            f"SL:    <b>{sig['sl']:.2f}</b> ({rp:.2f}%)\n"
            f"TP:    <b>{sig['tp']:.2f}</b> (RR={sig['rr']})\n"
            f"reversal-likelihood p={sig['p']}\n"
            f"Время: {t.strftime('%Y-%m-%d %H:%M')} UTC\n"
            f"⚠️ кандидат на обкатке (~33% WR / высокий RR, режим-зависимо). НЕ финсовет, НЕ рассылка.")


def _send_admin(text: str) -> bool:
    token = os.getenv("DASHBOARD_BOT_TOKEN", "")
    if not token:
        print("[magnitude] DASHBOARD_BOT_TOKEN не задан — не шлю")
        return False
    ok = False
    for chat in _admins():
        try:
            r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                              data={"chat_id": chat, "text": text, "parse_mode": "HTML",
                                    "disable_web_page_preview": "true"}, timeout=30)
            ok = ok or bool(r.json().get("ok"))
        except Exception as e:
            print(f"[magnitude] send admin={chat}: {e!r}")
    return ok


def magnitude_check() -> int:
    """Один почасовой проход. Возвращает число новых отправленных сигналов (0 при prefill)."""
    sent, first = _load_sent()
    n_new = 0
    for sym in SYMS:
        for tf, dirn in TF_DIR.items():
            try:
                df = _fetch(sym, tf)
                if len(df) < 120:
                    continue
                sigs = detect_magnitude_signals(df, dirn, n_recent=2)
            except Exception as e:
                print(f"[magnitude] {sym} {tf}: {e!r}")
                continue
            for sig in sigs:
                k = _key(sym, sig)
                if k in sent:
                    continue
                if first:
                    sent[k] = {"prefill": True}      # первый запуск — молча
                    continue
                if _send_admin(_fmt(sym, sig)):
                    sent[k] = {"sent_at": datetime.now(timezone.utc).isoformat(),
                               "dir": sig["direction"], "tf": sig["tf"], "entry": sig["entry"],
                               "sl": sig["sl"], "tp": sig["tp"], "p": sig["p"]}
                    n_new += 1
                    print(f"[magnitude] {sym} {sig['direction']} {sig['tf']} -> ADMIN")
                # если отправка не удалась — НЕ маркируем, повторим в след. час
    _save_sent(sent)
    print(f"[magnitude] check done: {'PREFILL silent (бэклог помечен)' if first else f'{n_new} new -> ADMIN'}")
    return n_new


if __name__ == "__main__":
    magnitude_check()
