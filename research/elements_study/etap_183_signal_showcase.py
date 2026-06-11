"""etap_183: Витрина всех сигналов — оценка нейросети 1-5 + реальный исход (честная OOS).

Пользователь: «возьми каждый сигнал каждой стратегии и фрактала, сделай как будто
нейронка его прислала, скажи хороший он или плохой + её оценку 1-5».

Каждый сигнал (все стратегии 1.1.x + фракталы Андрея, 3 актива, 2017+) получает
ЧЕСТНУЮ out-of-fold оценку нейросети (модель, которая его НЕ видела на обучении —
через Purged K-Fold OOF). Рядом — РЕАЛЬНЫЙ исход (хороший/плохой по факту TP/SL).

ВЫХОД: CSV etap183_signal_showcase.csv с колонками:
  время, стратегия, актив, направление, entry, sl, tp(2.2R), risk%,
  NN_оценка (1-5 предсказанная), NN_вердикт (хороший/плохой/средний),
  реальный_grade (1-5 по факту), реальный_исход (хороший/плохой),
  достигнутый_R, совпало (✓/✗).

Модель: etap_182 (лучшая, техники книг). OOF = честно (out-of-sample).

Запуск: OMP_NUM_THREADS=1 .venv-pivot/bin/python -u research/elements_study/etap_183_signal_showcase.py
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    if _ROOT.parent == _ROOT:
        raise RuntimeError("repo root not found")
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

import importlib.util as _ilu
import numpy as np
import pandas as pd

_s182 = _ilu.spec_from_file_location("e182", _ROOT / "research/elements_study/etap_182_book_techniques_2017.py")
_e182 = _ilu.module_from_spec(_s182); _s182.loader.exec_module(_e182)
_e180 = _e182._e180; _e179 = _e182._e179; _e178 = _e182._e178; _e177 = _e182._e177

OUT_DIR = _e179.OUT_DIR
SNAME = {0: "1.1.1", 1: "1.1.2", 2: "1.1.3", 3: "FRACTAL", 4: "1.1.4"}
TARGET_RR = 2.2

GRADE_VERDICT = {1: "плохой ⛔", 2: "слабый ⚠️", 3: "средний 🟡", 4: "хороший ✅", 5: "идеал 🔥"}


def main():
    import torch
    from sklearn.preprocessing import StandardScaler
    from scipy.stats import spearmanr
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    print(f"[etap_183] витрина сигналов: честная OOS-оценка нейросети + реальный исход", flush=True)

    ds = _e182.build_dataset_2017()       # переиспуем готовый датасет 2017+
    ds_f, why = _e180.add_knowledge_features(ds)
    base = [c for c in _e177.make_feature_list(list(_e177.BULK_ALL.keys())) if c in ds_f.columns] \
           + ["sig_strategy_id", "sig_direction_long", "sig_risk_pct", "sig_asset_id"]
    feats = list(dict.fromkeys([f for f in base + why if f in ds_f.columns]))
    ds_f = ds_f[ds_f[feats].notna().all(axis=1)].copy()
    print(f"[data] {len(ds_f)} сигналов (2017+), фич={len(feats)}", flush=True)

    g = ds_f["grade"].values.astype(float)
    uw = _e177.uniqueness_weights(ds_f.index, 7)
    w = _e180.balanced_weights(g, uw)
    X = ds_f[feats].values

    # === ЧЕСТНАЯ OOF-оценка: каждый сигнал оценивает модель, не видевшая его ===
    print("[OOF] обучаю Purged K-Fold, оцениваю каждый сигнал out-of-fold...", flush=True)
    oof_score = np.full(len(ds_f), np.nan)
    n = len(ds_f)
    for fi, (tri, vai) in enumerate(_e177.purged_splits(ds_f.index, _e182.KFOLD, _e182.EMBARGO_KF, 7)):
        sc = StandardScaler().fit(X[tri])
        net, vr = _e182.train_book(sc.transform(X[tri]), g[tri], w[tri],
                                   sc.transform(X[vai]), g[vai], len(feats), device)
        oof_score[vai] = _e178.ordinal_predict_score(net, sc.transform(X[vai]), device)
        print(f"    fold {fi}: оценено {len(vai)} сигналов (val ρ={vr:.3f})", flush=True)
    # сигналы вне всех val (если есть) — оценим финальной моделью на всём
    miss = np.isnan(oof_score)
    if miss.sum() > 0:
        sc = StandardScaler().fit(X[~miss])
        net, _ = _e182.train_book(sc.transform(X[~miss]), g[~miss], w[~miss],
                                  sc.transform(X[~miss][:100]), g[~miss][:100], len(feats), device)
        oof_score[miss] = _e178.ordinal_predict_score(net, sc.transform(X[miss]), device)
    print(f"[OOF] готово, оценено {(~np.isnan(oof_score)).sum()}/{n}", flush=True)

    # === собираем витрину ===
    nn_grade = np.clip(np.round(oof_score), 1, 5).astype(int)
    real_grade = ds_f["grade"].astype(int).values
    achieved_r = ds_f["achieved_r"].values
    direction = np.where(ds_f["sig_direction_long"].values == 1, "LONG", "SHORT")
    risk_pct = ds_f["sig_risk_pct"].values
    asset = [_e179.SYMBOLS[int(a)] for a in ds_f["sig_asset_id"].values]
    strat = [SNAME.get(int(s), str(s)) for s in ds_f["sig_strategy_id"].values]

    show = pd.DataFrame({
        "время": ds_f.index.strftime("%Y-%m-%d %H:%M"),
        "стратегия": strat,
        "актив": asset,
        "направление": direction,
        "entry": ds_f["entry"].round(2).values if "entry" in ds_f else np.nan,
        "sl": ds_f["sl"].round(2).values if "sl" in ds_f else np.nan,
        "risk_%": risk_pct.round(2),
        "NN_score": oof_score.round(2),
        "NN_оценка": nn_grade,
        "NN_вердикт": [GRADE_VERDICT[int(x)] for x in nn_grade],
        "реальный_grade": real_grade,
        "реальный_исход": np.where(real_grade >= 4, "хороший ✅", np.where(real_grade <= 2, "плохой ⛔", "средний 🟡")),
        "достигнутый_R": achieved_r.round(2),
        "NN_сказал_хороший": nn_grade >= 4,
        "реально_хороший": real_grade >= 4,
        "совпало": np.where((nn_grade >= 4) == (real_grade >= 4), "✓", "✗"),
    })
    show = show.sort_values("время")
    out_csv = OUT_DIR / "etap183_signal_showcase.csv"
    show.to_csv(out_csv, index=False)
    print(f"\n[saved] витрина всех {len(show)} сигналов → {out_csv}", flush=True)

    # === статистика точности нейросети по оценкам ===
    print("\n========== ТОЧНОСТЬ НЕЙРОСЕТИ ПО ОЦЕНКАМ (честная OOS) ==========", flush=True)
    print(f"{'NN оценка':<12}{'кол-во':<10}{'реально хороших':<18}{'средний real R':<15}", flush=True)
    for ng in [1, 2, 3, 4, 5]:
        sub = show[show["NN_оценка"] == ng]
        if len(sub) > 0:
            real_good = sub["реально_хороший"].mean() * 100
            mr = sub["достигнутый_R"].mean()
            print(f"  {ng}/5{'':<8}{len(sub):<10}{real_good:.0f}%{'':<14}{mr:.2f}", flush=True)

    # когда NN говорит "хороший" (4-5) — насколько права?
    nn_good = show[show["NN_сказал_хороший"]]
    if len(nn_good) > 0:
        prec = nn_good["реально_хороший"].mean() * 100
        base = show["реально_хороший"].mean() * 100
        print(f"\n  NN сказал ХОРОШИЙ (4-5): {len(nn_good)} сигналов, "
              f"реально хороших {prec:.0f}% (baseline {base:.0f}%, lift ×{prec/base:.2f})", flush=True)
        print(f"  средний R этих сигналов: {nn_good['достигнутый_R'].mean():.2f}", flush=True)
    rho = spearmanr(real_grade, oof_score).correlation
    print(f"\n  Spearman ρ (NN_score vs реальный grade): {rho:.4f}", flush=True)

    # разбивка по стратегиям: где NN точнее
    print("\n========== ТОЧНОСТЬ NN ПО СТРАТЕГИЯМ ==========", flush=True)
    for s in sorted(set(strat)):
        sub = show[show["стратегия"] == s]
        ng = sub[sub["NN_сказал_хороший"]]
        if len(ng) >= 5:
            prec = ng["реально_хороший"].mean() * 100
            b = sub["реально_хороший"].mean() * 100
            print(f"  {s:<10} NN-хороших={len(ng):<5} точность {prec:.0f}% (база {b:.0f}%)", flush=True)

    # примеры (первые 10 + последние 10)
    print("\n========== ПРИМЕРЫ (10 свежайших) ==========", flush=True)
    cols = ["время", "стратегия", "актив", "направление", "NN_оценка", "NN_вердикт", "реальный_исход", "достигнутый_R", "совпало"]
    print(show[cols].tail(10).to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
