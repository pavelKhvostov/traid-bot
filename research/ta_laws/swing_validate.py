"""Адверсарная валидация Дв.3 (HTF sweep+reclaim reversal) — последний гейт перед live.

Три удара:
  1) PERMUTATION-NULL (density-matched): та же сделка (risk_atr/dir/RR) в СЛУЧАЙНЫЙ момент → бьёт ли вход
     в момент свипа+reclaim случайный вход тем же профилем. p = P(null_mean >= strat_mean).
  2) SPECIFICITY-контроли: (a) sweep-БЕЗ-reclaim (нужен ли reclaim); (b) «купи любой 20-бар экстремум»
     (это не просто buy-the-dip без пивота/свипа?).
  3) АДВЕРСАРНЫЙ ГРИД SEARCH×HORIZON×SL×RR — edge широкий или нож-конфиг (cherry-pick).

Каузально, нетто косты. Знаки сверены (pitfall: шорт уровень/стоп выше).
Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/ta_laws/swing_validate.py
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
RNG = np.random.default_rng(53)


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
    for x in range(ei, end + 1):
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


def scan(series, mode="full", search=90, horizon=40, sl_buf=0.2, rr=1.5):
    """mode: full (sweep+reclaim) | noreclaim (sweep, без reclaim) | dip (любой 20-бар экстремум)."""
    out = []
    for sym, tf, tfh, h, l, c, atr, idx, n in series:
        if mode in ("full", "noreclaim"):
            piv = G.zigzag(rs_cache[(sym, tf)])
            for p in piv:
                ci = p.conf_i
                if ci < 5 or ci >= n - 3:
                    continue
                P = p.price; hit = None
                for j in range(ci + 1, min(ci + search, n)):
                    if p.kind == "L" and l[j] < P:
                        if mode == "full" and not (c[j] > P):
                            continue
                        hit = ("long", j); break
                    if p.kind == "H" and h[j] > P:
                        if mode == "full" and not (c[j] < P):
                            continue
                        hit = ("short", j); break
                if hit is None:
                    continue
                side, j = hit; aa = atr[j]
                if not (aa > 0):
                    continue
                d = 1 if side == "long" else -1
                entry = c[j]
                sl = (l[j] - sl_buf * aa) if side == "long" else (h[j] + sl_buf * aa)
                risk = abs(entry - sl)
                if risk <= 0:
                    continue
                tp = entry + d * rr * risk
                r = sim(h, l, c, j, n, d, entry, sl, tp, horizon, tfh)
                if r is not None:
                    out.append({"sym": sym, "tf": tf, "year": idx[j].year, "side": side,
                                "net": r, "risk_atr": risk / aa, "j": j})
        elif mode == "dip":
            for j in range(20, n - 3):
                aa = atr[j]
                if not (aa > 0):
                    continue
                lo20 = l[j - 20:j].min(); hi20 = h[j - 20:j].max()
                if l[j] < lo20:           # новый 20-бар low → long
                    d = 1; entry = c[j]; sl = l[j] - 0.2 * aa
                elif h[j] > hi20:         # новый 20-бар high → short
                    d = -1; entry = c[j]; sl = h[j] + 0.2 * aa
                else:
                    continue
                risk = abs(entry - sl)
                if risk <= 0:
                    continue
                tp = entry + d * 1.5 * risk
                r = sim(h, l, c, j, n, d, entry, sl, tp, 40, tfh)
                if r is not None:
                    out.append({"sym": sym, "tf": tf, "year": idx[j].year,
                                "side": "long" if d > 0 else "short", "net": r})
    return pd.DataFrame(out)


def perm_null(trades, series_map, iters=200):
    """Та же (risk_atr, dir, rr=1.5) сделка в случайный бар (по symbol/tf). null-распределение exp."""
    means = []
    grp = trades.groupby(["sym", "tf"])
    for _ in range(iters):
        rs_list = []
        for (sym, tf), g in grp:
            h, l, c, atr, n, tfh = series_map[(sym, tf)]
            ks = RNG.integers(20, n - 45, size=len(g))
            for risk_atr, side, b in zip(g.risk_atr.values, g.side.values, ks):
                aa = atr[b]
                if not (aa > 0):
                    continue
                d = 1 if side == "long" else -1
                entry = c[b]; sl = entry - d * risk_atr * aa; tp = entry + d * 1.5 * risk_atr * aa
                r = sim(h, l, c, b, n, d, entry, sl, tp, 40, tfh)
                if r is not None:
                    rs_list.append(r)
        if rs_list:
            means.append(float(np.mean(rs_list)))
    return np.array(means)


def stat(s):
    if len(s) < 12:
        return f"n={len(s):>4}(мало)"
    R = s.net.values
    pf = R[R > 0].sum() / abs(R[R <= 0].sum()) if R[R <= 0].sum() != 0 else 9.9
    sy = int((s.groupby('sym').net.mean() > 0).sum())
    yr = s.groupby('year').net.mean(); yp = int((yr > 0).sum())
    return f"n={len(s):>4} exp={R.mean():>+6.3f}R WR={(R>0).mean()*100:>4.0f}% PF={pf:>4.2f} sym{sy}/3 год{yp}/{yr.size}"


rs_cache = {}


def main():
    series = []; series_map = {}
    for sym in SYMBOLS:
        d1 = load_1m(sym)
        for tlabel, freq, tfh in TFS:
            df = rs(d1, freq); rs_cache[(sym, tlabel)] = df
            h = df["high"].values; l = df["low"].values; c = df["close"].values
            atr = G.compute_atr(df); n = len(df)
            series.append((sym, tlabel, tfh, h, l, c, atr, df.index, n))
            series_map[(sym, tlabel)] = (h, l, c, atr, n, tfh)

    out = ["АДВЕРСАРНАЯ ВАЛИДАЦИЯ Дв.3 HTF sweep+reclaim — BTC/ETH/SOL 12h/1d, фьюч нетто.\n"]
    full = scan(series, "full")
    sm = full.net.mean()
    out.append(f"=== БАЗА (full sweep+reclaim, RR1.5): {stat(full)} ===")

    out.append("\n=== 1) PERMUTATION-NULL (та же сделка в случайный момент) ===")
    nm = perm_null(full, series_map, iters=200)
    p = float((nm >= sm).mean())
    out.append(f"  strat exp={sm:+.3f}R | null exp медиана={np.median(nm):+.3f}R (std {nm.std():.3f}) | "
               f"P(null>=strat)={p:.3f} -> {'БЬЁТ null (момент свипа несёт edge)' if p < 0.05 else 'НЕ бьёт null'}")

    out.append("\n=== 2) SPECIFICITY-контроли ===")
    nore = scan(series, "noreclaim")
    dip = scan(series, "dip")
    out.append(f"  full (sweep+reclaim):  {stat(full)}")
    out.append(f"  sweep БЕЗ reclaim:     {stat(nore)}  -> reclaim {'ВАЖЕН' if full.net.mean()-nore.net.mean()>0.03 else 'не критичен'}")
    out.append(f"  любой 20-бар экстремум:{stat(dip)}  -> пивот+свип {'добавляет' if full.net.mean()-dip.net.mean()>0.03 else 'НЕ добавляет vs buy-dip'}")

    out.append("\n=== 3) АДВЕРСАРНЫЙ ГРИД (exp R по конфигам) ===")
    pos = tot = 0
    for search in (60, 90, 120):
        for horizon in (30, 40, 60):
            for sl_buf in (0.1, 0.2, 0.3):
                for rr in (1.5, 2.0):
                    g = scan(series, "full", search, horizon, sl_buf, rr)
                    if len(g) < 50:
                        continue
                    e = g.net.mean(); tot += 1; pos += int(e > 0)
                    if (search, horizon, sl_buf, rr) in [(60,30,0.1,1.5),(120,60,0.3,2.0),(90,40,0.2,1.5),(90,40,0.2,2.0)]:
                        out.append(f"  S{search} H{horizon} SL{sl_buf} RR{rr}: exp={e:+.3f}R n={len(g)}")
    out.append(f"  ИТОГО грид: {pos}/{tot} конфигов с положительной экспектацией "
               f"-> {'РОБАСТНО (не нож-конфиг)' if tot and pos/tot>=0.8 else 'нестабильно'}")

    out.append("\n=== ВЕРДИКТ ===")
    survive = (p < 0.05 and full.net.mean() - dip.net.mean() > 0.0 and pos / max(tot, 1) >= 0.8)
    out.append(f"  null p={p:.3f} | vs buy-dip Δ={full.net.mean()-dip.net.mean():+.3f} | грид {pos}/{tot} -> "
               f"{'✅ ВЫЖИВАЕТ — готов к live-подготовке' if survive else '⚠️ есть слабые места'}")

    rep = HERE / "swing_validate_report.txt"
    rep.write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))
    print(f"\n[val] -> {rep.name}")


if __name__ == "__main__":
    main()
