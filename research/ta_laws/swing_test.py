"""Дв.3 (дотест) — HTF-свинг: liquidity-sweep + reclaim → разворот, на 12h. Высокий ТФ = низкий cost-drag.

Канон свипа: подтверждённый swing-low пивот P. Позже бар пробивает low<P (свип ликвидности) И закрывается
обратно close>P (reclaim) → LONG-разворот. Зеркально для swing-high. Каузально, форвард-скан от conf+1.
RR-грид, нетто косты. (Прошлый engine_compare проверял свип НА conf_i — там разворот уже случился → n=0.)

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/ta_laws/swing_test.py
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
TFS = [("12h", "12h", 12.0), ("1d", "1d", 24.0)]
RT_FEE = 2 * (0.0005 + 0.0002)
FUND_8H = 0.0001
SEARCH = 90          # окно поиска свипа после пивота (баров)
HORIZON = 40         # горизонт сделки


def load_1m(sym):
    df = pd.read_csv(ROOT / "data" / f"{sym}_1m.csv", parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def rs(df, freq):
    return df.resample(freq, origin="epoch", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna(subset=["close"])


def sim(h, l, c, ei, n, d, entry, sl, tp, hz, tfh):
    risk = abs(entry - sl)
    if risk <= 0:
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


def stat(s):
    if len(s) < 12:
        return f"n={len(s):>4} (мало)"
    R = s.net.values
    pf = R[R > 0].sum() / abs(R[R <= 0].sum()) if R[R <= 0].sum() != 0 else 9.9
    sy = int((s.groupby('sym').net.mean() > 0).sum())
    yr = s.groupby('year').net.mean(); yp = int((yr > 0).sum())
    return (f"n={len(s):>4} exp={R.mean():>+6.3f}R WR={(R>0).mean()*100:>4.0f}% PF={pf:>4.2f} "
            f"tot={R.sum():>+6.1f}R sym{sy}/3 год{yp}/{yr.size}")


def main():
    rows = []
    for sym in SYMBOLS:
        d1 = load_1m(sym)
        for tlabel, freq, tfh in TFS:
            df = rs(d1, freq); n = len(df)
            h = df["high"].values; l = df["low"].values; c = df["close"].values
            atr = G.compute_atr(df); piv = G.zigzag(df)
            for p in piv:
                ci = p.conf_i
                if ci < 5 or ci >= n - 3:
                    continue
                P = p.price
                # форвард-скан свипа + reclaim
                hit = None
                for j in range(ci + 1, min(ci + SEARCH, n)):
                    if p.kind == "L" and l[j] < P and c[j] > P:
                        hit = ("long", j); break
                    if p.kind == "H" and h[j] > P and c[j] < P:
                        hit = ("short", j); break
                if hit is None:
                    continue
                side, j = hit; aa = atr[j]
                if not (aa > 0):
                    continue
                for rr in (1.5, 2.0, 2.5):
                    if side == "long":
                        entry = c[j]; sl = l[j] - 0.2 * aa; risk = entry - sl
                        if risk <= 0:
                            continue
                        r = sim(h, l, c, j, n, +1, entry, sl, entry + rr * risk, HORIZON, tfh)
                    else:
                        entry = c[j]; sl = h[j] + 0.2 * aa; risk = sl - entry
                        if risk <= 0:
                            continue
                        r = sim(h, l, c, j, n, -1, entry, sl, entry - rr * risk, HORIZON, tfh)
                    if r is not None:
                        rows.append({"sym": sym, "tf": tlabel, "year": df.index[j].year,
                                     "side": side, "rr": rr, "net": r})
    T = pd.DataFrame(rows)
    out = ["Дв.3 HTF-СВИНГ sweep+reclaim reversal (12h/1d) — BTC/ETH/SOL, фьюч нетто.\n"]
    out.append("=== по RR (нетто-R/сделку) ===")
    for rr in (1.5, 2.0, 2.5):
        out.append(f"  RR={rr}: {stat(T[T.rr == rr])}")
    best = max((1.5, 2.0, 2.5), key=lambda rr: T[T.rr == rr].net.mean() if len(T[T.rr == rr]) > 12 else -9)
    b = T[T.rr == best]
    out.append(f"\n=== лучший RR={best} ===")
    out.append(f"  LONG  (свип low+reclaim): {stat(b[b.side=='long'])}")
    out.append(f"  SHORT (свип high+reclaim):{stat(b[b.side=='short'])}")
    for tf, _, _ in TFS:
        out.append(f"  TF={tf}: {stat(b[b.tf==tf])}")
    for sym in SYMBOLS:
        out.append(f"  {sym}: {stat(b[b.sym==sym])}")
    rep = HERE / "swing_test_report.txt"
    rep.write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))
    print(f"\n[swing] -> {rep.name}")


if __name__ == "__main__":
    main()
