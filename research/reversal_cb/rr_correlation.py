"""КОРРЕЛЯЦИЯ reversal-комбо (①8h long RR2.5-4 + ②12h short RR1.5-4) с боевой корзиной (111/112/115/32/A_irdrb).
Помесячные R-ряды (по месяцу выхода), gross (для консистентности). Корр-матрица + прирост Sharpe от добавления reversal.
Equal-risk: portfolio = равновзвешенное среднее помесячных R компонент.

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/reversal_cb/rr_correlation.py
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
from rr_monthly import trades  # noqa: E402
ROOT = Path(__file__).resolve().parents[2]
FIN = ROOT / "research" / "financial"
BASKET = ["111", "112", "115", "32", "A_irdrb"]


def basket_monthly(name):
    d = pd.read_csv(FIN / f"trades_{name}.csv")
    d["exit_time"] = pd.to_datetime(d["exit_time"], utc=True, errors="coerce")
    d = d.dropna(subset=["exit_time"])
    s = d.set_index("exit_time")["gross_R"].sort_index()
    return s.resample("MS").sum()


def main():
    out = ["="*70, " КОРРЕЛЯЦИЯ reversal-комбо с боевой корзиной + прирост Sharpe", "="*70]
    A = out.append
    series = {}
    for n in BASKET:
        series[n] = basket_monthly(n)
    # reversal combo GROSS (cost=0)
    t1 = trades("8h", "long", 2.5, 4.0, 0.0, 0.0)
    t2 = trades("12h", "short", 1.5, 4.0, 0.0, 0.0)
    rev = pd.concat([pd.DataFrame(t1, columns=["t", "R", "sym", "dir"]),
                     pd.DataFrame(t2, columns=["t", "R", "sym", "dir"])]).set_index("t").sort_index()
    series["REV"] = rev["R"].resample("MS").sum()

    # общий индекс (union), пустые месяцы = 0
    allidx = pd.DatetimeIndex(sorted(set().union(*[s.index for s in series.values()])))
    M = pd.DataFrame({k: s.reindex(allidx, fill_value=0.0) for k, s in series.items()})
    # ограничим окном, где есть reversal (иначе корзина в одиночку до 2022)
    cut = rev.index.min().to_period("M").to_timestamp().tz_localize("UTC")
    M = M.loc[M.index >= cut]
    A(f"\n  период: {M.index.min():%Y-%m} … {M.index.max():%Y-%m} ({len(M)} мес)")

    A("\n  [Sharpe(год) и avg R/мес каждой компоненты]")
    for c in M.columns:
        s = M[c]; sh = s.mean() / (s.std() + 1e-9) * np.sqrt(12)
        A(f"    {c:8} avgR/мес={s.mean():+.2f}  Sharpe={sh:.2f}  плюс-мес={100*(s>0).mean():.0f}%")

    A("\n  [Корреляция REV с каждой (помесячно)]")
    for c in BASKET:
        A(f"    REV ↔ {c:8}: corr={M['REV'].corr(M[c]):+.2f}")
    basket_eq = M[BASKET].mean(axis=1)
    A(f"    REV ↔ КОРЗИНА(равновес): corr={M['REV'].corr(basket_eq):+.2f}")

    A("\n  [Прирост Sharpe от добавления REV в корзину]")
    def sharpe(s):
        return s.mean() / (s.std() + 1e-9) * np.sqrt(12)
    p5 = M[BASKET].mean(axis=1)
    p6 = M[BASKET + ["REV"]].mean(axis=1)
    A(f"    корзина 5 (равновес): Sharpe={sharpe(p5):.2f}  avgR/мес={p5.mean():+.2f}  maxDD={ (p5.cumsum()-p5.cumsum().cummax()).min():+.1f}R")
    A(f"    +REV  6 (равновес):  Sharpe={sharpe(p6):.2f}  avgR/мес={p6.mean():+.2f}  maxDD={ (p6.cumsum()-p6.cumsum().cummax()).min():+.1f}R")
    # вес-оптимум по Sharpe (грубо: доля reversal 0..0.6)
    A("    доля REV в портфеле -> Sharpe:")
    for w in [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]:
        p = (1 - w) * p5 + w * M["REV"]
        A(f"      w_REV={w:.1f}: Sharpe={sharpe(p):.2f} avgR/мес={p.mean():+.2f}")

    o = "\n".join(out); (Path(__file__).resolve().parent / "rr_correlation_report.txt").write_text(o, encoding="utf-8"); print(o)


if __name__ == "__main__":
    main()
