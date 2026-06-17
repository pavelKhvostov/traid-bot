"""etap_256 - ФИНАНСОВЫЙ тест разворотного слоя: меняет ли он ожидание 1.1.1?

Вопрос трейдера: описательная детекция разворота — это деньги или мишура? Деньги
появляются ТОЛЬКО если разворотный контекст НА МОМЕНТ ВХОДА меняет WR / R-на-сделку
реально зарабатывающей стратегии. Проверяем на дедуп-книге 1.1.1 SWEPT (BTC, fixed
RR=2.2, approved-версия live) — той же, что в etap_249.

Тэги контекста (всё известно НА ВХОДЕ, без подглядывания):
  - weekly_shape: структура текущей недели (свип PWH/PWL / продолжение / внутри)
  - wk_aligned : недельный свип В СТОРОНУ сделки (SHORT при свипе PWH вверх и т.п.)
  - ib_swept   : цена сняла утренний IB-экстремум до входа В СТОРОНУ фейда
  - dev_shape  : форма дня as-of входа (developing) — обычно range/trend (вход ДО разворота)

Вывод по каждому бакету: n, WR, R/сделку, ΣR, год-стабильность (бьёт ли базу в
большинстве лет). Сравнение с базой. Если ни один бакет робастно не бьёт базу на
значимый R — слой НЕ даёт денег как фильтр (честный негатив), остаётся как
риск-контекст. Цифры в R; $ = R × риск-на-сделку.

Запуск: set PYTHONIOENCODING=utf-8
        venv/Scripts/python.exe research/daily_engine/etap_256_reversal_pnl_overlay.py
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
from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_1_floating import (detect_signals_111, check_swept,
                                                 build_entry_sl, simulate_floating,
                                                 build_score_series)
import etap_217_daytype_layer as L
import reversal as RV

RR = 2.2


def load_book():
    df_1d = load_df("BTCUSDT", "1d"); df_4h = load_df("BTCUSDT", "4h"); df_1h = load_df("BTCUSDT", "1h")
    df_12h = compose_from_base(df_1h, "12h"); df_6h = compose_from_base(df_1h, "6h"); df_2h = compose_from_base(df_1h, "2h")
    df_15m = load_df("BTCUSDT", "15m"); df_1m = load_df("BTCUSDT", "1m"); df_20m = compose_from_base(df_1m, "20m")
    for d in (df_1h, df_1m):
        if d.index.tz is None: d.index = d.index.tz_localize("UTC")
    print("[detect] 1.1.1 + SWEPT (BTC)...")
    signals = detect_signals_111(df_1d, df_12h, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m)
    swept = [s for s in signals if check_swept(s, df_1h, df_2h)]
    seen, dedup = set(), []
    for s in swept:
        k = (pd.Timestamp(s["signal_time"]).isoformat(), s["direction"], tuple(s["fvg_zone"]))
        if k in seen: continue
        seen.add(k); dedup.append(s)
    print(f"  raw {len(signals)} -> SWEPT {len(swept)} -> dedup {len(dedup)}")
    score_long, score_short = build_score_series(df_1h)

    rows = []
    for s in dedup:
        res = simulate_floating(s, df_1m, df_1h, score_long, score_short,
                                R_cap=RR, threshold=-1e9, confirm=10**6, max_hold_days=3650)
        if res is None or res.outcome not in ("win", "loss"):
            continue
        t = pd.Timestamp(s["signal_time"]); t = t.tz_localize("UTC") if t.tz is None else t
        day = t.normalize(); direction = s["direction"]
        bars = df_1h[(df_1h.index.normalize() == day) & (df_1h.index <= t)]
        # --- разворотный контекст as-of входа ---
        dev_shape = "n/a"; ib_swept_for = False
        if len(bars) >= L.IB + 2:
            rec = RV.classify_day(bars, developing=True)
            if rec:
                dev_shape = rec["shape"]
            ib_h = bars["high"].iloc[:L.IB].max(); ib_l = bars["low"].iloc[:L.IB].min()
            took_high = bars["high"].max() > ib_h
            took_low = bars["low"].min() < ib_l
            # «снят экстремум в сторону фейда»: SHORT хочет снятый верх, LONG — снятый низ
            ib_swept_for = (took_high if direction == "SHORT" else took_low)
        d1 = df_1h[df_1h.index <= t].resample("1D").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
        wk = RV.weekly_structure(d1)
        wk_shape = wk["shape"] if wk else "n/a"
        # недельный свип в сторону сделки = confluence
        wk_aligned = ((direction == "SHORT" and wk_shape == "wk_sweep_high") or
                      (direction == "LONG" and wk_shape == "wk_sweep_low"))
        rows.append(dict(signal_time=t, year=t.year, win=int(res.outcome == "win"),
                         R=res.R, direction=direction, dev_shape=dev_shape,
                         ib_swept_for=ib_swept_for, wk_shape=wk_shape,
                         wk_aligned=wk_aligned))
    return pd.DataFrame(rows)


def report(book):
    n0 = len(book); w0 = book.win.sum()
    wr0 = w0 / n0 * 100; r0 = (w0 * RR - (n0 - w0)); rpt0 = r0 / n0
    print("\n" + "=" * 78)
    print(f"БАЗА 1.1.1 SWEPT (BTC, RR=2.2): n={n0}  WR {wr0:.1f}%  SR {r0:+.1f}R  "
          f"R/сделку {rpt0:+.3f}  ({book.signal_time.min().date()}..{book.signal_time.max().date()})")
    print("=" * 78)

    def yr_stable(g, base):
        yr = g.groupby("year").win.mean()
        yr = yr[g.groupby("year").size() >= 4]
        if len(yr) < 3:
            return "(мало лет)"
        beats = (yr * 100 > base).mean()
        return f"бьёт базу в {int(beats*len(yr))}/{len(yr)} лет"

    def show(title, col):
        print(f"\n--- {title} ---")
        print(f"  {'бакет':<22}{'n':>5}{'WR':>7}{'R/сд':>8}{'ΣR':>8}   год-стаб vs база")
        for val, g in book.groupby(col, observed=True):
            n = len(g); w = g.win.sum()
            if n < 8:
                continue
            wr = w / n * 100; sr = w * RR - (n - w); rpt = sr / n
            flag = yr_stable(g, wr0)
            mark = "  <== ЛУЧШЕ базы" if rpt > rpt0 + 0.05 else ("  (хуже)" if rpt < rpt0 - 0.05 else "")
            print(f"  {str(val):<22}{n:>5}{wr:>6.1f}%{rpt:>+8.3f}{sr:>+7.1f}R   {flag}{mark}")

    show("Недельная структура на входе", "wk_shape")
    show("Недельный свип В СТОРОНУ сделки (confluence)", "wk_aligned")
    show("Снят утр. IB-экстремум в сторону фейда", "ib_swept_for")
    show("Форма дня as-of входа (developing)", "dev_shape")


def main():
    book = load_book()
    if book.empty:
        print("нет сделок"); return
    report(book)
    print("\nЧитать: 'R/сд' — ожидание на сделку. Бакет имеет ДЕНЕЖНЫЙ смысл только если")
    print("его R/сделку РОБАСТНО (год-стабильно) выше базы И сам бакет не мизерный по n.")


if __name__ == "__main__":
    main()
