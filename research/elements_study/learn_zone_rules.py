"""learn_zone_rules.py — ОБУЧЕНИЕ правилам: какая зона интереса даст реакцию.

Задача пользователя: научиться с точной вероятностью определять зоны интереса,
которые РЕАЛЬНО дадут реакцию. На каждой зоне смотрим ИНДИКАТОРЫ (Hull/RSI/Money
Hands/ViC) в момент входа → если сделка прибыльна, учим 'ставить такую зону';
если убыточна — 'не ставить'. Выводим понятные ПРАВИЛА по индикаторам.

Источник зон: базовые FVG/OB + фракталы Вадима (78-80% precision).
ОБЯЗАТЕЛЬНО с индикаторами: каждая зона размечается контекстом индикаторов.
Период: 3 года.

Выход: правила вида 'FVG_bull + Hull=up + RSI<45 + после свипа = 76% прибыли (n=N)'.
Сохраняет output/zone_rules.json для применения при разметке через MCP.

Запуск: OMP_NUM_THREADS=1 .venv-pivot/bin/python -u research/elements_study/learn_zone_rules.py
"""
from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
_sys.path.insert(0, str(_ROOT))
_sys.path.insert(0, str(_ROOT / "smc-lib"))

import json, itertools
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
MAX_HOLD = 8
ENTRY_PCT = 0.80
SL_PCT = 0.35
YEARS = 3
END = pd.Timestamp("2026-06-01", tz="UTC")
START = END - pd.Timedelta(days=365 * YEARS)


def indicators(df):
    C = df["close"].tolist()
    hull = trend_line_asvk(C, length=49, length_mult=1.6, mode="Hma")
    s_hull = [1 if c == "up" else (-1 if c == "down" else 0) for c in hull["color"]]
    bars = list(zip(df["open"], df["high"], df["low"], df["close"], df["volume"]))
    mh = money_hands(bars)
    mhmap = {"green": 1.0, "white_weak_bull": 0.5, "neutral": 0.0, "white_weak_bear": -0.5, "red": -1.0}
    s_mh = [mhmap.get(c, 0.0) for c in mh["color"]]
    rsi = [float(x) if x is not None else 50.0 for x in rsi_wilder(C, 14)]
    L = min(len(s_hull), len(s_mh), len(rsi))
    return (np.array(s_hull[:L]), np.array(s_mh[:L]), np.array(rsi[:L]))


