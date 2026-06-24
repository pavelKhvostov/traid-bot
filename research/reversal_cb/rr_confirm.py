"""ПОДТВЕРЖДЕНИЕ RR-кандидатов (после поправки про натуральный барьер).
Кандидаты: 8h long RR[2.5,4], 12h short RR[1.5,4], 8h short RR[1.5,2.5].
Стены: permutation-null (отбор модели vs случайный отбор В ТОМ ЖЕ RR-бакете, 500x) + год-стабильность(per-year net-R) +
OOS-late(>=2024) + per-asset. Косты TAKER 10/10 (консервативно). Если год-нестаб/p высок/OOS- — cherry-pick.

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/reversal_cb/rr_confirm.py
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
CANDIDATES = [("8h", "long", 2.5, 4.0), ("12h", "short", 1.5, 4.0), ("8h", "short", 1.5, 2.5),
              ("12h", "long", 2.5, 4.0)]


def prep(sym, tf, direction):
    df = load(sym, tf); X = feats(df)
    y, R, risk = native(df, direction, 0.0010, 0.0010)
    m = (y >= 0) & X[FEATS].notna().all(axis=1).values & np.isfinite(risk)
    Xf = X[FEATS][m].reset_index(drop=True); yf = y[m]
    proba, foldid = wf_raw(Xf, yf)
    uu = foldid >= 0
    return dict(p=proba[uu], R=R[m][uu], risk=risk[m][uu], t=df.index[m][uu])


def main():
    out = ["="*72, " ПОДТВЕРЖДЕНИЕ RR-КАНДИДАТОВ (perm-null + год + OOS, косты TAKER 10/10)", "="*72]
    A = out.append
    for tf, direction, rlo, rhi in CANDIDATES:
        A(f"\n{'='*60}\n  {tf} · {direction.upper()} · RR[{rlo},{rhi})\n{'='*60}")
        flagged_R = []; flagged_t = []; per = {}; pvals = []; obs_edges = []
        for s in SYMS:
            d = prep(s, tf, direction)
            RRv = THR / d["risk"]
            inb = (RRv >= rlo) & (RRv < rhi)
            thr = np.quantile(d["p"], 0.70)
            fl = inb & (d["p"] >= thr)
            cand = np.where(inb)[0]                       # все в бакете (для perm-null)
            if fl.sum() < 12 or len(cand) < 40:
                A(f"  {s}: мало (flag {int(fl.sum())})"); continue
            obs = float(np.mean(d["R"][fl])); nf = int(fl.sum())
            # permutation-null: случайный отбор nf из бакета
            null = [float(np.mean(d["R"][RNG.choice(cand, nf, replace=False)])) for _ in range(500)]
            p = float((np.array(null) >= obs).mean())
            per[s] = obs; pvals.append(p); obs_edges.append(obs - np.mean(null))
            flagged_R.append(d["R"][fl]); flagged_t.append(d["t"][fl])
            A(f"  {s}: n={nf} net-R={obs:+.3f} vs perm-null {np.mean(null):+.3f} (edge {obs-np.mean(null):+.3f}) p={p:.3f}")
        if not flagged_R:
            continue
        pooled = np.concatenate(flagged_R); ts = pd.DatetimeIndex(np.concatenate([t.values for t in flagged_t]))
        cross = sum(1 for v in per.values() if v > 0)
        A(f"  ПУЛ: n={len(pooled)} net-R={np.mean(pooled):+.3f} cross={cross}/3 средн.perm-p={np.mean(pvals):.3f}")
        yr = pd.Series(pooled, index=ts).groupby(ts.year).agg(["mean", "count"])
        A("  год net-R(n): " + "  ".join(f"{y_}:{r['mean']:+.2f}({int(r['count'])})" for y_, r in yr.iterrows()))
        oos = pooled[ts.year >= 2024]
        A(f"  OOS>=2024: n={len(oos)} net-R={np.mean(oos):+.3f}" if len(oos) > 20 else "  OOS>=2024: мало")
        pos_years = (yr["mean"] > 0).sum(); tot_years = len(yr)
        verdict = ("РОБАСТНО" if cross >= 2 and np.mean(pvals) < 0.15 and pos_years >= tot_years * 0.6
                   and (len(oos) <= 20 or np.mean(oos) > 0) else "НЕ робастно (cherry-pick риск)")
        A(f"  >>> {verdict}  (плюс-лет {pos_years}/{tot_years})")
    (HERE / "rr_confirm_report.txt").write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
