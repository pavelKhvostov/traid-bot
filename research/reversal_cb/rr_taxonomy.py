"""RR-ФОКУС самоисправления: разделить флагнутые сигналы по знаку net-R, выкинуть max отрицательных, сохранить max
положительных (взвешенно по ΣR). Цель = деньги, не precision.
1) KMeans-категории по фичам: mean-R, ΣR, %R>0, профиль -> лузер-категории.
2) Дерево на ЗНАК R (OOS: учим 60% времени, тест 40%) -> дроп предсказанных лузеров. Фронтир: ΣR-kept, %винёр-R сохр, %лузер-R убр.
Применяю на ВСЕХ флагнутых (top-30% reversal-likelihood, любой RR) для 8h LONG и 12h SHORT. Косты TAKER 10/10.

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/reversal_cb/rr_taxonomy.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
from reversal_analysis import load, feats, THR  # noqa: E402
from reversal_module import FEATS  # noqa: E402
from ev_rescue import wf_raw  # noqa: E402
from rr_native import native  # noqa: E402
from sklearn.cluster import KMeans  # noqa: E402
from sklearn.tree import DecisionTreeClassifier  # noqa: E402
HERE = Path(__file__).resolve().parent
SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


def collect(tf, direction, flag_pct=0.70):
    XS = []; RS = []; TS = []
    for s in SYMS:
        df = load(s, tf); X = feats(df); y, R, risk = native(df, direction, 0.0010, 0.0010)
        m = (y >= 0) & X[FEATS].notna().all(axis=1).values & np.isfinite(risk)
        Xf = X[FEATS][m].reset_index(drop=True); yf = y[m]
        proba, foldid = wf_raw(Xf, yf); uu = foldid >= 0
        pr = proba[uu]; thr = np.quantile(pr, flag_pct)
        fl = pr >= thr
        XS.append(Xf[uu][fl].reset_index(drop=True)); RS.append(R[m][uu][fl]); TS.append(df.index[m][uu][fl])
    X = pd.concat(XS, ignore_index=True); R = np.concatenate(RS); T = pd.DatetimeIndex(np.concatenate([t.values for t in TS]))
    o = np.argsort(T.values); return X.iloc[o].reset_index(drop=True), R[o], T[o]


def kmeans_cats(X, R, out):
    cols = FEATS; A = out.append
    Xz = (X[cols].values - X[cols].values.mean(0)) / (X[cols].values.std(0) + 1e-9)
    km = KMeans(n_clusters=5, random_state=7, n_init=10).fit(Xz); lab = km.labels_
    A(f"  КАТЕГОРИИ (KMeans) — всего n={len(R)} ΣR={R.sum():+.0f} mean-R={R.mean():+.3f}")
    rows = []
    for c in range(5):
        idx = lab == c; rows.append((c, int(idx.sum()), R[idx].mean(), R[idx].sum(), (R[idx] > 0).mean(), idx))
    for c, n, mr, sr, pp, idx in sorted(rows, key=lambda r: r[2]):  # от худших к лучшим
        z = Xz[idx].mean(0); top = np.argsort(-np.abs(z))[:4]
        prof = ", ".join(f"{cols[i]}{'↑' if z[i]>0 else '↓'}" for i in top)
        tag = "✗ЛУЗЕР" if mr < 0 else ("✓донор" if mr > 0.1 else "~ноль")
        A(f"    cat{c} n={n:4} mean-R={mr:+.3f} ΣR={sr:+5.0f} %R>0={pp*100:.0f}% [{tag}] | {prof}")


def rfilter(X, R, T, out):
    """дерево на знак R, OOS 60/40 по времени. Фронтир: дроп предсказанных лузеров."""
    A = out.append; cols = FEATS
    n = len(R); cut = int(n * 0.6)
    ytr = (R[:cut] > 0).astype(int)
    tree = DecisionTreeClassifier(max_depth=4, min_samples_leaf=60, random_state=7).fit(X[cols].values[:cut], ytr)
    pte = tree.predict_proba(X[cols].values[cut:])[:, 1]
    Rte = R[cut:]; Tte = T[cut:]
    win_tot = Rte[Rte > 0].sum(); loss_tot = -Rte[Rte < 0].sum()
    base_sum = Rte.sum(); base_net = Rte.mean()
    A(f"\n  OOS R-ФИЛЬТР (дерево на знак R, test n={len(Rte)}): без фильтра ΣR={base_sum:+.0f} net-R={base_net:+.3f}")
    A(f"    {'P(R>0)≥':>9}{'оставл':>8}{'net-R':>8}{'ΣR':>7}{'винёр-R сохр%':>14}{'лузер-R убр%':>13}")
    best = None
    for thr in [0.0, 0.40, 0.50, 0.55, 0.60]:
        keep = pte >= thr
        if keep.sum() < 20:
            continue
        sr = Rte[keep].sum(); nr = Rte[keep].mean()
        wk = Rte[keep][Rte[keep] > 0].sum() / (win_tot + 1e-9) * 100
        lr = (loss_tot - (-Rte[keep][Rte[keep] < 0].sum())) / (loss_tot + 1e-9) * 100
        mark = ""
        if best is None or sr > best[1]:
            best = (thr, sr, nr, keep.sum(), wk, lr); mark = " <-лучш ΣR"
        A(f"    {thr:>9.2f}{int(keep.sum()):>8}{nr:>+8.3f}{sr:>+7.0f}{wk:>13.0f}%{lr:>12.0f}%{mark}")
    # год-разбивка ΣR при лучшем пороге
    if best:
        thr = best[0]; keep = pte >= thr
        yr = pd.Series(Rte[keep], index=Tte[keep]).groupby(Tte[keep].year).sum()
        A(f"    при P≥{thr:.2f}: год ΣR " + "  ".join(f"{y_}:{v:+.0f}" for y_, v in yr.items()))
        yrb = pd.Series(Rte, index=Tte).groupby(Tte.year).sum()
        A(f"    (без фильтра): год ΣR " + "  ".join(f"{y_}:{v:+.0f}" for y_, v in yrb.items()))
    return best


def main():
    out = ["="*76, " RR-ФОКУС самоисправления: убрать отрицательные-R, сохранить положительные-R", "="*76]
    for tf, direction in [("8h", "long"), ("12h", "short")]:
        out.append(f"\n{'='*60}\n  {tf} · {direction.upper()} (все флагнутые, top-30%)\n{'='*60}")
        X, R, T = collect(tf, direction)
        kmeans_cats(X, R, out)
        rfilter(X, R, T, out)
        (HERE / "rr_taxonomy_report.txt").write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
