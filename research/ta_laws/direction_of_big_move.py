"""НАПРАВЛЕНИЕ БОЛЬШОГО ХОДА — предсказуемо ли по СТРУКТУРЕ (VWAP, ViC-POC, ликвидность)?

Аргумент юзера: большой ход всегда направлен, у него были предпосылки — в какие зоны пришли/образовали,
как вёл ViC ASVK, VWAP ASVK. Проверяем на ЕГО структурных признаках (реплики в Python), отделяя
«предпосылки задним числом» (selection-bias) от «видно ДО хода».

Цель: среди БОЛЬШИХ ходов (|net move| >= BIG% за H баров) — предсказать НАПРАВЛЕНИЕ (вверх/вниз) из
каузальных структурных фич на close[i]. Стены: разделимость Cohen's d (up-big vs down-big), accuracy на
big-подвыборке vs монетка/дрейф/shuffle, cross-asset, раскол long/short (асимметрия=дрейф).

Структурные фичи (реплики ASVK-логики):
  • vwap_z1d / vwap_z1w — позиция цены в VWAP-полосах (1д/1нед), как VWAPs-ASVK;
  • dist_poc / poc_side — дистанция/сторона объёмного POC за окно = ViC-прокси (maxV-уровень);
  • liq_asym — асимметрия ликвидности (ближе buy-side над или sell-side под) = «цена ищет ликвидность»;
  • rpos, ema_slope, px_vs_ema — позиция/тренд; cvd_slope, tbr_dev — направление потока; bb_pos.

Непересекающиеся якоря, walk-forward + purge, shuffle, cross-asset. Критерий ACCURACY.
Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/ta_laws/direction_of_big_move.py
"""
from __future__ import annotations
import sys, os
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
DATA = ROOT / "research" / "elements_study" / "data"
H = int(os.environ.get("DBM_H", 4))            # 2 дня
BIG = float(os.environ.get("DBM_BIG", 5.0))    # «большой ход» = |net| >= 5%
STEP = H
N_FOLDS = 6
FEATS = ["vwap_z1d", "vwap_z1w", "dist_poc", "poc_side", "liq_asym", "rpos",
         "ema_slope", "px_vs_ema", "cvd_slope", "tbr_dev", "bb_pos", "imp3"]


def load_flow(sym, tf):
    df = pd.read_csv(DATA / f"{sym}_{tf}_flow.csv")
    df["open_time"] = pd.to_datetime(df["open_time"], utc=True)
    return df.sort_values("open_time").reset_index(drop=True)


