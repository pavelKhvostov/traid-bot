"""etap_244 — Волна 1 / модуль mltech-1+2: распределение диапазона дня (MultiQuantile + CQR).

Вместо ОДНОЙ точки прогноза диапазона (R²0.50 + ручной множитель k под 80%) —
ПОЛНОЕ распределение: квантили q10/q25/q50/q75/q90 (CatBoost MultiQuantile) +
split-conformal поправка (CQR, Romano 2019) → ГАРАНТИРОВАННЫЙ containment.

Фичи: лучший набор etap_243 (база + HAR-RV vol-эконометрика). Таргет: log_range.
Walk-forward тот же (etap_204): WIN/EMB/STEP/OOS_START.

Ценность (проверяем):
  1) Калибровка [q10,q90]-полосы по log_range: маргинальный coverage ≈ 80%?
  2) Калибровка ПО vol-РЕЖИМАМ (терцили atr_pct) — главная польза conditional
     квантилей: константная полоса проваливает хвосты, conditional держит.
  3) Острота (sharpness): медианная ширина полосы vs безусловная [q10,q90].
  4) CQR-поправка: поднимает coverage до целевого без раздувания.

Запуск: venv/Scripts/python.exe research/daily_engine/etap_244_distributional_range.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np, pandas as pd

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import etap_204_daily_engine as E
import etap_243_vol_econometrics as V

OUT = HERE / "output"
DATA = OUT / "etap_243_dataset.csv"
ALPHAS = [0.1, 0.25, 0.5, 0.75, 0.9]
TARGET_COV = 0.80          # целевой охват [q10,q90]
CAL_FRAC = 0.3             # доля хвоста train под conformal-калибровку


def main():
    if not DATA.exists():
        raise SystemExit("нет etap_243_dataset.csv — сначала запусти etap_243")
    data = pd.read_csv(DATA, parse_dates=["date"])
    if data["date"].dt.tz is None:
        data["date"] = data["date"].dt.tz_localize("UTC")
    feat_cols = [c for c in (E.assemble()[1] + V.VOL_FEATS) if c in data.columns]
    cat_idx = [feat_cols.index("asset")]
    from catboost import CatBoostRegressor, Pool

    oos = pd.Timestamp(E.OOS_START, tz="UTC"); last = data["date"].max()
    rows = []
    loss = "MultiQuantile:alpha=" + ",".join(str(a) for a in ALPHAS)
    for cut in pd.date_range(oos, last, freq=f"{E.STEP}D"):
        be = cut + pd.Timedelta(days=E.STEP)
        trf = data[(data.date < cut - pd.Timedelta(days=E.EMB)) & (data.date >= cut - pd.Timedelta(days=E.WIN))]
        bl = data[(data.date >= cut) & (data.date < be)]
        if len(trf) < 300 or len(bl) == 0:
            continue
        # split train → fit-часть и conformal-калибровка (последние CAL_FRAC по дате)
        trf = trf.sort_values("date")
        ncal = int(len(trf) * CAL_FRAC)
        fit, cal = trf.iloc[:-ncal], trf.iloc[-ncal:]
        m = CatBoostRegressor(loss_function=loss, iterations=400, depth=5,
                              learning_rate=0.03, l2_leaf_reg=6, random_seed=42, verbose=0)
        m.fit(Pool(fit[feat_cols], fit["log_range"], cat_features=cat_idx), verbose=0)
        # CQR: conformity по lo=q10, hi=q90 на калибровке
        qc = m.predict(Pool(cal[feat_cols], cat_features=cat_idx))
        lo_c, hi_c = qc[:, 0], qc[:, -1]
        y_c = cal["log_range"].values
        scores = np.maximum(lo_c - y_c, y_c - hi_c)
        n = len(scores)
        Q = float(np.quantile(scores, min(1.0, np.ceil((n + 1) * TARGET_COV) / n)))
        # предсказание на блоке
        qb = m.predict(Pool(bl[feat_cols], cat_features=cat_idx))
        b = bl.copy()
        for i, a in enumerate(ALPHAS):
            b[f"q{int(a*100)}"] = qb[:, i]
        b["lo_cqr"] = qb[:, 0] - Q
        b["hi_cqr"] = qb[:, -1] + Q
        rows.append(b)
    res = pd.concat(rows).sort_values("date")
    res["year"] = res.date.dt.year
    y = res["log_range"].values

    def cover(lo, hi): return ((res.log_range >= res[lo]) & (res.log_range <= res[hi])).mean()
    def width(lo, hi): return float(np.median(np.exp(res[hi]) - np.exp(res[lo])))  # в range_frac

    print("=" * 74)
    print(f"РАСПРЕДЕЛЕНИЕ ДИАПАЗОНА ДНЯ — OOS 2025-26, n={len(res)} (цель охвата {TARGET_COV:.0%})")
    print("=" * 74)
    print(f"  [q10,q90] сырой:   coverage={cover('q10','q90'):.0%}  ширина(медиана range_frac)={width('q10','q90'):.4f}")
    print(f"  [lo,hi]  +CQR:     coverage={cover('lo_cqr','hi_cqr'):.0%}  ширина={width('lo_cqr','hi_cqr'):.4f}")
    # безусловная полоса (константные квантили log_range из train) — baseline остроты
    tr = data[data.date < oos]
    ulo, uhi = np.quantile(tr["log_range"], [0.1, 0.9])
    uncond_cov = ((y >= ulo) & (y <= uhi)).mean()
    uncond_w = float(np.exp(uhi) - np.exp(ulo))
    print(f"  безусловная [q10,q90]: coverage={uncond_cov:.0%}  ширина={uncond_w:.4f}  ← baseline остроты")
    print(f"  → conditional острее в {uncond_w/width('q10','q90'):.2f}× при сравнимом охвате")

    print("\n■ КАЛИБРОВКА ПО VOL-РЕЖИМАМ (терцили atr_pct) — главная польза conditional:")
    res["voreg"] = pd.qcut(res["atr_pct"].rank(method="first"), 3, labels=["низкая", "средняя", "высокая"])
    print(f"  {'режим':<8} {'cqr-cov':>8} {'сырой-cov':>10} {'безусл-cov':>11}")
    for reg, g in res.groupby("voreg", observed=True):
        cc = ((g.log_range >= g.lo_cqr) & (g.log_range <= g.hi_cqr)).mean()
        rc = ((g.log_range >= g.q10) & (g.log_range <= g.q90)).mean()
        uc = ((g.log_range >= ulo) & (g.log_range <= uhi)).mean()
        print(f"  {reg:<8} {cc:>8.0%} {rc:>10.0%} {uc:>11.0%}")

    print("\n■ По годам (CQR coverage):")
    for yy, g in res.groupby("year"):
        cc = ((g.log_range >= g.lo_cqr) & (g.log_range <= g.hi_cqr)).mean()
        print(f"  {yy}: coverage={cc:.0%} n={len(g)}")

    res.to_csv(OUT / "etap_244_quantiles.csv", index=False)
    print(f"\nSaved: {OUT/'etap_244_quantiles.csv'}")
    print("ПРОДУКТ: q10/q50/q90 → «диапазон дня X–Y%, медиана Z%»; CQR-полоса для сайзинга.")


if __name__ == "__main__":
    main()
