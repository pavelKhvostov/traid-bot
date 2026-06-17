"""etap_245 — Волна 1 / модули regime-3 + micro1m-2/4/6: предиктор рваности дня.

Текущий baseline (etap_234, ml-6): cross_early = n пересечений сырой P(green) 0.5
в первой половине дня → AUC 0.631 на лейбле rough (day-type call флипает после 11ч).

Кандидаты-предикторы из УТРЕННЕЙ 1m-микроструктуры (часы 0..11 UTC, live-доступны
в полдень, лейбл — про вторую половину → без подглядывания):
  - VR (Lo-MacKinlay variance ratio) lag2/5: <1 mean-reversion (choppy), >1 momentum
  - Efficiency ratio (Kaufman): |нетто-ход| / Σ|шаги| — низкий = рваный путь
  - lag-1 автокорреляция 1m-ретёрнов: отриц = reversal-режим
  - run-length (Wald-Wolfowitz, число серий/n): много коротких серий = рвань
Bake-off: AUC каждого + объединяющая логистика vs baseline cross_early.

KILL: ни один новый и их логистика-комбо не бьют 0.631 на OOS (+0.02 порог).

Запуск: venv/Scripts/python.exe research/daily_engine/etap_245_choppiness_bakeoff.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np, pandas as pd

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import etap_217_daytype_layer as L
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

H1 = ROOT / "data" / "BTCUSDT_1h_orderflow.csv"
M1 = ROOT / "data" / "BTCUSDT_1m.csv"
V1 = L.FEATS


def variance_ratio(r, q):
    """Lo-MacKinlay VR(q) = Var(q-сумм ретёрнов)/(q·Var(1)). ~1 случайно, <1 reversal."""
    r = r[~np.isnan(r)]
    if len(r) < q * 3:
        return np.nan
    v1 = np.var(r, ddof=1)
    if v1 <= 0:
        return np.nan
    rq = np.convolve(r, np.ones(q), "valid")
    return float(np.var(rq, ddof=1) / (q * v1))


def morning_micro(day_1m: pd.DataFrame) -> dict:
    """1m-фичи по утренним барам (часы 0..11)."""
    r = np.log(day_1m["close"]).diff().dropna().values
    if len(r) < 200:
        return {}
    net = abs(np.sum(r)); path = np.sum(np.abs(r))
    eff = net / path if path > 0 else 0.0
    sign = np.sign(r); sign = sign[sign != 0]
    runs = 1 + int(np.sum(sign[1:] != sign[:-1])) if len(sign) > 1 else 1
    ac1 = float(pd.Series(r).autocorr(lag=1)) if len(r) > 5 else np.nan
    return dict(vr2=variance_ratio(r, 2), vr5=variance_ratio(r, 5),
                eff_ratio=eff, ac1=ac1, runs_norm=runs / len(sign) if len(sign) else np.nan,
                rv_morn=float(np.sum(r**2)))


def main():
    h1 = pd.read_csv(H1, index_col=0, parse_dates=True)
    if h1.index.tz is None: h1.index = h1.index.tz_localize("UTC")
    m1 = pd.read_csv(M1, usecols=["open_time", "close"], parse_dates=["open_time"])
    if m1["open_time"].dt.tz is None: m1["open_time"] = m1["open_time"].dt.tz_localize("UTC")
    m1 = m1.set_index("open_time").sort_index()

    R = L.build(h1).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    tr = R[R.day < L.CUTOFF]
    M = {k: LogisticRegression(max_iter=500).fit(tr[tr.k == k][V1], tr[tr.k == k].green)
         for k in range(24) if len(tr[tr.k == k]) >= 50 and tr[tr.k == k].green.nunique() > 1}
    te = R[R.day >= L.CUTOFF]

    rows = []
    for day, g in te.groupby("day"):
        g = g.sort_values("k")
        if len(g) < 20:
            continue
        p = np.array([M[k].predict_proba(g[g.k == k][V1])[:, 1][0] if k in M else 0.5 for k in g.k.values])
        sm = np.zeros(len(p)); sm[0] = p[0]
        for i in range(1, len(p)): sm[i] = L.ALPHA * p[i] + (1 - L.ALPHA) * sm[i - 1]
        call, flips_late, cross_early, dsum_early = "HOLD", 0, 0, 0.0
        for i in range(len(p)):
            new = "LONG" if sm[i] > L.HI else ("SHORT" if sm[i] < L.LO else call)
            if new != call and call != "HOLD" and i > 11: flips_late += 1
            call = new
            if i <= 11:
                dsum_early += abs(p[i] - sm[i])
                if i > 0 and (p[i] - 0.5) * (p[i - 1] - 0.5) < 0: cross_early += 1
        # утренние 1m-фичи
        d0 = pd.Timestamp(day)
        morn = m1[(m1.index >= d0) & (m1.index < d0 + pd.Timedelta(hours=12))]
        mf = morning_micro(morn)
        if not mf:
            continue
        rows.append(dict(day=day, rough=int(flips_late >= 1), cross_early=cross_early,
                         dsum_early=dsum_early, **mf))
    d = pd.DataFrame(rows).replace([np.inf, -np.inf], np.nan).dropna()
    print(f"OOS дней: {len(d)}, доля rough (поздний флип): {d.rough.mean():.2f}")

    print("\n■ Одиночный AUC предикторов рваности (rough):")
    cands = ["cross_early", "dsum_early", "vr2", "vr5", "eff_ratio", "ac1", "runs_norm", "rv_morn"]
    aucs = {}
    for c in cands:
        s = d[c].values.astype(float)
        # знак: для VR/eff/ac1/runs выбираем ориентацию по корреляции
        a = roc_auc_score(d.rough, s)
        a = max(a, 1 - a)
        aucs[c] = a
        base = "  ← baseline" if c == "cross_early" else ""
        print(f"   {c:<12} AUC={a:.3f}{base}")

    # комбо-логистика новых микро-фич (walk-free: train<2024 / test 2024+ внутри OOS)
    new = ["vr5", "eff_ratio", "ac1", "runs_norm"]
    d2 = d.sort_values("day")
    cut = pd.Timestamp("2024-06-01", tz="UTC")
    trn, ten = d2[d2.day < cut], d2[d2.day >= cut]
    if len(ten) > 30 and ten.rough.nunique() > 1:
        lr_new = LogisticRegression(max_iter=500).fit(trn[new], trn.rough)
        lr_base = LogisticRegression(max_iter=500).fit(trn[["cross_early"]], trn.rough)
        lr_all = LogisticRegression(max_iter=500).fit(trn[["cross_early"] + new], trn.rough)
        a_new = roc_auc_score(ten.rough, lr_new.predict_proba(ten[new])[:, 1])
        a_base = roc_auc_score(ten.rough, lr_base.predict_proba(ten[["cross_early"]])[:, 1])
        a_all = roc_auc_score(ten.rough, lr_all.predict_proba(ten[["cross_early"] + new])[:, 1])
        print(f"\n■ Комбо (train<2024-06 / test {len(ten)} дней):")
        print(f"   baseline cross_early:        AUC={a_base:.3f}")
        print(f"   ТОЛЬКО утр.микроструктура:   AUC={a_new:.3f}")
        print(f"   cross_early + микроструктура:AUC={a_all:.3f}  (lift {a_all-a_base:+.3f})")
        verdict = "KEEP" if a_all - a_base >= 0.02 or a_new - a_base >= 0.02 else "KILL"
        print(f"\nВЕРДИКТ: {verdict} (порог +0.02 к baseline 0.631)")

    d.to_csv(HERE / "output" / "etap_245_choppiness.csv", index=False)
    print(f"Saved: {HERE/'output'/'etap_245_choppiness.csv'}")


if __name__ == "__main__":
    main()
