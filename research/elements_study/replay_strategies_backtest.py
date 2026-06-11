"""replay_strategies_backtest.py — визуальный бэктест прибыльных стратегий за год.

Идея пользователя: взять год, прибыльные стратегии + индикаторы, рисовать зону
интереса, смотреть индикаторы в момент сигнала → решение вход/не вход, вести
до TP/SL, помечать прибыль ЗЕЛЁНЫМ, убыток КРАСНЫМ. Рисунки не стирать.

Стратегии (с реальными индикаторами):
- C2: OB-6h × FVG-2h, фильтр EMA200(2h) pro-trend. WR 55%, 0 bad years.
- 1.1.x: OB+FVG каскад, фильтр 4-indicator score (Hull/MH/RSI/ASVK).
- Фракталы Вадима: sweep HTF-зон + maxV, 78% precision.

Этот движок считает ВСЕ сделки за год с индикаторным фильтром, ведёт каждую до
TP(2.2R)/SL, выдаёт список для нанесения на график (зона, entry, sl, tp, исход).
Цвет: зелёный=прибыль(TP), красный=убыток(SL).

Выход: output/replay_trades_year.json — список сделок для MCP-разметки.

Запуск: OMP_NUM_THREADS=1 .venv-pivot/bin/python -u research/elements_study/replay_strategies_backtest.py
"""
from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
_sys.path.insert(0, str(_ROOT))
_sys.path.insert(0, str(_ROOT / "smc-lib"))

import json
import numpy as np
import pandas as pd
from data_manager import load_df
from indicators.trend_line_asvk import trend_line_asvk
from indicators.rsi_asvk import rsi_wilder, adjusted_rsi
from indicators.money_hands_asvk import money_hands

SYMBOL = "BTCUSDT"
TF = "12h"
N = 2
RR = 2.2
MAX_HOLD = 8          # макс держать (баров) — таймаут
ENTRY_PCT = 0.80      # вход в зону (как 1.1.1)
SL_PCT = 0.35
START = pd.Timestamp("2025-06-01", tz="UTC")
END = pd.Timestamp("2026-06-01", tz="UTC")


def build_indicators(df):
    """4 индикатора проекта на 12h: score = mean(hull, mh, rsi, asvk) ∈ [-1,1]."""
    C = df["close"].tolist()
    hull = trend_line_asvk(C, length=49, length_mult=1.6, mode="Hma")
    s_hull = np.array([1.0 if c == "up" else (-1.0 if c == "down" else 0.0) for c in hull["color"]])
    bars = list(zip(df["open"], df["high"], df["low"], df["close"], df["volume"]))
    mh = money_hands(bars)
    mhmap = {"green": 1.0, "white_weak_bull": 0.5, "neutral": 0.0, "white_weak_bear": -0.5, "red": -1.0}
    s_mh = np.array([mhmap.get(c, 0.0) for c in mh["color"]])
    rsi = np.array([float(x) if x is not None else 50.0 for x in rsi_wilder(C, 14)])
    s_rsi = np.clip((rsi - 50) / 50, -1, 1)
    asvk = adjusted_rsi(C, 14)
    def arr(l): return np.array([float(x) if x is not None else np.nan for x in l])
    e3, ab, be = arr(asvk["ema_3"]), arr(asvk["above"]), arr(asvk["below"])
    s_asvk = np.where(np.isnan(e3) | np.isnan(ab) | np.isnan(be), 0.0,
                      np.where(e3 > ab, 1.0, np.where(e3 < be, -1.0, 0.0)))
    L = min(len(s_hull), len(s_mh), len(s_rsi), len(s_asvk))
    score = (s_hull[:L] + s_mh[:L] + s_rsi[:L] + s_asvk[:L]) / 4.0
    return s_hull, score, rsi


def gen_signals(df, s_hull, score):
    """Сигналы зон с ИНДИКАТОРНЫМ фильтром (вход только если индикаторы согласны).

    Зона = непробитый FVG/OB (канон). Фильтр: Hull-тренд согласен с направлением
    зоны (это и есть 'смотрю индикаторы → решаю вход/не вход').
    """
    O, H, L, C = df["open"].values, df["high"].values, df["low"].values, df["close"].values
    n = len(df)
    sigs = []
    for i in range(N + 1, n - 1):
        # ищем зоны, рождённые недавно (последние 6 баров), которые цена тестирует на баре i
        for j in range(max(N + 1, i - 6), i):
            # bullish FVG (канон c1-c3): j-1, j, j+1
            if H[j-1] < L[j+1]:
                ztop, zbot = L[j+1], H[j-1]
                _maybe_add(sigs, df, i, j, "FVG", "LONG", ztop, zbot, s_hull, O, H, L, C)
            if L[j-1] > H[j+1]:
                ztop, zbot = L[j-1], H[j+1]
                _maybe_add(sigs, df, i, j, "FVG", "SHORT", ztop, zbot, s_hull, O, H, L, C)
            # OB
            if C[j-1] < O[j-1] and C[j] > O[j-1]:
                _maybe_add(sigs, df, i, j, "OB", "LONG", O[j-1], min(L[j-1], L[j]), s_hull, O, H, L, C)
            if C[j-1] > O[j-1] and C[j] < O[j-1]:
                _maybe_add(sigs, df, i, j, "OB", "SHORT", max(H[j-1], H[j]), O[j-1], s_hull, O, H, L, C)
    # дедуп по (signal_time, direction, round entry)
    seen = set(); uniq = []
    for s in sigs:
        k = (s["sig_i"], s["dir"], round(s["entry"], -1))
        if k in seen: continue
        seen.add(k); uniq.append(s)
    return uniq


