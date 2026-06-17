"""etap_187: сильная версия кластеры→геометрия — чёткие классы + робастный выбор.

etap_186 показал: per-class геометрия бьёт единую на OOS (Δ+9.8R), НО (а) кластеры
размыты (silhouette 0.18), (б) per-class геометрия выбиралась по сырому max train ΣR
→ переобучение (cluster 3 +44 train → −1 test), (в) прирост весь в 2025.

Чиним два рычага:
  1. ЧЁТКИЕ КЛАССЫ: StandardScaler → PCA-денойз (90% var, López §2 spirit) →
     KMeans И GaussianMixture, K по silhouette на TRAIN. Берём лучший по silhouette.
  2. РОБАСТНЫЙ per-class выбор геометрии: НЕ max train ΣR, а CV-внутри-train —
     time-contiguous 4 фолда, score = mean(fold R/tr) − std (штраф за нестабильность).
     Это убирает train-overfit геометрии.

Сравнение OOS: per-class робастная геометрия vs ЕДИНАЯ робастная глобальная (тот же
метод выбора) — честно, обе train-only. Per-year стабильность.

Вход = breakout (entry-варьирование = etap_188, когда классы чёткие).
Output: output/etap_187_clusters.csv
"""
from __future__ import annotations
import sys
import time
import warnings
from collections import Counter
from pathlib import Path

_ROOT = Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
warnings.filterwarnings('ignore')
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
from sklearn.cluster import KMeans
from sklearn.mixture import GaussianMixture
from sklearn.metrics import silhouette_score

from etap_186_cluster_per_class_geometry import collect, net_for_geometry, SYMBOLS
from etap_179_geometry_grid import SL_RULES, TP_RULES

OUT = _ROOT / 'research' / 'elements_study' / 'output'
_ROOT_DATA = _ROOT / 'data'


def robust_geometry(cands, store, n_folds=4):
    """Лучшая (sl,tp) по time-CV: score = mean(fold R/tr) − std(fold R/tr).

    Штраф за нестабильность между фолдами → не переобучается в один режим.
    """
    if len(cands) < 40:
        return None, None
    cs = sorted(cands, key=lambda x: x['time'])
    folds = np.array_split(np.arange(len(cs)), n_folds)
    best = None; best_score = -1e9
    for slr in SL_RULES:
        for tpr in TP_RULES:
            fold_means = []
            for f in folds:
                vals = [net_for_geometry(cs[j], slr, tpr, store) for j in f]
                vals = [v for v in vals if v is not None]
                if vals:
                    fold_means.append(np.mean(vals))
            if len(fold_means) < n_folds:
                continue
            score = np.mean(fold_means) - np.std(fold_means)
            if score > best_score:
                best_score = score; best = (slr, tpr)
    return best, best_score


def sum_net(cands, geom, store):
    return sum(v for cd in cands if (v := net_for_geometry(cd, geom[0], geom[1], store)) is not None)