def gen_zones_with_context(df, s_hull, s_mh, rsi):
    """Все зоны (FVG/OB/фрактал-Вадим) + контекст индикаторов + исход TP/SL."""
    O, H, L, C = df["open"].values, df["high"].values, df["low"].values, df["close"].values
    n = len(df)
    rows = []

    def make(i, j, kind, direction, ztop, zbot):
        # касание зоны на баре i
        if direction == "LONG":
            touched = L[i] <= ztop and L[i] >= zbot * 0.985 and C[i] > zbot
            entry = zbot + ENTRY_PCT * (ztop - zbot); sl = zbot - SL_PCT * (ztop - zbot)
            if entry <= sl: return None
            tp = entry + RR * (entry - sl)
        else:
            touched = H[i] >= zbot and H[i] <= ztop * 1.015 and C[i] < ztop
            entry = ztop - ENTRY_PCT * (ztop - zbot); sl = ztop + SL_PCT * (ztop - zbot)
            if sl <= entry: return None
            tp = entry - RR * (sl - entry)
        if not touched: return None
        # симуляция
        outcome, r = "TIMEOUT", 0.0
        for k in range(i + 1, min(n, i + 1 + MAX_HOLD)):
            if direction == "LONG":
                if L[k] <= sl: outcome, r = "SL", -1.0; break
                if H[k] >= tp: outcome, r = "TP", RR; break
            else:
                if H[k] >= sl: outcome, r = "SL", -1.0; break
                if L[k] <= tp: outcome, r = "TP", RR; break
        # КОНТЕКСТ ИНДИКАТОРОВ в момент i
        tr = int(s_hull[i]) if i < len(s_hull) else 0
        mh = float(s_mh[i]) if i < len(s_mh) else 0
        rs = float(rsi[i]) if i < len(rsi) else 50
        # признаки
        hull_align = (direction == "LONG" and tr > 0) or (direction == "SHORT" and tr < 0)
        mh_align = (direction == "LONG" and mh > 0) or (direction == "SHORT" and mh < 0)
        rsi_zone = "low" if rs < 40 else ("high" if rs > 60 else "mid")
        rsi_align = (direction == "LONG" and rs < 50) or (direction == "SHORT" and rs > 50)
        # свип ликвидности перед зоной? (последние 3 бара сняли экстремум 10-бар)
        swept = False
        if i >= 14:
            recent_lo, recent_hi = L[i-3:i+1], H[i-3:i+1]
            prior_lo, prior_hi = L[i-13:i-3], H[i-13:i-3]
            if len(recent_lo) and len(prior_lo):
                if direction == "LONG":
                    swept = bool(recent_lo.min() < prior_lo.min())
                else:
                    swept = bool(recent_hi.max() > prior_hi.max())
        return dict(i=int(i), kind=kind, dir=direction, outcome=outcome, R=r,
                    hull_align=bool(hull_align), mh_align=bool(mh_align),
                    rsi_zone=rsi_zone, rsi_align=bool(rsi_align), swept=bool(swept),
                    hull=tr, mh=round(mh, 1), rsi=round(rs, 0))

    for i in range(N + 1, n - 1):
        for j in range(max(N + 1, i - 6), i):
            if H[j-1] < L[j+1]:
                r = make(i, j, "FVG", "LONG", L[j+1], H[j-1]);  rows.append(r) if r else None
            if L[j-1] > H[j+1]:
                r = make(i, j, "FVG", "SHORT", L[j-1], H[j+1]); rows.append(r) if r else None
            if C[j-1] < O[j-1] and C[j] > O[j-1]:
                r = make(i, j, "OB", "LONG", O[j-1], min(L[j-1], L[j])); rows.append(r) if r else None
            if C[j-1] > O[j-1] and C[j] < O[j-1]:
                r = make(i, j, "OB", "SHORT", max(H[j-1], H[j]), O[j-1]); rows.append(r) if r else None
        # фрактал Вадима (упрощённо: фрактал + свип ликвидности)
        if N <= i < n - N - 1:
            if L[i] < min(L[i-N:i].min(), L[i+1:i+1+N].min()):  # LL фрактал → LONG
                r = make(i+N+1 if i+N+1 < n-1 else i, i, "FRACTAL", "LONG", L[i]*1.003, L[i])
                if r: rows.append(r)
            if H[i] > max(H[i-N:i].max(), H[i+1:i+1+N].max()):  # HH → SHORT
                r = make(i+N+1 if i+N+1 < n-1 else i, i, "FRACTAL", "SHORT", H[i], H[i]*0.997)
                if r: rows.append(r)

    # дедуп
    seen = set(); uniq = []
    for r in rows:
        k = (r["i"], r["dir"], r["kind"])
        if k in seen: continue
        seen.add(k); uniq.append(r)
    return uniq


def wr(rows):
    closed = [r for r in rows if r["outcome"] in ("TP", "SL")]
    if not closed: return 0, 0, 0
    w = sum(1 for r in closed if r["outcome"] == "TP")
    return w / len(closed) * 100, len(closed), sum(r["R"] for r in rows)


