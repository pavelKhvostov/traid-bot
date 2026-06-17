"""zone_reactor.zone_touch_verify — held/broke AUC 0.73 реальный/торгуемый или тавтология?

Проверки: (1) AUC без zone_width (широкая зона → дальний край далеко → held механически);
(2) net_R: стратегия вход-на-касании, TP +5%, SL=дальний край (risk≈zone_width); фильтр
по P улучшает ΣR? (3) per-year. (4) роль multi-TF confluence отдельно.
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
SIDE_COST = 0.0008
ZONE_F = ['tf_w', 'is_ob', 'conf_count', 'conf_strength', 'in_htf', 'n_tf_aligned',
          'disp_body', 'age_h', 'pos_in_range', 'zone_width_pct', 'side_long']
VOL_F = ['atr_pct', 'vol_z']; TREND_F = ['rsi14', 'ema200_dist', 'hull_dir', 'htf_1d_dir', 'htf_3d_dir']
ALL_F = ZONE_F + VOL_F + TREND_F
CONFL = ['conf_count', 'conf_strength', 'in_htf', 'n_tf_aligned']  # «multi-TF сила зоны» в чистом виде


def fit(df, cols, is_tr):
    Xtr = df.loc[is_tr, cols].fillna(0).values; ytr = df.loc[is_tr, 'held'].values
    te = df.loc[~is_tr]
    m = HistGradientBoostingClassifier(max_iter=400, learning_rate=0.04, max_leaf_nodes=31,
        min_samples_leaf=40, l2_regularization=1.0, random_state=0).fit(Xtr, ytr)
    return roc_auc_score(te['held'].values, m.predict_proba(te[cols].fillna(0).values)[:, 1]), m


def main():
    df = pd.read_csv(OUT / 'zone_touch_dataset.csv'); df['time'] = pd.to_datetime(df['time'], utc=True)
    df = df.sort_values('time').reset_index(drop=True)
    is_tr = (df['time'] < TRAIN_END).values
    print("=" * 76); print("zone_touch ВЕРИФИКАЦИЯ: реально/торгуемо или тавтология?"); print("=" * 76)

    print("\n1) AUC по группам (тавтология-чек):")
    for nm, cols in [('ВСЕ', ALL_F), ('без zone_width', [c for c in ALL_F if c != 'zone_width_pct']),
                     ('multi-TF confluence ТОЛЬКО', CONFL), ('зоны без width&confl',
                      [c for c in ZONE_F if c not in CONFL + ['zone_width_pct']]),
                     ('rsi+premium+age ТОЛЬКО', ['rsi14', 'pos_in_range', 'age_h'])]:
        a, _ = fit(df, cols, is_tr)
        print(f"   {nm:>26}: {a:.3f}")

    # 2) net_R: вход на касании, TP+5%, SL=дальний край (risk≈zone_width)
    a_all, clf = fit(df, ALL_F, is_tr)
    te = df.loc[~is_tr].copy()
    te['p'] = clf.predict_proba(te[ALL_F].fillna(0).values)[:, 1]
    risk = np.clip(te['zone_width_pct'].values / 100.0, 0.003, None)
    rr = (0.05) / risk
    cost = (2 * SIDE_COST) / risk
    te['net_R'] = np.where(te['held'] == 1, rr, -1.0) - cost
    base = te['net_R'].sum()
    print(f"\n2) net_R (вход на касании, TP+5%, SL=дальний край): rr_med={np.median(rr):.2f}")
    print(f"   baseline ВСЕ касания: n={len(te)} held%={te['held'].mean()*100:.0f} "
          f"ΣnetR={base:+.0f} R/tr={te['net_R'].mean():+.3f}")
    print(f"   {'P≥':>5} {'n':>5} {'held%':>6} {'rr_med':>7} {'ΣnetR':>8} {'R/tr':>7}")
    for tau in [0.5, 0.6, 0.7]:
        sel = te[te.p >= tau]
        if len(sel) < 30: continue
        print(f"   {tau:>5.2f} {len(sel):>5} {sel['held'].mean()*100:>5.0f} "
              f"{np.median(0.05/np.clip(sel['zone_width_pct']/100,0.003,None)):>7.2f} "
              f"{sel['net_R'].sum():>+8.0f} {sel['net_R'].mean():>+7.3f}")

    # 3) per-year R/tr при P≥0.6
    sel = te[te.p >= 0.6].copy(); sel['yr'] = sel['time'].dt.year
    print("\n3) P≥0.6 по годам:  ", end='')
    print("  ".join(f"{y}:n{len(g)}/R/tr{g['net_R'].mean():+.2f}" for y, g in sel.groupby('yr')))

    print("\n" + "=" * 76)
    a_nw, _ = fit(df, [c for c in ALL_F if c != 'zone_width_pct'], is_tr)
    a_confl, _ = fit(df, CONFL, is_tr)
    sel6 = te[te.p >= 0.6]
    bad = sum(1 for _, g in sel6.groupby(sel6['time'].dt.year) if g['net_R'].mean() < 0)
    print(f"AUC без width={a_nw:.3f} (с width {a_all:.3f}) | multi-TF confluence-только={a_confl:.3f}")
    if sel6['net_R'].mean() > 0.05 and bad == 0 and a_nw > 0.58:
        print(f"ТОРГУЕМО: фильтр P≥0.6 R/tr={sel6['net_R'].mean():+.3f}, 0 плохих лет, AUC без width {a_nw:.3f}.")
        print("  Сигнал реальный → есть смысл в GPU-сети с самообучением.")
    else:
        print(f"net_R фильтра P≥0.6 R/tr={sel6['net_R'].mean():+.3f}, bad years {bad}. "
              f"multi-TF confluence сам по себе AUC {a_confl:.3f}.")


if __name__ == '__main__':
    main()
