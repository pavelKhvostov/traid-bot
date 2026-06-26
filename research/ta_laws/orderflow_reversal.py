"""Ось B: ORDER-FLOW В ТОЧКЕ РЕАКЦИИ — оживляет ли абсорпция/CVD-дивергенция мёртвый зона-реверс?

Дв.2 показал: голый реверс У зоны = KILL (−0.10R). Гипотеза: flow-подтверждение отделяет реальные развороты
от ложных. На касании зоны Вадима (support→реверс вверх / resistance→вниз) меряем:
  - АБСОРПЦИЯ: агрессивная дельта в сторону подхода, но бар отвергает (закрытие назад) → поглощение → разворот.
  - CVD-ДИВЕРГЕНЦИЯ: цена новый экстремум к зоне, а CVD не подтверждает.
Сделка-реверс: вход open[t+1] (без entry-bar lookahead), стоп за зоной, TP=RR·risk. Сравниваем:
  baseline (все касания) vs flow-confirmed vs flow-absent, + null + cross-asset + год.
Данные: зоны из 1m (канон Вадима), OHLC+delta+CVD из {SYM}_1h_flow.csv (BTC/ETH/SOL).
Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/ta_laws/orderflow_reversal.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(HERE))
import geometry as G  # noqa: E402
from research.smc_adapter import precompute_zone_events, snapshot_from_events, ROLE  # noqa: E402

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
ZONE_TFS = ("12h", "1d")
ZTYPES = ("OB", "RDRB", "FVG", "ob_liq", "fractal")
APPROACH = 8         # окно подхода (1h-баров) для дивергенции
HORIZON = 40         # горизонт сделки
SL_BUF = 0.5         # стоп за зоной в ATR
RR = 2.0
RT_FEE = 2 * (0.0005 + 0.0002)
FUND_8H = 0.0001
RNG = np.random.default_rng(29)

UP_DIRS = {"long", "bottom", "low", "up", "bull", "bullish", "demand"}     # demand/support → реверс ВВЕРХ
DN_DIRS = {"short", "top", "high", "down", "bear", "bearish", "supply"}    # supply/resistance → реверс ВНИЗ


def load_1m(s):
    df = pd.read_csv(ROOT / "data" / f"{s}_1m.csv", parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def load_flow(s):
    df = pd.read_csv(ROOT / "research" / "elements_study" / "data" / f"{s}_1h_flow.csv",
                     parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def sim(o, h, l, c, ei, n, d, entry, sl, tp, tf_h=1.0):
    risk = abs(entry - sl)
    if risk <= 0 or entry <= 0:
        return None
    end = min(ei + HORIZON, n - 1); exitp = c[end]; held = end - ei
    for x in range(ei + 1, end + 1):     # вход=open[ei]; управление со следующего (без entry-bar lookahead)
        if d > 0:
            if l[x] <= sl:
                exitp = sl; held = x - ei; break
            if h[x] >= tp:
                exitp = tp; held = x - ei; break
        else:
            if h[x] >= sl:
                exitp = sl; held = x - ei; break
            if l[x] <= tp:
                exitp = tp; held = x - ei; break
    gross = (exitp - entry) / entry * d
    return (gross - RT_FEE - held * tf_h / 8 * FUND_8H) / (risk / entry)


def build(sym):
    d1 = load_1m(sym); fl = load_flow(sym)
    o = fl["open"].values; h = fl["high"].values; l = fl["low"].values; c = fl["close"].values
    delta = fl["delta_norm"].values if "delta_norm" in fl else (fl["delta"].values)
    cvd = np.cumsum(fl["delta"].values)
    atr = G.compute_atr(fl); n = len(fl); idx = fl.index
    ev, resampled = precompute_zone_events(d1, tfs=ZONE_TFS, types=ZTYPES)
    rows = []
    seen = set()
    for (tf, ztype), evs in ev.items():
        for e in evs:
            born = e.get("born_ts")
            if born is None:
                continue
            lo = e.get("zone_lo", e.get("lo")); hi = e.get("zone_hi", e.get("hi"))
            direction = e.get("direction", "")
            if lo is None or hi is None:
                continue
            up = direction in UP_DIRS
            if not up and direction not in DN_DIRS:
                continue
            b = idx.searchsorted(born, side="right")     # первый 1h-бар после рождения
            # первое касание зоны
            t = None
            for x in range(b + 1, min(b + 400, n - HORIZON - 2)):
                if l[x] <= hi and h[x] >= lo:            # бар пересёк зону
                    t = x; break
            if t is None or t < APPROACH + 2 or atr[t] <= 0:
                continue
            key = (round(lo), round(hi), t)
            if key in seen:
                continue
            seen.add(key)
            d = 1 if up else -1
            # flow-фичи (каузально, бары ≤ t)
            win_h = h[t - APPROACH:t + 1]; win_l = l[t - APPROACH:t + 1]
            win_cvd = cvd[t - APPROACH:t + 1]
            if up:   # support: ждём бычью дивергенцию (новый low, CVD выше min)
                diverg = (l[t] <= win_l.min() + 1e-9) and (cvd[t] > win_cvd.min())
                absorp = (delta[t] < -1.0) and (c[t] > o[t])   # продавцы агрессивны, но бар закрылся вверх
            else:    # resistance: медвежья дивергенция (новый high, CVD ниже max)
                diverg = (h[t] >= win_h.max() - 1e-9) and (cvd[t] < win_cvd.max())
                absorp = (delta[t] > 1.0) and (c[t] < o[t])
            # сделка-реверс
            entry = o[t + 1]
            sl = (lo - SL_BUF * atr[t]) if up else (hi + SL_BUF * atr[t])
            risk = abs(entry - sl)
            if risk <= 0:
                continue
            tp = entry + d * RR * risk
            r = sim(o, h, l, c, t + 1, n, d, entry, sl, tp)
            if r is None:
                continue
            rows.append({"sym": sym, "year": idx[t].year, "dir": d, "net": r,
                         "absorp": int(bool(absorp)), "diverg": int(bool(diverg)),
                         "flow": int(bool(absorp) or bool(diverg)), "risk_atr": risk / atr[t]})
    return rows


def stat(s):
    if len(s) < 15:
        return f"n={len(s):>4}(мало)"
    R = s.net.values
    pf = R[R > 0].sum() / abs(R[R <= 0].sum()) if R[R <= 0].sum() != 0 else 9.9
    sy = int((s.groupby('sym').net.mean() > 0).sum())
    yr = s.groupby('year').net.mean(); yp = int((yr > 0).sum())
    return f"n={len(s):>5} exp={R.mean():>+6.3f}R WR={(R>0).mean()*100:>4.0f}% PF={pf:>4.2f} sym{sy}/3 год{yp}/{yr.size}"


def main():
    rows = []
    for s in SYMBOLS:
        print(f"[{s}]...", flush=True); rows += build(s)
    T = pd.DataFrame(rows)
    out = ["ОСЬ B: order-flow в точке реакции (абсорпция/CVD-дивергенция у зон) — BTC/ETH/SOL, фьюч нетто.\n"]
    out.append(f"Касаний зон: {len(T)} | с flow-подтверждением: {T.flow.sum()} "
               f"(абсорпция {T.absorp.sum()}, дивергенция {T.diverg.sum()})\n")
    out.append("=== ЗОНА-РЕВЕРС: оживляет ли flow? ===")
    out.append(f"  baseline (все касания, ≈Дв.2):  {stat(T)}")
    out.append(f"  + flow-подтверждение (abs|div):  {stat(T[T.flow == 1])}")
    out.append(f"  flow-ОТСУТСТВУЕТ:                {stat(T[T.flow == 0])}")
    out.append(f"  только АБСОРПЦИЯ:                {stat(T[T.absorp == 1])}")
    out.append(f"  только ДИВЕРГЕНЦИЯ:              {stat(T[T.diverg == 1])}")
    out.append("\n  по стороне (flow-confirmed):")
    fc = T[T.flow == 1]
    out.append(f"    LONG (support):  {stat(fc[fc.dir == 1])}")
    out.append(f"    SHORT (resist):  {stat(fc[fc.dir == -1])}")

    # null: случайные касания (перетасуем flow-метку) — поднимает ли РЕАЛЬНЫЙ flow над случайным отбором того же размера
    out.append("\n=== NULL: случайный отбор того же размера vs flow-confirmed ===")
    k = int(T.flow.sum()); base_exp = T[T.flow == 1].net.mean()
    null_means = []
    for _ in range(2000):
        samp = T.net.values[RNG.integers(0, len(T), size=k)]
        null_means.append(samp.mean())
    nm = np.array(null_means); p = float((nm >= base_exp).mean())
    out.append(f"  flow-confirmed exp={base_exp:+.3f}R | random-отбор медиана {np.median(nm):+.3f}R | "
               f"P(random>=flow)={p:.3f} -> {'flow НЕСЁТ инфо' if p < 0.05 else 'flow НЕ бьёт случайный отбор'}")

    out.append("\n=== ВЕРДИКТ ===")
    fe = T[T.flow == 1].net.mean(); ne = T[T.flow == 0].net.mean()
    lift = fe - ne
    sy = int((T[T.flow == 1].groupby('sym').net.mean() > 0).sum())
    real = fe > 0 and p < 0.1 and sy >= 2 and lift > 0.05
    out.append(f"  flow-confirmed {fe:+.3f}R vs flow-absent {ne:+.3f}R (лифт {lift:+.3f}); sym {sy}/3; null p={p:.3f}")
    out.append(f"  -> {'✅ ORDER-FLOW ОЖИВЛЯЕТ зона-реверс (ось B несёт edge)' if real else '❌ flow НЕ оживляет — зона-реверс остаётся мёртвым'}")
    rep = HERE / "orderflow_reversal_report.txt"
    rep.write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))
    print(f"\n[B] -> {rep.name}")


if __name__ == "__main__":
    main()
