"""etap_234 — Модель анализа дня v2.0: ядро по итогам расследования (workflow wf_c8d84d08).

Реализует ВЕРИФИЦИРОВАННЫЕ quick-win фичи и новые выходы поверх day-type v1 (etap_217):

  A. ib_norm_atr (dalton-2, вердикт MODIFY/quick-win, эмпирика ревьюера:
     corr(ib_pct, atr_pct)=0.48 -> corr(ib_norm_atr, atr_pct)=-0.04, градиент Далтона OOS).
     = (IB_h-IB_l) / ATR14_daily.shift(1). В per-hour логистику для k>=IB.
  B. ORV (dalton-1-mod, regime-only) + overnight inventory (dalton-5-mod):
     open vs вчерашняя VA70 + перекос хвоста вчерашнего дня. ТОЛЬКО для ранних
     часов k<IB (FORMING-дыра) — A/B отдельно, по вердикту ревьюеров для
     направления это мертво (etap_211 AUC 0.512), ценность только в ранних k.
  C. P(trend-hold) — НОВЫЙ выход (ml-2+ml-3+ml-7 merged): эмпирическая таблица
     P(final_state == state_k | state_k, k) с beta-binomial shrinkage, train<2023,
     OOS-оценка. Это НЕ направление-вперёд (стена) — это персистентность УЖЕ
     наблюдаемого состояния (родственник big_day AUC 0.73). + срез по ib_norm терцилям.
  D. Choppiness (ml-6): рваность первой половины дня (n пересечений 0.5 сырой p,
     cum|p_raw-p_sm|) -> предсказывает ли флипы остатка дня. OOS.

Валидация: OOS 2023+, A/B AUC по часам v1 vs v2, пермутационный null для lift
(constraint: shuffle обязателен), калибровка, стабильность.

Запуск: venv/Scripts/python.exe research/daily_engine/etap_234_daytype_v2.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np, pandas as pd

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import etap_217_daytype_layer as L
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, brier_score_loss

DATA = HERE.parent.parent / "data" / "BTCUSDT_1h_orderflow.csv"
OUT = HERE / "output"
CUTOFF = L.CUTOFF
IB = L.IB
RNG = np.random.RandomState(42)

V1 = L.FEATS
V2 = V1 + ["ib_norm_atr"]
EARLY = ["orv_above", "orv_below", "orv_dist", "inv_ret6", "inv_clv"]


# ---------------------------------------------------------------------------
def daily_extras(df):
    """Пер-день величины: ATR14.shift(1), вчерашняя VA70, inventory. Всё as-of d-1."""
    d = df.resample("1D").agg({"open": "first", "high": "max", "low": "min",
                               "close": "last", "volume": "sum"}).dropna()
    tr = np.maximum(d.high - d.low,
                    np.maximum((d.high - d.close.shift(1)).abs(),
                               (d.low - d.close.shift(1)).abs()))
    atr14 = tr.rolling(14).mean().shift(1)            # as-of вчера

    # VA70 вчерашнего дня по 1h-барам (профиль hlc3 x volume, 24 бина)
    va = {}
    for day, g in df.groupby(df.index.normalize()):
        if len(g) < 12: continue
        price = ((g.high + g.low + g.close) / 3).values
        vol = g.volume.values
        lo, hi = price.min(), price.max()
        if hi <= lo: continue
        edges = np.linspace(lo, hi, 25)
        idx = np.clip(np.digitize(price, edges) - 1, 0, 23)
        binv = np.zeros(24)
        for i, v in zip(idx, vol): binv[i] += v
        if binv.sum() <= 0: continue
        order = np.argsort(binv)[::-1]
        acc, sel = 0.0, []
        for i in order:
            acc += binv[i]; sel.append(i)
            if acc >= binv.sum() * 0.70: break
        centers = (edges[:-1] + edges[1:]) / 2
        va[day] = (float(centers[min(sel)] if False else np.min(centers[sel])),
                   float(np.max(centers[sel])))

    # inventory вчера: ретёрн последних 6h и CLV дневного бара
    inv6, clv = {}, {}
    for day, g in df.groupby(df.index.normalize()):
        if len(g) < 7: continue
        inv6[day] = g.close.iloc[-1] / g.close.iloc[-7] - 1
        rngd = g.high.max() - g.low.min()
        clv[day] = (g.close.iloc[-1] - g.low.min()) / rngd if rngd > 0 else 0.5

    days = sorted(set(df.index.normalize()))
    rows = []
    for i, day in enumerate(days):
        prev = days[i - 1] if i > 0 else None
        a = atr14.get(day, np.nan)                    # уже shift(1)
        pva = va.get(prev) if prev is not None else None
        rows.append(dict(day=day, atr14=a,
                         pva_lo=pva[0] if pva else np.nan,
                         pva_hi=pva[1] if pva else np.nan,
                         inv_ret6=inv6.get(prev, np.nan) if prev else np.nan,
                         inv_clv=clv.get(prev, np.nan) if prev else np.nan))
    return pd.DataFrame(rows).set_index("day")


def build_v2(df):
    """Фичи v1 (L.build) + новые. final_state дня. Без lookahead."""
    R = L.build(df).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    ex = daily_extras(df)

    # ib_range и open per day из самих баров
    ibr, op = {}, {}
    for day, g in df.groupby(df.index.normalize()):
        if len(g) < IB + 2: continue
        ibr[day] = g.high.values[:IB].max() - g.low.values[:IB].min()
        op[day] = g.open.iloc[0]

    R["atr14"] = R.day.map(ex.atr14)
    R["ib_range"] = R.day.map(ibr)
    R["open_d"] = R.day.map(op)
    R["ib_norm_atr"] = np.where(R.ib_formed.astype(bool) & (R.atr14 > 0),
                                R.ib_range / R.atr14, 0.0)
    # ORV: open vs вчерашняя VA (константа дня)
    R["pva_lo"] = R.day.map(ex.pva_lo); R["pva_hi"] = R.day.map(ex.pva_hi)
    R["orv_above"] = (R.open_d > R.pva_hi).astype(float)
    R["orv_below"] = (R.open_d < R.pva_lo).astype(float)
    dist = np.where(R.open_d > R.pva_hi, R.open_d - R.pva_hi,
                    np.where(R.open_d < R.pva_lo, R.open_d - R.pva_lo, 0.0))
    R["orv_dist"] = np.where(R.atr14 > 0, dist / R.atr14, 0.0)
    R["inv_ret6"] = R.day.map(ex.inv_ret6)
    R["inv_clv"] = R.day.map(ex.inv_clv)

    # final_state дня (k=23) — для persistence-таблиц (классификация, не таргет-направление)
    last = R.sort_values("k").groupby("day").tail(1)
    fmap = {row["day"]: L.classify(row)[0] for _, row in last.iterrows()}
    R["final_state"] = R.day.map(fmap)
    R["state_k"] = R.apply(lambda row: L.classify(row)[0], axis=1)
    return R.replace([np.inf, -np.inf], np.nan).fillna(0.0)


def fit_eval(tr, te, feats, hours):
    """per-hour логистика -> dict k: (auc, n)."""
    out = {}
    for k in hours:
        s, t = tr[tr.k == k], te[te.k == k]
        if len(s) < 50 or s.green.nunique() < 2 or t.green.nunique() < 2: continue
        m = LogisticRegression(max_iter=500).fit(s[feats], s.green)
        out[k] = (roc_auc_score(t.green, m.predict_proba(t[feats])[:, 1]), len(t))
    return out


def main():
    df = pd.read_csv(DATA, index_col=0, parse_dates=True)
    if df.index.tz is None: df.index = df.index.tz_localize("UTC")
    R = build_v2(df)
    tr, te = R[R.day < CUTOFF], R[R.day >= CUTOFF]
    print(f"train дней: {tr.day.nunique()}  OOS дней: {te.day.nunique()}  (cutoff {CUTOFF.date()})")

    # ---------- A. ib_norm_atr: A/B v1 vs v2 ----------
    print("\n" + "=" * 72)
    print("A. ib_norm_atr в per-hour логистике — A/B OOS (часы k>=IB)")
    print("=" * 72)
    hours = list(range(IB, 24))
    a1 = fit_eval(tr, te, V1, hours)
    a2 = fit_eval(tr, te, V2, hours)
    lifts = []
    print(f"  {'k':>3} {'v1':>7} {'v2':>7} {'lift':>8}")
    for k in hours:
        if k in a1 and k in a2:
            l = a2[k][0] - a1[k][0]; lifts.append(l)
            mark = " *" if abs(l) >= 0.01 else ""
            print(f"  {k:>3} {a1[k][0]:>7.3f} {a2[k][0]:>7.3f} {l:>+8.3f}{mark}")
    mean_lift = float(np.mean(lifts))
    print(f"  средний lift: {mean_lift:+.4f}")

    # пермутационный null для среднего lift (shuffle y в train, 30 перм., часы 4..10)
    null_hours = [4, 5, 6, 7, 8, 9, 10]
    nulls = []
    for p in range(30):
        ls = []
        for k in null_hours:
            s, t = tr[tr.k == k].copy(), te[te.k == k]
            ys = s.green.sample(frac=1.0, random_state=1000 + p * 31 + k).values
            if len(set(ys)) < 2: continue
            m1 = LogisticRegression(max_iter=500).fit(s[V1], ys)
            m2 = LogisticRegression(max_iter=500).fit(s[V2], ys)
            ls.append(roc_auc_score(t.green, m2.predict_proba(t[V2])[:, 1]) -
                      roc_auc_score(t.green, m1.predict_proba(t[V1])[:, 1]))
        nulls.append(np.mean(ls))
    real = float(np.mean([a2[k][0] - a1[k][0] for k in null_hours if k in a1]))
    pval = float((np.array(nulls) >= real).mean())
    print(f"  shuffle-null (часы 4-10): real {real:+.4f}, null среднее {np.mean(nulls):+.4f}, p={pval:.3f}")

    # ---------- B. ORV + inventory: только ранние часы k<IB ----------
    print("\n" + "=" * 72)
    print("B. ORV + inventory — закрывает ли FORMING-дыру (часы k=0..2)? A/B OOS")
    print("=" * 72)
    base_early = ["ret_k", "pos_rng", "open_drive"]
    b1 = fit_eval(tr, te, base_early, [0, 1, 2])
    b2 = fit_eval(tr, te, base_early + EARLY, [0, 1, 2])
    for k in [0, 1, 2]:
        if k in b1 and k in b2:
            print(f"  k={k}: база {b1[k][0]:.3f} -> +ORV/inv {b2[k][0]:.3f}  lift {b2[k][0]-b1[k][0]:+.3f}")

    # ---------- C. P(trend-hold): persistence-таблица с shrinkage ----------
    print("\n" + "=" * 72)
    print("C. P(trend-hold) — доживёт ли состояние часа k до конца дня (НОВЫЙ выход)")
    print("=" * 72)
    # эмпирика train<2023 c Beta-shrinkage к глобальной персистентности состояния
    tbl = {}
    for st in ["TREND_UP", "TREND_DOWN", "ROTATION"]:
        sub_all = tr[(tr.state_k == st) & (tr.k >= IB)]
        g0 = (sub_all.final_state == st).mean() if len(sub_all) else 0.5
        a0 = 10.0  # сила prior
        for k in range(IB, 24):
            s = sub_all[sub_all.k == k]
            n = len(s); h = (s.final_state == st).sum() if n else 0
            tbl[(st, k)] = (h + g0 * a0) / (n + a0)
    # OOS оценка
    print(f"  {'k':>3} | " + " | ".join(f"{st:>20}" for st in ["TREND_UP", "TREND_DOWN", "ROTATION"]))
    briers, accs = [], []
    for k in [4, 6, 8, 10, 12, 14, 16, 18, 20]:
        row = []
        for st in ["TREND_UP", "TREND_DOWN", "ROTATION"]:
            s = te[(te.state_k == st) & (te.k == k)]
            if len(s) < 10:
                row.append(f"{'—':>20}"); continue
            p = tbl[(st, k)]; y = (s.final_state == st).astype(int)
            row.append(f"pred {p:.2f} факт {y.mean():.2f} n={len(y):>4}")
            briers.append(brier_score_loss(y, np.full(len(y), p)))
        print(f"  {k:>3} | " + " | ".join(row))
    print(f"  OOS Brier (средний по ячейкам): {np.mean(briers):.3f}")

    # срез: hold TREND_UP по терцилям ib_norm_atr (узкий IB -> тренд доживает?)
    print("\n  P(TREND_UP доживёт | ширина IB/ATR), k=6..12, OOS:")
    s = te[(te.state_k == "TREND_UP") & (te.k.between(6, 12)) & (te.ib_norm_atr > 0)].copy()
    if len(s) > 100:
        s["tercile"] = pd.qcut(s.ib_norm_atr, 3, labels=["узкий", "средний", "широкий"])
        for tc, g in s.groupby("tercile", observed=True):
            print(f"    IB {tc:<8} n={len(g):>4}  hold-rate {(g.final_state == 'TREND_UP').mean():.2f}")

    # ---------- D. Choppiness -> флипы остатка дня ----------
    print("\n" + "=" * 72)
    print("D. Choppiness первой половины дня -> флипы во второй половине (OOS)")
    print("=" * 72)
    M1 = {k: LogisticRegression(max_iter=500).fit(tr[tr.k == k][V1], tr[tr.k == k].green)
          for k in range(24) if len(tr[tr.k == k]) >= 50 and tr[tr.k == k].green.nunique() > 1}
    rows = []
    for day, g in te.groupby("day"):
        g = g.sort_values("k")
        if len(g) < 20: continue
        p = np.array([M1[k].predict_proba(g[g.k == k][V1])[:, 1][0] if k in M1 else 0.5
                      for k in g.k.values])
        # сглаживание и коллы как в L.stream
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
        rows.append((cross_early, dsum_early, flips_late))
    ch = pd.DataFrame(rows, columns=["cross_early", "dsum_early", "flips_late"])
    ch["rough"] = (ch.flips_late >= 1).astype(int)
    auc_cross = roc_auc_score(ch.rough, ch.cross_early) if ch.rough.nunique() > 1 else float("nan")
    auc_dsum = roc_auc_score(ch.rough, ch.dsum_early) if ch.rough.nunique() > 1 else float("nan")
    print(f"  дней OOS: {len(ch)}, доля дней с поздним флипом: {ch.rough.mean():.2f}")
    print(f"  AUC(early n_cross -> поздний флип): {auc_cross:.3f}")
    print(f"  AUC(early sum|p_raw-p_sm| -> поздний флип): {auc_dsum:.3f}")
    q = pd.qcut(ch.cross_early.rank(method="first"), 3, labels=["спокойный", "средний", "рваный"])
    for lab, g in ch.groupby(q, observed=True):
        print(f"    утро {lab:<10} n={len(g):>4}  P(флип после 12:00) = {g.flips_late.ge(1).mean():.2f}")

    OUT.mkdir(exist_ok=True)
    R.to_csv(OUT / "etap_234_v2_features.csv", index=False)
    print(f"\nSaved: {OUT / 'etap_234_v2_features.csv'}")


if __name__ == "__main__":
    main()
