"""etap_185: валидация big_m busted-сепаратора (lead из etap_184).

etap_184 нашёл единственный устойчивый OOS-сепаратор good/bad среди Bulkowski-
паттернов — у big_m: dist_swing_hi_pct (sign+) и rr_at_target (sign−, далёкий стоп),
оба держатся train↔te (AUC ~0.64). Проверяем, лид это или fluke:

  1. PER-ASSET: держится ли сепаратор на BTC/ETH/SOL по отдельности (univariate AUC
     train→test), или его тянет один актив.
  2. PER-YEAR (OOS): good% baseline vs после фильтра по годам 2024/2025/2026.
  3. КОМПОЗИТ-ФИЛЬТР: dist_swing_hi_pct ≥ thr ∩ rr_at_target ≤ thr (пороги = TRAIN-
     медиана, без подглядывания в OOS). good% и kept n на OOS.
  4. NET_R с издержками (колонка net_R = торговля TP+5%/SL=структурный, etap_177-178):
     даёт ли фильтр торгуемый плюс или good% растёт ценой ΣR.

Данные: output/etap_178_labeled.csv (pattern == 'big_m').
Output: output/etap_185_big_m.csv
"""
from __future__ import annotations
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

OUT = _ROOT / 'research' / 'elements_study' / 'output'
SEPS = [('dist_swing_hi_pct', +1), ('rr_at_target', -1)]


def uni(y, x, sign):
    if len(np.unique(y)) < 2 or np.nanstd(x) == 0:
        return np.nan
    return roc_auc_score(y, sign * x)


