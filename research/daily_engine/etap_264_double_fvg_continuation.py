"""etap_264 — ICT-2022 trend-continuation на DOUBLE-FVG (signal-able, в стиле 1.1.x).

Операционализирует ЕДИНСТВЕННУЮ год-стабильную находку проекта (etap_254 double-FVG):
по тренду (EMA50) + сильное смещение (displacement >= DISP ATR) -> продолжение 61%, ход 3.14×.
Это CONTINUATION (не counter-trend 1.1.1) -> genuinely distinct.

Сигнал: два подряд однонаправленных FVG (=displacement-leg) на TF; фильтры тренд+смещение;
вход ЛИМИТ на возврат в верхний (LONG) / нижний (SHORT) FVG, SL за ним, fixed RR.
Судим общим zone_harness: WR vs breakeven (1/(1+RR)), ΣR, R/сд, год-стаб, BTC/ETH/SOL.

Запуск: set PYTHONIOENCODING=utf-8
        venv/Scripts/python.exe research/daily_engine/etap_264_double_fvg_continuation.py BTCUSDT
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
import zone_harness as ZH

DISP = 2.9          # порог смещения в ATR (год-стабильная находка etap_254)
PAIR_K = 4          # 2-й FVG в пределах K баров от 1-го
BUF = 0.001
RR_GRID = [1.5, 2.0, 2.5, 3.0]


def find_fvgs(d):
    h = d["high"].values; l = d["low"].values; out = []
    for i in range(2, len(d)):
        if h[i - 2] < l[i]:
            out.append(("LONG", float(h[i - 2]), float(l[i]), i - 2, i))     # bull gap
        elif l[i - 2] > h[i]:
            out.append(("SHORT", float(h[i]), float(l[i - 2]), i - 2, i))     # bear gap
    return out


def gen_signals(df_tf, atr, ema):
    c = df_tf["close"].values; idx = df_tf.index
    fvgs = find_fvgs(df_tf)
    sig = []
    for a in range(len(fvgs)):
        Ad, Ab, At, Ac0, Ac2 = fvgs[a]
        for b in range(a + 1, len(fvgs)):
            Bd, Bb, Bt, Bc0, Bc2 = fvgs[b]
            if Bd != Ad:
                continue
            if Bc2 - Ac2 > PAIR_K:
                break
            j = Bc2
            s = atr[j]
            if not (s > 0):
                continue
            disp = (c[j] - c[Ac0]) / s if Ad == "LONG" else (c[Ac0] - c[j]) / s
            if disp < DISP:
                continue
            trend_ok = (c[j] > ema[j]) if Ad == "LONG" else (c[j] < ema[j])
            if not trend_ok:
                continue
            mid = (Bb + Bt) / 2
            if Ad == "LONG":
                entry = mid; sl = Bb * (1 - BUF)
            else:
                entry = mid; sl = Bt * (1 + BUF)
            sig.append(dict(time=idx[j], direction=Ad, entry=float(entry), sl=float(sl)))
            break   # одна сделка на двойной FVG (по 2-му)
    # дедуп по времени+направлению
    seen, out = set(), []
    for sx in sorted(sig, key=lambda x: x["time"]):
        k = (sx["time"], sx["direction"], round(sx["entry"], 1))
        if k in seen: continue
        seen.add(k); out.append(sx)
    return out


def run(sym, det_tf="12h"):
    df1h = load_df(sym, "1h")
    if df1h.empty:
        print(f"{sym}: нет данных"); return
    if df1h.index.tz is None: df1h.index = df1h.index.tz_localize("UTC")
    d = compose_from_base(df1h, det_tf) if det_tf != "1h" else df1h
    if d.index.tz is None: d.index = d.index.tz_localize("UTC")
    ema = d["close"].ewm(span=50, adjust=False).mean().values
    pc = d["close"].shift(1)
    tr = pd.concat([d.high - d.low, (d.high - pc).abs(), (d.low - pc).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean().values
    sigs = gen_signals(d, atr, ema)
    nL = sum(1 for s in sigs if s["direction"] == "LONG"); nS = len(sigs) - nL
    print(f"\n{'#'*70}\n {sym} double-FVG continuation (детект {det_tf}, disp>={DISP}ATR+тренд) | "
          f"сигналов {len(sigs)} (LONG {nL}/SHORT {nS})")
    best = None
    for rr in RR_GRID:
        book = ZH.simulate(sigs, df1h, rr=rr, wait_bars=240, hold_bars=720)
        r = ZH.report(book, rr=rr, title=f"{sym} RR={rr}")
        if r and (best is None or r["rpt"] > best[1]):
            best = (rr, r["rpt"], book)
    if best:
        rr, rpt, book = best
        print(f"\n  best RR={rr}: по годам ->", end=" ")
        cl = book[book.outcome.isin(["win", "loss"])]
        for yr, g in cl.groupby("year"):
            print(f"{yr}:{g.R.sum():+.0f}R", end=" ")
        print()


def main():
    syms = [sys.argv[1]] if len(sys.argv) > 1 else ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    for sym in syms:
        run(sym)


if __name__ == "__main__":
    main()