def rolling_vwap_z(tp, vol, C, n):
    mp = min(n, max(2, n // 2))
    pv = pd.Series(tp * vol).rolling(n, min_periods=mp).sum().values
    vv = pd.Series(vol).rolling(n, min_periods=mp).sum().values
    vwap = pv / (vv + 1e-9)
    sd = pd.Series(C).rolling(max(n, 5), min_periods=5).std().values + 1e-9
    return (C - vwap) / sd


def volume_poc(tp, vol, C, win=30, nbins=24):
    n = len(tp); poc = np.full(n, np.nan)
    for i in range(win, n):
        p = tp[i - win:i]; v = vol[i - win:i]
        lo, hi = p.min(), p.max()
        if hi <= lo:
            poc[i] = C[i]; continue
        idx = np.clip(((p - lo) / (hi - lo) * (nbins - 1)).astype(int), 0, nbins - 1)
        agg = np.zeros(nbins)
        np.add.at(agg, idx, v)
        b = agg.argmax()
        poc[i] = lo + (b + 0.5) / nbins * (hi - lo)
    return poc


def build(sym):
    h = load_flow(sym, "12h")
    O, Hi, Lo, C, V = (h[k].values.astype(float) for k in ("open", "high", "low", "close", "volume"))
    cvd = h["cvd"].values.astype(float); tbr = h["taker_buy_ratio"].values.astype(float)
    delta = h["delta"].values.astype(float)
    n = len(h)
    tp = (Hi + Lo + C) / 3
    atr = G.compute_atr(pd.DataFrame({"high": Hi, "low": Lo, "close": C}))
    atr_pct = np.where(C > 0, atr / C * 100, np.nan)
    vwap_z1d = rolling_vwap_z(tp, V, C, 2)
    vwap_z1w = rolling_vwap_z(tp, V, C, 14)
    poc = volume_poc(tp, V, C, win=30)
    dist_poc = (C - poc) / np.clip(C, 1e-9, None) * 100
    poc_side = np.sign(dist_poc)
    lo50 = pd.Series(Lo).rolling(50, min_periods=10).min().values
    hi50 = pd.Series(Hi).rolling(50, min_periods=10).max().values
    d_hi = (hi50 - C) / np.clip(C, 1e-9, None); d_lo = (C - lo50) / np.clip(C, 1e-9, None)
    liq_asym = (d_lo - d_hi) / (d_lo + d_hi + 1e-9)        # >0 = buy-side liq (хай) ближе
    rpos = d_lo / (d_lo + d_hi + 1e-9)
    ema_s = pd.Series(C).ewm(span=40, adjust=False).mean().values
    ema_slope = np.zeros(n); ema_slope[5:] = (ema_s[5:] - ema_s[:-5]) / np.clip(C[5:], 1e-9, None) * 100
    px_vs_ema = (C - ema_s) / np.clip(C, 1e-9, None) * 100
    base = pd.Series(np.abs(delta)).rolling(50, min_periods=5).mean().values + 1e-9
    cvd_slope = np.zeros(n); cvd_slope[3:] = (cvd[3:] - cvd[:-3]) / base[3:]
    tbr_dev = tbr - 0.5
    ma20 = pd.Series(C).rolling(20, min_periods=5).mean().values
    sd20 = pd.Series(C).rolling(20, min_periods=5).std().values + 1e-9
    bb_pos = (C - ma20) / sd20
    imp3 = np.zeros(n); imp3[3:] = (C[3:] - C[:-3]) / C[:-3] * 100 / np.clip(atr_pct[3:], 1e-9, None)

    F = np.column_stack([vwap_z1d, vwap_z1w, dist_poc, poc_side, liq_asym, rpos,
                         ema_slope, px_vs_ema, cvd_slope, tbr_dev, bb_pos, imp3])
    rows = []
    for i in range(60, n - H - 1, STEP):
        if not np.isfinite(F[i]).all() or not np.isfinite(C[i]) or C[i] <= 0:
            continue
        net = (C[i + H] - C[i]) / C[i] * 100
        rng = (Hi[i + 1:i + 1 + H].max() - Lo[i + 1:i + 1 + H].min()) / C[i] * 100
        rows.append({"sym": sym, "ts": h["open_time"].values[i], "net": net, "rng": rng,
                     "is_big": int(abs(net) >= BIG), "y_up": int(net > 0),
                     **{f: F[i][j] for j, f in enumerate(FEATS)}})
    return rows


def cohens_d(x, ybin):
    a = x[ybin == 1]; b = x[ybin == 0]
    if len(a) < 5 or len(b) < 5:
        return np.nan
    sp = np.sqrt(((len(a) - 1) * a.std() ** 2 + (len(b) - 1) * b.std() ** 2) / (len(a) + len(b) - 2))
    return (a.mean() - b.mean()) / (sp + 1e-12)


def walk_forward(df, feats):
    from catboost import CatBoostClassifier
    d = df.sort_values("ts").reset_index(drop=True)
    X = d[feats].values; y = d.y_up.values.astype(int)
    tns = d.ts.values.astype("datetime64[ns]"); n = len(d); fold = n // (N_FOLDS + 1)
    pred = np.full(n, np.nan); purge = np.timedelta64(H * 12, "h")
    for k in range(1, N_FOLDS + 1):
        te0 = fold * k; te1 = min(fold * (k + 1), n)
        if te1 - te0 < 30:
            continue
        tr = tns < (tns[te0] - purge)
        if tr.sum() < 200:
            continue
        m = CatBoostClassifier(iterations=1000, depth=5, learning_rate=0.03, l2_leaf_reg=5,
                               verbose=False, random_seed=k)
        m.fit(X[tr], y[tr])
        pred[te0:te1] = m.predict_proba(X[te0:te1])[:, 1]
    return d, pred, np.isfinite(pred)


def main():
    rows = []
    for s in SYMBOLS:
        print(f"[{s}] build...", flush=True); rows += build(s)
    df = pd.DataFrame(rows).sort_values("ts").reset_index(drop=True)
    df["year"] = pd.to_datetime(df.ts).dt.year
    big = df[df.is_big == 1]
    print(f"[data] {len(df)} якорей, больших ходов (|net|>={BIG}% за {H}бар) {len(big)} ({len(big)/len(df)*100:.0f}%), "
          f"среди них up {big.y_up.mean()*100:.0f}%", flush=True)

    out = []; A = out.append
    A(f"НАПРАВЛЕНИЕ БОЛЬШОГО ХОДА по структуре (VWAP/ViC-POC/ликвидность). Критерий ACCURACY.")
    A(f"Якорей {len(df)}, больших ходов {len(big)} ({len(big)/len(df)*100:.0f}%), up-доля среди больших {big.y_up.mean()*100:.1f}% (=дрейф/база).\n")

    # 1. разделимость структурных фич: up-big vs down-big
    A("=== 1. РАЗДЕЛИМОСТЬ up-big vs down-big (Cohen's d; |d|>0.4 = признак виден ДО хода) ===")
    dd = [(f, cohens_d(big[f].values, big.y_up.values)) for f in FEATS]
    for f, d in sorted(dd, key=lambda r: -abs(r[1])):
        A(f"  {f:12} d={d:+.2f}")
    sep = np.nanmean([abs(x[1]) for x in dd])
    A(f"  средн|d| = {sep:.2f}  -> {'структура РАЗДЕЛЯЕТ направление больших ходов!' if sep > 0.3 else 'структура НЕ разделяет (признаки совпадают у up и down)'}")

    # 2. accuracy на big-подвыборке (обучаем на всех, оцениваем на больших)
    A("\n=== 2. ACCURACY направления (walk-forward; оценка на БОЛЬШИХ ходах) ===")
    d, pr, m = walk_forward(df, FEATS)
    big_m = m & (d.is_big.values == 1)
    yb = d.y_up.values.astype(int)
    acc_big = ((pr[big_m] >= 0.5).astype(int) == yb[big_m]).mean()
    base_big = max(d[d.is_big == 1].y_up.mean(), 1 - d[d.is_big == 1].y_up.mean())
    acc_all = ((pr[m] >= 0.5).astype(int) == yb[m]).mean()
    A(f"  на БОЛЬШИХ ходах:  accuracy {acc_big*100:.1f}%  (база/дрейф {base_big*100:.1f}%)  n={big_m.sum()}")
    A(f"  на всех:           accuracy {acc_all*100:.1f}%")
    # shuffle
    rng = np.random.default_rng(7); ds = df.copy(); ds["y_up"] = rng.permutation(df.y_up.values)
    d2, ps, ms = walk_forward(ds, FEATS); bms = ms & (d2.is_big.values == 1)
    acc_sh = ((ps[bms] >= 0.5).astype(int) == ds.y_up.values[bms].astype(int)).mean()
    A(f"  shuffle-контроль:  {acc_sh*100:.1f}% (~{base_big*100:.0f}% -> {'честно' if acc_sh < base_big+0.03 else 'подозр.'})")

    # 3. раскол long/short (дрейф) + cross-asset + год
    pred = (pr >= 0.5).astype(int)
    upc = big_m & (pred == 1); dnc = big_m & (pred == 0)
    precU = (yb[upc] == 1).mean() if upc.sum() else np.nan
    precD = (yb[dnc] == 0).mean() if dnc.sum() else np.nan
    A("\n=== 3. РАСКОЛ по стороне прогноза (дрейф-тест) ===")
    A(f"  up-вызовы:   n={int(upc.sum()):4d} precision {precU*100:.1f}%")
    A(f"  down-вызовы: n={int(dnc.sum()):4d} precision {precD*100:.1f}%")
    A("  cross-asset (accuracy на больших):")
    for s in SYMBOLS:
        ms2 = big_m & (d.sym.values == s)
        if ms2.sum() > 30:
            A(f"    {s}: {((pr[ms2]>=0.5).astype(int)==yb[ms2]).mean()*100:.1f}% (n={ms2.sum()})")
    yr = pd.to_datetime(d.ts).dt.year.values; gy = 0; ty = 0
    A("  по годам (accuracy на больших):")
    for Y in sorted(set(yr[big_m])):
        mm = big_m & (yr == Y)
        if mm.sum() > 20:
            a = ((pr[mm] >= 0.5).astype(int) == yb[mm]).mean(); ty += 1; gy += a > base_big + 0.03
            A(f"    {Y}: {a*100:.1f}% (n={mm.sum()})")

    works = (acc_big > base_big + 0.04) and (acc_sh < base_big + 0.03) and (gy >= max(3, ty - 1))
    A("\n=== ВЕРДИКТ ===")
    if works:
        A(f"  СТРУКТУРА ПРЕДСКАЗЫВАЕТ направление больших ходов: {acc_big*100:.0f}% > базы {base_big*100:.0f}% "
          f"({gy}/{ty} лет, shuffle чист). VWAP/ViC/ликвидность несут направленную инфо ДО хода.")
    else:
        A(f"  НЕТ: направление больших ходов НЕ предсказуемо структурой ({acc_big*100:.0f}% ~ база {base_big*100:.0f}%, "
          f"годы {gy}/{ty}, shuffle {acc_sh*100:.0f}%). 'Предпосылки' видны ЗАДНИМ числом (selection-bias), не до хода.")
    A("  (Разделимость средн|d| и accuracy сходятся: если оба ~0/~база — признаки up-big и down-big совпадают.)")

    rep = HERE / "direction_of_big_move_report.txt"
    rep.write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out)); print(f"\n[ok] -> {rep.name}")


if __name__ == "__main__":
    main()
