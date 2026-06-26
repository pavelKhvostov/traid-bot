"""TF-SWEEP Магнитуды: оптимален ли фикс 8h-long / 12h-short, или другой ТФ сильнее?
Для каждого (направление × TF): селектор reversal-likelihood (wf_raw, top-30%) + RR-бакеты, net-R + cross-asset
+ matched-random-null. Канон: long RR[2.5,4), short RR[1.5,4). TF={4h,6h,8h,12h,1d}.

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/reversal_cb/tf_sweep_magnituda.py
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
TFS = ["4h", "6h", "8h", "12h", "1d"]
RNG = np.random.default_rng(7)
BUCKETS = [(1.5, 2.5), (2.5, 4.0), (4.0, 7.0)]
CANON = {"long": (2.5, 4.0), "short": (1.5, 4.0)}


def collect(direction, tf):
    data = {}
    for s in SYMS:
        df = load(s, tf); X = feats(df); y, R, risk = native(df, direction, 0.0010, 0.0010)
        m = (y >= 0) & X[FEATS].notna().all(axis=1).values & np.isfinite(risk)
        if m.sum() < 400:
            continue
        Xf = X[FEATS][m].reset_index(drop=True); yf = y[m]
        proba, foldid = wf_raw(Xf, yf); uu = foldid >= 0
        data[s] = dict(p=proba[uu], R=R[m][uu], risk=risk[m][uu], thr=np.quantile(proba[uu], 0.70))
    return data


def bucket_stats(data, rlo, rhi):
    fR = []; nR = []; per = {}
    for s, d in data.items():
        RRv = THR / d["risk"]
        inb = (RRv >= rlo) & (RRv < rhi)
        fl = inb & (d["p"] >= d["thr"]); nu = inb & (d["p"] < d["thr"])
        if fl.sum() >= 12:
            fR.append(d["R"][fl]); per[s] = float(np.mean(d["R"][fl]))
            if nu.sum() >= 12:
                rs = RNG.choice(np.where(nu)[0], min(fl.sum(), nu.sum()), replace=False)
                nR.append(d["R"][rs])
    if not fR:
        return None
    pooled = np.concatenate(fR); nulls = np.concatenate(nR) if nR else np.array([np.nan])
    return dict(n=len(pooled), netR=float(np.mean(pooled)), null=float(np.nanmean(nulls)),
                cross=sum(1 for v in per.values() if v > 0), edge=float(np.mean(pooled) - np.nanmean(nulls)))


def main():
    out = ["="*78, " TF-SWEEP Магнитуды (селектор+RR-бакет+null, cross-asset BTC/ETH/SOL)", "="*78]
    for direction in ["long", "short"]:
        clo, chi = CANON[direction]
        out.append(f"\n{'#'*60}\n## {direction.upper()}  (канон RR[{clo},{chi}))\n{'#'*60}")
        out.append(f"  {'TF':>4} {'RR-бакет':>11}{'n':>6}{'net-R':>8}{'null':>8}{'edge':>8}{'cross':>7}{'':>4}")
        for tf in TFS:
            data = collect(direction, tf)
            if not data:
                out.append(f"  {tf:>4}  мало данных"); continue
            best = None
            for rlo, rhi in BUCKETS:
                st = bucket_stats(data, rlo, rhi)
                if st is None:
                    continue
                canon_mark = " ←канон" if (rlo, rhi) == (clo, chi) or (direction == "short" and (rlo, rhi) in [(1.5, 2.5), (2.5, 4.0)]) else ""
                good = st["cross"] >= 2 and st["edge"] > 0 and st["netR"] > 0
                out.append(f"  {tf:>4} [{rlo},{rhi})".ljust(20) + f"{st['n']:>6}{st['netR']:>+8.3f}{st['null']:>+8.3f}"
                           f"{st['edge']:>+8.3f}{st['cross']:>5}/3{('  ★' if good else ''):>4}{canon_mark}")
                if best is None or (st["cross"] >= 2 and st["edge"] > 0 and st["netR"] > best[0]):
                    best = (st["netR"], tf, rlo, rhi, st["cross"], st["edge"])
            if best and best[0] > 0:
                out.append(f"     -> лучший на {tf}: RR[{best[2]},{best[3]}) net-R={best[0]:+.3f} cross{best[4]}/3 edge{best[5]:+.3f}")
        out.append("  (★ = cross>=2 И edge>null>0 И net-R>0)")
    o = "\n".join(out); (HERE / "tf_sweep_magnituda_report.txt").write_text(o, encoding="utf-8"); print(o)


if __name__ == "__main__":
    main()
