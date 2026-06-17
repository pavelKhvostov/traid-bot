"""etap_238 — xmkt-7-mod: USDT.D (shift(1)) в range/big_day модель. A/B с kill-критерием.

Вердикт верификатора (wf_c8d84d08): медленный дневной prior в РОБАСТНУЮ ветку
(range R²0.50 / big_day AUC 0.73) — выживший класс фич; в FEATS нет ни одной
кросс-активной. Таргеты НЕ направление.

Фичи (все вычислены на сыром ряду → shift(1) → join по дате):
  usdtd_ret_1d, usdtd_ret_5d, usdtd_z20 (z-score уровня к 20д).
Данные: data/USDT_D_1d.csv (заголовок 'datetime,symbol,...', клип >=2018).

Протокол: пулированная CatBoost (BTC+ETH+SOL, asset категория) как в etap_201.
Train < 2025-01-01, test 2025-26 (канон daily_engine). Метрики: R²(log_range),
AUC(big_day) — база vs +usdtd, по годам.
KILL: нет улучшения обеих метрик ИЛИ инверсия в один из годов.

Запуск: venv/Scripts/python.exe research/daily_engine/etap_238_usdtd_ab.py
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
from sklearn.metrics import roc_auc_score, r2_score

USDTD = HERE.parent.parent / "data" / "USDT_D_1d.csv"
CUT = pd.Timestamp("2025-01-01", tz="UTC")


def usdtd_features():
    u = pd.read_csv(USDTD)
    tcol = "datetime" if "datetime" in u.columns else "open_time"
    u[tcol] = pd.to_datetime(u[tcol], utc=True)
    u = u.set_index(tcol).sort_index()
    u = u[u.index >= "2018-01-01"]
    c = pd.to_numeric(u["close"])
    f = pd.DataFrame(index=u.index.normalize())
    f["usdtd_ret_1d"] = c.pct_change().values
    f["usdtd_ret_5d"] = c.pct_change(5).values
    f["usdtd_z20"] = ((c - c.rolling(20).mean()) / c.rolling(20).std()).values
    f = f[~f.index.duplicated(keep="last")]
    return f.shift(1)  # as-of вчера


def build_dataset():
    uf = usdtd_features()
    frames = []
    for sym in A.SYMBOLS:
        d = A.daily_from_flow(sym)
        f = A.build_features(d).shift(1)
        f["gap"] = (d["open"] - d["close"].shift(1)) / A.atr(d, 14)
        f["asset"] = sym
        rng = (d["high"] - d["low"]) / d["close"].shift(1)
        f["log_range"] = np.log(rng.clip(lower=1e-6))
        f["big_day"] = (rng > rng.rolling(30).median()).astype(int)
        f["date"] = d.index
        idx = d.index.normalize()
        for c in ["usdtd_ret_1d", "usdtd_ret_5d", "usdtd_z20"]:
            f[c] = uf[c].reindex(idx).values
        frames.append(f.dropna(subset=["log_range", "atr_pct"]))
    return pd.concat(frames).sort_values("date")


def fit_eval(data, feat_cols, label):
    from catboost import CatBoostRegressor, CatBoostClassifier, Pool
    cat_idx = [feat_cols.index("asset")]
    tr = data[data.date < CUT].dropna(subset=feat_cols, how="all")
    te = data[data.date >= CUT]
    X_tr, X_te = tr[feat_cols].fillna(0.0), te[feat_cols].fillna(0.0)
    reg = CatBoostRegressor(iterations=500, depth=5, learning_rate=0.03, l2_leaf_reg=6,
                            loss_function="RMSE", random_seed=42, verbose=0)
    reg.fit(Pool(X_tr, tr["log_range"], cat_features=cat_idx))
    clf = CatBoostClassifier(iterations=400, depth=4, learning_rate=0.03, l2_leaf_reg=8,
                             random_seed=42, verbose=0)
    clf.fit(Pool(X_tr, tr["big_day"], cat_features=cat_idx))
    pr = reg.predict(X_te); pb = clf.predict_proba(X_te)[:, 1]
    r2 = r2_score(te["log_range"], pr)
    auc = roc_auc_score(te["big_day"], pb)
    print(f"  {label:<14} R²(log_range)={r2:.4f}  AUC(big_day)={auc:.4f}  (test n={len(te)})")
    res = {"r2": r2, "auc": auc}
    for y, g in te.groupby(te.date.dt.year):
        Xg = g[feat_cols].fillna(0.0)
        r2y = r2_score(g["log_range"], reg.predict(Xg))
        aucy = roc_auc_score(g["big_day"], clf.predict_proba(Xg)[:, 1]) if g["big_day"].nunique() > 1 else float("nan")
        print(f"    {y}: R²={r2y:.4f}  AUC={aucy:.4f}  n={len(g)}")
        res[f"r2_{y}"] = r2y; res[f"auc_{y}"] = aucy
    return res


def main():
    data = build_dataset()
    print(f"датасет: {len(data)} строк, USDT.D покрытие "
          f"{data['usdtd_ret_1d'].notna().mean()*100:.0f}% строк, тест с {CUT.date()}")
    base_cols = [c for c in data.columns if c not in
                 ("log_range", "big_day", "date", "usdtd_ret_1d", "usdtd_ret_5d", "usdtd_z20")]
    full_cols = base_cols + ["usdtd_ret_1d", "usdtd_ret_5d", "usdtd_z20"]
    print("\nA/B (train <2025, test 2025-26):")
    b = fit_eval(data, base_cols, "БАЗА")
    f = fit_eval(data, full_cols, "+USDT.D")
    dr, da = f["r2"] - b["r2"], f["auc"] - b["auc"]
    print(f"\nИТОГ: ΔR²={dr:+.4f}  ΔAUC={da:+.4f}")
    years = sorted({int(k.split('_')[1]) for k in b if k.startswith('r2_')})
    inv = any(f.get(f"r2_{y}", 0) < b.get(f"r2_{y}", 0) - 0.02 or
              (f.get(f"auc_{y}", 0) < b.get(f"auc_{y}", 0) - 0.02) for y in years)
    if dr <= 0.005 and da <= 0.005:
        print("ВЕРДИКТ: KILL — USDT.D не улучшает робастную ветку (kill-критерий xmkt-7-mod).")
    elif inv:
        print("ВЕРДИКТ: KILL — есть годовая инверсия (kill-критерий).")
    else:
        print("ВЕРДИКТ: KEEP — добавить usdtd-фичи в прод-модель etap_201.")


if __name__ == "__main__":
    main()
