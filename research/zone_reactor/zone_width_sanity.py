"""zone_reactor.zone_width_sanity — критика пользователя: «широкие зоны = глупость, не зона».

Если held-зоны / high-P зоны на деле 10-15% шириной, то «реакция +5% раньше закрытия за
дальним краем» выполняется тривиально (5% << ширины) → edge = артефакт абсурдных зон.
Killer-тест: выживает ли AUC и net_R на РЕАЛИСТИЧНЫХ зонах (ширина ≤2/3/5%)?
"""
from __future__ import annotations
import sys
from pathlib import Path
_ROOT = Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score
OUT = _ROOT / 'research' / 'zone_reactor'
TRAIN_END = pd.Timestamp("2024-01-01", tz="UTC")
FEAT = ['tf_w', 'is_ob', 'conf_count', 'conf_strength', 'in_htf', 'n_tf_aligned', 'disp_body',
        'age_h', 'pos_in_range', 'zone_width_pct', 'side_long', 'atr_pct', 'vol_z', 'rsi14',
        'ema200_dist', 'hull_dir', 'htf_1d_dir', 'htf_3d_dir']


def main():
    df = pd.read_csv(OUT / 'zone_touch_dataset.csv'); df['time'] = pd.to_datetime(df['time'], utc=True)
    df = df.sort_values('time').reset_index(drop=True); df[FEAT] = df[FEAT].fillna(0)
    is_tr = (df['time'] < TRAIN_END).values
    clf = HistGradientBoostingClassifier(max_iter=400, learning_rate=0.04, max_leaf_nodes=31,
        min_samples_leaf=40, l2_regularization=1.0, random_state=0).fit(df.loc[is_tr, FEAT].values, df.loc[is_tr, 'held'].values)
    df['p'] = clf.predict_proba(df[FEAT].values)[:, 1]
    te = df.loc[~is_tr].copy()
    w = df['zone_width_pct']
    print("=" * 76)
    print("ШИРИНА ЗОНЫ: критика пользователя — широкие зоны это глупость?")
    print("=" * 76)
    print(f"\nРаспределение zone_width_pct (все {len(df)}): "
          f"median={w.median():.2f}%  p75={w.quantile(.75):.2f}%  p90={w.quantile(.9):.2f}%  "
          f"p99={w.quantile(.99):.2f}%  max={w.max():.1f}%")
    print(f"  доля зон шире 5%: {(w>5).mean()*100:.1f}%   шире 10%: {(w>10).mean()*100:.1f}%   шире 15%: {(w>15).mean()*100:.1f}%")
    print(f"\nширина held=1 (реакция): median={df[df.held==1]['zone_width_pct'].median():.2f}%  "
          f"p90={df[df.held==1]['zone_width_pct'].quantile(.9):.2f}%")
    print(f"ширина held=0 (пробой):  median={df[df.held==0]['zone_width_pct'].median():.2f}%  "
          f"p90={df[df.held==0]['zone_width_pct'].quantile(.9):.2f}%")
    hi = te[te.p >= 0.65]
    print(f"\nВЫСОКО-P зоны (P≥0.65, n={len(hi)}): ширина median={hi['zone_width_pct'].median():.2f}%  "
          f"p90={hi['zone_width_pct'].quantile(.9):.2f}%  доля >10%: {(hi['zone_width_pct']>10).mean()*100:.0f}%")

    print("\nТОП-10 P зон — какая у них ширина (правда ли 10-15%?):")
    for _, r in te.sort_values('p', ascending=False).head(10).iterrows():
        print(f"   {r['symbol']} {r['time'].strftime('%Y-%m-%d')} "
              f"{'LONG' if r['side_long']==1 else 'SHORT'}  ширина={r['zone_width_pct']:>5.1f}%  "
              f"P={r['p']:.2f}  held={int(r['held'])}")

    # KILLER: edge на РЕАЛИСТИЧНЫХ зонах (узкие)
    print("\n" + "=" * 76)
    print("KILLER-ТЕСТ: выживает ли edge на РЕАЛИСТИЧНЫХ зонах (ширина ≤ порога)?")
    print("=" * 76)
    print(f"{'макс.ширина':>12} {'n_te':>6} {'held%':>6} {'AUC':>6} {'P≥0.6 R/tr':>11} {'P≥0.6 n':>8}")
    for wmax in [2.0, 3.0, 5.0, 100.0]:
        sub_tr = df[is_tr & (df.zone_width_pct <= wmax)]
        sub_te = te[te.zone_width_pct <= wmax].copy()
        if len(sub_te) < 50 or sub_tr['held'].nunique() < 2:
            continue
        c2 = HistGradientBoostingClassifier(max_iter=400, learning_rate=0.04, max_leaf_nodes=31,
            min_samples_leaf=40, l2_regularization=1.0, random_state=0).fit(sub_tr[FEAT].values, sub_tr['held'].values)
        pte = c2.predict_proba(sub_te[FEAT].values)[:, 1]
        auc = roc_auc_score(sub_te['held'], pte) if sub_te['held'].nunique() == 2 else np.nan
        risk = np.clip(sub_te['zone_width_pct'].values/100, 0.003, None); rr = 0.05/risk
        netR = np.where(sub_te['held'] == 1, rr, -1.0) - (2*0.0008)/risk
        sel = netR[pte >= 0.6]
        lbl = '≤%.0f%%' % wmax if wmax < 100 else 'все'
        print(f"{lbl:>12} {len(sub_te):>6} {sub_te['held'].mean()*100:>5.0f} {auc:>6.3f} "
              f"{(sel.mean() if len(sel) else float('nan')):>+11.3f} {len(sel):>8}")

    print("\n" + "=" * 76)
    hi_wide = (hi['zone_width_pct'] > 10).mean() * 100
    print(f"ВЫВОД: {hi_wide:.0f}% высоко-P зон шире 10%. См. killer-тест — если на узких "
          f"(≤2-3%) AUC→0.5 и R/tr→0, то ты прав: edge был на абсурдно широких 'зонах'.")


if __name__ == '__main__':
    main()
