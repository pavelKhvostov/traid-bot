"""ОСЬ 1b — ИНТРАДЕЙ lead-lag только BTC/ETH/SOL (идеальное выравнивание, полная история).
Вопрос: опережают ли ETH/SOL знак BTC[t+1] на 1h/4h сверх собств. AR BTC? Стены те же.
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


def lc(name, tf):
    d = pd.read_csv(ROOT / "data" / f"{name}_{tf}.csv")
    tc = [c for c in d.columns if "time" in c.lower() or "date" in c.lower()][0]
    d[tc] = pd.to_datetime(d[tc], utc=True)
    return d.set_index(tc).sort_index()["close"].astype(float)


def fit(Xtr, ytr, Xte):
    mu = Xtr.mean(0); sd = Xtr.std(0) + 1e-9
    Z = np.c_[np.ones(len(Xtr)), (Xtr - mu) / sd]; Zt = np.c_[np.ones(len(Xte)), (Xte - mu) / sd]
    w = np.zeros(Z.shape[1])
    for _ in range(600):
        p = 1 / (1 + np.exp(-Z @ w))
        w -= 0.3 * (Z.T @ (p - ytr) / len(ytr) + 1e-3 * np.r_[0, w[1:]])
    return 1 / (1 + np.exp(-Zt @ w))


def run(tf, out):
    df = pd.DataFrame({"btc": lc("BTCUSDT", tf), "eth": lc("ETHUSDT", tf), "sol": lc("SOLUSDT", tf)}).dropna()
    r = df.pct_change(fill_method=None)
    X = pd.DataFrame(index=df.index)
    X["r_btc"] = r.btc; X["r_btc1"] = r.btc.shift(1); X["r_btc2"] = r.btc.shift(2)
    X["r_eth"] = r.eth; X["r_eth1"] = r.eth.shift(1); X["r_sol"] = r.sol; X["r_sol1"] = r.sol.shift(1)
    X["rel_eth"] = r.eth - r.btc; X["rel_sol"] = r.sol - r.btc
    X["fwd"] = r.btc.shift(-1)
    X = X.dropna()
    y = (X.fwd > 0).astype(int).values; fwd = X.fwd.values
    spl = X.index < pd.Timestamp("2024-01-01", tz="UTC"); te = ~spl
    own = ["r_btc", "r_btc1", "r_btc2"]
    cross = ["r_eth", "r_eth1", "r_sol", "r_sol1", "rel_eth", "rel_sol"]

    def ev(feats):
        p = fit(X[feats].values[spl], y[spl], X[feats].values[te])
        pred = (p > 0.5).astype(int)
        return (pred == y[te]).mean(), float(np.mean(np.where(pred == 1, 1, -1) * fwd[te])), pred

    a_own, s_own, _ = ev(own)
    a_full, s_full, pred = ev(own + cross)
    a_cr, s_cr, _ = ev(cross)
    yte = y[te]; maj = max(yte.mean(), 1 - yte.mean())
    nulls = [np.mean(pred == RNG.permutation(yte)) for _ in range(400)]
    null_p = float((np.array(nulls) >= a_full).mean())
    idx = X.index[te]
    yrs = pd.Series(pred == yte, index=idx).groupby(idx.year).mean()
    out.append(f"\n--- ТФ={tf} | {len(X)} баров, OOS>=2024 {te.sum()} ---")
    out.append(f"majority={maj:.3f}  own-AR={a_own:.3f}  cross-only={a_cr:.3f}  FULL={a_full:.3f}  "
               f"(cross над own {a_full-a_own:+.3f})")
    out.append(f"signed-ret: own={s_own:+.6f} FULL={s_full:+.6f}   null: {np.mean(nulls):.3f}±{np.std(nulls):.3f} p={null_p:.3f}")
    out.append("год OOS: " + "  ".join(f"{y_}:{v:.3f}" for y_, v in yrs.items()))


def main():
    out = ["="*60, " ОСЬ 1b — ИНТРАДЕЙ lead-lag BTC<-ETH/SOL", "="*60]
    for tf in ["1h", "4h"]:
        run(tf, out)
    o = "\n".join(out)
    (Path(__file__).resolve().parent / "axis1b_report.txt").write_text(o, encoding="utf-8")
    print(o)


if __name__ == "__main__":
    main()
