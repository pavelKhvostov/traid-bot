"""etap_259 - BLOCK 1: Breaker block (сломанный OB со сменой полярности).

Канон (vault SMC-обзор): breaker = OB, который НЕ удержал уровень и был пробит ->
полярность флипается. Бычий breaker = SHORT-OB (supply), который цена ПРОБИЛА вверх
(close>top) -> при возврате вниз в зону = поддержка -> LONG. Зеркально для медвежьего.

Вход = возврат в флипнутую зону (лимит у края), SL за зоной, fixed RR=2.2.
Детект OB на HTF (4h/12h), исполнение на 1h. Судим общим zone_harness:
OOS-нет (вся история), год-стабильность, R/просадка, BTC->ETH/SOL.

Запуск: set PYTHONIOENCODING=utf-8
        venv/Scripts/python.exe research/daily_engine/etap_259_breaker.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np, pandas as pd

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(ROOT))
from data_manager import load_df, compose_from_base
from strategies.strategy_1_1_1 import detect_ob_pair
import zone_harness as ZH

RR = 2.2


def gen_breakers(df_tf, entry_pct=0.0, sl_buf=0.10, min_risk=0.003, max_risk=0.04,
                 break_wait=120):
    """Сломанные OB -> breaker-сигналы (time=бар пробоя, вход на возврате)."""
    H = df_tf["high"].values; Lo = df_tf["low"].values; C = df_tf["close"].values
    idx = df_tf.index
    sig = []
    for i in range(1, len(df_tf)):
        ob = detect_ob_pair(df_tf, i)
        if ob is None:
            continue
        height = ob.top - ob.bottom
        if height <= 0:
            continue
        broke = None
        for j in range(i + 1, min(i + 1 + break_wait, len(df_tf))):
            if ob.direction == "SHORT" and C[j] > ob.top:     # supply failed -> bullish breaker
                broke = ("LONG", j); break
            if ob.direction == "LONG" and C[j] < ob.bottom:   # demand failed -> bearish breaker
                broke = ("SHORT", j); break
            # если зона ушла слишком далеко без пробоя в нужную сторону — бросаем
        if broke is None:
            continue
        bdir, bj = broke
        if bdir == "LONG":
            entry = ob.top - entry_pct * height
            sl = ob.bottom - sl_buf * height
        else:
            entry = ob.bottom + entry_pct * height
            sl = ob.top + sl_buf * height
        risk_pct = abs(entry - sl) / entry
        if not (min_risk <= risk_pct <= max_risk):
            continue
        sig.append(dict(time=idx[bj], direction=bdir, entry=float(entry), sl=float(sl)))
    # дедуп близких (один бар пробоя + направление)
    seen, out = set(), []
    for s in sorted(sig, key=lambda x: x["time"]):
        k = (s["time"], s["direction"], round(s["entry"], 1))
        if k in seen: continue
        seen.add(k); out.append(s)
    return out


def run_symbol(sym, det_tf="4h"):
    df1h = load_df(sym, "1h")
    if df1h.empty:
        print(f"{sym}: нет данных"); return None
    if df1h.index.tz is None: df1h.index = df1h.index.tz_localize("UTC")
    df_tf = compose_from_base(df1h, det_tf) if det_tf != "1h" else df1h
    sigs = gen_breakers(df_tf)
    book = ZH.simulate(sigs, df1h, rr=RR)
    return ZH.report(book, rr=RR, title=f"{sym} BREAKER (детект {det_tf}, исп. 1h) | сигналов {len(sigs)}")


def main():
    for tf in ("4h", "12h"):
        print("\n" + "#" * 76)
        print(f"#  ДЕТЕКТ-TF = {tf}")
        print("#" * 76)
        for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
            run_symbol(sym, det_tf=tf)


if __name__ == "__main__":
    main()
