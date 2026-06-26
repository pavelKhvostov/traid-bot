"""ВОЛА-ГЕЙТ для reversal-комбо: брать сигналы только при НИЗКОЙ воле (atr_ptile<=порог, известен на входе).
Из регим-теста: edge живёт в низкой воле/ренже, дохнет в высоковола-быке (=провальные 2023-24).
Свип порога {1.0(без),0.7,0.5,0.3}: net-R/мес, Sharpe, maxDD, %плюс, год-разбивка, сделок/год. Лечит ли слабые годы?
Комбо ①8h long RR2.5-4 + ②12h short RR1.5-4. Косты TAKER 10/10 (консервативно).

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/reversal_cb/vol_gate.py
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
from rr_monthly import native_ex  # noqa: E402
HERE = Path(__file__).resolve().parent
SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


def collect(tf, direction, rlo, rhi):
    rows = []
    for s in SYMS:
        df = load(s, tf); X = feats(df)
        y, R, risk, ex = native_ex(df, direction, 0.0010, 0.0010)
        m = (y >= 0) & X[FEATS].notna().all(axis=1).values & np.isfinite(risk)
        Xf = X[FEATS][m].reset_index(drop=True); yf = y[m]
        proba, foldid = wf_raw(Xf, yf); uu = foldid >= 0
        pr = proba[uu]; thr = np.quantile(pr, 0.70); RRv = THR / risk[m][uu]
        fl = (pr >= thr) & (RRv >= rlo) & (RRv < rhi)
        ext = df.index[ex[m][uu][fl]]; Rs = R[m][uu][fl]; atrp = X["atr_ptile"].values[m][uu][fl]
        for e, r, a in zip(ext, Rs, atrp):
            rows.append(dict(exit=e, R=float(r), atrp=float(a), sym=s, dir=direction))
    return rows


def stats(M, tag, out):
    if len(M) == 0 or M.sum() == 0:
        out.append(f"    {tag}: пусто"); return
    sh = M.mean() / (M.std() + 1e-9) * np.sqrt(12)
    dd = (M.cumsum() - M.cumsum().cummax()).min()
    out.append(f"    {tag}: avgR/мес={M.mean():+.2f} Sharpe={sh:.2f} %плюс={100*(M>0).mean():.0f}% maxDD={dd:+.1f}R ΣR={M.sum():+.0f}")


def main():
    out = ["="*72, " ВОЛА-ГЕЙТ reversal-комбо (брать только при низкой воле atr_ptile<=порог)", "="*72]
    A = out.append
    rows = collect("8h", "long", 2.5, 4.0) + collect("12h", "short", 1.5, 4.0)
    df = pd.DataFrame(rows)
    df["exit"] = pd.to_datetime(df.exit, utc=True)
    df["yr"] = df.exit.dt.year
    full_idx = pd.date_range(df.exit.min().to_period("M").to_timestamp().tz_localize("UTC"),
                             df.exit.max(), freq="MS")
    A(f"\n  всего сигналов: {len(df)} (8h long + 12h short), период {full_idx.min():%Y-%m}…{full_idx.max():%Y-%m}")
    for thr in [1.01, 0.70, 0.50, 0.30]:
        g = df[df.atrp <= thr]
        lab = "БЕЗ гейта" if thr > 1 else f"вола≤{thr:.2f}"
        M = g.set_index("exit")["R"].resample("MS").sum().reindex(full_idx, fill_value=0.0)
        A(f"\n  [{lab}] сделок={len(g)} ({100*len(g)/len(df):.0f}% от всех)")
        stats(M, "комбо", out)
        # год-разбивка
        yr = g.groupby("yr")["R"].agg(["sum", "count"])
        A("    год ΣR(n): " + "  ".join(f"{int(y_)}:{r['sum']:+.0f}({int(r['count'])})" for y_, r in yr.iterrows()))
    A("\n  -> если вола≤0.5/0.3 поднимает Sharpe И тянет 2023-24 из минуса, НЕ обнуляя сделки → гейт работает.")
    o = "\n".join(out); (HERE / "vol_gate_report.txt").write_text(o, encoding="utf-8"); print(o)


if __name__ == "__main__":
    main()
