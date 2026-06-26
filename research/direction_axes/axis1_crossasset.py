"""ОСЬ 1 — cross-asset lead-lag: предсказывает ли знак BTC[t+1] инфо ВНЕ свечи BTC?
Фичи в t (известны на закрытии t): собств. AR BTC + ETH/SOL/USDT.D/TOTAL ретёрны + относит.сила + базис BTC1!.
Стены: accuracy(full) vs own-AR vs majority vs persistence; block-OOS(<=23/>=24); permutation-null; год-стабильность;
cross-target (та же модель на ETH/SOL). Метрика — ACCURACY (Right/Wrong) + чистый signed-return.

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/direction_axes/axis1_crossasset.py
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


def load_close(name, tf="1d", daily_norm=False):
    f = ROOT / "data" / f"{name}_{tf}.csv"
    d = pd.read_csv(f)
    tc = [c for c in d.columns if "time" in c.lower() or "date" in c.lower()][0]
    d[tc] = pd.to_datetime(d[tc], utc=True)
    d = d.set_index(tc).sort_index()
    s = d["close"].astype(float)
    if daily_norm:                       # фьючерс/доминация бывают со смещением часов -> к дате
        s.index = s.index.normalize()
        s = s[~s.index.duplicated(keep="last")]
    return s


def build(tf="1d"):
    dn = (tf == "1d")
    btc = load_close("BTCUSDT", tf, dn); eth = load_close("ETHUSDT", tf, dn); sol = load_close("SOLUSDT", tf, dn)
    usdtd = load_close("USDT_D", tf, dn); total = load_close("TOTALES", tf, dn)
    try:
        btc1 = load_close("BTC1", tf, dn)
    except Exception:
        btc1 = None
    df = pd.DataFrame({"btc": btc, "eth": eth, "sol": sol, "usdtd": usdtd, "total": total})
    if btc1 is not None:
        df["btc1"] = btc1
    df = df.dropna(subset=["btc", "eth", "sol", "usdtd"])
    r = df.pct_change(fill_method=None)
    X = pd.DataFrame(index=df.index)
    X["r_btc"] = r.btc; X["r_btc1"] = r.btc.shift(1); X["r_btc2"] = r.btc.shift(2)  # own-AR
    X["r_eth"] = r.eth; X["r_sol"] = r.sol; X["r_usdtd"] = r.usdtd
    X["r_total"] = r.total
    X["rel_eth"] = r.eth - r.btc; X["rel_sol"] = r.sol - r.btc
    if "btc1" in df:
        X["basis"] = (df.btc1 - df.btc) / df.btc
    X["fwd_btc"] = r.btc.shift(-1)  # цель: ретёрн BTC t->t+1
    X["fwd_eth"] = r.eth.shift(-1); X["fwd_sol"] = r.sol.shift(-1)
    # фичи с покрытием < 90% (basis/total там, где история короче) исключаем, чтобы не обнулять выборку
    must = OWN + ["r_eth", "r_sol", "r_usdtd", "rel_eth", "rel_sol", "fwd_btc", "fwd_eth", "fwd_sol"]
    opt = [c for c in ["r_total", "basis"] if c in X and X[c].notna().mean() >= 0.90]
    X = X[must + opt].dropna()
    X.attrs["opt"] = opt
    return X


OWN = ["r_btc", "r_btc1", "r_btc2"]
CROSS = ["r_eth", "r_sol", "r_usdtd", "r_total", "rel_eth", "rel_sol", "basis"]


def fit_logit(Xtr, ytr, Xte):
    """мини-логистика на numpy (стандартизация + GD), без sklearn-зависимостей."""
    mu = Xtr.mean(0); sd = Xtr.std(0) + 1e-9
    Z = (Xtr - mu) / sd; Zt = (Xte - mu) / sd
    Z = np.c_[np.ones(len(Z)), Z]; Zt = np.c_[np.ones(len(Zt)), Zt]
    w = np.zeros(Z.shape[1]); lr = 0.3
    for _ in range(600):
        p = 1 / (1 + np.exp(-Z @ w))
        g = Z.T @ (p - ytr) / len(ytr) + 1e-3 * np.r_[0, w[1:]]
        w -= lr * g
    return 1 / (1 + np.exp(-Zt @ w))


def evalset(X, feats, target="fwd_btc", split="2024-01-01"):
    y = (X[target] > 0).astype(int).values
    fwd = X[target].values
    tr = X.index < pd.Timestamp(split, tz="UTC"); te = ~tr
    Xtr, Xte = X[feats].values[tr], X[feats].values[te]
    ytr, yte = y[tr], y[te]
    p = fit_logit(Xtr, ytr, Xte)
    pred = (p > 0.5).astype(int)
    acc = (pred == yte).mean()
    # signed-return: лонг если pred=1 иначе шорт, на fwd
    sgn = np.where(pred == 1, 1, -1)
    sret = float(np.mean(sgn * fwd[te]))
    return acc, sret, yte, pred, fwd[te], p


def main():
    out = []; A = out.append
    for tf in ["1d", "4h"]:
        A(f"\n{'='*68}\n ОСЬ 1 — CROSS-ASSET LEAD-LAG, ТФ={tf}\n{'='*68}")
        X = build(tf)
        A(f"выборка: {len(X)} баров, {X.index[0].date()} -> {X.index[-1].date()}; "
          f"OOS-тест >= 2024 ({(X.index>=pd.Timestamp('2024-01-01',tz='UTC')).sum()} баров)")
        feats_avail = [f for f in CROSS if f in X.columns and X[f].notna().all()]

        # базлайны
        yte_all = (X["fwd_btc"] > 0).astype(int).values[X.index >= pd.Timestamp("2024-01-01", tz="UTC")]
        maj = max(yte_all.mean(), 1 - yte_all.mean())
        # persistence: pred[t]=y[t-1] (знак сегодня = знак вчера) на OOS
        ysign = (X["fwd_btc"] > 0).astype(int).values
        te = X.index >= pd.Timestamp("2024-01-01", tz="UTC")
        pers = (ysign[te][1:] == ysign[te][:-1]).mean()  # P(знак повторяется)
        A(f"\nБАЗЛАЙНЫ OOS:  majority={maj:.3f}   persistence(знак=вчера)={pers:.3f}")

        acc_own, sr_own, *_ = evalset(X, OWN)
        acc_full, sr_full, yte, pred, fwdte, p = evalset(X, OWN + feats_avail)
        acc_cross, sr_cross, *_ = evalset(X, feats_avail)
        A(f"own-AR(цена BTC):   acc={acc_own:.3f}  signed-ret={sr_own:+.5f}")
        A(f"cross-only:         acc={acc_cross:.3f}  signed-ret={sr_cross:+.5f}")
        A(f"FULL(own+cross):    acc={acc_full:.3f}  signed-ret={sr_full:+.5f}")
        A(f"-> ПРИБАВКА cross над own-AR: acc {acc_full-acc_own:+.3f}, ret {sr_full-sr_own:+.5f}")

        # permutation-null: перемешать OOS-метки, распределение accuracy случайной модели
        nulls = [np.mean(pred == RNG.permutation(yte)) for _ in range(500)]
        null_p = float((np.array(nulls) >= acc_full).mean())
        A(f"permutation-null: acc_full={acc_full:.3f} vs null {np.mean(nulls):.3f}±{np.std(nulls):.3f}  p={null_p:.3f}")

        # год-стабильность OOS
        idx_te = X.index[te]
        yrs = pd.Series(pred == yte, index=idx_te).groupby(idx_te.year).mean()
        A("год-стабильность (acc OOS): " + "  ".join(f"{y}:{v:.3f}" for y, v in yrs.items()))

        # cross-target robustness: та же FULL-модель на ETH и SOL
        for tgt in ["fwd_eth", "fwd_sol"]:
            a, s, *_ = evalset(X, OWN + feats_avail, target=tgt)
            A(f"  cross-target {tgt}: acc={a:.3f} ret={s:+.5f}")

        # прямой тест гипотезы USDT.D: big risk-off квартиль -> P(BTC вниз завтра)
        q = X["r_usdtd"]
        hi = X[q >= q.quantile(0.8)]; lo = X[q <= q.quantile(0.2)]
        A(f"\nГИПОТЕЗА USDT.D: рост доминации (top20%) -> BTC next: "
          f"P(down)={(hi.fwd_btc<0).mean():.3f}  meanFwd={hi.fwd_btc.mean():+.5f} | "
          f"падение домин.(bot20%): P(down)={(lo.fwd_btc<0).mean():.3f} meanFwd={lo.fwd_btc.mean():+.5f}")

    o = "\n".join(out)
    (Path(__file__).resolve().parent / "axis1_report.txt").write_text(o, encoding="utf-8")
    print(o)


if __name__ == "__main__":
    main()
