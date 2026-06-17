"""etap_188: permutation null-test — реальный ли edge у кластеры→геометрия (etap_187)?

etap_187 дал per-class OOS +20.5R vs единая геометрия −19.4R (Δ+40). НО 5 кластеров ×
28 геометрий = 140 переборов → риск, что +40 это степени свободы, а не сигнал
(López de Prado §1.4.2 / false-strategy theorem). Честный тест:

  Перетасовать метки кластеров СЛУЧАЙНО M раз (сохраняя размеры), каждый раз выбрать
  per-class робастную геометрию на TRAIN и применить к TEST. Получить нулевое
  распределение per-class OOS ΣR. p = доля null ≥ реального.

Если реальный +20.5 глубоко в хвосте (p<0.05) — feature-кластеризация захватывает
что-то реальное. Если в массе null — это артефакт перебора, не edge.

Ускорение: предрасчёт net_R[cand, geometry] один раз → всё остальное = индексация.
Output: output/etap_188_null.csv
"""
from __future__ import annotations
import sys
import time
import warnings
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

from etap_186_cluster_per_class_geometry import collect, SYMBOLS
from etap_179_geometry_grid import sl_price, tp_price, simulate, SL_RULES, TP_RULES

OUT = _ROOT / 'research' / 'elements_study' / 'output'
GEO = [(s, t) for s in SL_RULES for t in TP_RULES]
K = 5
N_PERM = 400
RNG = np.random.RandomState(0)   # argless Date/random запрещены; seed фиксирован


def build_net_matrix(cands, store):
    """net[i, g] для всех сигналов × геометрий (nan если невалидно)."""
    net = np.full((len(cands), len(GEO)), np.nan)
    for i, cd in enumerate(cands):
        side = cd['side']; entry = cd['entry']; h1, l1, c1 = store[cd['symbol']]
        for gi, (slr, tpr) in enumerate(GEO):
            sl = sl_price(slr, side, entry, cd['struct'], cd['atr'])
            tp = tp_price(tpr, side, entry, sl, cd['breakout'], cd['height_pct'])
            r = simulate(side, entry, sl, tp, h1, l1, c1, cd['_start'], cd['_end'])
            if r is not None:
                net[i, gi] = r['net_R']
    return net


def robust_geo_idx(rows_idx, net, t_order, n_folds=4):
    """Индекс лучшей геометрии по CV-score (mean−std по фолдам) на train-подмножестве."""
    if len(rows_idx) < 40:
        return None
    ordered = rows_idx[np.argsort(t_order[rows_idx])]
    folds = np.array_split(ordered, n_folds)
    best_gi, best_score = None, -1e9
    for gi in range(len(GEO)):
        fmeans = []
        for f in folds:
            col = net[f, gi]; col = col[~np.isnan(col)]
            if len(col):
                fmeans.append(col.mean())
        if len(fmeans) < n_folds:
            continue
        score = np.mean(fmeans) - np.std(fmeans)
        if score > best_score:
            best_score = score; best_gi = gi
    return best_gi


def per_class_oos(labels, net, is_tr, t_order, global_gi):
    """Сумма OOS net_R при per-class робастной геометрии для данной разметки labels."""
    total = 0.0
    for cl in np.unique(labels):
        tr_rows = np.where((labels == cl) & is_tr)[0]
        te_rows = np.where((labels == cl) & ~is_tr)[0]
        gi = robust_geo_idx(tr_rows, net, t_order)
        if gi is None:
            gi = global_gi
        col = net[te_rows, gi]
        total += np.nansum(col)
    return total


def main():
    t0 = time.time()
    print("=" * 80)
    print(f"etap_188: permutation null-test кластеры→геометрия (M={N_PERM})")
    print("=" * 80)
    ud = pd.read_csv(_ROOT / 'data' / 'USDT_D_1d.csv', parse_dates=['datetime'])
    ud_ret = ud['close'].pct_change().fillna(0) * 100
    udby = {pd.Timestamp(d).normalize(): r for d, r in zip(ud['datetime'], ud_ret.values)}

    store = {}; cands = []
    for sym in SYMBOLS:
        cands.extend(collect(sym, udby, store))
    print(f"  сигналов: {len(cands)}  ·  предрасчёт net-матрицы {len(cands)}×{len(GEO)}...")
    net = build_net_matrix(cands, store)

    X = np.nan_to_num(np.array([cd['feat'] for cd in cands], dtype=float))
    is_tr = np.array([cd['period'] == 'train' for cd in cands])
    t_order = np.array([cd['time'].value for cd in cands])
    tr_idx = np.where(is_tr)[0]

    scaler = StandardScaler().fit(X[tr_idx])
    # fit PCA на train, transform всех
    pca = PCA(n_components=0.90, random_state=0).fit(scaler.transform(X)[tr_idx])
    Xp = pca.transform(scaler.transform(X))
    km = KMeans(n_clusters=K, n_init=10, random_state=0).fit(Xp[tr_idx])
    real_labels = km.predict(Xp)

    global_gi = robust_geo_idx(tr_idx, net, t_order)
    base_oos = np.nansum(net[~is_tr, global_gi])
    real_oos = per_class_oos(real_labels, net, is_tr, t_order, global_gi)
    print(f"\n  BASELINE единая геометрия {GEO[global_gi]}: OOS ΣR={base_oos:+.1f}")
    print(f"  РЕАЛЬНАЯ feature-кластеризация (K={K}): per-class OOS ΣR={real_oos:+.1f}  "
          f"(Δ над baseline {real_oos-base_oos:+.1f})")

    # null: случайные метки той же размерности
    sizes = np.bincount(real_labels, minlength=K)
    null = np.empty(N_PERM)
    for m in range(N_PERM):
        perm = RNG.permutation(len(cands))   # случайная переразбивка с теми же размерами
        lab = np.empty(len(cands), int); pos = 0
        for cl, sz in enumerate(sizes):
            lab[perm[pos:pos + sz]] = cl; pos += sz
        null[m] = per_class_oos(lab, net, is_tr, t_order, global_gi)

    p = (null >= real_oos).mean()
    print(f"\n  NULL (случайные кластеры, M={N_PERM}): "
          f"mean={null.mean():+.1f}  std={null.std():.1f}  "
          f"p95={np.percentile(null,95):+.1f}  max={null.max():+.1f}")
    print(f"  p-value (доля null ≥ реального {real_oos:+.1f}): {p:.3f}")
    z = (real_oos - null.mean()) / (null.std() + 1e-9)
    print(f"  z-score реального над null: {z:+.2f}")

    pd.DataFrame({'null_oos': null}).to_csv(OUT / 'etap_188_null.csv', index=False)
    print("\n" + "=" * 80)
    if p < 0.05:
        print(f"РЕАЛЬНО: p={p:.3f} < 0.05 — feature-кластеризация бьёт случайную группировку.")
        print("  Кластеры→геометрия захватывают настоящий тип сигнала. Можно строить дальше (entry).")
    elif p < 0.20:
        print(f"СЛАБО-ПОЛОЖИТЕЛЬНО: p={p:.3f} — намёк, но не значимо. Нужно больше данных / лучше фичи.")
    else:
        print(f"АРТЕФАКТ: p={p:.3f} — случайные кластеры дают то же. +40 был степенями свободы,")
        print("  не сигналом. Feature-кластеризация НЕ захватывает реальный тип. Не строить дальше.")
    print(f"Done in {time.time()-t0:.1f}s")


if __name__ == '__main__':
    main()
