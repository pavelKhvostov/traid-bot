"""etap_214 — #1 ORDER FLOW в nowcaster. Бьёт ли signed flow стену РАННИХ часов?

Harris: сделки раскрывают информированный поток до цены. Гипотеза: в часы 0–4,
где price-only = коин, накопленный CVD/дельта различают «настоящий» ход от тонкого.

Сравниваем per-hour (walk-forward fit<2023, test 2023+):
  naive(ret_k) | price-only[ret_k,pos_rng] | +flow[+cvd,delta_now,cvd_slope, divergence]
Цель: green (close>open). Смотрим LIFT(+flow − price-only) на k≤6.

Запуск: venv/Scripts/python.exe research/daily_engine/etap_214_orderflow_nowcaster.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np, pandas as pd

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, brier_score_loss

DATA = Path(__file__).resolve().parent.parent.parent / "data" / "BTCUSDT_1h_orderflow.csv"
CUTOFF = pd.Timestamp("2023-01-01", tz="UTC")
PRICE = ["ret_k", "pos_rng"]
FLOW = ["ret_k", "pos_rng", "cvd_norm", "delta_now", "cvd_slope", "diverg"]


def build(df):
    d = df.index.normalize()
    rows = []
    for day, g in df.groupby(d):
        if len(g) < 4: continue
        o = g["open"].iloc[0]; c = g["close"].values
        hi = np.maximum.accumulate(g["high"].values); lo = np.minimum.accumulate(g["low"].values)
        dlt = g["delta"].values; vol = g["volume"].values
        cum_d = np.cumsum(dlt); cum_v = np.cumsum(vol)
        green = int(c[-1] > o)
        for k in range(len(g)):
            rng = hi[k] - lo[k]
            ret_k = c[k]/o - 1
            cvd = cum_d[k]/cum_v[k] if cum_v[k] > 0 else 0.0
            if k >= 3:
                dv = cum_v[k]-cum_v[k-3]; cs = (cum_d[k]-cum_d[k-3])/dv if dv > 0 else cvd
            else: cs = cvd
            # дивергенция: ход вверх но поток вниз (или наоборот) — нормированный
            diverg = np.sign(ret_k) * cvd          # >0 = поток подтверждает ход, <0 = расходится
            rows.append(dict(day=day, k=k, green=green, ret_k=ret_k,
                             pos_rng=(c[k]-lo[k])/rng if rng > 0 else 0.5,
                             cvd_norm=cvd, delta_now=g["delta_norm"].values[k], cvd_slope=cs, diverg=diverg))
    return pd.DataFrame(rows)


def per_hour_auc(tr, te, feats, kmax=8):
    out = {}
    for k in range(kmax):
        s = tr[tr.k == k]; t = te[te.k == k]
        if len(s) < 50 or len(t) < 20 or s.green.nunique() < 2: continue
        m = LogisticRegression(max_iter=300, C=1.0).fit(s[feats], s.green)
        out[k] = roc_auc_score(t.green, m.predict_proba(t[feats])[:, 1])
    return out


def main():
    df = pd.read_csv(DATA, index_col=0, parse_dates=True)
    if df.index.tz is None: df.index = df.index.tz_localize("UTC")
    R = build(df)
    R[FLOW] = R[FLOW].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    tr, te = R[R.day < CUTOFF], R[R.day >= CUTOFF]
    print("="*72); print(f"#1 ORDER FLOW в nowcaster — test 2023+ ({te.day.nunique()} дней)"); print("="*72)

    a_price = per_hour_auc(tr, te, PRICE)
    a_flow = per_hour_auc(tr, te, FLOW)
    print(f"\n■ AUC по часам — где flow бьёт цену (k≤7 = ранние часы, тут была стена)")
    print(f"  {'час':>4} {'naive(ret)':>11} {'price-only':>11} {'+flow':>8} {'lift':>7}")
    for k in range(8):
        s = te[te.k == k]
        if len(s) < 20: continue
        an = roc_auc_score(s.green, s.ret_k)
        ap = a_price.get(k, float('nan')); af = a_flow.get(k, float('nan'))
        print(f"  {k:>4} {an:>11.3f} {ap:>11.3f} {af:>8.3f} {af-ap:>+7.3f}")

    # калибровка + shuffle для flow-модели (пул по часам через per-hour fit, оценим overall на k<=6)
    early_tr = tr[tr.k <= 6]; early_te = te[te.k <= 6]
    m = LogisticRegression(max_iter=300).fit(early_tr[FLOW], early_tr.green)
    p = m.predict_proba(early_te[FLOW])[:, 1]
    print(f"\n■ Ранние часы k≤6, flow-модель: AUC {roc_auc_score(early_te.green, p):.3f} | "
          f"Brier {brier_score_loss(early_te.green, p):.3f} | naive ret AUC {roc_auc_score(early_te.green, early_te.ret_k):.3f}")
    rng = np.random.default_rng(0)
    ms = LogisticRegression(max_iter=300).fit(early_tr[FLOW], rng.permutation(early_tr.green.values))
    print(f"  shuffle AUC {roc_auc_score(early_te.green, ms.predict_proba(early_te[FLOW])[:,1]):.3f} (≈0.50)")

    # отдельный вклад дивергенции: только flow без ret_k/pos (чистый поток предсказывает цвет?)
    pure = ["cvd_norm", "delta_now", "cvd_slope"]
    ap_pure = per_hour_auc(tr, te, pure)
    print(f"\n■ ЧИСТЫЙ ПОТОК (без цены) предсказывает цвет дня? AUC по часам:")
    print("  " + " ".join(f"k{k}:{ap_pure.get(k, float('nan')):.2f}" for k in range(8)))
    print("   (k=0: поток ПЕРВОГО часа vs цвет всего дня — это ближе к 'прогнозу вперёд')")

    R.to_csv(Path(__file__).resolve().parent / "output" / "etap_214_orderflow.csv", index=False)
    print("\nSaved: output/etap_214_orderflow.csv")


if __name__ == "__main__":
    main()