def main():
    t0 = time.time()
    print("=" * 84)
    print("etap_187: чёткие классы (PCA+GMM/KMeans) + робастная per-class геометрия (CV)")
    print("=" * 84)
    ud = pd.read_csv(_ROOT_DATA / 'USDT_D_1d.csv', parse_dates=['datetime'])
    ud_ret = ud['close'].pct_change().fillna(0) * 100
    udby = {pd.Timestamp(d).normalize(): r for d, r in zip(ud['datetime'], ud_ret.values)}

    store = {}; cands = []
    for sym in SYMBOLS:
        r = collect(sym, udby, store)
        cands.extend(r)
    print(f"  сигналов всего: {len(cands)}")

    X = np.nan_to_num(np.array([cd['feat'] for cd in cands], dtype=float))
    is_tr = np.array([cd['period'] == 'train' for cd in cands])
    tr_idx = np.where(is_tr)[0]; te_idx = np.where(~is_tr)[0]

    # 1) денойз: scaler + PCA(90% var) на TRAIN
    scaler = StandardScaler().fit(X[tr_idx])
    Xs = scaler.transform(X)
    pca = PCA(n_components=0.90, random_state=0).fit(Xs[tr_idx])
    Xp = pca.transform(Xs)
    print(f"\n1) денойз: {X.shape[1]} фич → {Xp.shape[1]} PCA-компонент (90% var)")

    # 2) выбор алгоритма+K по silhouette на TRAIN
    print("2) кластеризация (silhouette на TRAIN PCA-пространстве):")
    best = None  # (sil, name, K, labels_all)
    for name in ['kmeans', 'gmm']:
        for K in [3, 4, 5, 6, 8]:
            if name == 'kmeans':
                mdl = KMeans(n_clusters=K, n_init=10, random_state=0).fit(Xp[tr_idx])
                lab_tr = mdl.labels_
            else:
                mdl = GaussianMixture(n_components=K, covariance_type='full', n_init=3,
                                      random_state=0).fit(Xp[tr_idx])
                lab_tr = mdl.predict(Xp[tr_idx])
            if len(np.unique(lab_tr)) < 2:
                continue
            sil = silhouette_score(Xp[tr_idx], lab_tr)
            print(f"   {name:>7} K={K}: silhouette={sil:.3f}")
            if best is None or sil > best[0]:
                lab_all = mdl.predict(Xp)
                best = (sil, name, K, lab_all)
    sil, name, K, lab_all = best
    print(f"   → выбран {name} K={K} (silhouette {sil:.3f}; было KMeans 0.18 в etap_186)")
    for cd, lb in zip(cands, lab_all):
        cd['cluster'] = int(lb)

    tr_c = [cands[i] for i in tr_idx]; te_c = [cands[i] for i in te_idx]

    # baseline: ЕДИНАЯ робастная геометрия (тот же CV-метод на всём train)
    g_glob, _ = robust_geometry(tr_c, store)
    glob_test = sum_net(te_c, g_glob, store)
    print(f"\n3) BASELINE робастная единая геометрия (train-CV) = {g_glob}:  OOS ΣR={glob_test:+.1f}")

    print(f"\n4) PER-CLASS робастная геометрия → OOS:")
    print(f"   {'cl':>3} {'n_tr':>5}{'n_te':>5}  {'geom':>16}  {'teΣR':>7}  {'te_base':>7}  top-patterns")
    geom_by_cluster = {}; rows_out = []
    for cl in range(K):
        ctr = [cd for cd in tr_c if cd['cluster'] == cl]
        cte = [cd for cd in te_c if cd['cluster'] == cl]
        g, _ = robust_geometry(ctr, store)
        if g is None:
            g = g_glob
        geom_by_cluster[cl] = g
        te_sum = sum_net(cte, g, store); te_base = sum_net(cte, g_glob, store)
        toppat = ', '.join(f"{p}:{n}" for p, n in Counter(cd['pattern'] for cd in ctr).most_common(3))
        print(f"   {cl:>3} {len(ctr):>5}{len(cte):>5}  {g[0]+'×'+g[1]:>16}  {te_sum:>+7.1f}  {te_base:>+7.1f}  {toppat}")
        rows_out.append({'cluster': cl, 'n_tr': len(ctr), 'n_te': len(cte), 'geom': f"{g[0]}x{g[1]}",
                         'te_sumR': round(te_sum, 1), 'te_base_sumR': round(te_base, 1), 'top_patterns': toppat})
    pd.DataFrame(rows_out).to_csv(OUT / 'etap_187_clusters.csv', index=False)

    per_class_test = sum(sum_net([cd for cd in te_c if cd['cluster'] == cl], geom_by_cluster[cl], store)
                         for cl in range(K))
    print(f"\n   PER-CLASS OOS ΣR={per_class_test:+.1f}  vs  BASELINE {glob_test:+.1f}  Δ={per_class_test-glob_test:+.1f}")

    # per-year
    print("\n5) PER-YEAR (OOS): per-class vs baseline:")
    yr_pc = {}; yr_bs = {}
    for cd in te_c:
        g = geom_by_cluster[cd['cluster']]
        vpc = net_for_geometry(cd, g[0], g[1], store); vbs = net_for_geometry(cd, g_glob[0], g_glob[1], store)
        y = cd['time'].year
        if vpc is not None: yr_pc[y] = yr_pc.get(y, 0.0) + vpc
        if vbs is not None: yr_bs[y] = yr_bs.get(y, 0.0) + vbs
    for y in sorted(yr_pc):
        print(f"   {y}: per-class {yr_pc[y]:+6.1f}  baseline {yr_bs.get(y,0):+6.1f}  Δ={yr_pc[y]-yr_bs.get(y,0):+6.1f}")
    bad_pc = sum(1 for v in yr_pc.values() if v < 0)

    print("\n" + "=" * 84)
    diff = per_class_test - glob_test
    if diff > 0.1 * max(abs(glob_test), 10) and bad_pc <= 1 and per_class_test > 0:
        print(f"ПРОГРЕСС: per-class бьёт единую (Δ={diff:+.1f}), OOS положителен ({per_class_test:+.1f}), "
              f"bad years {bad_pc}. Идея кластеры→геометрия работает; след. шаг — per-class ВХОД (etap_188).")
    elif diff > 0:
        print(f"ЧАСТИЧНО: per-class > baseline (Δ={diff:+.1f}), но OOS {per_class_test:+.1f} / bad years {bad_pc}.")
        print("  Кластеризация помогает направленно, но пул Bulkowski сам по себе ~нулевой EV —")
        print("  потолок ограничен источником сигналов (ср. etap_179: геометрия = бета режима).")
    else:
        print(f"НЕТ: робастная per-class геометрия не бьёт единую на OOS (Δ={diff:+.1f}).")
        print("  Даже с чёткими классами и CV-выбором перенос не держится — геометрия режимо-зависима.")
    print(f"Done in {time.time()-t0:.1f}s")


if __name__ == '__main__':
    main()
