"""Реален ли остаточный edge = mean-reversion у 12h/1d экстремумов, или это бычий ДРЕЙФ?

Контроль специфичности убил sweep+reclaim → остался baseline «купи новый 20-бар low / продай 20-бар high».
+0.58R/PF2.64 подозрительно для наива → проверяем дрейф-конфаунд:
  1) LONG vs SHORT раздельно — если только LONG, это бычий дрейф, не MR.
  2) Горизонт 8/20/40 баров — короткий режет дрейф; если edge живёт на коротком → реальный MR.
  3) PERMUTATION-NULL (та же сделка случайный момент) на baseline.
Каузально, нетто косты.
Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/ta_laws/mr_validate.py
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
sys.path.insert(0, str(HERE))
import geometry as G  # noqa: E402

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
TFS = [("12h", 12.0), ("1d", 24.0)]
RT_FEE = 2 * (0.0005 + 0.0002)
FUND_8H = 0.0001
RNG = np.random.default_rng(61)


def load_1m(sym):
    df = pd.read_csv(ROOT / "data" / f"{sym}_1m.csv", parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def rs(df, freq):
    return df.resample(freq, origin="epoch", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna(subset=["close"])


def sim(h, l, c, ei, n, d, entry, sl, tp, hz, tfh):
    risk = abs(entry - sl)
    if risk <= 0 or entry <= 0:
        return None
    end = min(ei + hz, n - 1); exitp = c[end]; held = end - ei
    for x in range(ei + 1, end + 1):   # вход=close[ei]; управление со СЛЕДУЮЩЕГО бара (без entry-bar lookahead)
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
    net = gross - RT_FEE - (held * tfh / 8) * FUND_8H
    return net / (risk / entry)


def scan(series, hz):
    rows = []
    for sym, tfh, h, l, c, atr, idx, n in series:
        for j in range(20, n - 3):
            aa = atr[j]
            if not (aa > 0):
                continue
            lo20 = l[j - 20:j].min(); hi20 = h[j - 20:j].max()
            if l[j] < lo20:
                d = 1; entry = c[j]; sl = l[j] - 0.2 * aa
            elif h[j] > hi20:
                d = -1; entry = c[j]; sl = h[j] + 0.2 * aa
            else:
                continue
            risk = abs(entry - sl)
            if risk <= 0:
                continue
            r = sim(h, l, c, j, n, d, entry, sl, entry + d * 1.5 * risk, hz, tfh)
            if r is not None:
                rows.append({"sym": sym, "year": idx[j].year, "side": "long" if d > 0 else "short",
                             "net": r, "risk_atr": risk / aa})
    return pd.DataFrame(rows)


def perm_null(trades, smap, hz, iters=150):
    means = []
    grp = trades.groupby("sym")
    for _ in range(iters):
        rr = []
        for sym, g in grp:
            h, l, c, atr, n, tfh = smap[sym]
            ks = RNG.integers(20, n - hz - 2, size=len(g))
            for ra, side, b in zip(g.risk_atr.values, g.side.values, ks):
                aa = atr[b]
                if not (aa > 0):
                    continue
                d = 1 if side == "long" else -1
                entry = c[b]; sl = entry - d * ra * aa
                r = sim(h, l, c, b, n, d, entry, sl, entry + d * 1.5 * ra * aa, hz, tfh)
                if r is not None:
                    rr.append(r)
        if rr:
            means.append(float(np.mean(rr)))
    return np.array(means)


def stat(s):
    if len(s) < 12:
        return f"n={len(s):>4}(мало)"
    R = s.net.values
    pf = R[R > 0].sum() / abs(R[R <= 0].sum()) if R[R <= 0].sum() != 0 else 9.9
    sy = int((s.groupby('sym').net.mean() > 0).sum())
    yr = s.groupby('year').net.mean(); yp = int((yr > 0).sum())
    return f"n={len(s):>5} exp={R.mean():>+6.3f}R WR={(R>0).mean()*100:>4.0f}% PF={pf:>4.2f} sym{sy}/3 год{yp}/{yr.size}"


def main():
    # 12h только (основная масса) для чистоты
    series = []; smap = {}
    for sym in SYMBOLS:
        d1 = load_1m(sym); df = rs(d1, "12h")
        h = df["high"].values; l = df["low"].values; c = df["close"].values
        atr = G.compute_atr(df); n = len(df)
        series.append((sym, 12.0, h, l, c, atr, df.index, n))
        smap[sym] = (h, l, c, atr, n, 12.0)

    out = ["Реален ли MR у 12h-экстремумов или бычий ДРЕЙФ? — BTC/ETH/SOL, фьюч нетто.\n"]
    out.append("=== 1) ГОРИЗОНТ × СТОРОНА (короткий горизонт режет дрейф) ===")
    for hz in (8, 20, 40):
        t = scan(series, hz)
        out.append(f"  -- горизонт {hz} баров ({hz*0.5:.0f} дней):")
        out.append(f"     ВСЕ:   {stat(t)}")
        out.append(f"     LONG:  {stat(t[t.side=='long'])}")
        out.append(f"     SHORT: {stat(t[t.side=='short'])}")
    out.append("\n=== 2) PERMUTATION-NULL (та же сделка случайный момент) ===")
    for hz in (8, 40):
        t = scan(series, hz); sm = t.net.mean()
        nm = perm_null(t, smap, hz, iters=150)
        p = float((nm >= sm).mean())
        out.append(f"  hz={hz}: strat exp={sm:+.3f}R | null медиана={np.median(nm):+.3f}R | "
                   f"P(null>=strat)={p:.3f} -> {'edge сверх дрейфа' if p < 0.05 else 'НЕ бьёт дрейф/null'}")
    out.append("\n=== ВЕРДИКТ ===")
    t8 = scan(series, 8); sh8 = t8[t8.side == 'short']
    short_ok = len(sh8) > 12 and sh8.net.mean() > 0 and int((sh8.groupby('sym').net.mean() > 0).sum()) >= 2
    nm8 = perm_null(t8, smap, 8, iters=150); p8 = float((nm8 >= t8.net.mean()).mean())
    out.append(f"  SHORT на коротком гор.8: {stat(sh8)}")
    out.append(f"  -> {'РЕАЛЬНЫЙ MR (short+ и бьёт null на коротком гор.)' if short_ok and p8 < 0.05 else 'СКОРЕЕ ДРЕЙФ (short слаб/не бьёт null) — не самостоятельный edge'}")
    rep = HERE / "mr_validate_report.txt"
    rep.write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))
    print(f"\n[mr] -> {rep.name}")


if __name__ == "__main__":
    main()
