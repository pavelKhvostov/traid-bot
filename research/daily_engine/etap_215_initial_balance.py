"""etap_215 — #2 Initial Balance / range-extension / open-type (Dalton Market Profile).

Не «цена уже сходила» (это ret_k), а СТРУКТУРА: сформировался начальный баланс (IB,
первые часы), затем range-extension за IB = initiative participants = трендовый день
= ход доезжает (а не выкупается). Open-drive (сильный первый бар) → тоже trend-tell.

Тест: добавляют ли IB-фичи AUC над price-only [ret_k,pos_rng] на часах k≥IB?
+ Далтоновская условная таблица: пробил IB вверх и держит к часу k → P(green)?

Запуск: venv/Scripts/python.exe research/daily_engine/etap_215_initial_balance.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np, pandas as pd

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

DATA = Path(__file__).resolve().parent.parent.parent / "data" / "BTCUSDT_1h_orderflow.csv"
CUTOFF = pd.Timestamp("2023-01-01", tz="UTC")
IB = 3                              # начальный баланс = первые 3 часа
PRICE = ["ret_k", "pos_rng"]
IBF = PRICE + ["ext_up", "ext_dn", "above_ib", "below_ib", "dist_ib", "open_drive"]


def build(df):
    dd = df.index.normalize(); rows = []
    for day, g in df.groupby(dd):
        if len(g) < IB + 2: continue
        o = g["open"].iloc[0]; c = g["close"].values
        H = g["high"].values; L = g["low"].values
        hi = np.maximum.accumulate(H); lo = np.minimum.accumulate(L)
        ib_h = H[:IB].max(); ib_l = L[:IB].min(); ib_r = max(ib_h - ib_l, 1e-9)
        ib_mid = (ib_h + ib_l)/2
        open_drive = (c[0] - o)/ib_r           # сила первого бара относительно IB
        green = int(c[-1] > o)
        for k in range(IB, len(g)):
            rng = hi[k]-lo[k]
            rows.append(dict(day=day, k=k, green=green,
                             ret_k=c[k]/o-1, pos_rng=(c[k]-lo[k])/rng if rng > 0 else 0.5,
                             ext_up=max(0, hi[k]-ib_h)/ib_r, ext_dn=max(0, ib_l-lo[k])/ib_r,
                             above_ib=int(c[k] > ib_h), below_ib=int(c[k] < ib_l),
                             dist_ib=(c[k]-ib_mid)/ib_r, open_drive=open_drive))
    return pd.DataFrame(rows)


def per_hour(tr, te, feats, ks):
    out = {}
    for k in ks:
        s = tr[tr.k == k]; t = te[te.k == k]
        if len(s) < 50 or len(t) < 20 or s.green.nunique() < 2: continue
        m = LogisticRegression(max_iter=300).fit(s[feats], s.green)
        out[k] = roc_auc_score(t.green, m.predict_proba(t[feats])[:, 1])
    return out


def main():
    df = pd.read_csv(DATA, index_col=0, parse_dates=True)
    if df.index.tz is None: df.index = df.index.tz_localize("UTC")
    R = build(df).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    tr, te = R[R.day < CUTOFF], R[R.day >= CUTOFF]
    ks = list(range(IB, 10))
    print("="*72); print(f"#2 INITIAL BALANCE (IB={IB}ч) — test 2023+ ({te.day.nunique()} дней)"); print("="*72)

    ap = per_hour(tr, te, PRICE, ks); ai = per_hour(tr, te, IBF, ks)
    print(f"\n■ AUC по часам: price-only vs +IB-структура")
    print(f"  {'час':>4} {'naive(ret)':>11} {'price-only':>11} {'+IB':>8} {'lift':>7}")
    for k in ks:
        s = te[te.k == k]
        if len(s) < 20: continue
        an = roc_auc_score(s.green, s.ret_k)
        print(f"  {k:>4} {an:>11.3f} {ap.get(k, float('nan')):>11.3f} {ai.get(k, float('nan')):>8.3f} "
              f"{ai.get(k, float('nan'))-ap.get(k, float('nan')):>+7.3f}")

    print("\n■ ДАЛТОН: условная P(green) по состоянию относительно IB (test, час k=4)")
    t4 = te[te.k == 4]
    for lab, m in [("пробил IB ВВЕРХ и держит (close>IB_high)", t4.above_ib == 1),
                   ("внутри IB (close между)", (t4.above_ib == 0) & (t4.below_ib == 0)),
                   ("пробил IB ВНИЗ и держит", t4.below_ib == 1)]:
        s = t4[m]
        if len(s): print(f"   {lab:<42} n={len(s):>4} P(green)={s.green.mean():.2f}")

    print("\n■ OPEN-TYPE: сильный open-drive (первый час) → трендовый исход?")
    od = te[te.k == IB].copy()
    od["bucket"] = pd.cut(od.open_drive, [-9, -0.5, -0.1, 0.1, 0.5, 9],
                          labels=["drive↓↓", "↓", "auction", "↑", "drive↑↑"])
    for b, g in od.groupby("bucket", observed=True):
        # «трендовый» = |ход дня| большой; направленность = green-rate
        print(f"   open {str(b):<9} n={len(g):>4} P(green)={g.green.mean():.2f}")

    # чистый IB без ret_k — несёт ли структура инфу сверх цены?
    pure = ["ext_up", "ext_dn", "above_ib", "below_ib", "dist_ib", "open_drive"]
    apu = per_hour(tr, te, pure, ks)
    print(f"\n■ ЧИСТАЯ IB-структура (без ret_k): AUC по часам:")
    print("  " + " ".join(f"k{k}:{apu.get(k, float('nan')):.2f}" for k in ks))

    R.to_csv(Path(__file__).resolve().parent / "output" / "etap_215_ib.csv", index=False)
    print("\nSaved: output/etap_215_ib.csv")


if __name__ == "__main__":
    main()
