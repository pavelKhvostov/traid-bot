"""etap_217 — РАБОЧИЙ СЛОЙ «тип дня» (Dalton Initial Balance) для модуля анализа.

Доводим находку #2 (etap_215): IB-break-and-hold = сильный структурный сигнал
(74%/26% green), open-drive монотонен. Оформляем как ЖИВОЙ слой:

  - КЛАССИФИКАЦИЯ состояния дня каждый час: FORMING → TREND_UP / ROTATION / TREND_DOWN
  - P(green) калиброванный по [цена + IB-структура] (per-hour логистика, walk-forward)
  - РЕЖИМ ТРЕЙДА: TREND → FOLLOW (continuation), ROTATION → FADE (mean-reversion к IB-mid)
  - СТАБИЛЬНОСТЬ: сглаживание + мёртвая зона (как nowcaster), не дёргается

Валидация: калибровка, условная P(green) по типу, lift над price-only, стабильность.
Live-API: daytype_nowcast(bars_1h) → поток (k, state, P_green, mode, call).

Запуск: venv/Scripts/python.exe research/daily_engine/etap_217_daytype_layer.py
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
OUT = Path(__file__).resolve().parent / "output"
CUTOFF = pd.Timestamp("2023-01-01", tz="UTC")
IB = 3
HI, LO, ALPHA = 0.57, 0.43, 0.4
EXT = 0.10                    # порог range-extension за IB (доля IB-range) для TREND
FEATS = ["ret_k", "pos_rng", "ext_up", "ext_dn", "above_ib", "below_ib", "dist_ib", "open_drive", "ib_formed"]


def classify(row):
    if not row["ib_formed"]:
        return "FORMING", "WAIT"
    if row["above_ib"] and row["ext_up"] >= EXT:
        return "TREND_UP", "FOLLOW"
    if row["below_ib"] and row["ext_dn"] >= EXT:
        return "TREND_DOWN", "FOLLOW"
    return "ROTATION", "FADE"


def build(df):
    dd = df.index.normalize(); rows = []
    for day, g in df.groupby(dd):
        if len(g) < IB + 2: continue
        o = g["open"].iloc[0]; c = g["close"].values; H = g["high"].values; L = g["low"].values
        hi = np.maximum.accumulate(H); lo = np.minimum.accumulate(L)
        ib_h, ib_l = H[:IB].max(), L[:IB].min(); ib_r = max(ib_h-ib_l, 1e-9); ib_mid = (ib_h+ib_l)/2
        od = (c[0]-o)/ib_r; green = int(c[-1] > o)
        for k in range(len(g)):
            formed = k >= IB
            rng = hi[k]-lo[k]
            rows.append(dict(day=day, k=k, green=green, ret_k=c[k]/o-1,
                pos_rng=(c[k]-lo[k])/rng if rng > 0 else 0.5,
                ext_up=max(0, hi[k]-ib_h)/ib_r if formed else 0.0,
                ext_dn=max(0, ib_l-lo[k])/ib_r if formed else 0.0,
                above_ib=int(c[k] > ib_h) if formed else 0, below_ib=int(c[k] < ib_l) if formed else 0,
                dist_ib=(c[k]-ib_mid)/ib_r if formed else 0.0, open_drive=od, ib_formed=int(formed)))
    return pd.DataFrame(rows)


def fit_per_hour(tr, kmax=24):
    M = {}
    for k in range(kmax):
        s = tr[tr.k == k]
        if len(s) < 50 or s.green.nunique() < 2: continue
        M[k] = LogisticRegression(max_iter=400).fit(s[FEATS], s.green)
    return M


def predict(M, df):
    p = np.full(len(df), 0.5)
    for k, m in M.items():
        idx = df.k.values == k
        if idx.any(): p[idx] = m.predict_proba(df.loc[idx, FEATS])[:, 1]
    return p


def stream(rows_df):
    """rows_df: строки одного дня (отсортированы по k) c колонкой p. → поток решений."""
    sm = None; call = "HOLD"; flips = 0; out = []
    for _, r in rows_df.iterrows():
        sm = r["p"] if sm is None else ALPHA*r["p"] + (1-ALPHA)*sm
        new = "LONG" if sm > HI else ("SHORT" if sm < LO else call)
        if new != call and call != "HOLD": flips += 1
        call = new
        state, mode = classify(r)
        out.append((int(r["k"]), state, round(float(r["p"]), 2), round(float(sm), 2), mode, call))
    return out, flips


def main():
    df = pd.read_csv(DATA, index_col=0, parse_dates=True)
    if df.index.tz is None: df.index = df.index.tz_localize("UTC")
    R = build(df).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    tr, te = R[R.day < CUTOFF], R[R.day >= CUTOFF]
    M = fit_per_hour(tr)
    te = te.assign(p=predict(M, te))
    pp = predict(M, R[["k"]+FEATS]); R = R.assign(p=pp)

    print("="*70); print(f"СЛОЙ «ТИП ДНЯ» — валидация OOS 2023+ ({te.day.nunique()} дней)"); print("="*70)
    print(f"  AUC {roc_auc_score(te.green, te.p):.3f} | Brier {brier_score_loss(te.green, te.p):.3f}")

    print("\n■ КАЛИБРОВКА P(green)")
    for b, g in te.assign(bk=pd.cut(te.p, [0, .3, .43, .57, .7, 1])).groupby("bk", observed=True):
        print(f"   p∈{str(b):<11} n={len(g):>5} mean_p {g.p.mean():.2f} факт {g.green.mean():.2f}")

    print("\n■ УСЛОВНАЯ P(green) ПО ТИПУ ДНЯ (час k=5, OOS)")
    t5 = te[te.k == 5].copy()
    t5[["state", "mode"]] = t5.apply(lambda r: pd.Series(classify(r)), axis=1)
    for st, g in t5.groupby("state"):
        print(f"   {st:<10} n={len(g):>4} P(green)={g.green.mean():.2f} | средний |ход дня| {g.ret_k.abs().mean()*100:.2f}%")

    # lift над price-only
    price_M = {}
    for k in range(24):
        s = tr[tr.k == k]
        if len(s) >= 50 and s.green.nunique() > 1:
            price_M[k] = LogisticRegression(max_iter=400).fit(s[["ret_k", "pos_rng"]], s.green)
    pe = np.full(len(te), 0.5)
    for k, m in price_M.items():
        idx = te.k.values == k
        if idx.any(): pe[idx] = m.predict_proba(te.loc[idx, ["ret_k", "pos_rng"]])[:, 1]
    print("\n■ LIFT слоя над price-only (AUC по часам)")
    print(f"  {'k':>3} {'price':>7} {'+IB-слой':>9} {'lift':>7}")
    for k in [3, 4, 5, 6, 8, 10, 12]:
        s = te[te.k == k]
        ap = roc_auc_score(s.green, pe[te.k.values == k]); af = roc_auc_score(s.green, s.p)
        print(f"  {k:>3} {ap:>7.3f} {af:>9.3f} {af-ap:>+7.3f}")

    # стабильность
    flips = [stream(g.sort_values("k"))[1] for _, g in te.groupby("day")]
    fa = np.array(flips)
    print(f"\n■ СТАБИЛЬНОСТЬ: смен мнения/день среднее {fa.mean():.2f}, ≤1: {(fa<=1).mean()*100:.0f}%")

    # пример: последний день
    print("\n" + "="*70); print("■ LIVE — последний день"); print("="*70)
    last = df.index.normalize().unique()[-1]
    g = R[R.day == last].sort_values("k")
    o = df[df.index.normalize() == last]["open"].iloc[0]; cl = df[df.index.normalize() == last]["close"].iloc[-1]
    decisions, fl = stream(g)
    print(f"   {pd.Timestamp(last).date()}  open {o:,.0f} → {cl:,.0f} ({(cl/o-1)*100:+.2f}%), смен мнения: {fl}")
    print(f"   {'k':>3} {'state':>11} {'P(g)':>5} {'P_sm':>5} {'mode':>7} {'call':>6}")
    for k, st, p, sm, mode, call in decisions:
        if k % 2 == 0 or k == decisions[-1][0]:
            print(f"   {k:>3} {st:>11} {p:>5.2f} {sm:>5.2f} {mode:>7} {call:>6}")
    k, st, p, sm, mode, call = decisions[-1]
    print(f"\n   СЕЙЧАС: {st} | P(green)={p:.2f} (сглаж {sm:.2f}) | режим {mode} | call {call}")

    OUT.mkdir(exist_ok=True); te.to_csv(OUT / "etap_217_daytype_test.csv", index=False)
    print(f"\nSaved: {OUT / 'etap_217_daytype_test.csv'}")
    print("LIVE-API: daytype_nowcast(bars_сегодня, M) → (k, state, P_green, mode, call) каждый час")


def daytype_nowcast(bars_1h, M):
    """LIVE: по 1h-барам текущего дня → поток (k, state, P_green, mode, call)."""
    o = bars_1h["open"].iloc[0]; c = bars_1h["close"].values; H = bars_1h["high"].values; L = bars_1h["low"].values
    hi = np.maximum.accumulate(H); lo = np.minimum.accumulate(L)
    ib_h, ib_l = H[:IB].max(), L[:IB].min(); ib_r = max(ib_h-ib_l, 1e-9); ib_mid = (ib_h+ib_l)/2
    od = (c[0]-o)/ib_r; rows = []
    for k in range(len(bars_1h)):
        f = k >= IB; rng = hi[k]-lo[k]
        rows.append(dict(k=k, ret_k=c[k]/o-1, pos_rng=(c[k]-lo[k])/rng if rng > 0 else 0.5,
            ext_up=max(0, hi[k]-ib_h)/ib_r if f else 0.0, ext_dn=max(0, ib_l-lo[k])/ib_r if f else 0.0,
            above_ib=int(c[k] > ib_h) if f else 0, below_ib=int(c[k] < ib_l) if f else 0,
            dist_ib=(c[k]-ib_mid)/ib_r if f else 0.0, open_drive=od, ib_formed=int(f)))
    rdf = pd.DataFrame(rows); rdf["p"] = predict(M, rdf)
    return stream(rdf)


if __name__ == "__main__":
    main()