def _maybe_add(sigs, df, i, j, kind, direction, ztop, zbot, s_hull, O, H, L, C):
    # цена тестирует зону на баре i?
    if direction == "LONG":
        touched = L[i] <= ztop and L[i] >= zbot * 0.99 and C[i] > zbot
    else:
        touched = H[i] >= zbot and H[i] <= ztop * 1.01 and C[i] < ztop
    if not touched:
        return
    # ИНДИКАТОРНЫЙ ФИЛЬТР (решение вход/не вход): Hull-тренд согласен
    tr = s_hull[i] if i < len(s_hull) else 0
    if direction == "LONG" and tr <= 0:
        return  # тренд не вверх → НЕ входим
    if direction == "SHORT" and tr >= 0:
        return  # тренд не вниз → НЕ входим
    # entry/SL/TP
    if direction == "LONG":
        entry = zbot + ENTRY_PCT * (ztop - zbot)
        sl = zbot - SL_PCT * (ztop - zbot)
        risk = entry - sl
        if risk <= 0: return
        tp = entry + RR * risk
    else:
        entry = ztop - ENTRY_PCT * (ztop - zbot)
        sl = ztop + SL_PCT * (ztop - zbot)
        risk = sl - entry
        if risk <= 0: return
        tp = entry - RR * risk
    sigs.append(dict(sig_i=i, j=j, kind=kind, dir=direction,
                     ztop=float(ztop), zbot=float(zbot),
                     entry=float(entry), sl=float(sl), tp=float(tp)))


def simulate(df, sig):
    """Ведём сделку от sig_i+1 до TP/SL/таймаут. Возвращает исход + R."""
    H, L = df["high"].values, df["low"].values
    n = len(df)
    i = sig["sig_i"]
    for k in range(i + 1, min(n, i + 1 + MAX_HOLD)):
        if sig["dir"] == "LONG":
            # SL раньше TP при тае (анти-оптимизм)
            if L[k] <= sig["sl"]:
                return "SL", -1.0, k
            if H[k] >= sig["tp"]:
                return "TP", RR, k
        else:
            if H[k] >= sig["sl"]:
                return "SL", -1.0, k
            if L[k] <= sig["tp"]:
                return "TP", RR, k
    return "TIMEOUT", 0.0, min(n - 1, i + MAX_HOLD)


def main():
    df = load_df(SYMBOL, TF).sort_index()
    df = df[(df.index >= START - pd.Timedelta(days=20)) & (df.index <= END)].reset_index(drop=False)
    tcol = df.columns[0]
    s_hull, score, rsi = build_indicators(df)
    print(f"[backtest] {SYMBOL} {TF}: {len(df)} баров, {START.date()}..{END.date()}", flush=True)

    sigs = gen_signals(df, s_hull, score)
    # только в обучающем окне
    start_i = df.index[df[tcol] >= START][0]
    sigs = [s for s in sigs if s["sig_i"] >= start_i]

    trades = []
    for s in sigs:
        outcome, r, exit_k = simulate(df, s)
        s["outcome"] = outcome; s["R"] = r
        s["time"] = int(df[tcol].iloc[s["sig_i"]].timestamp())
        s["exit_time"] = int(df[tcol].iloc[exit_k].timestamp())
        s["date"] = str(df[tcol].iloc[s["sig_i"]].date())
        trades.append(s)

    wins = [t for t in trades if t["outcome"] == "TP"]
    losses = [t for t in trades if t["outcome"] == "SL"]
    to = [t for t in trades if t["outcome"] == "TIMEOUT"]
    closed = len(wins) + len(losses)
    wr = len(wins) / closed * 100 if closed else 0
    totR = sum(t["R"] for t in trades)
    print(f"\n=== РЕЗУЛЬТАТ (год, индикаторный фильтр Hull) ===", flush=True)
    print(f"  Сделок: {len(trades)} | TP: {len(wins)} | SL: {len(losses)} | timeout: {len(to)}", flush=True)
    print(f"  Winrate: {wr:.0f}% | Итого R: {totR:+.1f} | R/сделку: {totR/len(trades):+.2f}", flush=True)
    by = {}
    for t in trades:
        by.setdefault(t["kind"]+"_"+t["dir"], [0,0,0.0])
        by[t["kind"]+"_"+t["dir"]][0]+=1
        if t["outcome"]=="TP": by[t["kind"]+"_"+t["dir"]][1]+=1
        by[t["kind"]+"_"+t["dir"]][2]+=t["R"]
    print(f"\n  По типам:", flush=True)
    for k,(nn,w,rr) in sorted(by.items(),key=lambda x:-x[1][2]):
        print(f"    {k:<12} n={nn:<4} TP={w:<4} R={rr:+.1f}", flush=True)

    out = _ROOT / "research/elements_study/output/replay_trades_year.json"
    json.dump(trades, open(out, "w"), ensure_ascii=False, indent=1)
    print(f"\n[saved] {len(trades)} сделок → {out}", flush=True)
    print(f"  Зелёные (TP): {len(wins)}, Красные (SL): {len(losses)}, Серые (timeout): {len(to)}", flush=True)


if __name__ == "__main__":
    main()
