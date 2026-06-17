"""zone_reactor.diagnostic — это СИЛА ЗОНЫ или просто волатильность?

baseline дал OOS AUC 0.64, но atr_pct доминирует в importance (0.104), а zone_strength
0.005. Подозрение: 0.64 = «хватит ли волатильности на 5%», не multi-TF сила зоны.
Проверяем: AUC по группам фич + per-asset (убирает кросс-актив разницу волатильности).
"""
from __future__ import annotations
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score

OUT = _ROOT / 'research' / 'zone_reactor'
TRAIN_END = pd.Timestamp("2024-01-01", tz="UTC")

VOL = ['atr_pct', 'vol_z', 'bb_pctb']
ZONE = ['zone_conf_count', 'zone_strength', 'in_htf_zone', 'nearest_zone_dist',
        'n_tf_aligned', 'untouched_frac', 'n_untouched_htf']
ICT = ['liq_swept', 'liq_reclaim', 'sweep_mag_pct', 'pos_in_range']
TREND = ['rsi14', 'ema200_dist', 'hull_dir', 'htf_1d_dir', 'htf_3d_dir']
ALL = VOL + ZONE + ICT + TREND + ['side_long']


def fit_auc(df, cols, is_tr):
    Xtr = df.loc[is_tr, cols].fillna(0).values; ytr = df.loc[is_tr, 'react5'].values
    te = df.loc[~is_tr]; Xte = te[cols].fillna(0).values; yte = te['react5'].values
    if len(np.unique(ytr)) < 2 or len(np.unique(yte)) < 2:
        return np.nan
    m = HistGradientBoostingClassifier(max_iter=400, learning_rate=0.04, max_leaf_nodes=31,
        min_samples_leaf=30, l2_regularization=1.0, random_state=0).fit(Xtr, ytr)
    return roc_auc_score(yte, m.predict_proba(Xte)[:, 1])


def main():
    df = pd.read_csv(OUT / 'dataset.csv'); df['time'] = pd.to_datetime(df['time'], utc=True)
    df = df.sort_values('time').reset_index(drop=True)
    is_tr = (df['time'] < TRAIN_END).values
    print("=" * 74)
    print("zone_reactor ДИАГНОСТИКА: сила зоны или волатильность?")
    print("=" * 74)
    print("\nOOS AUC по группам фич (pooled):")
    print(f"   ВСЕ ({len(ALL)}):                 {fit_auc(df, ALL, is_tr):.3f}")
    print(f"   БЕЗ волатильности:          {fit_auc(df, ZONE+ICT+TREND+['side_long'], is_tr):.3f}")
    print(f"   ТОЛЬКО зоны ({len(ZONE)}):           {fit_auc(df, ZONE, is_tr):.3f}")
    print(f"   ТОЛЬКО ICT ({len(ICT)}):            {fit_auc(df, ICT, is_tr):.3f}")
    print(f"   ТОЛЬКО волатильность ({len(VOL)}):   {fit_auc(df, VOL, is_tr):.3f}")
    print(f"   ТОЛЬКО atr_pct:             {fit_auc(df, ['atr_pct'], is_tr):.3f}")
    print(f"   зоны+ICT (без vol/trend):   {fit_auc(df, ZONE+ICT, is_tr):.3f}")

    print("\nPER-ASSET OOS AUC (убирает кросс-актив разницу волатильности):")
    for sym in ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']:
        d = df[df.symbol == sym].reset_index(drop=True)
        itr = (d['time'] < TRAIN_END).values
        a_all = fit_auc(d, ALL, itr); a_zone = fit_auc(d, ZONE+ICT, itr)
        base = d.loc[~itr, 'react5'].mean()*100
        print(f"   {sym}: AUC всё={a_all:.3f}  зоны+ICT={a_zone:.3f}  (реакция база {base:.0f}%, n_te={int((~itr).sum())})")

    print("\n" + "=" * 74)
    a_novol = fit_auc(df, ZONE+ICT+TREND+['side_long'], is_tr)
    a_zone = fit_auc(df, ZONE+ICT, is_tr)
    if a_zone > 0.56 and a_novol > 0.57:
        print(f"СИЛА ЗОНЫ РЕАЛЬНА: зоны+ICT AUC={a_zone:.3f}, без волатильности {a_novol:.3f}.")
        print("  Multi-TF confluence несёт сигнал сверх волатильности → строим GPU-сеть.")
    else:
        print(f"ЭТО ВОЛАТИЛЬНОСТЬ: зоны+ICT только {a_zone:.3f}, без vol {a_novol:.3f}.")
        print("  0.64 был atr_pct (хватит ли волатильности на 5%), не сила зоны. Зоны почти не")
        print("  добавляют. Multi-TF confluence реакцию не предсказывает — как в etap_192.")


if __name__ == '__main__':
    main()
