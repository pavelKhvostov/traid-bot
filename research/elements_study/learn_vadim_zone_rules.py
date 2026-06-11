"""learn_vadim_zone_rules.py — обучение правилам на НАСТОЯЩИХ зонах Вадима (78%) + индикаторы.

Усиление learn_zone_rules: вместо упрощённых фракталов берём настоящий детектор
ViC Vadim Core (sweep HTF-зон + maxV из 15m, ~78% precision на фрактал) + добавляем
полный индикаторный контекст (Hull/RSI/MoneyHands/ViC). Учим: при каких индикаторах
зона Вадима даёт прибыльную сделку → рисовать только такие.

3 года, BTC. ОБЯЗАТЕЛЬНО с индикаторами.

Запуск: OMP_NUM_THREADS=1 .venv-pivot/bin/python -u research/elements_study/learn_vadim_zone_rules.py
"""
from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
_sys.path.insert(0, str(_ROOT))
_sys.path.insert(0, str(_ROOT / "smc-lib"))

import importlib.util as _ilu
import json, itertools
import numpy as np
import pandas as pd
from data_manager import load_df
from indicators.trend_line_asvk import trend_line_asvk
from indicators.rsi_asvk import rsi_wilder
from indicators.money_hands_asvk import money_hands

# настоящий детектор Вадима из etap_185
_s185 = _ilu.spec_from_file_location("e185", _ROOT / "research/elements_study/etap_185_vadim_reversals_nn.py")
_e185 = _ilu.module_from_spec(_s185); _s185.loader.exec_module(_e185)

SYMBOL = "BTCUSDT"
RR = 2.2
MAX_HOLD = 8
N = 2
END = pd.Timestamp("2026-06-01", tz="UTC")
START = END - pd.Timedelta(days=365 * 3)


def indicators_12h(df):
    C = df["close"].tolist()
    hull = trend_line_asvk(C, length=49, length_mult=1.6, mode="Hma")
    s_hull = [1 if c == "up" else (-1 if c == "down" else 0) for c in hull["color"]]
    bars = list(zip(df["open"], df["high"], df["low"], df["close"], df["volume"]))
    mh = money_hands(bars)
    mhmap = {"green": 1.0, "white_weak_bull": 0.5, "neutral": 0.0, "white_weak_bear": -0.5, "red": -1.0}
    s_mh = [mhmap.get(c, 0.0) for c in mh["color"]]
    rsi = [float(x) if x is not None else 50.0 for x in rsi_wilder(C, 14)]
    L = min(len(s_hull), len(s_mh), len(rsi))
    return np.array(s_hull[:L]), np.array(s_mh[:L]), np.array(rsi[:L])


