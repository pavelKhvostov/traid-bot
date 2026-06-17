"""etap_184: изучение КАЖДОГО Bulkowski-паттерна В ОТДЕЛЬНОСТИ (good vs bad).

Постановка пользователя: разделить сигналы на удачные/неудачные, изучить их в
ОТДЕЛЬНОСТИ, обучить искать закономерности, отсеять плохие. Прошлые этапы (178-181)
МЕШАЛИ все паттерны в один пул — это размывает паттерн-специфичную сигнатуру.
Здесь изучаем каждый паттерн отдельно.

Лейбл = условие пользователя (etap_178): good(1) = цена прошла +5% в сторону сигнала
РАНЬШЕ, чем сняла структурный low(long)/high(short) паттерна; busted(0) = сняла раньше.
Данные = output/etap_178_labeled.csv (BTC+ETH+SOL, 12h, фичи на момент сигнала).
Сплит: train < 2024-01, test ≥ 2024-01.

Для каждого паттерна:
  1. n train/test, base good% (планка).
  2. UNIVARIATE-сепараторы: для каждой фичи single-feature AUC на TRAIN, и держится ли
     он на TEST. Сепаратор реален, если |AUC-0.5| заметен И TRAIN↔TEST согласованы по
     направлению. Для топ-сепаратора — концретный сплит good% выше/ниже порога на TEST.
  3. MULTIVARIATE: HGB purged-CV + OOS AUC (где n позволяет).
  Вердикт: разделяется ли good/bad у этого паттерна на честном OOS.

Output: output/etap_184_per_pattern.csv
"""
from __future__ import annotations
import sys
import warnings
from pathlib import Path

_ROOT = Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent

import numpy as np
import pandas as pd
warnings.filterwarnings('ignore')
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score

OUT = _ROOT / 'research' / 'elements_study' / 'output'
TRAIN_END = pd.Timestamp("2024-01-01", tz="UTC")
HORIZON_D = 30
EMBARGO_D = 3
MIN_CLASS = 8           # минимум на класс для univariate AUC

LEAK = {'symbol', 'time', 'entry', 'pattern', 'pattern_id', 'sym_id', 'period',
        'success', 'outcome', 'gross_R', 'net_R', 'risk_pct', 'bars_held_1h'}


def uni_auc(y, x):
    """Single-feature AUC (с авто-направлением). Возвращает (auc_oriented, sign)."""
    if len(np.unique(y)) < 2 or np.nanstd(x) == 0:
        return 0.5, +1
    a = roc_auc_score(y, x)
    return (a, +1) if a >= 0.5 else (1 - a, -1)


def purged_cv_auc(X, y, t_days, n_splits=4):
    order = np.argsort(t_days)
    folds = np.array_split(order, n_splits)
    aucs = []
    for f in folds:
        lo, hi = t_days[f].min(), t_days[f].max()
        keep = np.ones(len(y), bool); keep[f] = False
        keep &= ~((t_days + HORIZON_D >= lo - EMBARGO_D) & (t_days <= hi + EMBARGO_D))
        if keep.sum() < 40 or y[f].sum() < 3 or (1 - y[f]).sum() < 3 or len(np.unique(y[keep])) < 2:
            continue
        m = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05,
            max_leaf_nodes=15, min_samples_leaf=15, l2_regularization=1.0, random_state=0).fit(X[keep], y[keep])
        aucs.append(roc_auc_score(y[f], m.predict_proba(X[f])[:, 1]))
    return (np.mean(aucs), len(aucs)) if aucs else (np.nan, 0)


