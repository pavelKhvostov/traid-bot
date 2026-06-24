"""СЛОЙ САМОИСПРАВЛЕНИЯ: таксономия разворотных сигналов + OOS-отбраковка ложных (мало теряя верных).
1) Категории по общим признакам (KMeans) + precision/net-R каждой.
2) Дерево решений на флагнутых (листья=категории с порогами фич) -> дроп низко-precision листьев.
   ВАЛИДАЦИЯ OOS: фильтр учится на первых 60% времени, проверяется на последних 40% (иначе мираж).
   Метрика: % убранных FP vs % сохранённых TP (фронтир) + net-R до/после.
long и short, пул BTC/ETH/SOL (+per-asset), 12h.

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/reversal_cb/reversal_taxonomy.py
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
from reversal_analysis import load, feats  # noqa: E402
from reversal_module import FEATS, label_and_outcome  # noqa: E402
from ev_rescue import wf_raw  # noqa: E402
from sklearn.cluster import KMeans  # noqa: E402
from sklearn.tree import DecisionTreeClassifier, export_text  # noqa: E402
HERE = Path(__file__).resolve().parent
SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
TF = "12h"


def collect(direction):
    """пул флагнутых OOS-кандидатов (top-30% proba per asset): фичи, y, R, время, актив."""
    rows = []
    for sym in SYMS:
        df = load(sym, TF); X = feats(df); y, R, kind = label_and_outcome(df, direction)
        m = (y >= 0) & X[FEATS].notna().all(axis=1).values
        Xf = X[FEATS][m].reset_index(drop=True); yf = y[m]; Rf = R[m]; ix = df.index[m]
        proba, foldid = wf_raw(Xf, yf)
        uu = foldid >= 0
        pr = proba[uu]; yk = yf[uu]; Rk = Rf[uu]; Xk = Xf[uu].reset_index(drop=True); ixu = ix[uu]
        thr = np.quantile(pr, 0.70)               # «флаг» = верхние 30% уверенности
        fl = pr >= thr
        sub = Xk[fl].copy()
        sub["_y"] = yk[fl]; sub["_R"] = Rk[fl]; sub["_t"] = ixu[fl]; sub["_sym"] = sym; sub["_p"] = pr[fl]
        rows.append(sub)
    return pd.concat(rows, ignore_index=True)


def zprofile(Xz, idx, cols, top=4):
    """топ отличительных фич категории: средний z (по всему пулу) внутри idx."""
    z = Xz[idx].mean(0)
    order = np.argsort(-np.abs(z))[:top]
    return ", ".join(f"{cols[i]}{'↑' if z[i]>0 else '↓'}{z[i]:+.1f}" for i in order)


def categories(P, out):
    cols = FEATS
    Xall = P[cols].values
    mu = Xall.mean(0); sd = Xall.std(0) + 1e-9; Xz = (Xall - mu) / sd
    base = P["_y"].mean()
    out.append(f"\n  КАТЕГОРИИ (KMeans k=5) — n={len(P)}, base precision={base:.3f}, ср.net-R={P['_R'].mean():+.3f}")
    km = KMeans(n_clusters=5, random_state=7, n_init=10).fit(Xz)
    lab = km.labels_
    cat = []
    for c in range(5):
        idx = lab == c
        prec = P["_y"][idx].mean(); nr = P["_R"][idx].mean(); n = int(idx.sum())
        # per-asset precision
        pa = P[idx].groupby("_sym")["_y"].mean()
        prof = zprofile(Xz, idx, cols)
        cat.append((c, n, prec, nr, prof, pa))
    for c, n, prec, nr, prof, pa in sorted(cat, key=lambda r: -r[2]):
        tag = "✓верн.-богатая" if prec >= base + 0.05 else ("✗ложно-богатая" if prec <= base - 0.05 else "~средняя")
        pas = "/".join(f"{s[:3]}{v:.2f}" for s, v in pa.items())
        out.append(f"    cat{c} n={n:4} precision={prec:.3f} net-R={nr:+.3f} [{tag}] | {prof} | per-asset {pas}")
    return base


def fp_filter(P, out):
    """дерево решений (категории=листья) -> дроп низко-precision листьев. OOS: учим на 60% времени, тест на 40%."""
    P = P.sort_values("_t").reset_index(drop=True)
    cols = FEATS
    X = P[cols].values; y = P["_y"].values; R = P["_R"].values
    n = len(P); cut = int(n * 0.6)
    Xtr, ytr = X[:cut], y[:cut]; Xte, yte, Rte = X[cut:], y[cut:], R[cut:]
    base_te = yte.mean()
    tree = DecisionTreeClassifier(max_depth=3, min_samples_leaf=80, random_state=7).fit(Xtr, ytr)
    leaf_tr = tree.apply(Xtr); leaf_te = tree.apply(Xte)
    # precision каждого листа на TRAIN
    lp = {lf: ytr[leaf_tr == lf].mean() for lf in np.unique(leaf_tr)}
    out.append(f"\n  OOS-ФИЛЬТР (дерево гл.3, train 60%/test 40%) — test n={len(yte)} base precision={base_te:.3f}")
    out.append(f"    {'drop-порог':>11}{'оставлено':>10}{'precision':>10}{'TP-сохр%':>10}{'FP-убр%':>9}{'net-R':>8}")
    tp_all = int((yte == 1).sum()); fp_all = int((yte == 0).sum())
    best = None
    for bar in [0.00, base_te, base_te + 0.05, base_te + 0.10, base_te + 0.15]:
        keep_leaves = {lf for lf, p in lp.items() if p >= bar}
        keep = np.array([l in keep_leaves for l in leaf_te])
        if keep.sum() < 30:
            continue
        prec = yte[keep].mean(); tpk = int(((yte == 1) & keep).sum()); fpk = int(((yte == 0) & keep).sum())
        tp_pct = tpk / max(1, tp_all) * 100; fp_rm = (1 - fpk / max(1, fp_all)) * 100
        nr = float(np.nanmean(Rte[keep]))
        mark = ""
        if best is None or (tp_pct >= 80 and prec > best[1]):
            best = (bar, prec, tp_pct, fp_rm, nr); mark = " <-"
        out.append(f"    {bar:>11.3f}{int(keep.sum()):>10}{prec:>10.3f}{tp_pct:>10.1f}{fp_rm:>9.1f}{nr:>+8.3f}{mark}")
    # «ложные» листья: precision на train ниже base
    low = {lf for lf, p in lp.items() if p < base_te}
    if low:
        # описать общие признаки ложных (mean фич в low-листьях на test) vs верных
        lowmask = np.array([l in low for l in leaf_te])
        out.append("    ОБЩИЕ ПРИЗНАКИ ЛОЖНЫХ листьев (test, среднее vs верные):")
        mu = X.mean(0); sd = X.std(0) + 1e-9
        zlow = ((Xte[lowmask] - mu) / sd).mean(0); zhi = ((Xte[~lowmask] - mu) / sd).mean(0)
        d = zlow - zhi; order = np.argsort(-np.abs(d))[:5]
        out.append("      " + " | ".join(f"{cols[i]}: ложн {zlow[i]:+.2f} vs верн {zhi[i]:+.2f}" for i in order))
    # читаемое дерево (первые строки)
    txt = export_text(tree, feature_names=list(cols), max_depth=3).splitlines()
    out.append("    дерево (фрагмент): " + " ;; ".join(s.strip() for s in txt[:8]))
    return best


def main():
    out = ["="*74, " ТАКСОНОМИЯ РАЗВОРОТОВ + OOS-ОТБРАКОВКА ЛОЖНЫХ (long & short, 12h)", "="*74]
    for d in ["long", "short"]:
        out.append(f"\n{'#'*60}\n## {d.upper()}\n{'#'*60}")
        P = collect(d)
        base = categories(P, out)
        best = fp_filter(P, out)
        if best:
            out.append(f"\n  >>> РЕКОМЕНД. точка фильтра: drop<{best[0]:.3f} -> precision {best[1]:.3f}, "
                       f"сохранено TP {best[2]:.0f}%, убрано FP {best[3]:.0f}%, net-R {best[4]:+.3f}")
        (HERE / "reversal_taxonomy_report.txt").write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
