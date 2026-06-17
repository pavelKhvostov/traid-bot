"""etap_190: диагностика — AUC 0.758 из etap_189 это сигнал или ГЕОМЕТРИЯ ЛЕЙБЛА?

etap_189 дал OOS AUC 0.758, но importance топ = side_long / close_pos / range_atr —
подозрение на тавтологию: стоп = собственный low/high свечи, поэтому "дойдёт до +5%
раньше снятия" тривиально зависит от того, КАК ДАЛЕКО стоп (close_pos), а не от
предсказания движения. Проверяем тремя способами:

  1. Single-feature OOS AUC геометрии (close_pos, range_atr, side_long, atr_pct).
  2. OOS AUC модели БЕЗ геометрии/направления (только market-state индикаторы:
     RSI/MACD/ADX/тренд/vol/macro) — если падает к 0.5, AUC был геометрией.
  3. КОНВЕРТАЦИЯ В net_R: реконструируем risk_pct из фич (long: close_pos·range_atr·
     atr_pct/100; short: (1-close_pos)·…), rr=5%/risk. Фильтр по P повышает good%,
     но падает ли R/tr и ΣnetR (т.к. высокий P = далёкий стоп = rr<1)?

Если (а) close_pos в одиночку даёт ~0.7, (б) без геометрии AUC≈0.5, (в) фильтр не
улучшает net_R — значит edge'а нет, 0.758 был артефактом определения лейбла.

Output: только печать.
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
TARGET = 5.0
SIDE_COST = 0.0008   # taker+slip / сторону

# фичи геометрии лейбла / направления (подозреваемые тавтологии)
GEOM = {'close_pos', 'range_atr', 'side_long', 'upper_wick', 'lower_wick', 'body_pct',
        'gap', 'is_bull', 'atr_pct', 'bb_bw', 'parkinson', 'realized_vol'}


def main():
    df = pd.read_csv(OUT / 'etap_189_dataset.csv')
    df['time'] = pd.to_datetime(df['time'], utc=True)
    df = df.sort_values('time').reset_index(drop=True)
    feat = [c for c in df.columns if c not in ('symbol', 'time', 'y', 't_days') and df[c].dtype != object]
    df[feat] = df[feat].fillna(0)
    is_tr = (df['time'] < TRAIN_END).values
    te = df.loc[~is_tr].copy(); ytr = df.loc[is_tr, 'y'].values; yte = te['y'].values

    print("=" * 78)
    print("etap_190: диагностика AUC 0.758 — сигнал или геометрия лейбла?")
    print("=" * 78)

    # 1. single-feature OOS AUC
    print("\n1) Single-feature OOS AUC (одна фича как скор):")
    for c in ['close_pos', 'range_atr', 'side_long', 'atr_pct', 'usdtd_1d_ret', 'rsi14', 'macd_hist', 'adx']:
        x = te[c].values
        if np.nanstd(x) == 0:
            continue
        a = roc_auc_score(yte, x); a = max(a, 1 - a)
        print(f"   {c:>14}: AUC={a:.3f}")

    # 2. модель БЕЗ геометрии/направления
    market = [c for c in feat if c not in GEOM]
    def fit_auc(cols):
        m = HistGradientBoostingClassifier(max_iter=500, learning_rate=0.03, max_leaf_nodes=31,
            min_samples_leaf=80, l2_regularization=1.0, random_state=0).fit(df.loc[is_tr, cols].values, ytr)
        return roc_auc_score(yte, m.predict_proba(te[cols].values)[:, 1])
    print("\n2) OOS AUC модели:")
    print(f"   ВСЕ фичи ({len(feat)}):                 {fit_auc(feat):.3f}")
    print(f"   БЕЗ геометрии/направления ({len(market)}): {fit_auc(market):.3f}")
    print(f"   ТОЛЬКО геометрия ({len(GEOM & set(feat))}):        {fit_auc(list(GEOM & set(feat))):.3f}")
    print(f"   ТОЛЬКО close_pos:                  {fit_auc(['close_pos']):.3f}")

    # 3. конвертация в net_R (реконструкция risk из фич)
    print("\n3) КОНВЕРТАЦИЯ В net_R (реконструкция risk_pct из фич):")
    full = HistGradientBoostingClassifier(max_iter=600, learning_rate=0.03, max_leaf_nodes=31,
        min_samples_leaf=80, l2_regularization=1.0, random_state=42).fit(df.loc[is_tr, feat].values, ytr)
    te['p'] = full.predict_proba(te[feat].values)[:, 1]
    rng_over_c = te['range_atr'] * te['atr_pct'] / 100.0
    risk_pct = np.where(te['side_long'] == 1, te['close_pos'] * rng_over_c,
                        (1 - te['close_pos']) * rng_over_c)
    risk_pct = np.clip(risk_pct, 1e-4, None)
    rr = (TARGET / 100.0) / risk_pct
    cost_R = (2 * SIDE_COST) / risk_pct
    net_R = np.where(te['y'] == 1, rr, -1.0) - cost_R
    te['rr'] = rr; te['net_R'] = net_R
    print(f"   rr_at_target медиана={np.median(rr):.2f}  (rr<1 → нужен WR>50% просто в ноль)")
    print(f"   baseline ВСЕ: n={len(te)}  good%={yte.mean()*100:.1f}  ΣnetR={net_R.sum():+.0f}  R/tr={net_R.mean():+.3f}")
    print(f"   {'τ':>5} {'n':>6} {'good%':>6} {'rr_med':>7} {'ΣnetR':>7} {'R/tr':>7}")
    for tau in [0.5, 0.6, 0.7, 0.8]:
        sel = te[te.p >= tau]
        if len(sel) < 20:
            continue
        print(f"   {tau:>5.2f} {len(sel):>6} {sel['y'].mean()*100:>5.1f} {sel['rr'].median():>7.2f} "
              f"{sel['net_R'].sum():>+7.0f} {sel['net_R'].mean():>+7.3f}")

    print("\n" + "=" * 78)
    a_market = fit_auc(market); a_cp = fit_auc(['close_pos'])
    if a_market < 0.55 and a_cp > 0.6:
        print(f"ПОДТВЕРЖДЕНО — ТАВТОЛОГИЯ: close_pos один даёт AUC={a_cp:.2f}, market-only={a_market:.2f}.")
        print("  AUC 0.758 был геометрией лейбла (как далеко собственный стоп), НЕ предсказанием.")
        print("  В net_R не конвертируется (высокий P = далёкий стоп = rr<1). Edge'а нет.")
    else:
        print(f"market-only AUC={a_market:.3f}, close_pos AUC={a_cp:.3f} — смотреть net_R-таблицу выше.")


if __name__ == '__main__':
    main()
