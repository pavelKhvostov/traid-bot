"""le_validate_null — density-matched / confound-controlled null для силы уровня.

Критик #11: наивный null (случайные равномерные полосы или shuffle-y) НЕ годится — он
под-оценивает нуль и выдаёт ложное p<0.05, т.к. не контролирует конфаунд
близость×волатильность (зоны и сила скапливаются там, где цена дольше была).

Тесты:
  1. Наивный shuffle-y null -> p  (ЛОВУШКА: покажет 'значимо', но это конфаунд).
  2. Стратиф. shuffle силы ВНУТРИ бинов [dist × atr] -> p  (правильный null: бьёт ли
     сила базу СВЕРХ близости/волатильности). Real AUC внутри этого нуля = edcha нет.
  3. Инкремент: AUC[y~dist+atr] vs AUC[y~dist+atr+strength] (логит). Не растёт -> нет edge.
  4. Регрессия strength_raw ~ [dist,atr,sumw] -> R² (высокий -> сила = тот самый конфаунд).

Запуск: set PYTHONIOENCODING=utf-8
        venv/Scripts/python.exe research/level_engine/le_validate_null.py BTCUSDT
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import le_validate as V
from sklearn.metrics import roc_auc_score
from sklearn.linear_model import LogisticRegression, LinearRegression

RNG = np.random.default_rng(42)
N = 2000


def main():
    sym = sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT"
    fp = Path(__file__).resolve().parent / f"_val_{sym}.csv"
    if fp.exists():
        df = pd.read_csv(fp)
    else:
        df = V.collect_tests(sym)
    df = df.dropna(subset=["raw", "dist_rel", "atr_rel", "y"])
    y = df["y"].values.astype(int); raw = df["raw"].values
    real = roc_auc_score(y, raw)
    print(f"\n{sym}: тестов {len(df)}, base hold {y.mean():.1%}, REAL AUC(strength)={real:.3f}")

    # 1) наивный shuffle-y
    naive = np.array([roc_auc_score(RNG.permutation(y), raw) for _ in range(N)])
    p1 = (naive >= real).mean()
    print(f"\n[1] Наивный shuffle-y null: mean {naive.mean():.3f}, 95%до {np.quantile(naive,0.95):.3f} "
          f"-> p={p1:.3f}  ({'<<ЛОВУШКА: значимо, но конфаунд не учтён' if p1<0.05 else 'нез.'})")

    # 2) стратиф. shuffle силы внутри [dist x atr] квартилей
    dq = pd.qcut(df["dist_rel"].rank(method="first"), 4, labels=False)
    aq = pd.qcut(df["atr_rel"].rank(method="first"), 4, labels=False)
    strata = (dq.values * 4 + aq.values)
    null_strat = []
    for _ in range(N):
        sh = raw.copy()
        for s in np.unique(strata):
            idx = np.where(strata == s)[0]
            sh[idx] = RNG.permutation(raw[idx])
        null_strat.append(roc_auc_score(y, sh))
    null_strat = np.array(null_strat)
    p2 = (null_strat >= real).mean()
    print(f"[2] Стратиф-shuffle (внутри dist×atr) null: mean {null_strat.mean():.3f}, "
          f"95%до {np.quantile(null_strat,0.95):.3f} -> p={p2:.3f}  "
          f"({'нет edge сверх близости/vol' if p2>=0.05 else 'есть инкремент'})")

    # 3) инкремент логит: dist+atr vs dist+atr+strength (in-sample AUC = верхняя оценка)
    X0 = df[["dist_rel", "atr_rel"]].values
    X1 = df[["dist_rel", "atr_rel", "raw"]].values
    a0 = roc_auc_score(y, LogisticRegression(max_iter=500).fit(X0, y).predict_proba(X0)[:, 1])
    a1 = roc_auc_score(y, LogisticRegression(max_iter=500).fit(X1, y).predict_proba(X1)[:, 1])
    print(f"[3] AUC[y~dist+atr]={a0:.3f}  vs  AUC[+strength]={a1:.3f}  Δ={a1-a0:+.3f}  "
          f"({'сила НЕ добавляет' if a1-a0<0.005 else 'добавляет '+str(round(a1-a0,3))})")

    # 4) регрессия strength ~ конфаунды
    Xc = df[["dist_rel", "atr_rel", "sumw"]].values
    r2 = LinearRegression().fit(Xc, raw).score(Xc, raw)
    print(f"[4] R²(strength_raw ~ dist+atr+sumw) = {r2:.3f}  "
          f"({'сила = переупакованный конфаунд' if r2>0.6 else 'частично объяснимо'})")

    print(f"\nВЕРДИКТ: " + ("предиктив УБИТ — сила не бьёт конфаунд близость/волатильность "
          "(стратиф-null p>=0.05 и/или инкремент~0); + год-нестаб." if (p2 >= 0.05 or a1 - a0 < 0.005)
          else "есть остаточный инкремент — смотреть год-стабильность отдельно"))


if __name__ == "__main__":
    main()
