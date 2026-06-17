"""etap_199 — Walk-forward («самообучаемый») тест направления дня.

Статичная модель (etap_198) дала OOS 0.507 — режим 2020-24 не переносится на 2025-26.
Честный тест «самообучаемости»: переобучаем CatBoost на СКОЛЬЗЯЩЕМ окне (rolling),
предсказываем следующий блок, катимся по 2025-2026. Адаптация к текущему режиму.

Сетка: rolling train-окно WIN дней, embargo EMB дней, retrain каждые STEP дней.
Пул BTC+ETH+SOL. Метрика: pooled OOS AUC + по годам + простая экспектация по порогу.

Запуск: venv/Scripts/python.exe research/daily_engine/etap_199_walkforward.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

OUT = Path(__file__).resolve().parent / "output"
WIN = 540        # скользящее окно train (≈1.5 года) — захват текущего режима
EMB = 3          # embargo (López de Prado)
STEP = 21        # переобучение раз в ~месяц
OOS_START = "2025-01-01"


def main():
    from catboost import CatBoostClassifier, Pool
    from sklearn.metrics import roc_auc_score

    data = pd.read_csv(OUT / "etap198_dataset.csv", parse_dates=["date"]).sort_values("date").reset_index(drop=True)
    feat_cols = [c for c in data.columns if c not in ("y", "date")]
    # asset категориальная
    cat_idx = [feat_cols.index("asset")] if "asset" in feat_cols else []

    def fit(tr):
        m = CatBoostClassifier(iterations=350, depth=4, learning_rate=0.03, l2_leaf_reg=8,
                               loss_function="Logloss", random_seed=42, verbose=0, task_type="CPU")
        m.fit(Pool(tr[feat_cols], tr["y"], cat_features=cat_idx), verbose=0)
        return m

    oos_start = pd.Timestamp(OOS_START, tz="UTC")
    last = data["date"].max()
    preds = []
    cuts = pd.date_range(oos_start, last, freq=f"{STEP}D")
    for cut in cuts:
        blk_end = cut + pd.Timedelta(days=STEP)
        train = data[(data["date"] < cut - pd.Timedelta(days=EMB)) &
                     (data["date"] >= cut - pd.Timedelta(days=WIN))]
        block = data[(data["date"] >= cut) & (data["date"] < blk_end)]
        if len(train) < 300 or len(block) == 0:
            continue
        m = fit(train)
        p = m.predict_proba(block[feat_cols])[:, 1]
        b = block[["date", "y"]].copy(); b["p"] = p
        preds.append(b)
    res = pd.concat(preds).sort_values("date")
    res["year"] = res["date"].dt.year

    auc = roc_auc_score(res["y"], res["p"])
    print(f"[walk-forward] WIN={WIN}d EMB={EMB} STEP={STEP} | n_pred={len(res)} "
          f"base up={res['y'].mean():.3f}")
    print(f"[WF OOS] pooled AUC = {auc:.4f}  (статика была 0.507)")
    for yr, g in res.groupby("year"):
        if len(g) > 20:
            print(f"   {yr}: AUC {roc_auc_score(g['y'], g['p']):.3f} (n={len(g)})")

    # простая экспектация: long-day если p>=thr, short-day если p<=1-thr; "выигрыш" = угадали знак дня
    print("\n[порог: точность угадывания направления дня среди уверенных]")
    for thr in (0.50, 0.53, 0.55, 0.58):
        conf = res[(res["p"] >= thr) | (res["p"] <= 1 - thr)].copy()
        if len(conf) < 30:
            print(f"   thr={thr}: мало сделок ({len(conf)})"); continue
        conf["call"] = (conf["p"] >= 0.5).astype(int)
        acc = (conf["call"] == conf["y"]).mean()
        cov = len(conf) / len(res)
        print(f"   thr={thr}: точность {acc:.3f}  (охват {cov:.0%}, n={len(conf)})")

    res.to_csv(OUT / "etap199_walkforward_preds.csv", index=False)
    print(f"\n[saved] {OUT/'etap199_walkforward_preds.csv'}")
    print("\nВЕРДИКТ WF:")
    if auc > 0.55:
        print(f"  AUC {auc:.3f} > 0.55 → самообучение СПАСАЕТ направление, строим продукт с lean.")
    elif auc > 0.52:
        print(f"  AUC {auc:.3f} — слабый, но не ноль. Направление = очень осторожный lean, не основа.")
    else:
        print(f"  AUC {auc:.3f} ≈ монетка. Направление дня НЕ предсказуемо даже walk-forward.")
        print("  Продукт строим на робастном: границы (волатильность) + зоны (VP/ICT/VIC).")


if __name__ == "__main__":
    main()