def main():
    df = pd.read_csv(OUT / 'etap_178_labeled.csv')
    df['time'] = pd.to_datetime(df['time'], utc=True)
    df = df.sort_values('time').reset_index(drop=True)
    df['t_days'] = (df['time'] - df['time'].min()).dt.total_seconds() / 86400.0
    feat_cols = [c for c in df.columns if c not in LEAK and c != 't_days' and df[c].dtype != object]
    df[feat_cols] = df[feat_cols].fillna(0)

    print("=" * 90)
    print("etap_184: каждый Bulkowski-паттерн В ОТДЕЛЬНОСТИ · good=+5%>стоп · 4y train / 2y OOS")
    print("=" * 90)

    rows = []
    patterns = sorted(df['pattern'].unique(), key=lambda p: -len(df[df.pattern == p]))
    for pat in patterns:
        d = df[df.pattern == pat]
        tr = d[d.period == 'train']; te = d[d.period == 'test']
        if len(tr) < 30 or len(te) < 20:
            print(f"\n### {pat:<13} n(tr/te)={len(tr)}/{len(te)} — мало данных, пропуск")
            continue
        base_tr = tr['success'].mean() * 100; base_te = te['success'].mean() * 100
        print(f"\n### {pat:<13} n(tr/te)={len(tr)}/{len(te)}  good% tr={base_tr:.0f} te={base_te:.0f}")

        # univariate сепараторы: AUC на train, направление, и тот же AUC на test
        uni = []
        ytr = tr['success'].values; yte = te['success'].values
        for c in feat_cols:
            if min(ytr.sum(), (1 - ytr).sum()) < MIN_CLASS:
                break
            a_tr, sgn = uni_auc(ytr, tr[c].values)
            a_te = roc_auc_score(yte, sgn * te[c].values) if len(np.unique(yte)) == 2 and np.nanstd(te[c].values) > 0 else np.nan
            uni.append((c, a_tr, a_te, sgn))
        uni.sort(key=lambda x: -x[1])
        print("  univariate top-4 (single-feature AUC train → test, sign=+ значит выше→good):")
        best_hold = None
        for c, a_tr, a_te, sgn in uni[:4]:
            hold = "✓" if (not np.isnan(a_te) and a_tr > 0.60 and a_te > 0.56) else " "
            if hold == "✓" and best_hold is None:
                best_hold = (c, sgn, a_tr, a_te)
            print(f"    {hold} {c:>20}  tr={a_tr:.3f}  te={a_te:.3f}  sign={'+' if sgn>0 else '-'}")

        # конкретный сплит по топ-удержавшемуся сепаратору (на TEST)
        split_note = ""
        if best_hold:
            c, sgn, _, _ = best_hold
            thr = tr[c].median()
            hi_mask = (te[c] >= thr) if sgn > 0 else (te[c] < thr)
            hi = te[hi_mask]; lo = te[~hi_mask]
            if len(hi) >= 8 and len(lo) >= 8:
                split_note = (f"{c}{'≥' if sgn>0 else '<'}{thr:.3g}: good% {hi['success'].mean()*100:.0f} "
                              f"(n={len(hi)}) vs {lo['success'].mean()*100:.0f} (n={len(lo)})")
                print(f"  → OOS split: {split_note}")

        # multivariate HGB purged-CV + OOS
        cv_auc, k = purged_cv_auc(tr[feat_cols].values, ytr, tr['t_days'].values)
        oos_auc = np.nan
        if len(np.unique(ytr)) == 2 and len(np.unique(yte)) == 2:
            m = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05,
                max_leaf_nodes=15, min_samples_leaf=15, l2_regularization=1.0, random_state=0).fit(tr[feat_cols].values, ytr)
            oos_auc = roc_auc_score(yte, m.predict_proba(te[feat_cols].values)[:, 1])
        print(f"  multivariate HGB: purgedCV={cv_auc:.3f} (folds {k})  OOS={oos_auc:.3f}")

        sep = "ДА" if (best_hold is not None or (not np.isnan(oos_auc) and not np.isnan(cv_auc)
                                                  and oos_auc > 0.58 and cv_auc > 0.56)) else "нет"
        print(f"  ВЕРДИКТ разделяется good/bad OOS: {sep}")
        rows.append({'pattern': pat, 'n_train': len(tr), 'n_test': len(te),
                     'good_tr': round(base_tr, 1), 'good_te': round(base_te, 1),
                     'top_uni': uni[0][0] if uni else '', 'uni_tr': round(uni[0][1], 3) if uni else np.nan,
                     'uni_te': round(uni[0][2], 3) if uni and not np.isnan(uni[0][2]) else np.nan,
                     'mv_purgedCV': round(cv_auc, 3) if not np.isnan(cv_auc) else np.nan,
                     'mv_OOS': round(oos_auc, 3) if not np.isnan(oos_auc) else np.nan,
                     'separable': sep, 'oos_split': split_note})

    res = pd.DataFrame(rows)
    res.to_csv(OUT / 'etap_184_per_pattern.csv', index=False)
    print("\n" + "=" * 90)
    print("СВОДКА (паттерны, у которых good/bad разделяется на OOS):")
    sep = res[res.separable == 'ДА']
    if len(sep) == 0:
        print("  НЕТ ни одного паттерна с устойчивым OOS-разделением.")
        print("  Вывод: busted vs чистый разворот у Bulkowski-паттернов не предсказуем")
        print("  из пред-входного контекста — ни в пуле, ни по отдельности.")
    else:
        for _, r in sep.iterrows():
            print(f"  {r['pattern']:>13}: uni {r['top_uni']} tr={r['uni_tr']} te={r['uni_te']}  "
                  f"mvOOS={r['mv_OOS']}  | {r['oos_split']}")
    print(f"\nSaved: {OUT/'etap_184_per_pattern.csv'}")


if __name__ == '__main__':
    main()
