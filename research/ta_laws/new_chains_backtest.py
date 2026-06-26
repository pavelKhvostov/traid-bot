"""Новые цепочки (НЕ 1.1.x): ① structure break-retest (CHoCH/BOS) + ② Marubozu open-magnet.
Эталонный net-cost harness: BTC/ETH/SOL, вход open[t+1] (lookahead-clean), косты, год, cross-asset, null.

① break-retest (4h, ортогонален trend-riderам 1.1.x): close ломает последний swing (zigzag) → ретест
   сломанного уровня → вход (медвежий слом+ретест вверх→SHORT; бычий→LONG). SL за ретест-экстремумом, TP RR2.
② Marubozu open-magnet (4h): сильный marubozu (тело≥1ATR) → возврат к уровню OPEN (магнит) → вход в
   направлении marubozu (long: open=низ, возврат вниз→LONG; short→SHORT). SL за open, TP RR2.

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/ta_laws/new_chains_backtest.py
Выход: research/ta_laws/new_chains_report.txt + new_chains_trades.csv
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
import research.smc_adapter as SA  # noqa: E402  (ставит sys.path на smc-lib)
from candle import Candle  # noqa: E402
from elements.marubozu.code import detect_marubozu  # noqa: E402

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
TF = "4h"; TF_H = 4.0
RR = 2.0; HORIZON = 40; SL_BUF = 0.3; RETEST_W = 30; MARU_W = 40
RT_FEE = 2 * (0.0005 + 0.0002); FUND_8H = 0.0001
RNG = np.random.default_rng(31)


def load_1m(s):
    df = pd.read_csv(ROOT / "data" / f"{s}_1m.csv", parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def rs(df, f):
    return df.resample(f, origin="epoch", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna(subset=["close"])


def sim(o, h, l, c, ei, n, d, entry, sl, tp):
    risk = abs(entry - sl)
    if risk <= 0 or entry <= 0:
        return None
    end = min(ei + HORIZON, n - 1); exitp = c[end]; held = end - ei
    for x in range(ei + 1, end + 1):    # вход=open[ei], управление со следующего
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
    return (gross - RT_FEE - held * TF_H / 8 * FUND_8H) / (risk / entry)


def chain_break_retest(df):
    o = df["open"].values; h = df["high"].values; l = df["low"].values; c = df["close"].values
    atr = G.compute_atr(df); n = len(df)
    piv = G.zigzag(df)
    lastH = np.full(n, np.nan); lastL = np.full(n, np.nan)
    for p in piv:
        if 0 <= p.conf_i < n:
            if p.kind == "H":
                lastH[p.conf_i:] = p.price
            else:
                lastL[p.conf_i:] = p.price
    rows = []
    x = 26
    while x < n - HORIZON - 2:
        # свежий медвежий слом: close пробил последний swing low
        if not np.isnan(lastL[x]) and c[x] < lastL[x] and (x == 0 or c[x - 1] >= lastL[x - 1]) and atr[x] > 0:
            lvl = lastL[x]
            for t in range(x + 1, min(x + RETEST_W, n - 2)):
                if h[t] >= lvl:                      # ретест сломанного low (теперь сопротивление)
                    entry = o[t + 1]; sl = max(h[t], lvl) + SL_BUF * atr[t]; risk = sl - entry
                    if risk > 0:
                        r = sim(o, h, l, c, t + 1, n, -1, entry, sl, entry - RR * risk)
                        if r is not None:
                            rows.append({"year": df.index[t].year, "dir": -1, "net": r})
                    x = t; break
        # свежий бычий слом
        elif not np.isnan(lastH[x]) and c[x] > lastH[x] and (x == 0 or c[x - 1] <= lastH[x - 1]) and atr[x] > 0:
            lvl = lastH[x]
            for t in range(x + 1, min(x + RETEST_W, n - 2)):
                if l[t] <= lvl:
                    entry = o[t + 1]; sl = min(l[t], lvl) - SL_BUF * atr[t]; risk = entry - sl
                    if risk > 0:
                        r = sim(o, h, l, c, t + 1, n, 1, entry, sl, entry + RR * risk)
                        if r is not None:
                            rows.append({"year": df.index[t].year, "dir": 1, "net": r})
                    x = t; break
        x += 1
    return rows


def chain_marubozu(df):
    o = df["open"].values; h = df["high"].values; l = df["low"].values; c = df["close"].values
    atr = G.compute_atr(df); n = len(df)
    rows = []
    i = 5
    while i < n - HORIZON - 2:
        if atr[i] <= 0:
            i += 1; continue
        cd = Candle(o[i], h[i], l[i], c[i])
        m = detect_marubozu(cd)
        if m is not None and (h[i] - l[i]) >= 1.0 * atr[i]:
            lvl = o[i]; d = 1 if m.direction == "long" else -1
            for t in range(i + 1, min(i + MARU_W, n - 2)):
                touch = (l[t] <= lvl) if d > 0 else (h[t] >= lvl)
                if touch:
                    entry = o[t + 1]
                    sl = lvl - SL_BUF * atr[i] if d > 0 else lvl + SL_BUF * atr[i]
                    risk = abs(entry - sl)
                    if risk > 0:
                        r = sim(o, h, l, c, t + 1, n, d, entry, sl, entry + d * RR * risk)
                        if r is not None:
                            rows.append({"year": df.index[t].year, "dir": d, "net": r})
                    i = t; break
        i += 1
    return rows


def stat(s):
    if len(s) < 15:
        return f"n={len(s):>4}(мало)"
    R = s.net.values
    pf = R[R > 0].sum() / abs(R[R <= 0].sum()) if R[R <= 0].sum() != 0 else 9.9
    sy = int((s.groupby('sym').net.mean() > 0).sum()) if 'sym' in s else 0
    yr = s.groupby('year').net.mean(); yp = int((yr > 0).sum())
    return (f"n={len(s):>5} exp={R.mean():>+6.3f}R WR={(R>0).mean()*100:>4.0f}% PF={pf:>4.2f} "
            f"tot={R.sum():>+6.1f}R sym{sy}/3 год{yp}/{yr.size}")


def null_p(T):
    """random-entry null: тот же размер, случайные бары/направление на BTC 4h, та же RR-механика."""
    d1 = load_1m("BTCUSDT"); df = rs(d1, TF)
    o = df["open"].values; h = df["high"].values; l = df["low"].values; c = df["close"].values
    atr = G.compute_atr(df); n = len(df)
    k = len(T); base = T.net.mean(); means = []
    for _ in range(300):
        rr = []
        for _ in range(k):
            b = int(RNG.integers(26, n - HORIZON - 2)); d = int(RNG.choice([-1, 1]))
            if atr[b] <= 0:
                continue
            entry = o[b]; risk = 0.8 * atr[b]
            sl = entry - d * risk
            r = sim(o, h, l, c, b, n, d, entry, sl, entry + d * RR * risk)
            if r is not None:
                rr.append(r)
        if rr:
            means.append(np.mean(rr))
    nm = np.array(means)
    return float((nm >= base).mean()), float(np.median(nm))


def main():
    br = []; mr = []
    for s in SYMBOLS:
        print(f"[{s}]...", flush=True)
        df = rs(load_1m(s), TF)
        for r in chain_break_retest(df):
            r["sym"] = s; br.append(r)
        for r in chain_marubozu(df):
            r["sym"] = s; mr.append(r)
    BR = pd.DataFrame(br); MR = pd.DataFrame(mr)
    out = ["НОВЫЕ ЦЕПОЧКИ (не 1.1.x) — BTC/ETH/SOL 4h, фьюч нетто, вход open[t+1], RR2.\n"]
    out.append("=== ① STRUCTURE BREAK-RETEST (CHoCH/BOS) ===")
    out.append(f"  все:   {stat(BR)}")
    if len(BR):
        out.append(f"  SHORT: {stat(BR[BR.dir == -1])}")
        out.append(f"  LONG:  {stat(BR[BR.dir == 1])}")
        p, nmed = null_p(BR)
        out.append(f"  NULL: exp {BR.net.mean():+.3f}R vs random {nmed:+.3f}R, P(rnd>=)={p:.3f} "
                   f"-> {'бьёт null' if p < 0.05 else 'НЕ бьёт null'}")
    out.append("\n=== ② MARUBOZU OPEN-MAGNET ===")
    out.append(f"  все:   {stat(MR)}")
    if len(MR):
        out.append(f"  LONG:  {stat(MR[MR.dir == 1])}")
        out.append(f"  SHORT: {stat(MR[MR.dir == -1])}")
        p, nmed = null_p(MR)
        out.append(f"  NULL: exp {MR.net.mean():+.3f}R vs random {nmed:+.3f}R, P(rnd>=)={p:.3f} "
                   f"-> {'бьёт null' if p < 0.05 else 'НЕ бьёт null'}")
    out.append("\n=== ВЕРДИКТ ===")
    for nm, T in [("① break-retest", BR), ("② marubozu", MR)]:
        if len(T) < 15:
            out.append(f"  {nm}: мало сделок"); continue
        sy = int((T.groupby('sym').net.mean() > 0).sum())
        yr = T.groupby('year').net.mean(); ok = T.net.mean() > 0 and sy >= 2 and (yr > 0).mean() >= 0.6
        out.append(f"  {nm}: exp {T.net.mean():+.3f}R sym{sy}/3 год{int((yr>0).sum())}/{yr.size} "
                   f"-> {'✅ кандидат (далее: декорреляция vs корзина)' if ok else '❌ нет чистого edge'}")
    pd.concat([BR.assign(chain='break'), MR.assign(chain='maru')]).to_csv(HERE / "new_chains_trades.csv", index=False)
    rep = HERE / "new_chains_report.txt"
    rep.write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))
    print(f"\n[new_chains] -> {rep.name}")


if __name__ == "__main__":
    main()
