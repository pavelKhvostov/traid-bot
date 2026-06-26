"""Bracket-INDEPENDENT диагностика ① structure break-retest: есть ли направленная инфо, НЕ зависящая от TP/SL?

Возражение: «всё в минусе» могло быть из-за тугого стопа/RR, а не пустого сетапа. Честно отделяем СЕТАП от
БРЕКЕТА:
  1) forward signed-return @ горизонты + MFE/MAE (в ATR, без фикс-стопа) — двигается ли цена в сторону слома.
  2) triple-barrier ±1.5ATR — направление независимо от RR (cont vs rev что первым).
  3) обе гипотезы: КОНТИНУАЦИЯ (резюм слома) и РАЗВОРОТ (fade слома).
  4) сетка SL×RR (нетто-косты) — есть ли ХОТЬ ОДИН брекет в плюсе и бьёт ли null.
BTC/ETH/SOL, 4h, каузально (сигнал на ретесте t, форвард от t+1). vs NULL (случайные бары).
Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/ta_laws/break_retest_diagnostic.py
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

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
TF = "4h"; TF_H = 4.0; RETEST_W = 30; HMAX = 40
RT_FEE = 2 * (0.0005 + 0.0002); FUND_8H = 0.0001
RNG = np.random.default_rng(37)


def load_1m(s):
    df = pd.read_csv(ROOT / "data" / f"{s}_1m.csv", parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def rs(df, f):
    return df.resample(f, origin="epoch", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna(subset=["close"])


def signals(df):
    """Ретест-сигналы: (t, d_cont) — d_cont = направление слома (континуация)."""
    o = df["open"].values; h = df["high"].values; l = df["low"].values; c = df["close"].values
    n = len(df); piv = G.zigzag(df)
    lastH = np.full(n, np.nan); lastL = np.full(n, np.nan)
    for p in piv:
        if 0 <= p.conf_i < n:
            (lastH if p.kind == "H" else lastL)[p.conf_i:] = p.price
    out = []; x = 26
    while x < n - HMAX - 2:
        if not np.isnan(lastL[x]) and c[x] < lastL[x] and c[x - 1] >= lastL[x - 1]:
            lvl = lastL[x]
            for t in range(x + 1, min(x + RETEST_W, n - HMAX - 2)):
                if h[t] >= lvl:
                    out.append((t, -1)); x = t; break
        elif not np.isnan(lastH[x]) and c[x] > lastH[x] and c[x - 1] <= lastH[x - 1]:
            lvl = lastH[x]
            for t in range(x + 1, min(x + RETEST_W, n - HMAX - 2)):
                if l[t] <= lvl:
                    out.append((t, 1)); x = t; break
        x += 1
    return out


def fwd_stats(h, l, c, atr, t, d, n):
    """d = направление, по которому меряем (cont). signed_ret в ATR @ горизонты, MFE/MAE, triple-barrier."""
    base = c[t]; ap = atr[t]
    if ap <= 0 or base <= 0:
        return None
    res = {}
    for hh in (5, 10, 20, 40):
        j = min(t + hh, n - 1)
        res[f"r{hh}"] = (c[j] - base) / base / (ap / base) * d
    end = min(t + HMAX, n - 1)
    mfe = mae = 0.0
    for x in range(t + 1, end + 1):
        fav = (h[x] - base) if d > 0 else (base - l[x])
        adv = (base - l[x]) if d > 0 else (h[x] - base)
        mfe = max(mfe, fav); mae = max(mae, adv)
    res["mfe"] = mfe / ap; res["mae"] = mae / ap
    # triple-barrier ±1.5 ATR
    up = base + 1.5 * ap; dn = base - 1.5 * ap; uh = dh = None
    for x in range(t + 1, end + 1):
        if uh is None and h[x] >= up:
            uh = x
        if dh is None and l[x] <= dn:
            dh = x
        if uh and dh:
            break
    cont_hit = (dh if d < 0 else uh); rev_hit = (uh if d < 0 else dh)
    ci = cont_hit if cont_hit else 10**9; ri = rev_hit if rev_hit else 10**9
    res["cont_first"] = np.nan if (ci == 10**9 and ri == 10**9) else (1 if ci < ri else 0)
    return res


def sim_bracket(o, h, l, c, t, n, d, sl_atr, rr, atr):
    base = c[t]; entry = o[t + 1] if t + 1 < n else base
    risk = sl_atr * atr[t]
    if risk <= 0:
        return None
    sl = entry - d * risk; tp = entry + d * rr * risk
    end = min(t + 1 + HMAX, n - 1); exitp = c[end]; held = end - (t + 1)
    for x in range(t + 2, end + 1):
        if d > 0:
            if l[x] <= sl:
                exitp = sl; held = x - t - 1; break
            if h[x] >= tp:
                exitp = tp; held = x - t - 1; break
        else:
            if h[x] >= sl:
                exitp = sl; held = x - t - 1; break
            if l[x] <= tp:
                exitp = tp; held = x - t - 1; break
    gross = (exitp - entry) / entry * d
    return (gross - RT_FEE - held * TF_H / 8 * FUND_8H) / (risk / entry)


def main():
    rows = []; series = {}
    for s in SYMBOLS:
        print(f"[{s}]...", flush=True)
        df = rs(load_1m(s), TF)
        o = df["open"].values; h = df["high"].values; l = df["low"].values; c = df["close"].values
        atr = G.compute_atr(df); n = len(df)
        series[s] = (o, h, l, c, atr, n, df.index)
        for (t, d) in signals(df):
            st = fwd_stats(h, l, c, atr, t, d, n)
            if st:
                st["sym"] = s; st["t"] = t; st["d"] = d; rows.append(st)
    T = pd.DataFrame(rows)
    out = ["BRACKET-INDEPENDENT диагностика ① break-retest (4h, BTC/ETH/SOL). d=направление СЛОМА (континуация).\n"]
    out.append(f"Сигналов: {len(T)}")

    # NULL: случайные бары/направление
    nrows = []
    for s in SYMBOLS:
        o, h, l, c, atr, n, idx = series[s]
        for _ in range(len(T) // 3 + 50):
            b = int(RNG.integers(26, n - HMAX - 2)); d = int(RNG.choice([-1, 1]))
            st = fwd_stats(h, l, c, atr, b, d, n)
            if st:
                nrows.append(st)
    N = pd.DataFrame(nrows)

    out.append("\n=== 1) FORWARD SIGNED-RETURN в сторону слома (ATR), сетап vs null ===")
    out.append(f"{'гориз':>6} {'сетап':>8} {'null':>8}")
    for hh in (5, 10, 20, 40):
        out.append(f"{hh:>6} {T[f'r{hh}'].mean():>+8.3f} {N[f'r{hh}'].mean():>+8.3f}")
    out.append(f"\n  MFE(cont) сетап {T.mfe.mean():.2f} / null {N.mfe.mean():.2f} ATR;  "
               f"MAE сетап {T.mae.mean():.2f} / null {N.mae.mean():.2f} ATR")
    cf = T.cont_first.dropna(); nf = N.cont_first.dropna()
    out.append(f"  triple-barrier P(континуация первой): сетап {cf.mean()*100:.1f}% / null {nf.mean()*100:.1f}% "
               f"-> {'есть направл. инфо' if abs(cf.mean()-0.5)>0.03 else 'НЕТ (≈50%)'}")
    # знак: континуация или разворот?
    r20 = T.r20.mean()
    out.append(f"  Вывод направления: r20 сетап {r20:+.3f} ATR -> "
               f"{'КОНТИНУАЦИЯ (слом продолжается)' if r20 > 0.05 else ('РАЗВОРОТ/fade (слом гасится)' if r20 < -0.05 else 'НЕЙТРАЛЬНО — нет направл. edge')}")

    out.append("\n=== 2) СЕТКА SL×RR (нетто-косты) — есть ли ХОТЬ ОДИН брекет в плюсе? ===")
    out.append("  (если ничего не в плюсе при любой сетке → сетап пустой, не вопрос брекета)")
    out.append("  " + "SL/RR".ljust(8) + "".join(f"RR{rr:<6}" for rr in (1.0, 1.5, 2.0, 3.0)))
    best = (-9, None)
    for sl_atr in (0.5, 1.0, 1.5, 2.5):
        cells = []
        for rr in (1.0, 1.5, 2.0, 3.0):
            rs_ = []
            for _, row in T.iterrows():
                o, h, l, c, atr, n, idx = series[row.sym]
                r = sim_bracket(o, h, l, c, int(row.t), n, int(row.d), sl_atr, rr, atr)
                if r is not None:
                    rs_.append(r)
            e = float(np.mean(rs_)) if rs_ else 0.0
            cells.append(f"{e:+.3f} ")
            if e > best[0]:
                best = (e, (sl_atr, rr))
        out.append(f"  SL{sl_atr:<6}" + "".join(c8.ljust(8) for c8 in cells))
    out.append(f"  Лучший брекет: SL={best[1][0]} RR={best[1][1]} → exp {best[0]:+.3f}R")

    out.append("\n=== ВЕРДИКТ ===")
    directionless = abs(r20) < 0.05 and abs(cf.mean() - 0.5) < 0.03
    out.append(f"  r20 {r20:+.3f}ATR, P(cont) {cf.mean()*100:.0f}%, лучший брекет {best[0]:+.3f}R -> "
               + ("СЕТАП ПУСТОЙ: нет направл. инфо ни при каком брекете (минус был не из-за TP/SL)"
                  if directionless and best[0] <= 0 else
                  ("есть слабая направленность — брекет важен, тюним"
                   if best[0] > 0 else "направление есть, но брекет нетто не вытягивает")))
    rep = HERE / "break_retest_diag_report.txt"
    rep.write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))
    print(f"\n[diag] -> {rep.name}")


if __name__ == "__main__":
    main()
