"""etap_200 — переориентация нейро-модуля: прогноз ДИАПАЗОНА дня (не направления).

Направление дня = монетка (etap_198/199). НО волатильность КЛАСТЕРИЗУЕТСЯ — диапазон
дня предсказуем. Это и есть «границы торговли дня» из ТЗ. CatBoost учит:
  - регрессия: log(range_t / close_{t-1})  → ожидаемый диапазон дня
  - классификация: «большой день» range_t > rolling-median(range,30)
Фичи — те же (as-of t-1, leak-safe) из etap198_dataset.csv. Метка считается заново из flow.
Статичный split 2020-24 / 2025-26 + walk-forward. Метрики: OOS corr/R² (рег) + AUC (класс).

Запуск: venv/Scripts/python.exe research/daily_engine/etap_200_range_forecast.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

ROOT = Path(__file__).resolve().parents[2]
FLOW = ROOT / "research" / "elements_study" / "data"
OUT = Path(__file__).resolve().parent / "output"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
TRAIN_END = "2025-01-01"


def range_labels(sym):
    df = pd.read_csv(FLOW / f"{sym}_1h_flow.csv", parse_dates=["open_time"]).set_index("open_time")
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    d = df.resample("1D", origin="epoch", label="left", closed="left").agg(agg).dropna(subset=["open"])
    rng = (d["high"] - d["low"]) / d["close"].shift(1)        # дневной диапазон в долях
    lr = np.log(rng.clip(lower=1e-6))
    med30 = rng.rolling(30).median()
    out = pd.DataFrame({"date": d.index, "asset": sym,
                        "range_frac": rng, "log_range": lr,
                        "big_day": (rng > med30).astype(int)})
    return out.dropna()


def main():
    from catboost import CatBoostRegressor, CatBoostClassifier, Pool
    from sklearn.metrics import roc_auc_score, r2_score

    feats = pd.read_csv(OUT / "etap198_dataset.csv", parse_dates=["date"])
    feats["date"] = pd.to_datetime(feats["date"], utc=True)
    lab = pd.concat([range_labels(s) for s in SYMBOLS])
    lab["date"] = pd.to_datetime(lab["date"], utc=True)
    data = feats.merge(lab, on=["date", "asset"], how="inner").sort_values("date").reset_index(drop=True)
    feat_cols = [c for c in feats.columns if c not in ("y", "date")]
    cat_idx = [feat_cols.index("asset")]
    print(f"[data] {len(data)} строк, {len(feat_cols)} фич | big_day base={data['big_day'].mean():.3f}")

    tr = data[data["date"] < pd.Timestamp(TRAIN_END, tz='UTC')].reset_index(drop=True)
    te = data[data["date"] >= pd.Timestamp(TRAIN_END, tz='UTC')].reset_index(drop=True)
    print(f"[split] train {len(tr)} | test {len(te)}")

    # --- регрессия log_range ---
    reg = CatBoostRegressor(iterations=500, depth=5, learning_rate=0.03, l2_leaf_reg=6,
                            loss_function="RMSE", random_seed=42, verbose=0)
    reg.fit(Pool(tr[feat_cols], tr["log_range"], cat_features=cat_idx))
    pred = reg.predict(te[feat_cols])
    r2 = r2_score(te["log_range"], pred)
    corr = np.corrcoef(pred, te["log_range"])[0, 1]
    # naive baseline: вчерашний log_range (persistence)
    naive = tr["log_range"].mean()  # для R2 baseline берётся среднее train; persistence сравним отдельно
    print(f"\n[РЕГРЕССИЯ log_range] OOS R²={r2:.3f}  corr(pred,real)={corr:.3f}")
    # persistence baseline на OOS: предсказание = log_range предыдущего дня того же актива
    te2 = te.copy()
    te2["persist"] = te2.groupby("asset")["log_range"].shift(1)
    m = te2["persist"].notna()
    r2_persist = r2_score(te2.loc[m, "log_range"], te2.loc[m, "persist"])
    print(f"   persistence(вчера) baseline OOS R²={r2_persist:.3f}  → модель {'бьёт' if r2>r2_persist else 'НЕ бьёт'} persistence")

    # --- классификация big_day ---
    clf = CatBoostClassifier(iterations=400, depth=4, learning_rate=0.03, l2_leaf_reg=8,
                             loss_function="Logloss", random_seed=42, verbose=0)
    clf.fit(Pool(tr[feat_cols], tr["big_day"], cat_features=cat_idx))
    pc = clf.predict_proba(te[feat_cols])[:, 1]
    auc = roc_auc_score(te["big_day"], pc)
    print(f"\n[КЛАССИФИКАЦИЯ big_day] OOS AUC={auc:.3f}  base={te['big_day'].mean():.3f}")
    te3 = te.copy(); te3["p"] = pc; te3["year"] = te3["date"].dt.year
    for yr, g in te3.groupby("year"):
        if len(g) > 20: print(f"   {yr}: AUC {roc_auc_score(g['big_day'], g['p']):.3f} (n={len(g)})")

    imp = reg.get_feature_importance(Pool(tr[feat_cols], tr["log_range"], cat_features=cat_idx))
    top = sorted(zip(feat_cols, imp), key=lambda x: -x[1])[:10]
    print("\n[top-10 importance (range)]")
    for n, vv in top: print(f"   {n:16} {vv:5.2f}")

    print("\nВЕРДИКТ:")
    if r2 > 0.15 and r2 > r2_persist:
        print(f"  Диапазон дня ПРЕДСКАЗУЕМ (R²={r2:.3f}, бьёт persistence) → нейро-ядро = прогноз границ.")
    elif r2 > max(0.05, r2_persist):
        print(f"  Диапазон умеренно предсказуем (R²={r2:.3f}) → границы строим, но скромно vs persistence.")
    else:
        print(f"  Диапазон слабо предсказуем сверх persistence — границы брать проще через ATR/EWMA.")


if __name__ == "__main__":
    main()
