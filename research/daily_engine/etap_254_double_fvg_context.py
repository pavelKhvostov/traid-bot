"""etap_254 — double-FVG ПО КОНТЕКСТУ: зависит ли исход от условий формации.

Гипотеза пользователя: результативность double-FVG зависит от того, ГДЕ и ПОСЛЕ ЧЕГО
он образован. Сырое «направление=монетка» может маскировать разные контексты.

События: все double-FVG (etap_253 find_fvg) на 12h/1d/2d/3d, BTC+ETH (пул, тег tf/sym).
Контекст на баре подтверждения i (всё из данных ≤ i, без лукахеда):
  loc20      — позиция close в 20-баровом диапазоне (премиум>0.66 / eq / дисконт<0.33)
  aligned    — FVG по тренду (close vs EMA50): bull&>EMA / bear&<EMA = continuation-локация
  swept      — перед смещением сняли прошлый swing-экстремум (ICT liquidity grab)
  disp_atr   — размах 3-барного смещения / ATR (сила displacement): big vs small
  mom_before — ход за 10 баров ДО, в сторону FVG (>0 = после движения туда; <0 = против)
Forward: dir_next, cont5, fill5, fwd_range× — по корзинам + год-стабильность направления.

Дисциплина: малый набор контекстов; n и per-year знак; честный мультитест-caveat.
Пул ТФ → один ценовой импульс может дать FVG на нескольких ТФ (корреляция, n завышен) — caveat.

Запуск: venv/Scripts/python.exe research/daily_engine/etap_254_double_fvg_context.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np, pandas as pd

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(HERE))
from data_manager import compose_from_base, load_df
from etap_253_ict_fvg_formations import find_fvg

SYMS = ["BTCUSDT", "ETHUSDT"]
NFWD = 5


def ema(a, n):
    return pd.Series(a).ewm(span=n, adjust=False).mean().values


def collect(sym, tf, df):
    if len(df) < 70:
        return []
    o, h, l, c = (df[x].values for x in ["open", "high", "low", "close"])
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr = pd.Series(tr).rolling(14).mean().shift(1).values
    e50 = ema(c, 50)
    med_rng = pd.Series(h - l).rolling(20).median().shift(1).values
    fvgs = find_fvg(df)
    by = {i: d for i, d, lo, hi in fvgs}
    rows = []
    for i, d, lo, hi in fvgs:
        if not ((i - 1) in by and by[i - 1] == d):   # только ДВОЙНЫЕ
            continue
        if i + NFWD >= len(df) or i < 55:
            continue
        w_hi = np.max(h[i - 19:i + 1]); w_lo = np.min(l[i - 19:i + 1])
        pos = (c[i] - w_lo) / (w_hi - w_lo) if w_hi > w_lo else 0.5
        aligned = int((d > 0 and c[i] > e50[i]) or (d < 0 and c[i] < e50[i]))
        # sweep: перед 3-барным смещением снят прошлый 10-баровый экстремум, затем reclaim
        if d > 0:
            swept = int(np.min(l[i - 2:i + 1]) < np.min(l[i - 12:i - 2]) and c[i] > np.min(l[i - 12:i - 2]))
        else:
            swept = int(np.max(h[i - 2:i + 1]) > np.max(h[i - 12:i - 2]) and c[i] < np.max(h[i - 12:i - 2]))
        disp_atr = (np.max(h[i - 2:i + 1]) - np.min(l[i - 2:i + 1])) / atr[i] if atr[i] and atr[i] > 0 else np.nan
        mom_before = (c[i - 3] / c[i - 13] - 1) * d
        # forward
        dir_next = int(np.sign(c[i + 1] - c[i]) == d)
        cont = int((c[i + NFWD] - c[i]) * d > 0)
        fill = int(any(l[j] <= hi and h[j] >= lo for j in range(i + 1, i + 1 + NFWD)))
        fwd = (np.max(h[i + 1:i + 1 + NFWD]) - np.min(l[i + 1:i + 1 + NFWD]))
        fwd_ratio = fwd / med_rng[i] if med_rng[i] and med_rng[i] > 0 else np.nan
        rows.append(dict(sym=sym, tf=tf, t=df.index[i], year=df.index[i].year, dir=d,
                         pos=pos, aligned=aligned, swept=swept, disp_atr=disp_atr, mom_before=mom_before,
                         dir_next=dir_next, cont=cont, fill=fill, fwd=fwd_ratio))
    return rows


def seg(d, mask, label):
    g = d[mask]
    if len(g) < 15:
        print(f"  {label:<34} n={len(g):>3}  (мало)"); return
    # год-стабильность направления: в скольких годах dir_next>0.5
    yr = g.groupby("year").dir_next.mean()
    yc = g.groupby("year").size()
    stab = ((yr > 0.5)[yc >= 5]).mean() if (yc >= 5).any() else float("nan")
    print(f"  {label:<34} n={len(g):>3}  dir_next={g.dir_next.mean():.0%}  cont={g.cont.mean():.0%}  "
          f"fill={g.fill.mean():.0%}  fwd×={g.fwd.median():.2f}  год↑={stab:.0%}" if stab == stab
          else f"  {label:<34} n={len(g):>3}  dir_next={g.dir_next.mean():.0%}  cont={g.cont.mean():.0%}  fill={g.fill.mean():.0%}  fwd×={g.fwd.median():.2f}")


def main():
    allrows = []
    for sym in SYMS:
        h1 = load_df(sym, "1h"); d1 = load_df(sym, "1d")
        for x in (h1, d1):
            if x.index.tz is None: x.index = x.index.tz_localize("UTC")
        T = {"12h": compose_from_base(h1, "12h"), "1d": d1,
             "2d": compose_from_base(d1, "2d"), "3d": compose_from_base(d1, "3d")}
        for tf, df in T.items():
            allrows += collect(sym, tf, df)
    d = pd.DataFrame(allrows).replace([np.inf, -np.inf], np.nan).dropna(subset=["disp_atr", "mom_before", "fwd"])
    print(f"Всего double-FVG (пул BTC+ETH, 12h-3d): {len(d)}")
    print(f"БАЗА: dir_next={d.dir_next.mean():.0%}  cont={d.cont.mean():.0%}  fill={d.fill.mean():.0%}  fwd×={d.fwd.median():.2f}\n")

    print("■ ЛОКАЦИЯ (позиция в 20-баровом диапазоне):")
    seg(d, d.pos <= 0.33, "дисконт (низ диапазона)")
    seg(d, (d.pos > 0.33) & (d.pos < 0.66), "равновесие")
    seg(d, d.pos >= 0.66, "премиум (верх диапазона)")

    print("\n■ ТРЕНД-ВЫРАВНИВАНИЕ (FVG vs EMA50):")
    seg(d, d.aligned == 1, "по тренду (continuation)")
    seg(d, d.aligned == 0, "против тренда (reversal-loc)")

    print("\n■ СНЯТИЕ ЛИКВИДНОСТИ перед смещением:")
    seg(d, d.swept == 1, "со снятием (sweep→displ)")
    seg(d, d.swept == 0, "без снятия")

    print("\n■ СИЛА СМЕЩЕНИЯ (размах 3-бар / ATR):")
    hi = d.disp_atr.median()
    seg(d, d.disp_atr >= hi, f"сильное (>={hi:.1f} ATR)")
    seg(d, d.disp_atr < hi, f"слабое (<{hi:.1f} ATR)")

    print("\n■ ИМПУЛЬС ДО (10 баров в сторону FVG):")
    seg(d, d.mom_before > 0.02, "после движения В сторону FVG (поздно/extended)")
    seg(d, (d.mom_before >= -0.02) & (d.mom_before <= 0.02), "плоско до")
    seg(d, d.mom_before < -0.02, "после движения ПРОТИВ (свежий разворот)")

    print("\n■ КОМБО ICT-качество (по тренду + снятие + дисконт/премиум по направлению):")
    favloc = ((d.dir > 0) & (d.pos <= 0.5)) | ((d.dir < 0) & (d.pos >= 0.5))
    hq = (d.aligned == 1) & (d.swept == 1) & favloc
    seg(d, hq, "HQ-сетап")
    seg(d, ~hq, "остальные")

    print("\n■ Лучшая по cont корзина — разрез по ТФ (n>=10):")
    best = d[(d.aligned == 1) & (d.swept == 1)]
    for tf in ["12h", "1d", "2d", "3d"]:
        g = best[best.tf == tf]
        if len(g) >= 10:
            print(f"    {tf}: n={len(g):>3} dir_next={g.dir_next.mean():.0%} cont={g.cont.mean():.0%} fill={g.fill.mean():.0%} fwd×={g.fwd.median():.2f}")
    d.to_csv(HERE / "output" / "etap_254_double_fvg_context.csv", index=False)
    print(f"\nSaved: {HERE/'output'/'etap_254_double_fvg_context.csv'}")


if __name__ == "__main__":
    main()
