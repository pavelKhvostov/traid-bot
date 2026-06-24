"""РЕГИМ-ТЕСТ комбо ①8h long RR2.5-4 + ②12h short RR1.5-4: почему профит в 2025-26?
(а) режим-ставка или (б) walk-forward крепчание модели.
1) net-R по фолдам (монотонно? = крепчание). 2) net-R по режиму BTC (тренд×вола). 3) режим рано(≤2024) vs поздно(≥2025).
Косты TAKER 10/10. Режим BTC = дневной: тренд=знак 60d-ретёрна, вола=перцентиль ATR.

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/reversal_cb/rr_regime.py
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


def btc_regime():
    d = load("BTCUSDT", "1d")
    c = d.close
    ret60 = c.pct_change(60)
    tr = pd.Series(np.maximum(d.high - d.low, np.maximum((d.high - c.shift()).abs(), (d.low - c.shift()).abs())))
    atr = tr.rolling(14).mean(); atrp = atr.rolling(200).rank(pct=True)
    reg = pd.DataFrame({"trend_bull": (ret60 > 0).astype(float), "vol_hi": (atrp.values >= 0.5).astype(float),
                        "ret60": ret60.values}, index=c.index)
    return reg


def collect(tf, direction, rlo, rhi, flag_pct=0.70):
    rows = []
    for s in SYMS:
        df = load(s, tf); X = feats(df)
        y, R, risk, ex = native_ex(df, direction, 0.0010, 0.0010)
        m = (y >= 0) & X[FEATS].notna().all(axis=1).values & np.isfinite(risk)
        Xf = X[FEATS][m].reset_index(drop=True); yf = y[m]
        proba, foldid = wf_raw(Xf, yf); uu = foldid >= 0
        pr = proba[uu]; thr = np.quantile(pr, flag_pct); RRv = THR / risk[m][uu]
        fl = (pr >= thr) & (RRv >= rlo) & (RRv < rhi)
        ent = df.index[m][uu][fl]; ext = df.index[ex[m][uu][fl]]
        Rs = R[m][uu][fl]; fds = foldid[uu][fl]
        for e, x, r, fd in zip(ent, ext, Rs, fds):
            rows.append(dict(entry=e, exit=x, R=float(r), fold=int(fd), sym=s, dir=direction))
    return rows


def main():
    out = ["="*72, " РЕГИМ-ТЕСТ комбо разворотов (режим-ставка или крепчание модели?)", "="*72]
    A = out.append
    rows = collect("8h", "long", 2.5, 4.0) + collect("12h", "short", 1.5, 4.0)
    df = pd.DataFrame(rows).sort_values("entry").reset_index(drop=True)
    reg = btc_regime()
    # asof режим BTC на момент входа (merge_asof — устойчив к дубликатам таймстемпов)
    df["entry"] = pd.to_datetime(df.entry, utc=True)
    df = df.sort_values("entry").reset_index(drop=True)
    regr = reg.reset_index(); regr = regr.rename(columns={regr.columns[0]: "rt"}).sort_values("rt")
    df = pd.merge_asof(df, regr, left_on="entry", right_on="rt", direction="backward")
    df = df.rename(columns={"trend_bull": "bull", "vol_hi": "volhi"})
    df["yr"] = pd.to_datetime(df.exit, utc=True).dt.year

    A(f"\n  сделок={len(df)}  ΣR={df.R.sum():+.0f}  net-R={df.R.mean():+.3f}")

    A("\n  [1] net-R ПО WALK-FORWARD ФОЛДАМ (рост = крепчание модели):")
    for fd, g in df.groupby("fold"):
        yrs = sorted(pd.to_datetime(g.exit, utc=True).dt.year.unique())
        A(f"    fold{fd}: n={len(g):4} net-R={g.R.mean():+.3f} ΣR={g.R.sum():+5.0f}  годы {yrs}")

    A("\n  [2] net-R ПО РЕЖИМУ BTC (на входе):")
    for name, mask in [("тренд БЫК", df.bull == 1), ("тренд МЕДВЕДЬ", df.bull == 0),
                       ("вола ВЫСОКАЯ", df.volhi == 1), ("вола НИЗКАЯ", df.volhi == 0)]:
        g = df[mask]
        if len(g) > 20:
            A(f"    {name:14} n={len(g):4} net-R={g.R.mean():+.3f} ΣR={g.R.sum():+5.0f} %плюс={100*(g.R>0).mean():.0f}%")
    A("    --- 2x2 (тренд×вола): ---")
    for b in [1, 0]:
        for v in [1, 0]:
            g = df[(df.bull == b) & (df.volhi == v)]
            if len(g) > 15:
                A(f"    {'бык' if b else 'медв'}/{'волаВ' if v else 'волаН'}: n={len(g):4} net-R={g.R.mean():+.3f} ΣR={g.R.sum():+5.0f}")
    A("    --- по направлению × тренд: ---")
    for d in ["long", "short"]:
        for b in [1, 0]:
            g = df[(df.dir == d) & (df.bull == b)]
            if len(g) > 15:
                A(f"    {d:5}/{'бык' if b else 'медв'}: n={len(g):4} net-R={g.R.mean():+.3f} ΣR={g.R.sum():+5.0f}")

    A("\n  [3] РЕЖИМ РАНО (≤2024) vs ПОЗДНО (≥2025):")
    early = df[df.yr <= 2024]; late = df[df.yr >= 2025]
    for nm, g in [("≤2024", early), ("≥2025", late)]:
        A(f"    {nm}: n={len(g):4} net-R={g.R.mean():+.3f} ΣR={g.R.sum():+5.0f} | "
          f"%бык={100*g.bull.mean():.0f}% %волаВ={100*g.volhi.mean():.0f}% ret60_avg={g.ret60.mean():+.3f}")
    A("    -> если режимы рано/поздно ПОХОЖИ, а net-R разный → крепчание модели (б), не режим (а).")
    A("    -> если поздно сильно %бык/вола иной И edge сидит в этой ячейке выше → режим-ставка (а).")

    o = "\n".join(out); (HERE / "rr_regime_report.txt").write_text(o, encoding="utf-8"); print(o)


if __name__ == "__main__":
    main()
