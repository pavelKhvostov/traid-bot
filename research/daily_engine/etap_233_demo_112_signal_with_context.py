"""etap_233 — демо: сигнал 1.1.2 (≈21:00 UTC) с новым авто-контекстом → тест-бот.

Берём реальный сигнал 1.1.2 с последних суток (ближайший к 21:00 UTC),
прогоняем через ТОТ ЖЕ путь, что live (apply_user_params → _format_message
с подключённым signal_context), и шлём ОДНО сообщение в @new_edge_neiro_bot
(DASHBOARD_BOT_TOKEN → DASHBOARD_CHAT_ID). НЕ продакшн-рассылка.

Запуск: venv/Scripts/python.exe research/daily_engine/etap_233_demo_112_signal_with_context.py
"""
from __future__ import annotations
import os, sys
from pathlib import Path
import pandas as pd
import requests
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass

from multi_strategy_scanner import MultiStrategyScanner
from strategies.strategy_1_1_2 import detect_strategy_1_1_2_signals

TOKEN = os.getenv("DASHBOARD_BOT_TOKEN", "")
CHAT = os.getenv("DASHBOARD_CHAT_ID", "")
TARGET = pd.Timestamp("2026-06-11 21:00", tz="UTC")   # «сигнал в 21:00 UTC»

s112 = MultiStrategyScanner(
    strategy_id="S112", strategy_name="1.1.2",
    detector_fn=detect_strategy_1_1_2_signals, needs_ltf=True,
    entry_pct=0.70, sl_pct=0.35, rr=2.2,
)

best = None  # (dist, symbol, sig)
for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
    try:
        sigs = s112._collect_signals(sym)
    except Exception as e:
        print(f"{sym}: detect error {e!r}"); continue
    for raw in sigs:
        sig = s112.apply_user_params(raw)
        if sig is None:
            continue
        t = pd.Timestamp(sig["signal_time"])
        if t.tz is None: t = t.tz_localize("UTC")
        if t < TARGET - pd.Timedelta(hours=36):
            continue
        dist = abs((t - TARGET).total_seconds())
        print(f"  кандидат: {sym} {sig['direction']} {t}  (до 21:00: {dist/3600:.1f}ч)")
        if best is None or dist < best[0]:
            best = (dist, sym, sig)

if best is None:
    raise SystemExit("Сигналов 1.1.2 за последние 36ч не найдено.")

dist, sym, sig = best
print(f"\nВыбран: {sym} {sig['direction']} signal_time={sig['signal_time']}")
text = s112._format_message(sym, sig)
print("\n" + "=" * 60)
print(text.replace("<b>", "").replace("</b>", ""))
print("=" * 60)

if not TOKEN or not CHAT:
    raise SystemExit("Нет DASHBOARD_BOT_TOKEN/DASHBOARD_CHAT_ID — не шлю.")
r = requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                  data={"chat_id": CHAT, "text": text, "parse_mode": "HTML"},
                  timeout=30).json()
print("\nОтправка:", "OK" if r.get("ok") else r)
