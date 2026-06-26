"""ОСЬ 3 — signed order flow (taker delta / CVD) -> направление BTC[t+1], 1h. Реальные данные orderflow.csv.
Отлично от прошлого теста «поток В ТОЧКЕ реакции у зон» (тот провалился): тут глобальный директ-предиктор.
Стены: own-AR baseline + flow; block-OOS; null; год; квантиль-кондишн.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
ROOT = Path(__file__).resolve().parents[2]
RNG = np.random.default_rng(7)


def fit(Xtr, ytr, Xte):
    mu = Xtr.mean(0); sd = Xtr.std(0) + 1e-9
    Z = np.c_[np.ones(len(Xtr)), (Xtr - mu) / sd]; Zt = np.c_[np.ones(len(Xte)), (Xte - mu) / sd]
    w = np.zeros(Z.shape[1])
    for _ in range(700):
        p = 1 / (1 + np.exp(-Z @ w))
        w -= 0.3 * (Z.T @ (p - ytr) / len(ytr) + 1e-3 * np.r_[0, w[1:]])
    return 1 / (1 + np.exp(-Zt @ w))


def ev(X, feats, te, spl):
    y = (X.fwd > 0).astype(int).values; fwd = X.fwd.values
    p = fit(X[feats].values[spl], y[spl], X[feats].values[te]); pred = (p > 0.5).astype(int)
    return (pred == y[te]).mean(), float(np.mean(np.where(pred == 1, 1, -1) * fwd[te])), pred, y[te]


def main():
    out = ["="*60, " ОСЬ 3 — SIGNED ORDER FLOW (taker delta/CVD) -> BTC 1h", "="*60]; A = out.append
    d = pd.read_csv(ROOT / "data" / "BTCUSDT_1h_orderflow.csv", parse_dates=["open_time"])
    d = d.set_index("open_time").sort_index()
    r = d.close.pct_change(fill_method=None)
    X = pd.DataFrame(index=d.index)
    X["dn"] = d.delta_norm; X["dn1"] = d.delta_norm.shift(1); X["dn2"] = d.delta_norm.shift(2)
    X["cvd6"] = d.delta_norm.rolling(6).mean(); X["cvd24"] = d.delta_norm.rolling(24).mean()
    X["r1"] = r; X["r2"] = r.shift(1); X["r3"] = r.shift(2)
    X["fwd"] = r.shift(-1)
    X = X.dropna()
    spl = X.index < pd.Timestamp("2024-01-01", tz="UTC") if X.index.tz else X.index < pd.Timestamp("2024-01-01")
    te = ~spl
    A(f"{len(X)} 1h-баров {X.index[0].date()}->{X.index[-1].date()}; OOS>=2024 {te.sum()}")
    FLOW = ["dn", "dn1", "dn2", "cvd6", "cvd24"]; OWN = ["r1", "r2", "r3"]
    a_o, s_o, *_ = ev(X, OWN, te, spl)
    a_f, s_f, pf, yte = ev(X, OWN + FLOW, te, spl)
    a_fl, s_fl, *_ = ev(X, FLOW, te, spl)
    maj = max(yte.mean(), 1 - yte.mean())
    nulls = [np.mean(pf == RNG.permutation(yte)) for _ in range(400)]
    idx = X.index[te]; yrs = pd.Series(pf == yte, index=idx).groupby(idx.year).mean()
    A(f"majority={maj:.3f}")
    A(f"own-AR:        acc={a_o:.3f} ret={s_o:+.6f}")
    A(f"flow-only:     acc={a_fl:.3f} ret={s_fl:+.6f}")
    A(f"FULL(own+flow):acc={a_f:.3f} ret={s_f:+.6f}  -> flow над own {a_f-a_o:+.3f}")
    A(f"null {np.mean(nulls):.3f}±{np.std(nulls):.3f} p={(np.array(nulls)>=a_f).mean():.3f}")
    A("год OOS: " + "  ".join(f"{y_}:{v:.3f}" for y_, v in yrs.items()))
    A("\nКВАНТИЛЬ delta_norm -> следующий 1h:")
    for lab, m in [("top10% (агресс. покупки)", X.dn >= X.dn.quantile(0.9)),
                   ("bot10% (агресс. продажи)", X.dn <= X.dn.quantile(0.1))]:
        s = X[m]; A(f"  {lab:26} n={len(s):5} P(up)={(s.fwd>0).mean():.3f} meanFwd={s.fwd.mean():+.6f}")
    o = "\n".join(out); (Path(__file__).resolve().parent / "axis3_report.txt").write_text(o, encoding="utf-8"); print(o)


if __name__ == "__main__":
    main()