def main():
    print(f"[learn-vadim] генерирую настоящие Core-сигналы Вадима (sweep+maxV)...", flush=True)
    vsig = _e185.gen_vadim_core_signals(SYMBOL)
    if vsig is None or vsig.empty:
        print("[ERR] нет сигналов Вадима"); return
    vsig = vsig[(vsig["signal_time"] >= START) & (vsig["signal_time"] <= END)].copy()
    print(f"  {len(vsig)} Core-сигналов Вадима за 3 года", flush=True)

    # 12h данные + индикаторы
    df = load_df(SYMBOL, "12h").sort_index()
    df = df[(df.index >= START - pd.Timedelta(days=20)) & (df.index <= END)]
    dfr = df.reset_index(drop=False); tcol = dfr.columns[0]
    s_hull, s_mh, rsi = indicators_12h(dfr)
    H, L, C = dfr["high"].values, dfr["low"].values, dfr["close"].values
    n = len(dfr)
    tmap = {int(t.timestamp()): k for k, t in enumerate(dfr[tcol])}

    rows = []
    for _, sg in vsig.iterrows():
        ts = int(sg["signal_time"].timestamp())
        i = tmap.get(ts)
        if i is None or i >= n - 1: continue
        direction = "LONG" if sg["direction"] == "LONG" else "SHORT"
        # entry/SL/TP по канону: фрактал-разворот, SL за экстремум, RR 2.2
        if direction == "LONG":
            entry = C[i]; sl = L[i] * 0.997; risk = entry - sl
            if risk <= 0: continue
            tp = entry + RR * risk
        else:
            entry = C[i]; sl = H[i] * 1.003; risk = sl - entry
            if risk <= 0: continue
            tp = entry - RR * risk
        # симуляция
        outcome, r = "TIMEOUT", 0.0
        for k in range(i + 1, min(n, i + 1 + MAX_HOLD)):
            if direction == "LONG":
                if L[k] <= sl: outcome, r = "SL", -1.0; break
                if H[k] >= tp: outcome, r = "TP", RR; break
            else:
                if H[k] >= sl: outcome, r = "SL", -1.0; break
                if L[k] <= tp: outcome, r = "TP", RR; break
        # КОНТЕКСТ ИНДИКАТОРОВ
        tr = int(s_hull[i]) if i < len(s_hull) else 0
        mh = float(s_mh[i]) if i < len(s_mh) else 0
        rs = float(rsi[i]) if i < len(rsi) else 50
        hull_align = (direction == "LONG" and tr > 0) or (direction == "SHORT" and tr < 0)
        mh_align = (direction == "LONG" and mh > 0) or (direction == "SHORT" and mh < 0)
        rsi_oversold = (direction == "LONG" and rs < 45) or (direction == "SHORT" and rs > 55)
        is_fractal = bool(sg["is_fractal"])
        rows.append(dict(i=i, dir=direction, outcome=outcome, R=r,
                         hull_align=bool(hull_align), mh_align=bool(mh_align),
                         rsi_oversold=bool(rsi_oversold), is_fractal=is_fractal,
                         hull=tr, mh=round(mh,1), rsi=round(rs,0)))

    def wr(rs_):
        cl = [r for r in rs_ if r["outcome"] in ("TP","SL")]
        if not cl: return 0,0,0
        w = sum(1 for r in cl if r["outcome"]=="TP")
        return w/len(cl)*100, len(cl), sum(r["R"] for r in rs_)

    base_wr, base_n, base_r = wr(rows)
    frac_rate = np.mean([r["is_fractal"] for r in rows])*100
    print(f"\n=== БАЗА: зоны Вадима без индикаторного фильтра ===", flush=True)
    print(f"  {len(rows)} зон, стали фракталом {frac_rate:.0f}%, сделка WR {base_wr:.0f}% (n={base_n}, R {base_r:+.0f})", flush=True)

    conds = {
        "hull_align": lambda r: r["hull_align"],
        "mh_align": lambda r: r["mh_align"],
        "rsi_oversold": lambda r: r["rsi_oversold"],
        "is_fractal": lambda r: r["is_fractal"],
    }
    print(f"\n=== ОБУЧЕНИЕ: индикаторы → прибыльная зона Вадима ===", flush=True)
    print("  ОДИНОЧНЫЕ:", flush=True)
    singles=[]
    for name, fn in conds.items():
        sub=[r for r in rows if fn(r)]; w,nn,rr=wr(sub)
        singles.append((name,w,nn,rr))
        print(f"    {name:<14} WR {w:.0f}% (n={nn}, R{rr:+.0f})  Δ{w-base_wr:+.0f}pp", flush=True)

    print("\n  КОМБИНАЦИИ (топ по WR, n>=10):", flush=True)
    rules=[]
    names=list(conds.keys())
    for size in [2,3]:
        for combo in itertools.combinations(names,size):
            sub=[r for r in rows if all(conds[c](r) for c in combo)]
            w,nn,rr=wr(sub)
            if nn>=10: rules.append((combo,w,nn,rr))
    rules.sort(key=lambda x:-x[1])
    for combo,w,nn,rr in rules[:8]:
        print(f"    {'+'.join(combo):<42} WR {w:.0f}% (n={nn}, R{rr:+.0f})", flush=True)

    best = rules[0] if rules else None
    if best:
        print(f"\n=== ВЫУЧЕННОЕ ПРАВИЛО (рисовать ТОЛЬКО такие зоны Вадима) ===", flush=True)
        print(f"  Вадим + [{' + '.join(best[0])}] → WR {best[1]:.0f}% (база {base_wr:.0f}%, +{best[1]-base_wr:.0f}pp)", flush=True)
        print(f"  Объём {best[2]} сделок, R {best[3]:+.0f}", flush=True)

    json.dump(dict(base_wr=base_wr, base_n=base_n, frac_rate=frac_rate,
                   singles=[{"cond":s[0],"wr":s[1],"n":s[2]} for s in singles],
                   rules=[{"conds":list(c),"wr":w,"n":nn,"R":rr} for c,w,nn,rr in rules[:10]]),
              open(_ROOT/"research/elements_study/output/vadim_zone_rules.json","w"), ensure_ascii=False, indent=1)
    print(f"\n[saved] output/vadim_zone_rules.json", flush=True)


if __name__ == "__main__":
    main()
