"""ДОЖИМ РОБАСТНОСТИ 2 кандидатов: ①8h long RR[2.5,4) ②12h short RR[1.5,4).
1) block-bootstrap net-R и edge-над-null (CI + P<=0, учёт врем. кластеризации сделок).
2) режимный сплит вола(atr_ptile hi/lo) × тренд(dist_ema100 up/dn).
3) порог флага top{20,30,40}% (плато vs спайк).
4) соседние RR-бакеты (гладкость).
Косты TAKER 10/10 (консервативно).

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/reversal_cb/rr_harden.py
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
HERE = Path(__file__).resolve().parent
SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
RNG = np.random.default_rng(7)


_CACHE = {}


def prep(sym, tf, direction):
    key = (sym, tf, direction)
    if key in _CACHE:
        return _CACHE[key]
    df = load(sym, tf); X = feats(df)
    y, R, risk = native(df, direction, 0.0010, 0.0010)
    m = (y >= 0) & X[FEATS].notna().all(axis=1).values & np.isfinite(risk)
    Xf = X[FEATS][m].reset_index(drop=True); yf = y[m]
    proba, foldid = wf_raw(Xf, yf); uu = foldid >= 0
    res = dict(p=proba[uu], R=R[m][uu], risk=risk[m][uu], t=df.index[m][uu],
               atrp=X["atr_ptile"].values[m][uu], dema=X["dist_ema100"].values[m][uu])
    _CACHE[key] = res
    return res


def mbb(x, L=15, reps=2000):
    x = np.asarray(x); n = len(x)
    if n < L + 2:
        return np.array([x.mean()])
    nb = int(np.ceil(n / L)); means = []
    for _ in range(reps):
        starts = RNG.integers(0, n - L + 1, nb)
        samp = np.concatenate([x[s:s + L] for s in starts])[:n]
        means.append(samp.mean())
    return np.array(means)


def collect(tf, direction, rlo, rhi, flag_pct=0.70):
    """пул флагнутых сделок по 3 активам в RR-бакете + matched-random-null."""
    fl_R = []; nu_R = []; fl_meta = []; per = {}
    for s in SYMS:
        d = prep(s, tf, direction)
        RRv = THR / d["risk"]
        inb = (RRv >= rlo) & (RRv < rhi)
        thr = np.quantile(d["p"], flag_pct)
        fl = inb & (d["p"] >= thr); nu = inb & (d["p"] < thr)
        if fl.sum() < 12:
            continue
        order = np.argsort(d["t"][fl].values)
        fl_R.append(d["R"][fl][order]); per[s] = float(np.mean(d["R"][fl]))
        fl_meta.append(np.c_[d["atrp"][fl][order], d["dema"][fl][order]])
        if nu.sum() >= 12:
            rs = RNG.choice(np.where(nu)[0], size=min(fl.sum(), nu.sum()), replace=False)
            nu_R.append(d["R"][rs])
    if not fl_R:
        return None
    return (np.concatenate(fl_R), np.concatenate(nu_R) if nu_R else np.array([np.nan]),
            np.concatenate(fl_meta), per)


def main():
    out = ["="*72, " ДОЖИМ РОБАСТНОСТИ 2 RR-КАНДИДАТОВ (block-bootstrap+режим+порог+RR-соседи)", "="*72]
    A = out.append
    cands = [("8h", "long", 2.5, 4.0, [(2.0, 2.5), (2.5, 4.0), (4.0, 5.5)]),
             ("12h", "short", 1.5, 4.0, [(1.0, 1.5), (1.5, 2.5), (2.5, 4.0), (4.0, 5.5)])]
    for tf, direction, rlo, rhi, neighbors in cands:
        A(f"\n{'='*60}\n  {tf} · {direction.upper()} · main RR[{rlo},{rhi})\n{'='*60}")
        c = collect(tf, direction, rlo, rhi)
        if c is None:
            A("  пусто"); continue
        flR, nuR, meta, per = c
        # 1) block-bootstrap
        bm = mbb(flR); lo5, hi95 = np.percentile(bm, [5, 95]); p_le0 = float((bm <= 0).mean())
        edge = float(np.mean(flR) - np.nanmean(nuR))
        bn = mbb(nuR[~np.isnan(nuR)]) if np.isfinite(nuR).any() else np.array([0.0])
        L = min(len(bm), len(bn)); edist = bm[:L] - bn[:L]
        e_lo, e_hi = np.percentile(edist, [5, 95]); pe_le0 = float((edist <= 0).mean())
        A(f"  [1] net-R={np.mean(flR):+.3f}  block-CI90[{lo5:+.3f},{hi95:+.3f}]  P(netR<=0)={p_le0:.3f}")
        A(f"      edge-над-null={edge:+.3f}  CI90[{e_lo:+.3f},{e_hi:+.3f}]  P(edge<=0)={pe_le0:.3f}  cross={sum(v>0 for v in per.values())}/3")
        # 2) режимный сплит
        atrp = meta[:, 0]; dema = meta[:, 1]
        vhi = atrp >= np.nanmedian(atrp); tup = dema > 0
        A("  [2] режим net-R: "
          f"вола↑{np.mean(flR[vhi]):+.3f}(n{vhi.sum()}) вола↓{np.mean(flR[~vhi]):+.3f}(n{(~vhi).sum()}) | "
          f"тренд↑{np.mean(flR[tup]):+.3f}(n{tup.sum()}) тренд↓{np.mean(flR[~tup]):+.3f}(n{(~tup).sum()})")
        # 3) порог флага
        A("  [3] порог флага: " + "  ".join(
            f"top{int((1-fp)*100)}%:netR{np.mean(collect(tf,direction,rlo,rhi,fp)[0]):+.3f}(n{len(collect(tf,direction,rlo,rhi,fp)[0])})"
            for fp in [0.80, 0.70, 0.60]))
        # 4) соседние RR
        nb = []
        for nlo, nhi in neighbors:
            cc = collect(tf, direction, nlo, nhi)
            if cc is not None:
                nb.append(f"[{nlo},{nhi}):netR{np.mean(cc[0]):+.3f}(n{len(cc[0])},cross{sum(v>0 for v in cc[3].values())}/3)")
        A("  [4] RR-соседи: " + "  ".join(nb))
        # вердикт
        robust = (p_le0 < 0.15 and pe_le0 < 0.20 and sum(v > 0 for v in per.values()) >= 2
                  and np.mean(flR[vhi]) > 0 and np.mean(flR[~vhi]) > 0)
        A(f"  >>> {'ВЫДЕРЖАЛ дожим' if robust else 'СЛАБО (режим/CI/edge не уверены)'}")
    (HERE / "rr_harden_report.txt").write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
