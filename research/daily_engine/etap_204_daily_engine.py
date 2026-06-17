"""etap_204 — ПРОДАКШН daily_engine (Фаза 4): коррекции вшиты + intraday-flow + VIC maxV-прокси.

Капстоун. Объединяет всё:
  - расширенные фичи: base+VP (etap198) + squeeze + INTRADAY 1h order-flow + VIC maxV-прокси
  - walk-forward («самообучаемый»): обучение на данных ДО даты анализа, скользящее окно
  - ИСПРАВЛЕННЫЕ границы (Фаза 3): калиброванный k (контейнмент ~80%) + режимная де-калибровка
  - продукт: analyze_day() — границы/режим/зоны/bias/трейд/SHAP-аргументация

Сначала OOS-валидация: помогают ли intraday-flow + maxV (vs Фаза 3: R²0.50 / AUC0.73 / контейнмент77%)?

Запуск:
  validate: venv/Scripts/python.exe research/daily_engine/etap_204_daily_engine.py
  отчёт:    venv/Scripts/python.exe research/daily_engine/etap_204_daily_engine.py report BTCUSDT
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FLOW = ROOT / "research" / "elements_study" / "data"
OUT = HERE / "output"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
WIN, EMB, STEP, OOS_START = 540, 3, 21, "2025-01-01"


# ---------- intraday 1h order-flow + VIC maxV-прокси (дневные фичи) ----------
def intraday_features(sym):
    df = pd.read_csv(FLOW / f"{sym}_1h_flow.csv", parse_dates=["open_time"])
    df["date"] = df["open_time"].dt.floor("1D")
    df["hflow"] = 2 * df["taker_buy_base"] - df["volume"]   # 1h delta
    df["hour"] = df["open_time"].dt.hour
    rows = []
    for date, g in df.groupby("date"):
        g = g.sort_values("open_time")
        if len(g) < 6: continue
        vol = g["volume"].sum() or 1.0
        n = len(g); half = n // 2
        early = g["hflow"].iloc[:half].sum(); late = g["hflow"].iloc[half:].sum()
        cum = g["hflow"].cumsum()
        # VIC maxV-прокси: типичная цена 1h-бара с макс объёмом за день
        mv = g.loc[g["volume"].idxmax()]
        maxv_px = (mv["high"] + mv["low"] + mv["close"]) / 3
        rows.append({"date": date, "asset": sym,
                     "id_delta_norm": (early + late) / vol,
                     "id_delta_skew": (late - early) / vol,          # поздний поток − ранний
                     "id_cvd_slope": (cum.iloc[-1] - cum.iloc[0]) / vol,
                     "id_maxvol_hourpos": g["volume"].values.argmax() / n,  # когда был объёмный час
                     "id_late_buy_ratio": (g["taker_buy_base"].iloc[half:].sum() /
                                           (g["volume"].iloc[half:].sum() or 1.0)),
                     "maxv_px": maxv_px, "day_close": g["close"].iloc[-1]})
    out = pd.DataFrame(rows)
    # дистанция до вчерашнего maxV (как-of: сдвинем при сборке)
    out["maxv_dist"] = (out["day_close"] - out["maxv_px"]) / out["day_close"]
    return out.drop(columns=["maxv_px", "day_close"])


def actuals(sym):
    df = pd.read_csv(FLOW / f"{sym}_1h_flow.csv", parse_dates=["open_time"]).set_index("open_time")
    d = df.resample("1D", origin="epoch", label="left", closed="left").agg(
        {"open":"first","high":"max","low":"min","close":"last"}).dropna(subset=["open"])
    rng = (d["high"]-d["low"])/d["close"].shift(1)
    return pd.DataFrame({"date":d.index,"asset":sym,"open":d["open"],"high":d["high"],"low":d["low"],
                         "close":d["close"],"prev_close":d["close"].shift(1),
                         "range_frac":rng,"log_range":np.log(rng.clip(lower=1e-6)),
                         "big_day":(rng>rng.rolling(30).median()).astype(int)}).dropna()


def assemble():
    feats = pd.read_csv(OUT/"etap198_dataset.csv", parse_dates=["date"]); feats["date"]=pd.to_datetime(feats["date"],utc=True)
    # intraday-фичи: считаем по дням, СДВИГАЕМ на 1 (as-of t-1), мёржим
    idf = []
    for s in SYMBOLS:
        x = intraday_features(s).sort_values("date")
        x["date"] = pd.to_datetime(x["date"], utc=True)
        idcols = [c for c in x.columns if c.startswith(("id_","maxv_"))]
        x[idcols] = x[idcols].shift(1)            # leak-guard
        idf.append(x)
    idf = pd.concat(idf)
    data = feats.merge(idf, on=["date","asset"], how="left")
    act = pd.concat([actuals(s) for s in SYMBOLS]); act["date"]=pd.to_datetime(act["date"],utc=True)
    data = data.merge(act, on=["date","asset"], how="inner").sort_values("date").reset_index(drop=True)
    data["squeeze"] = data.groupby("asset")["atr_pct"].transform(lambda s: s/s.rolling(60).mean())
    base = [c for c in feats.columns if c not in ("y","date")]
    extra = ["squeeze","id_delta_norm","id_delta_skew","id_cvd_slope","id_maxvol_hourpos",
             "id_late_buy_ratio","maxv_dist"]
    feat_cols = base + extra
    data = data.dropna(subset=feat_cols + ["log_range"]).reset_index(drop=True)
    return data, feat_cols


def walk_forward(data, feat_cols):
    from catboost import CatBoostRegressor, CatBoostClassifier, Pool
    cat_idx = [feat_cols.index("asset")]
    oos = pd.Timestamp(OOS_START,tz="UTC"); last = data["date"].max(); rows=[]
    for cut in pd.date_range(oos,last,freq=f"{STEP}D"):
        be=cut+pd.Timedelta(days=STEP)
        tr=data[(data["date"]<cut-pd.Timedelta(days=EMB))&(data["date"]>=cut-pd.Timedelta(days=WIN))]
        bl=data[(data["date"]>=cut)&(data["date"]<be)]
        if len(tr)<300 or len(bl)==0: continue
        reg=CatBoostRegressor(iterations=400,depth=5,learning_rate=0.03,l2_leaf_reg=6,loss_function="RMSE",random_seed=42,verbose=0)
        reg.fit(Pool(tr[feat_cols],tr["log_range"],cat_features=cat_idx),verbose=0)
        clf=CatBoostClassifier(iterations=350,depth=4,learning_rate=0.03,l2_leaf_reg=8,random_seed=42,verbose=0)
        clf.fit(Pool(tr[feat_cols],tr["big_day"],cat_features=cat_idx),verbose=0)
        trc=tr.copy(); trc["pr"]=np.exp(reg.predict(trc[feat_cols])); trc["pb"]=clf.predict_proba(trc[feat_cols])[:,1]
        r_big=(trc.loc[trc.pb>=.5,"range_frac"]/trc.loc[trc.pb>=.5,"pr"]).median()
        r_flat=(trc.loc[trc.pb<.5,"range_frac"]/trc.loc[trc.pb<.5,"pr"]).median()
        trc["prc"]=np.where(trc.pb>=.5,trc.pr*r_big,trc.pr*r_flat)
        need=(np.maximum(trc.high-trc.open,trc.open-trc.low)/trc.prev_close/trc.prc).replace([np.inf,-np.inf],np.nan).dropna()
        k=float(np.quantile(need,0.80))
        b=bl.copy(); b["pr"]=np.exp(reg.predict(b[feat_cols])); b["pb"]=clf.predict_proba(b[feat_cols])[:,1]
        b["prc"]=np.where(b.pb>=.5,b.pr*r_big,b.pr*r_flat); b["k"]=k
        rows.append(b)
    return pd.concat(rows).sort_values("date")


def main_validate():
    from sklearn.metrics import r2_score, roc_auc_score
    data, feat_cols = assemble()
    print(f"[data] {len(data)} строк, {len(feat_cols)} фич (base+VP+squeeze+intraday-flow+maxV)")
    res = walk_forward(data, feat_cols); res["year"]=res["date"].dt.year
    half=res["k"]*res["prc"]*res["prev_close"]
    cont=((res.high<=res.open+half)&(res.low>=res.open-half)).mean()
    print(f"\n■ OOS 2025-26 (расширенные фичи + коррекции):")
    print(f"  range R² = {r2_score(res['log_range'], np.log(res['prc'].clip(lower=1e-6))):.3f}")
    print(f"  regime AUC = {roc_auc_score(res['big_day'], res['pb']):.3f}")
    print(f"  границы держат = {cont:.0%}")
    print(f"  (Фаза 3 было: R²~0.45-0.50 / AUC 0.71-0.72 / контейнмент 77%)")
    # помогли ли intraday/maxV? — importance
    from catboost import CatBoostRegressor, Pool
    cat_idx=[feat_cols.index("asset")]
    tr=data[data["date"]<pd.Timestamp(OOS_START,tz="UTC")]
    reg=CatBoostRegressor(iterations=400,depth=5,learning_rate=0.03,l2_leaf_reg=6,random_seed=42,verbose=0)
    reg.fit(Pool(tr[feat_cols],tr["log_range"],cat_features=cat_idx),verbose=0)
    imp=dict(zip(feat_cols,reg.get_feature_importance(Pool(tr[feat_cols],tr["log_range"],cat_features=cat_idx))))
    newf=["id_delta_norm","id_delta_skew","id_cvd_slope","id_maxvol_hourpos","id_late_buy_ratio","maxv_dist","squeeze"]
    print(f"\n■ Importance НОВЫХ фич (вклад в диапазон):")
    for f in sorted(newf,key=lambda x:-imp.get(x,0)):
        print(f"   {f:18} {imp.get(f,0):.2f}")
    print(f"   (для сравнения atr_pct={imp.get('atr_pct',0):.1f}, dow={imp.get('dow',0):.1f})")
    res.to_csv(OUT/"etap204_walkforward.csv",index=False)
    print(f"\n[saved] {OUT/'etap204_walkforward.csv'}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "report":
        print("report-режим: используйте etap_201_daily_analyzer (продукт-отчёт); здесь — валидация Ф4.")
    else:
        main_validate()
