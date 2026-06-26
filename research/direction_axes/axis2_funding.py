"""ОСЬ 2 — funding rate (позиционирование перпов): предсказывает ли funding знак BTC?
Гипотеза: экстрим funding = перегрев толпы = контртренд. Цадь: знак 8h-fwd (и 1d-fwd) BTC.
Фичи: уровень, z-score(90), изменение, кумулятивы. Стены: own-AR baseline + funding; block-OOS; null; год;
cross-asset(ETH/SOL funding -> свой знак); квантиль-кондишн (экстрим funding -> P(down), meanFwd).

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/direction_axes/axis2_funding.py
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
HERE = Path(__file__).resolve().parent
RNG = np.random.default_rng(7)


def load(sym):
    px = pd.read_csv(ROOT / "data" / f"{sym}_8h.csv")
    tc = [c for c in px.columns if "time" in c.lower()][0]
    px[tc] = pd.to_datetime(px[tc], utc=True)
    px = px.set_index(tc).sort_index()["close"].astype(float)
    fr = pd.read_csv(HERE / f"funding_{sym}.csv")
    fr["fundingTime"] = pd.to_datetime(fr["fundingTime"], utc=True, format="ISO8601")
    fr = fr.set_index("fundingTime").sort_index()["fundingRate"].astype(float)
    fr.index = fr.index.floor("8h")
    fr = fr[~fr.index.duplicated(keep="last")]
    df = pd.DataFrame({"close": px, "fr": fr}).dropna()
    return df


def feats_of(df):
    X = pd.DataFrame(index=df.index)
    r = df.close.pct_change(fill_method=None)
    X["fr"] = df.fr
    X["fr_z"] = (df.fr - df.fr.rolling(90).mean()) / (df.fr.rolling(90).std() + 1e-12)
    X["fr_chg"] = df.fr.diff()
    X["fr_cum3"] = df.fr.rolling(3).sum()
    X["fr_cum9"] = df.fr.rolling(9).sum()
    X["r1"] = r; X["r2"] = r.shift(1); X["r3"] = r.shift(2)   # own-AR
    X["fwd"] = r.shift(-1)
    return X.dropna()


def fit(Xtr, ytr, Xte):
    mu = Xtr.mean(0); sd = Xtr.std(0) + 1e-9
    Z = np.c_[np.ones(len(Xtr)), (Xtr - mu) / sd]; Zt = np.c_[np.ones(len(Xte)), (Xte - mu) / sd]
    w = np.zeros(Z.shape[1])
    for _ in range(700):
        p = 1 / (1 + np.exp(-Z @ w))
        w -= 0.3 * (Z.T @ (p - ytr) / len(ytr) + 1e-3 * np.r_[0, w[1:]])
    return 1 / (1 + np.exp(-Zt @ w))


FUND = ["fr", "fr_z", "fr_chg", "fr_cum3", "fr_cum9"]
OWN = ["r1", "r2", "r3"]


def ev(X, feats, te, spl):
    y = (X.fwd > 0).astype(int).values; fwd = X.fwd.values
    p = fit(X[feats].values[spl], y[spl], X[feats].values[te])
    pred = (p > 0.5).astype(int)
    return (pred == y[te]).mean(), float(np.mean(np.where(pred == 1, 1, -1) * fwd[te])), pred, y[te], fwd[te]


def main():
    out = ["="*64, " ОСЬ 2 — FUNDING RATE -> направление BTC (8h)", "="*64]
    A = out.append
    dfb = load("BTCUSDT"); X = feats_of(dfb)
    A(f"BTC: {len(X)} 8h-баров, {X.index[0].date()} -> {X.index[-1].date()}")
    spl = X.index < pd.Timestamp("2024-01-01", tz="UTC"); te = ~spl
    A(f"OOS>=2024: {te.sum()} баров")

    a_own, s_own, *_ = ev(X, OWN, te, spl)
    a_f, s_f, predf, yte, fwdte = ev(X, OWN + FUND, te, spl)
    a_fund, s_fund, *_ = ev(X, FUND, te, spl)
    maj = max(yte.mean(), 1 - yte.mean())
    nulls = [np.mean(predf == RNG.permutation(yte)) for _ in range(500)]
    null_p = float((np.array(nulls) >= a_f).mean())
    idx = X.index[te]; yrs = pd.Series(predf == yte, index=idx).groupby(idx.year).mean()
    A(f"\nmajority={maj:.3f}")
    A(f"own-AR:            acc={a_own:.3f}  signed-ret={s_own:+.6f}")
    A(f"funding-only:      acc={a_fund:.3f}  signed-ret={s_fund:+.6f}")
    A(f"FULL(own+funding): acc={a_f:.3f}  signed-ret={s_f:+.6f}   -> funding над own: {a_f-a_own:+.3f}")
    A(f"permutation-null: {np.mean(nulls):.3f}±{np.std(nulls):.3f}  p={null_p:.3f}")
    A("год OOS: " + "  ".join(f"{y_}:{v:.3f}" for y_, v in yrs.items()))

    # квантиль-кондишн: экстрим funding -> что дальше (описательно, на всей выборке)
    A("\nКВАНТИЛЬ-КОНДИШН (экстрим funding -> следующий 8h BTC):")
    for lab, mask in [("top10% (перегрев лонгов)", X.fr >= X.fr.quantile(0.9)),
                      ("bot10% (перегрев шортов)", X.fr <= X.fr.quantile(0.1)),
                      ("z>+2 (резкий перегрев)", X.fr_z >= 2),
                      ("z<-2", X.fr_z <= -2)]:
        s = X[mask]
        if len(s) > 20:
            A(f"  {lab:26} n={len(s):4}  P(down)={(s.fwd<0).mean():.3f}  meanFwd={s.fwd.mean():+.6f}")

    # 1d-горизонт: funding (дневное среднее) -> знак BTC завтра
    A("\n1d-ГОРИЗОНТ: дневной funding -> знак BTC[t+1d]")
    d = dfb.copy()
    dd = pd.DataFrame({"close": d.close.resample("1d").last(), "fr": d.fr.resample("1d").mean()}).dropna()
    rr = dd.close.pct_change(fill_method=None)
    Xd = pd.DataFrame({"fr": dd.fr, "fr_z": (dd.fr - dd.fr.rolling(30).mean()) / (dd.fr.rolling(30).std() + 1e-12),
                       "r1": rr, "r2": rr.shift(1), "fwd": rr.shift(-1)}).dropna()
    spl2 = Xd.index < pd.Timestamp("2024-01-01", tz="UTC"); te2 = ~spl2
    a_o2, s_o2, *_ = ev(Xd, ["r1", "r2"], te2, spl2)
    a_f2, s_f2, p2, y2, _ = ev(Xd, ["fr", "fr_z", "r1", "r2"], te2, spl2)
    n2 = [np.mean(p2 == RNG.permutation(y2)) for _ in range(500)]
    A(f"  own-AR acc={a_o2:.3f} | +funding acc={a_f2:.3f} ({a_f2-a_o2:+.3f})  null {np.mean(n2):.3f} p={(np.array(n2)>=a_f2).mean():.3f}")
    hi = Xd[Xd.fr >= Xd.fr.quantile(0.9)]; lo = Xd[Xd.fr <= Xd.fr.quantile(0.1)]
    A(f"  top10% funding -> P(down завтра)={(hi.fwd<0).mean():.3f} meanFwd={hi.fwd.mean():+.5f} | "
      f"bot10% -> P(down)={(lo.fwd<0).mean():.3f} meanFwd={lo.fwd.mean():+.5f}")

    # cross-asset robustness
    A("\nCROSS-ASSET (funding -> свой знак, 8h, OOS>=2024):")
    for sym in ["ETHUSDT", "SOLUSDT"]:
        try:
            Xs = feats_of(load(sym)); ss = Xs.index < pd.Timestamp("2024-01-01", tz="UTC"); ts = ~ss
            ao, so, *_ = ev(Xs, OWN, ts, ss); af, sf, *_ = ev(Xs, OWN + FUND, ts, ss)
            A(f"  {sym}: own={ao:.3f} +funding={af:.3f} ({af-ao:+.3f})  ret_full={sf:+.6f}")
        except Exception as e:
            A(f"  {sym}: err {str(e)[:60]}")

    o = "\n".join(out); (HERE / "axis2_report.txt").write_text(o, encoding="utf-8"); print(o)


if __name__ == "__main__":
    main()
