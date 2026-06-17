"""etap_218 — #3 Нормировка внутридня на ПРЕДСКАЗАННЫЙ дневной диапазон (CatBoost range).

Связываем два робастных куска: range-модель (R²0.50, as-of вчера) нормирует внутридневной
ход. Признаки «сколько % ожидаемого range уже выбрано и в какую сторону» (Market Profile).
Гипотеза: помогает не столько AUC, сколько КАЛИБРОВКЕ по волатильным режимам.

Тест: raw [ret_k,pos_rng] vs +norm [+ret_k/exp, range_used, up_used, dn_used].
  - AUC-lift по часам
  - калибровка raw vs norm в РАЗНЫХ vol-режимах (тертили exp_range)

Запуск: venv/Scripts/python.exe research/daily_engine/etap_218_vol_normalized.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np, pandas as pd

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import etap_201_daily_analyzer as A
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

DATA = HERE.parent.parent / "data" / "BTCUSDT_1h_orderflow.csv"
CUTOFF = pd.Timestamp("2023-01-01", tz="UTC")
RAW = ["ret_k", "pos_rng"]
NORM = RAW + ["ret_k_n", "range_used", "up_used", "dn_used"]


def exp_range_pct_per_day():
    d = A.daily_from_flow("BTCUSDT")
    reg, clf, feat_cols, cat_idx, calib = A.train_models(CUTOFF)
    fb = A.build_features(d).shift(1)
    fb["gap"] = (d["open"] - d["close"].shift(1)) / A.atr(d, 14)
    fb["asset"] = "BTCUSDT"
    X = fb.reindex(columns=feat_cols).dropna()
    pr = np.exp(reg.predict(X))
    pb = clf.predict_proba(X)[:, 1]
    ratio = np.where(pb >= 0.5, calib["r_big"], calib["r_flat"])
    exp_pct = pd.Series(pr * ratio, index=X.index)   # ожидаемый |H-L|/prev_close (доля)
    return exp_pct


def main():
    df = pd.read_csv(DATA, index_col=0, parse_dates=True)
    if df.index.tz is None: df.index = df.index.tz_localize("UTC")
    exp_pct = exp_range_pct_per_day()

    dd = df.index.normalize(); rows = []
    for day, g in df.groupby(dd):
        if len(g) < 4 or day not in exp_pct.index: continue
        er = float(exp_pct.loc[day])
        if not np.isfinite(er) or er <= 0: continue
        o = g["open"].iloc[0]; c = g["close"].values
        hi = np.maximum.accumulate(g["high"].values); lo = np.minimum.accumulate(g["low"].values)
        green = int(c[-1] > o)
        for k in range(len(g)):
            rng = hi[k]-lo[k]
            ret_k = c[k]/o-1
            rows.append(dict(day=day, k=k, green=green, exp=er, ret_k=ret_k,
                pos_rng=(c[k]-lo[k])/rng if rng > 0 else 0.5,
                ret_k_n=ret_k/er, range_used=(rng/o)/er,
                up_used=(hi[k]/o-1)/er, dn_used=(o/lo[k]-1)/er))
    R = pd.DataFrame(rows).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    tr, te = R[R.day < CUTOFF], R[R.day >= CUTOFF]
    print("="*64); print(f"#3 VOL-НОРМИРОВКА — test 2023+ ({te.day.nunique()} дней)"); print("="*64)

    def fit_pred(feats):
        p = np.full(len(te), 0.5)
        for k in range(24):
            s = tr[tr.k == k]; idx = te.k.values == k
            if len(s) >= 50 and s.green.nunique() > 1 and idx.any():
                m = LogisticRegression(max_iter=400).fit(s[feats], s.green)
                p[idx] = m.predict_proba(te.loc[idx, feats])[:, 1]
        return p
    p_raw, p_norm = fit_pred(RAW), fit_pred(NORM)
    te = te.assign(p_raw=p_raw, p_norm=p_norm)

    print("\n■ AUC-lift по часам (raw vs +norm)")
    print(f"  {'k':>3} {'raw':>7} {'+norm':>7} {'lift':>7}")
    for k in [2, 3, 4, 6, 8, 10, 12]:
        s = te[te.k == k]
        ar = roc_auc_score(s.green, s.p_raw); an = roc_auc_score(s.green, s.p_norm)
        print(f"  {k:>3} {ar:>7.3f} {an:>7.3f} {an-ar:>+7.3f}")

    print("\n■ КАЛИБРОВКА по VOL-РЕЖИМАМ (тертили ожидаемого range) — ECE (ниже=лучше)")
    te = te.assign(reg=pd.qcut(te.exp, 3, labels=["низкий vol", "средний", "высокий vol"]))
    def ece(g, col):
        b = pd.cut(g[col], np.linspace(0, 1, 11))
        e = 0.0
        for _, gg in g.groupby(b, observed=True):
            if len(gg): e += len(gg)/len(g)*abs(gg[col].mean()-gg.green.mean())
        return e
    print(f"  {'режим':<13} {'ECE raw':>8} {'ECE norm':>9} {'улучш.':>8}")
    for rg, g in te.groupby("reg", observed=True):
        er, en = ece(g, "p_raw"), ece(g, "p_norm")
        print(f"  {str(rg):<13} {er:>8.3f} {en:>9.3f} {er-en:>+8.3f}")
    print(f"  ВСЕГО         {ece(te,'p_raw'):>8.3f} {ece(te,'p_norm'):>9.3f} {ece(te,'p_raw')-ece(te,'p_norm'):>+8.3f}")

    print("\n■ Bonus: '% ожидаемого range, выбранного вверх к часу 6' → P(green)")
    t6 = te[te.k == 6]
    for b, g in t6.assign(bk=pd.cut(t6.up_used-t6.dn_used, [-9, -0.5, -0.1, 0.1, 0.5, 9],
            labels=["<-50%", "-50..-10", "±10%", "+10..50", ">+50%"])).groupby("bk", observed=True):
        print(f"   net range-used {str(b):<9} n={len(g):>4} P(green)={g.green.mean():.2f}")

    R.to_csv(HERE / "output" / "etap_218_volnorm.csv", index=False)
    print("\nSaved: output/etap_218_volnorm.csv")


if __name__ == "__main__":
    main()
