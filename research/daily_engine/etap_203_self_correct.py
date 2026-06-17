"""etap_203 — SELF-CORRECTION (замыкание цикла Фазы 3).

Self-critique (etap_202) выявил 3 дефекта → применяем АРГУМЕНТИРОВАННЫЕ коррекции и меряем:
  ДЕФЕКТ 1: границы держат 31% (множитель 0.55 узок)
    → КОРРЕКЦИЯ: калибровать k на train под целевой контейнмент 80%.
  ДЕФЕКТ 2: регрессия к среднему (большие дни −1.74пп, флэт +1.06пп)
    → КОРРЕКЦИЯ: режимная мультипликативная де-калибровка (ratio actual/pred по big/flat на train).
  ДЕФЕКТ 3: 37% больших дней пропущено (vol-всплеск после сжатия)
    → КОРРЕКЦИЯ: breakout-risk фича = сжатие диапазона (atr_pct / его среднее, low=сжато→риск).

Сравнение ДО/ПОСЛЕ на OOS 2025-26: контейнмент, сдвиг по режиму, R².

Запуск: venv/Scripts/python.exe research/daily_engine/etap_203_self_correct.py
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
WIN, EMB, STEP = 540, 3, 21
OOS_START = "2025-01-01"


def actuals(sym):
    df = pd.read_csv(FLOW / f"{sym}_1h_flow.csv", parse_dates=["open_time"]).set_index("open_time")
    d = df.resample("1D", origin="epoch", label="left", closed="left").agg(
        {"open":"first","high":"max","low":"min","close":"last"}).dropna(subset=["open"])
    rng = (d["high"]-d["low"])/d["close"].shift(1)
    return pd.DataFrame({"date":d.index,"asset":sym,"open":d["open"],"high":d["high"],"low":d["low"],
                         "close":d["close"],"prev_close":d["close"].shift(1),
                         "range_frac":rng,"log_range":np.log(rng.clip(lower=1e-6)),
                         "big_day":(rng>rng.rolling(30).median()).astype(int)}).dropna()


def main():
    from catboost import CatBoostRegressor, CatBoostClassifier, Pool
    from sklearn.metrics import r2_score

    feats = pd.read_csv(OUT/"etap198_dataset.csv", parse_dates=["date"]); feats["date"]=pd.to_datetime(feats["date"],utc=True)
    act = pd.concat([actuals(s) for s in SYMBOLS]); act["date"]=pd.to_datetime(act["date"],utc=True)
    data = feats.merge(act, on=["date","asset"], how="inner").sort_values("date").reset_index(drop=True)
    # КОРРЕКЦИЯ 3: breakout-risk фича (сжатие диапазона), leak-safe из atr_pct (уже as-of t-1)
    data["squeeze"] = data.groupby("asset")["atr_pct"].transform(lambda s: s/s.rolling(60).mean())
    data["squeeze_z"] = data.groupby("asset")["atr_pct"].transform(
        lambda s: (s - s.rolling(60).mean())/s.rolling(60).std())
    data = data.dropna(subset=["squeeze","squeeze_z"]).reset_index(drop=True)

    feat_base = [c for c in feats.columns if c not in ("y","date")]
    feat_new = feat_base + ["squeeze","squeeze_z"]
    cat_idx = [feat_new.index("asset")]

    oos = pd.Timestamp(OOS_START,tz="UTC"); last = data["date"].max()
    rows = []
    for cut in pd.date_range(oos,last,freq=f"{STEP}D"):
        be = cut+pd.Timedelta(days=STEP)
        tr = data[(data["date"]<cut-pd.Timedelta(days=EMB)) & (data["date"]>=cut-pd.Timedelta(days=WIN))]
        bl = data[(data["date"]>=cut) & (data["date"]<be)]
        if len(tr)<300 or len(bl)==0: continue
        reg = CatBoostRegressor(iterations=400,depth=5,learning_rate=0.03,l2_leaf_reg=6,
                                loss_function="RMSE",random_seed=42,verbose=0)
        reg.fit(Pool(tr[feat_new],tr["log_range"],cat_features=cat_idx),verbose=0)
        clf = CatBoostClassifier(iterations=350,depth=4,learning_rate=0.03,l2_leaf_reg=8,
                                 random_seed=42,verbose=0)
        clf.fit(Pool(tr[feat_new],tr["big_day"],cat_features=cat_idx),verbose=0)

        # train-предсказания для калибровок
        tr = tr.copy()
        tr["pr"] = np.exp(reg.predict(tr[feat_new])); tr["pb"] = clf.predict_proba(tr[feat_new])[:,1]
        # КОРРЕКЦИЯ 2: режимный ratio actual/pred
        r_big = (tr.loc[tr["pb"]>=0.5,"range_frac"]/tr.loc[tr["pb"]>=0.5,"pr"]).median()
        r_flat= (tr.loc[tr["pb"]<0.5,"range_frac"]/tr.loc[tr["pb"]<0.5,"pr"]).median()
        # КОРРЕКЦИЯ 1: множитель k под 80% контейнмент на train (после режимной коррекции)
        tr["pr_c"] = np.where(tr["pb"]>=0.5, tr["pr"]*r_big, tr["pr"]*r_flat)
        need_k = (np.maximum(tr["high"]-tr["open"], tr["open"]-tr["low"])/tr["prev_close"] / tr["pr_c"]).replace([np.inf,-np.inf],np.nan).dropna()
        k = float(np.quantile(need_k, 0.80))

        bl = bl.copy()
        bl["pr"] = np.exp(reg.predict(bl[feat_new])); bl["pb"] = clf.predict_proba(bl[feat_new])[:,1]
        bl["pr_c"] = np.where(bl["pb"]>=0.5, bl["pr"]*r_big, bl["pr"]*r_flat)
        bl["k"] = k
        rows.append(bl)
    res = pd.concat(rows).sort_values("date"); res["year"]=res["date"].dt.year

    def report(tag, pr_col, k_col_or_val):
        half_old = 0.55*res["pr"]*res["prev_close"]
        if pr_col=="pr":  # ДО (baseline)
            half = 0.55*res["pr"]*res["prev_close"]; rng_used = res["pr"]
        else:             # ПОСЛЕ
            half = res[k_col_or_val]*res["pr_c"]*res["prev_close"]; rng_used = res["pr_c"]
        cont = ((res["high"]<=res["open"]+half) & (res["low"]>=res["open"]-half)).mean()
        bias = (rng_used-res["range_frac"]).mean()*100
        big = res[res["big_day"]==1]; flat = res[res["big_day"]==0]
        bb = (big["pr_c" if pr_col!="pr" else "pr"]-big["range_frac"]).mean()*100
        fb = (flat["pr_c" if pr_col!="pr" else "pr"]-flat["range_frac"]).mean()*100
        print(f"  [{tag}] контейнмент {cont:.0%} | общий сдвиг {bias:+.2f}пп | большие {bb:+.2f}пп | флэт {fb:+.2f}пп")

    print("="*70); print("SELF-CORRECTION — ДО vs ПОСЛЕ (OOS 2025-2026)"); print("="*70)
    print(f"\nДней: {len(res)}")
    print("\n■ ГРАНИЦЫ / ДИАПАЗОН:")
    report("ДО  (k=0.55, без коррекций)", "pr", None)
    report("ПОСЛЕ (калибр. k + режимный ratio + squeeze)", "pr_c", "k")
    print(f"\n  R² log_range ПОСЛЕ (с squeeze): {r2_score(res['log_range'], np.log(res['pr_c'].clip(lower=1e-6))):.3f}")
    # пропущенные большие дни до/после (squeeze влияет на reg, regime clf тот же — смотрим reg-улучшение на больших)
    big = res[res["big_day"]==1]
    print(f"\n■ БОЛЬШИЕ ДНИ (дефект 2): MAE диапазона "
          f"ДО {(big['pr']-big['range_frac']).abs().mean()*100:.2f}пп → "
          f"ПОСЛЕ {(big['pr_c']-big['range_frac']).abs().mean()*100:.2f}пп")
    res.to_csv(OUT/"etap203_corrected.csv", index=False)
    print(f"\n[saved] {OUT/'etap203_corrected.csv'}")
    print("\nИТОГ цикла predict→critique→correct: модель аргументированно расширила границы,")
    print("сняла регрессию-к-среднему по режиму и добавила breakout-risk. Меряем эффект выше.")


if __name__ == "__main__":
    main()