def main():
    df = load_df(SYMBOL, TF).sort_index()
    df = df[(df.index >= START - pd.Timedelta(days=20)) & (df.index <= END)].reset_index(drop=False)
    tcol = df.columns[0]
    s_hull, s_mh, rsi = indicators(df)
    rows = gen_zones_with_context(df, s_hull, s_mh, rsi)
    start_i = df.index[df[tcol] >= START][0]
    rows = [r for r in rows if r["i"] >= start_i]
    print(f"[learn] {SYMBOL} {TF}, {YEARS}г, {len(rows)} зон с контекстом индикаторов", flush=True)

    base_wr, base_n, base_r = wr(rows)
    print(f"\n=== БАЗА: все зоны без фильтра ===", flush=True)
    print(f"  WR {base_wr:.0f}% (n={base_n}), R {base_r:+.0f}", flush=True)

    # ОБУЧЕНИЕ: перебираем комбинации индикаторных условий, ищем правила с высоким WR
    print(f"\n=== ОБУЧЕНИЕ ПРАВИЛАМ (какие индикаторы → прибыльная зона) ===", flush=True)
    conds = {
        "hull_align": lambda r: r["hull_align"],
        "mh_align": lambda r: r["mh_align"],
        "rsi_align": lambda r: r["rsi_align"],
        "swept": lambda r: r["swept"],
    }
    # одиночные условия
    print("\n  ОДИНОЧНЫЕ индикаторы:", flush=True)
    single = []
    for name, fn in conds.items():
        sub = [r for r in rows if fn(r)]
        w, nn, rr = wr(sub)
        single.append((name, w, nn, rr))
        delta = w - base_wr
        print(f"    {name:<14} WR {w:.0f}% (n={nn}, R {rr:+.0f})  Δ{delta:+.0f}pp", flush=True)

    # парные комбинации
    print("\n  КОМБИНАЦИИ 2-3 индикатора (топ по WR, n>=15):", flush=True)
    rules = []
    names = list(conds.keys())
    for size in [2, 3, 4]:
        for combo in itertools.combinations(names, size):
            sub = [r for r in rows if all(conds[c](r) for c in combo)]
            w, nn, rr = wr(sub)
            if nn >= 15:
                rules.append((combo, w, nn, rr))
    rules.sort(key=lambda x: -x[1])
    for combo, w, nn, rr in rules[:8]:
        print(f"    {'+'.join(combo):<40} WR {w:.0f}% (n={nn}, R {rr:+.0f})", flush=True)

    # ОБРАТНОЕ: какие условия дают УБЫТОК (не ставить такие зоны)
    print("\n  АНТИ-ПРАВИЛА (зоны которые НЕ ставить — низкий WR):", flush=True)
    anti = []
    for name, fn in conds.items():
        sub = [r for r in rows if not fn(r)]
        w, nn, rr = wr(sub)
        anti.append((f"NOT_{name}", w, nn, rr))
    anti.sort(key=lambda x: x[1])
    for name, w, nn, rr in anti[:3]:
        print(f"    {name:<14} WR {w:.0f}% (n={nn}, R {rr:+.0f}) — избегать", flush=True)

    # по типу зоны + лучший фильтр
    print("\n  ПО ТИПУ ЗОНЫ (с лучшим индикаторным фильтром hull+rsi):", flush=True)
    for kind in ["FVG", "OB", "FRACTAL"]:
        for d in ["LONG", "SHORT"]:
            sub = [r for r in rows if r["kind"] == kind and r["dir"] == d]
            subf = [r for r in sub if r["hull_align"] and r["rsi_align"]]
            w0, n0, _ = wr(sub); wf, nf, rf = wr(subf)
            if n0 >= 10:
                print(f"    {kind}_{d:<6} база {w0:.0f}%(n={n0}) → +Hull+RSI {wf:.0f}%(n={nf}, R{rf:+.0f})", flush=True)

    # лучшее правило
    best = rules[0] if rules else None
    out = dict(base_wr=base_wr, base_n=base_n,
               best_rule={"conds": list(best[0]), "wr": best[1], "n": best[2], "R": best[3]} if best else None,
               single=[{"cond": s[0], "wr": s[1], "n": s[2]} for s in single],
               rules=[{"conds": list(c), "wr": w, "n": nn, "R": rr} for c, w, nn, rr in rules[:10]])
    json.dump(out, open(_ROOT / "research/elements_study/output/zone_rules.json", "w"), ensure_ascii=False, indent=1)

    if best:
        print(f"\n=== ВЫУЧЕННОЕ ПРАВИЛО (рисовать ТОЛЬКО такие зоны) ===", flush=True)
        print(f"  Зона + [{' + '.join(best[0])}] → WR {best[1]:.0f}% (база {base_wr:.0f}%, +{best[1]-base_wr:.0f}pp)", flush=True)
        print(f"  Объём: {best[2]} сделок, R {best[3]:+.0f}", flush=True)
    print(f"\n[saved] output/zone_rules.json", flush=True)


if __name__ == "__main__":
    main()