def main():
    df = pd.read_csv(OUT / 'etap_178_labeled.csv')
    df['time'] = pd.to_datetime(df['time'], utc=True)
    d = df[df.pattern == 'big_m'].copy()
    tr = d[d.period == 'train']; te = d[d.period == 'test']
    print("=" * 78)
    print(f"etap_185: валидация big_m сепаратора · n train={len(tr)} test={len(te)}")
    print(f"  baseline good%: train={tr['success'].mean()*100:.1f}  test={te['success'].mean()*100:.1f}")
    print(f"  baseline net_R: train ΣR={tr['net_R'].sum():+.1f} (R/tr {tr['net_R'].mean():+.3f})  "
          f"test ΣR={te['net_R'].sum():+.1f} (R/tr {te['net_R'].mean():+.3f})")
    print("=" * 78)

    # 1. PER-ASSET univariate AUC (train→test)
    print("\n1) PER-ASSET univariate AUC (train→test):")
    print(f"{'asset':>8} {'ntr':>4}{'nte':>4}  {'good%te':>7}  "
          f"{'dist_hi tr→te':>15}  {'rr_tgt tr→te':>15}")
    for a in ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']:
        atr_ = tr[tr.symbol == a]; ate = te[te.symbol == a]
        if len(atr_) < 15 or len(ate) < 10:
            print(f"{a:>8} {len(atr_):>4}{len(ate):>4}  — мало")
            continue
        row = f"{a:>8} {len(atr_):>4}{len(ate):>4}  {ate['success'].mean()*100:>6.0f}%  "
        for feat, sgn in SEPS:
            atr_auc = uni(atr_['success'].values, atr_[feat].values, sgn)
            ate_auc = uni(ate['success'].values, ate[feat].values, sgn)
            row += f"  {atr_auc:>5.2f}→{ate_auc:<5.2f}"
        print(row)

    # 2 & 3. КОМПОЗИТ-ФИЛЬТР: пороги = TRAIN-медиана (без подглядывания)
    thr_dist = tr['dist_swing_hi_pct'].median()
    thr_rr = tr['rr_at_target'].median()
    print(f"\n2) КОМПОЗИТ-ФИЛЬТР (пороги по TRAIN-медиане): "
          f"dist_swing_hi≥{thr_dist:.2f} ∩ rr_at_target≤{thr_rr:.2f}")

    def report(name, sub_full, mask):
        base = sub_full['success'].mean() * 100
        sel = sub_full[mask]
        if len(sel) == 0:
            print(f"  {name}: пусто"); return
        print(f"  {name}: kept {len(sel)}/{len(sub_full)} ({len(sel)/len(sub_full)*100:.0f}%)  "
              f"good% {sel['success'].mean()*100:.0f} (base {base:.0f}, Δ{sel['success'].mean()*100-base:+.0f}pp)  "
              f"ΣnetR {sel['net_R'].sum():+.1f} (base {sub_full['net_R'].sum():+.1f})  "
              f"R/tr {sel['net_R'].mean():+.3f} (base {sub_full['net_R'].mean():+.3f})")

    for label, sub in [('TRAIN (in-sample)', tr), ('TEST (OOS)', te)]:
        print(f"  --- {label} ---")
        m_dist = sub['dist_swing_hi_pct'] >= thr_dist
        m_rr = sub['rr_at_target'] <= thr_rr
        report('dist_hi only ', sub, m_dist)
        report('rr_tgt only  ', sub, m_rr)
        report('composite ∩  ', sub, m_dist & m_rr)

    # 4. PER-YEAR (OOS) baseline vs composite
    print("\n3) PER-YEAR (OOS) baseline vs composite-filter:")
    te2 = te.copy(); te2['yr'] = te2['time'].dt.year
    m = (te2['dist_swing_hi_pct'] >= thr_dist) & (te2['rr_at_target'] <= thr_rr)
    te2['kept'] = m
    for yr, g in te2.groupby('yr'):
        gk = g[g.kept]
        print(f"  {yr}: base n={len(g):>3} good%={g['success'].mean()*100:>3.0f} ΣR={g['net_R'].sum():>+5.1f}"
              f"  →  filtered n={len(gk):>3} good%={(gk['success'].mean()*100 if len(gk) else 0):>3.0f} "
              f"ΣR={gk['net_R'].sum():>+5.1f}")

    # save
    out = te.copy()
    out['kept_composite'] = ((out['dist_swing_hi_pct'] >= thr_dist) & (out['rr_at_target'] <= thr_rr)).astype(int)
    out[['symbol', 'time', 'side_long', 'dist_swing_hi_pct', 'rr_at_target',
         'success', 'net_R', 'kept_composite']].to_csv(OUT / 'etap_185_big_m.csv', index=False)

    # ВЕРДИКТ
    sel = te[(te['dist_swing_hi_pct'] >= thr_dist) & (te['rr_at_target'] <= thr_rr)]
    base_rtr = te['net_R'].mean(); sel_rtr = sel['net_R'].mean() if len(sel) else np.nan
    print("\n" + "=" * 78)
    yk = te2[te2.kept].groupby('yr')['net_R'].sum()
    bad_years = (yk < 0).sum()
    print(f"ВЕРДИКТ big_m composite-фильтр (OOS): kept {len(sel)}/{len(te)}, "
          f"good% {sel['success'].mean()*100:.0f} vs {te['success'].mean()*100:.0f}, "
          f"R/tr {sel_rtr:+.3f} vs {base_rtr:+.3f}, bad years {bad_years}/{te2['yr'].nunique()}")
    if len(sel) >= 25 and sel['success'].mean()*100 - te['success'].mean()*100 > 5 \
       and sel_rtr > base_rtr and bad_years == 0:
        print("  → ЛИД ПОДТВЕРЖДЁН: фильтр поднимает good% И R/tr, 0 плохих лет. Торгуемый busted-фильтр для big_m.")
    else:
        print("  → СЛАБО/ШУМ: фильтр не даёт устойчивого торгуемого плюса (мало n / нет роста R/tr / есть плохой год).")
    print(f"Saved: {OUT/'etap_185_big_m.csv'}")


if __name__ == '__main__':
    main()
