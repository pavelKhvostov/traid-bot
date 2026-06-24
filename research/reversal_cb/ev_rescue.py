"""EV-RESCUE модуля разворотов: отбор по ожидаемому R, а не по вероятности.
EV = p_cal*RR - (1-p_cal)*1 - cost_R, где RR=3%/риск известен на входе, риск=(close-low)/close (long).
Калибровка p — leak-free: isotonic на OOS ПРОШЛЫХ фолдов (только прошлое). CatBoost БЕЗ class-weights (нативная p).
Сравнение: p>0.55 (старое) vs EV>0 vs EV>0.10. Гейты: cross-asset net-R>0 (>=2/3) + год-стабильность.

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/reversal_cb/ev_rescue.py
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
from reversal_analysis import load, feats, THR, CAP  # noqa: E402
from reversal_module import FEATS, label_and_outcome, RT_COST, SYMS  # noqa: E402
HERE = Path(__file__).resolve().parent
try:
    from sklearn.isotonic import IsotonicRegression
    HAS_ISO = True
except Exception:
    HAS_ISO = False


def cb_nw(Xtr, ytr, Xte):
    """CatBoost БЕЗ class-weights -> нативные (≈калиброванные) вероятности."""
    from catboost import CatBoostClassifier
    for tt in ("GPU", "CPU"):
        try:
            kw = dict(iterations=300, depth=6, learning_rate=0.05, loss_function="Logloss",
                      random_seed=7, verbose=False)
            if tt == "GPU":
                kw.update(task_type="GPU", devices="0")
            m = CatBoostClassifier(**kw); m.fit(Xtr, ytr); return m.predict_proba(Xte)[:, 1]
        except Exception:
            continue
    return np.full(len(Xte), 0.5)


def wf_raw(X, y, n_folds=6, embargo=CAP):
    Xv = X.values; n = len(X); edges = np.linspace(int(n * 0.4), n, n_folds + 1).astype(int)
    proba = np.full(n, np.nan); foldid = np.full(n, -1)
    for k in range(n_folds):
        te0, te1 = edges[k], edges[k + 1]; tr_end = max(0, te0 - embargo)
        if tr_end < 800 or te1 - te0 < 100:
            continue
        proba[te0:te1] = cb_nw(Xv[:tr_end], y[:tr_end], Xv[te0:te1]); foldid[te0:te1] = k
    return proba, foldid


def calib_seq(proba, y, foldid):
    cal = proba.copy()
    if not HAS_ISO:
        return cal
    for k in sorted(set(foldid[foldid >= 0])):
        cur = foldid == k; past = (foldid >= 0) & (foldid < k)
        if past.sum() > 400:
            ir = IsotonicRegression(out_of_bounds="clip"); ir.fit(proba[past], y[past])
            cal[cur] = ir.predict(proba[cur])
    return cal


def evalsel(name, sel, y, R, base, out):
    nf = int(sel.sum())
    if nf < 10:
        out.append(f"    [{name}] флагов мало ({nf})"); return None
    prec = y[sel].mean(); netR = float(np.nanmean(R[sel])); tot = float(np.nansum(R[sel]))
    out.append(f"    [{name}] флагов={nf:4} precision={prec:.3f}(база {base:.3f}) net-R={netR:+.3f} ΣR={tot:+.0f}")
    return netR


def run_dir(direction, out):
    out.append(f"\n{'='*70}\n  EV-RESCUE — {direction.upper()}\n{'='*70}")
    for tf in ["8h", "12h"]:
        out.append(f"\n--- TF {tf} ---")
        agg = {"p055": [], "ev0": [], "ev10": []}
        yragg = {"p055": {}, "ev0": {}, "ev10": {}}
        for sym in SYMS:
            df = load(sym, tf); X = feats(df); y, R, kind = label_and_outcome(df, direction)
            c = df.close.values; lo = df.low.values; h = df.high.values
            risk = (c - lo) / c if direction == "long" else (h - c) / c
            m = (y >= 0) & X[FEATS].notna().all(axis=1).values & (risk > 1e-5)
            Xf = X[FEATS][m].reset_index(drop=True); yf = y[m]; Rf = R[m]; rk = risk[m]; ix = df.index[m]
            proba, foldid = wf_raw(Xf, yf)
            cal = calib_seq(proba, yf, foldid)
            uu = foldid >= 0
            pc = cal[uu]; yk = yf[uu]; Rk = Rf[uu]; rr = THR / rk[uu]; costR = RT_COST / rk[uu]; ixu = ix[uu]
            base = yk.mean()
            ev = pc * rr - (1 - pc) * 1.0 - costR
            sel_p = (pc > 0.55)
            sel_ev0 = (ev > 0)
            sel_ev10 = (ev > 0.10)
            out.append(f"\n  {sym}: OOS n={len(yk)} base={base:.3f} (isotonic={'on' if HAS_ISO else 'off'})")
            r0 = evalsel("p>0.55", sel_p, yk, Rk, base, out)
            r1 = evalsel("EV>0", sel_ev0, yk, Rk, base, out)
            r2 = evalsel("EV>0.10", sel_ev10, yk, Rk, base, out)
            for key, sel, store in [("p055", sel_p, r0), ("ev0", sel_ev0, r1), ("ev10", sel_ev10, r2)]:
                if store is not None:
                    agg[key].append(store)
                    yr = pd.Series(Rk[sel], index=ixu[sel]).groupby(ixu[sel].year).mean()
                    for yy, vv in yr.items():
                        yragg[key].setdefault(yy, []).append(vv)
            # год для EV>0
            if r1 is not None:
                yr = pd.Series(Rk[sel_ev0], index=ixu[sel_ev0]).groupby(ixu[sel_ev0].year).mean()
                out.append("       EV>0 год net-R: " + "  ".join(f"{y_}:{v:+.2f}" for y_, v in yr.items()))
        out.append(f"\n  ИТОГ {tf} (cross-asset net-R>0 / средн net-R):")
        for key, lab in [("p055", "p>0.55"), ("ev0", "EV>0"), ("ev10", "EV>0.10")]:
            v = agg[key]
            if v:
                out.append(f"    {lab:9}: {sum(1 for r in v if r>0)}/3  средн {np.mean(v):+.3f}")


def main():
    out = ["="*70, " EV-RESCUE разворотного модуля (отбор по ожидаемому R + калибровка)", "="*70,
           f" sklearn-isotonic={'есть' if HAS_ISO else 'НЕТ (raw p)'}  RT={RT_COST*1e4:.0f}bps TP=±{THR*100:.0f}%"]
    for d in ["long", "short"]:
        run_dir(d, out)
        (HERE / "ev_rescue_report.txt").write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
