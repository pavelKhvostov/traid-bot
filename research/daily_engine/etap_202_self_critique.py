"""etap_202 — SELF-CRITIQUE LOOP (Фаза 3).

«Нейронка в случае ошибки разбирает зоны/показатели, чтобы понять почему ошиблась и
исправляться аргументированно; при правоте — чётко понимать почему права» (ТЗ).

Работает на ПРЕДСКАЗУЕМЫХ целях (направление = монетка, не критикуем):
  - ГРАНИЦЫ/ДИАПАЗОН дня (range-регрессор, OOS R² 0.50)
  - РЕЖИМ дня big/flat (AUC 0.73)
Walk-forward по 2025-2026 (rolling retrain). Для КАЖДОГО дня:
  - предсказание vs факт (range, regime, удержались ли границы)
  - SHAP-атрибуция: какие фичи двигали прогноз
Затем САМОКРИТИКА:
  - систематический сдвиг (над/недо-оценка диапазона), по режиму и dow
  - худшие промахи → их SHAP-подпись → паттерн ошибки → предложение коррекции
  - на правильных днях → какие фичи реально работали

Запуск: venv/Scripts/python.exe research/daily_engine/etap_202_self_critique.py
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
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    d = df.resample("1D", origin="epoch", label="left", closed="left").agg(agg).dropna(subset=["open"])
    rng = (d["high"] - d["low"]) / d["close"].shift(1)
    out = pd.DataFrame({"date": d.index, "asset": sym,
                        "open": d["open"], "high": d["high"], "low": d["low"], "close": d["close"],
                        "prev_close": d["close"].shift(1),
                        "range_frac": rng, "log_range": np.log(rng.clip(lower=1e-6)),
                        "big_day": (rng > rng.rolling(30).median()).astype(int),
                        "dir_up": (d["close"] > d["open"]).astype(int),
                        "dow": d.index.dayofweek})
    return out.dropna()


def main():
    from catboost import CatBoostRegressor, CatBoostClassifier, Pool
    from sklearn.metrics import roc_auc_score, r2_score

    feats = pd.read_csv(OUT / "etap198_dataset.csv", parse_dates=["date"])
    feats["date"] = pd.to_datetime(feats["date"], utc=True)
    act = pd.concat([actuals(s) for s in SYMBOLS]); act["date"] = pd.to_datetime(act["date"], utc=True)
    data = feats.merge(act[["date","asset","open","high","low","close","prev_close",
                            "range_frac","log_range","big_day","dir_up"]],
                       on=["date","asset"], how="inner", suffixes=("","_a")).sort_values("date").reset_index(drop=True)
    feat_cols = [c for c in feats.columns if c not in ("y","date")]
    cat_idx = [feat_cols.index("asset")]

    oos_start = pd.Timestamp(OOS_START, tz="UTC"); last = data["date"].max()
    rows = []
    for cut in pd.date_range(oos_start, last, freq=f"{STEP}D"):
        blk_end = cut + pd.Timedelta(days=STEP)
        tr = data[(data["date"] < cut - pd.Timedelta(days=EMB)) & (data["date"] >= cut - pd.Timedelta(days=WIN))]
        bl = data[(data["date"] >= cut) & (data["date"] < blk_end)]
        if len(tr) < 300 or len(bl) == 0: continue
        reg = CatBoostRegressor(iterations=400, depth=5, learning_rate=0.03, l2_leaf_reg=6,
                                loss_function="RMSE", random_seed=42, verbose=0)
        reg.fit(Pool(tr[feat_cols], tr["log_range"], cat_features=cat_idx), verbose=0)
        clf = CatBoostClassifier(iterations=350, depth=4, learning_rate=0.03, l2_leaf_reg=8,
                                 random_seed=42, verbose=0)
        clf.fit(Pool(tr[feat_cols], tr["big_day"], cat_features=cat_idx), verbose=0)
        pred_lr = reg.predict(bl[feat_cols])
        pred_big = clf.predict_proba(bl[feat_cols])[:, 1]
        shap = reg.get_feature_importance(Pool(bl[feat_cols], bl["log_range"], cat_features=cat_idx),
                                          type="ShapValues")
        b = bl.copy()
        b["pred_log_range"] = pred_lr
        b["pred_range_frac"] = np.exp(pred_lr)
        b["pred_big_p"] = pred_big
        # топ-фича вклада SHAP по модулю на каждый день
        sv = shap[:, :-1]
        top_idx = np.abs(sv).argmax(axis=1)
        b["top_feat"] = [feat_cols[i] for i in top_idx]
        b["top_feat_contrib"] = sv[np.arange(len(sv)), top_idx]
        rows.append(b)
    res = pd.concat(rows).sort_values("date").reset_index(drop=True)
    res["year"] = res["date"].dt.year

    # --- оценки ---
    res["range_err"] = res["pred_range_frac"] - res["range_frac"]        # +над-оценка / −недо
    res["abs_err"] = res["range_err"].abs()
    # границы: контейнмент = факт high/low внутри open ± 0.55*pred_range
    half = 0.55 * res["pred_range_frac"] * res["prev_close"]
    res["hi_b"] = res["open"] + half; res["lo_b"] = res["open"] - half
    res["contained"] = ((res["high"] <= res["hi_b"]) & (res["low"] >= res["lo_b"])).astype(int)
    res["regime_correct"] = ((res["pred_big_p"] >= 0.5).astype(int) == res["big_day"]).astype(int)

    print("="*70); print("SELF-CRITIQUE — дневной анализатор на OOS 2025-2026"); print("="*70)
    print(f"\nДней оценено: {len(res)} (пул BTC+ETH+SOL)")
    print("\n■ SCORECARD по годам:")
    for yr, g in res.groupby("year"):
        if len(g) < 20: continue
        print(f"  {yr}: range_R²={r2_score(g['log_range'],g['pred_log_range']):.3f} | "
              f"regime AUC={roc_auc_score(g['big_day'],g['pred_big_p']):.3f} | "
              f"границы удержали {g['contained'].mean():.0%} | "
              f"range bias {g['range_err'].mean()*100:+.2f}пп")

    # --- САМОКРИТИКА ---
    print("\n■ САМОКРИТИКА (почему ошибались / были правы):")
    sb = res["range_err"].mean()*100
    print(f"\n1) Систематический сдвиг диапазона: {sb:+.2f}пп "
          f"({'СИСТЕМАТИЧЕСКИ ЗАВЫШАЕМ' if sb>0.1 else ('СИСТЕМАТИЧЕСКИ ЗАНИЖАЕМ' if sb<-0.1 else 'почти без сдвига')}).")
    # по режиму
    for lbl_, sub in [("в БОЛЬШИЕ дни", res[res["big_day"]==1]), ("во ФЛЭТ-дни", res[res["big_day"]==0])]:
        print(f"   {lbl_}: сдвиг {sub['range_err'].mean()*100:+.2f}пп, MAE {sub['abs_err'].mean()*100:.2f}пп")
    # по дню недели
    dow_names = ["Пн","Вт","Ср","Чт","Пт","Сб","Вс"]
    print("   по дням недели (сдвиг диапазона):")
    for dw, g in res.groupby("dow"):
        print(f"     {dow_names[int(dw)]}: {g['range_err'].mean()*100:+.2f}пп (n={len(g)})")

    print("\n2) Худшие промахи (топ-8 по |ошибке|) — их SHAP-подпись:")
    worst = res.reindex(res["abs_err"].sort_values(ascending=False).index).head(8)
    for _, r in worst.iterrows():
        kind = "завысили" if r["range_err"]>0 else "ЗАНИЗИЛИ"
        print(f"   {r['date']:%Y-%m-%d} {r['asset']}: pred {r['pred_range_frac']*100:.1f}% vs факт {r['range_frac']*100:.1f}% "
              f"({kind}) | гл.драйвер: {r['top_feat']} ({r['top_feat_contrib']:+.2f})")

    print("\n3) Где модель ПРАВА (контейнмент=1) — какие фичи чаще всего ведущие:")
    ok = res[res["contained"]==1]
    vc = ok["top_feat"].value_counts().head(6)
    for name, cnt in vc.items():
        print(f"   {name:14} ведущая в {cnt} верных днях ({cnt/len(ok):.0%})")

    print("\n4) Паттерн ошибки → коррекция:")
    miss_big = res[(res["big_day"]==1) & (res["pred_big_p"]<0.5)]   # пропущенные большие дни
    if len(miss_big):
        print(f"   • Пропущено больших дней: {len(miss_big)} ({len(miss_big)/max(1,res['big_day'].sum()):.0%} от всех больших).")
        print(f"     На них чаще ведущая фича: {miss_big['top_feat'].value_counts().head(1).index[0]}.")
        print(f"     → КОРРЕКЦИЯ: эти дни = всплеск волатильности после низкого atr (vol-clustering ломается).")
        print(f"     Добавить breakout-risk фичу (сжатие диапазона / Bollinger squeeze) + расширять границы в low-vol кластерах.")
    if sb < -0.1:
        print(f"   • Занижаем диапазон на {abs(sb):.2f}пп → границы узкие, частые пробои. → расширить множитель границ.")
    elif sb > 0.1:
        print(f"   • Завышаем диапазон → границы широкие, mean-reversion трейды редко доходят. → сузить множитель.")

    res.to_csv(OUT / "etap202_self_critique.csv", index=False)
    print(f"\n[saved] {OUT/'etap202_self_critique.csv'}")


if __name__ == "__main__":
    main()
