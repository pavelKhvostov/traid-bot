"""etap_193: forensics ПУТИ движения — как шли эти 5% (победители vs busted) +
предсказуемо ли ПО ХОДУ, что дойдёт.

Сдвиг постановки (идея пользователя): не прогноз в t=0 (доказано непредсказуем,
etap 178-192), а ЧТЕНИЕ ДВИЖЕНИЯ по ходу — как трейдер. Решение обновляется по мере
развития сделки: удержалась зона, пошёл импульс, прошли чекпоинты.

Пул = Bulkowski reversal-сигналы (etap_172), BTC+ETH+SOL, 12h. Вход=breakout,
стоп=структурный low/high, цель=+5%. Резолв на 1h с записью ВСЕГО ПУТИ:
  • финальный исход success(+5% раньше снятия) / busted;
  • чекпоинты +1/+2/+3% — достигнуты ли раньше снятия и за сколько 1h-баров;
  • ранний MAE/MFE (в долях риска) в первые 6/12/24/48 1h-баров;
  • снимок состояния на K=12h (для in-process модели).

Анализ:
  1. ФОРЕНЗИКА: распределения раннего MAE / времени-до-+1% / displacement у
     победителей vs busted — чем путь победителя отличается.
  2. УСЛОВНАЯ ЭСКАЛАЦИЯ: P(success | достиг +c% раньше снятия) vs база — растёт ли.
  3. IN-PROCESS МОДЕЛЬ: среди ещё ОТКРЫТЫХ на +12h, фичи пути ≤12h → предсказать
     финал (purged-CV + OOS). Это and есть «определить по ходу».
  4. ПОЛИТИКА: «держать/добавлять только после +1% подтверждения, резать при глубоком
     раннем MAE» — net_R vs наивный baseline.

Output: output/etap_193_paths.csv
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
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score
from sklearn.inspection import permutation_importance

from data_manager import load_df, compose_from_base
from etap_172_bulkowski_patterns import DETECTORS, LOOKBACK, SWING_N

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
START_DATE = pd.Timestamp("2020-01-01", tz="UTC")
END_DATE = pd.Timestamp("2026-05-01", tz="UTC")
TRAIN_END = pd.Timestamp("2024-01-01", tz="UTC")
OUT = _ROOT / 'research' / 'elements_study' / 'output'
TARGET = 5.0
TIMEOUT_1H = 30 * 24      # 30 дней
SNAPS = [6, 12, 24, 48]   # 1h-бары для снимков
HORIZON_D = 30; EMBARGO_D = 3


def resolve_path(side, entry, stop, h1, l1, c1, start, n):
    """Полный путь сделки на 1h. Возвращает dict пути или None."""
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    tp = entry * (1 + TARGET/100) if side == 'long' else entry * (1 - TARGET/100)
    end = min(start + TIMEOUT_1H, n)
    cp_bar = {1.0: None, 2.0: None, 3.0: None}
    mae = 0.0; mfe = 0.0                    # в долях риска (mae>0 к стопу)
    snap = {k: None for k in SNAPS}
    outcome = 'timeout'; out_bar = end - start
    for b in range(start, end):
        k = b - start
        hi = h1[b]; lo = l1[b]
        if side == 'long':
            fav = (hi - entry) / risk; adv = (entry - lo) / risk
            fav_pct = (hi - entry) / entry * 100
            hit_stop = lo <= stop; hit_tp = hi >= tp
        else:
            fav = (entry - lo) / risk; adv = (hi - entry) / risk
            fav_pct = (entry - lo) / entry * 100
            hit_stop = hi >= stop; hit_tp = lo <= tp
        # снимок ДО обработки стопа (состояние на конец бара k)
        if hit_stop:
            outcome = 'busted'; out_bar = k; break
        mfe = max(mfe, fav); mae = max(mae, adv)
        for cp in (1.0, 2.0, 3.0):
            if cp_bar[cp] is None and fav_pct >= cp:
                cp_bar[cp] = k
        if (k + 1) in snap and snap[k + 1] is None:
            snap[k + 1] = (mae, mfe, cp_bar[1.0] is not None, cp_bar[2.0] is not None)
        if hit_tp:
            outcome = 'success'; out_bar = k; break
    # доснять снимки, если сделка кончилась раньше snap-бара (mae/mfe заморожены)
    for sk in SNAPS:
        if snap[sk] is None:
            snap[sk] = (mae, mfe, cp_bar[1.0] is not None, cp_bar[2.0] is not None)
    # signed R по close на отметках 12/24ч (для политики early-cut)
    def r_at(k):
        b = start + k
        if b >= n:
            b = n - 1
        px = c1[b]
        return ((px - entry) if side == 'long' else (entry - px)) / risk
    return {
        'success': 1 if outcome == 'success' else 0, 'outcome': outcome, 'out_bar': out_bar,
        'cp1_bar': cp_bar[1.0], 'cp2_bar': cp_bar[2.0], 'cp3_bar': cp_bar[3.0],
        'reached_1pct': int(cp_bar[1.0] is not None), 'reached_2pct': int(cp_bar[2.0] is not None),
        'reached_3pct': int(cp_bar[3.0] is not None),
        'mae6': snap[6][0], 'mfe6': snap[6][1], 'r1_6': int(snap[6][2]),
        'mae12': snap[12][0], 'mfe12': snap[12][1], 'r1_12': int(snap[12][2]), 'r2_12': int(snap[12][3]),
        'mae24': snap[24][0], 'mfe24': snap[24][1],
        'mae48': snap[48][0], 'mfe48': snap[48][1],
        'risk_pct': risk / entry * 100, 'rr_at_target': (TARGET/100) / (risk/entry),
        # ОТКРЫТА ли на +12h (не снята и не дошла +5%): для in-process модели
        'open_at_12': int(out_bar > 12), 'r_at_12': r_at(12), 'r_at_24': r_at(24),
    }


def build_symbol(sym):
    d1h = load_df(sym, "1h"); d1h = d1h[(d1h.index >= START_DATE) & (d1h.index <= END_DATE)].copy()
    df12 = compose_from_base(d1h, "12h"); df12 = df12[(df12.index >= START_DATE) & (df12.index <= END_DATE)].copy().reset_index()
    if 'time' not in df12.columns:
        df12 = df12.rename(columns={df12.columns[0]: 'time'})
    times = df12['time']; n12 = len(df12)
    h1 = d1h['high'].values.astype(float); l1 = d1h['low'].values.astype(float)
    c1 = d1h['close'].values.astype(float)
    t1_ns = d1h.index.values.astype('datetime64[ns]').astype(np.int64)
    rows = []
    for i in range(LOOKBACK + SWING_N + 2, n12 - SWING_N):
        fired = [s for s in (det(df12, i) for det in DETECTORS) if s is not None]
        if not fired:
            continue
        t_close_ns = (times.iloc[i] + pd.Timedelta(hours=12)).value
        start = int(np.searchsorted(t1_ns, t_close_ns, side='left'))
        if start >= len(c1):
            continue
        for sig in fired:
            side = sig['side']; entry = sig['breakout_price']
            stop = sig['low_price'] if side == 'long' else sig['high_price']
            p = resolve_path(side, entry, stop, h1, l1, c1, start, len(c1))
            if p is None:
                continue
            p.update({'symbol': sym, 'time': times.iloc[i], 'side_long': 1 if side == 'long' else 0,
                      'pattern': sig['pattern']})
            rows.append(p)
    return rows


def purged_cv(X, y, t):
    order = np.argsort(t); folds = np.array_split(order, 5); aucs = []
    for f in folds:
        lo, hi = t[f].min(), t[f].max()
        keep = np.ones(len(y), bool); keep[f] = False
        keep &= ~((t + HORIZON_D >= lo - EMBARGO_D) & (t <= hi + EMBARGO_D))
        if keep.sum() < 80 or y[f].sum() < 5 or len(np.unique(y[keep])) < 2:
            continue
        m = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, max_leaf_nodes=15,
            min_samples_leaf=20, l2_regularization=1.0, random_state=0).fit(X[keep], y[keep])
        aucs.append(roc_auc_score(y[f], m.predict_proba(X[f])[:, 1]))
    return (np.mean(aucs), len(aucs)) if aucs else (np.nan, 0)


def main():
    t0 = time.time()
    print("=" * 82)
    print("etap_193: forensics ПУТИ +5% (победители vs busted) + предсказуемость ПО ХОДУ")
    print("=" * 82)
    rows = []
    for sym in SYMBOLS:
        r = build_symbol(sym); rows.extend(r)
        print(f"  [{sym}] сигналов: {len(r)}")
    df = pd.DataFrame(rows).sort_values('time').reset_index(drop=True)
    df['t_days'] = (df['time'] - df['time'].min()).dt.total_seconds() / 86400.0
    df.to_csv(OUT / 'etap_193_paths.csv', index=False)
    base = df['success'].mean() * 100
    print(f"\nВСЕГО: {len(df)}  success(+5%>снятие)%={base:.1f}")

    # 1) ФОРЕНЗИКА: путь победителя vs busted
    print("\n1) ПУТЬ: победители vs busted (медианы):")
    W = df[df.success == 1]; B = df[df.success == 0]
    print(f"   {'метрика':>16} {'WIN':>8} {'BUST':>8}")
    for m, lab in [('mae6', 'ранний MAE 6h'), ('mae12', 'MAE 12h'), ('mae24', 'MAE 24h'),
                   ('mfe12', 'MFE 12h'), ('out_bar', 'баров до развязки'), ('cp1_bar', 'баров до +1%')]:
        wv = W[m].median(); bv = B[m].median()
        print(f"   {lab:>16} {wv:>8.2f} {bv:>8.2f}")
    print(f"   достигли +1% (любой момент): WIN {W['reached_1pct'].mean()*100:.0f}% / BUST {B['reached_1pct'].mean()*100:.0f}%")
    print(f"   достигли +2%:                WIN {W['reached_2pct'].mean()*100:.0f}% / BUST {B['reached_2pct'].mean()*100:.0f}%")

    # 2) УСЛОВНАЯ ЭСКАЛАЦИЯ: P(success | достиг +c% раньше снятия)
    print(f"\n2) P(дойдёт +5% | уже достиг +c% раньше снятия) — база {base:.1f}%:")
    for cp, col in [(1.0, 'reached_1pct'), (2.0, 'reached_2pct'), (3.0, 'reached_3pct')]:
        sub = df[df[col] == 1]
        print(f"   достиг +{cp:.0f}%: n={len(sub):>4} ({len(sub)/len(df)*100:>3.0f}%)  P(+5%)={sub['success'].mean()*100:>4.1f}%")
    # ранний MAE как сигнал
    print("   по раннему MAE (12h, доля риска):")
    df['mae12_b'] = pd.qcut(df['mae12'].rank(method='first'), 4, labels=['мелкий', 'Q2', 'Q3', 'глубокий'])
    for b, g in df.groupby('mae12_b'):
        print(f"     MAE12 {b:>9}: success%={g['success'].mean()*100:.1f} (n={len(g)})")

    # 3) IN-PROCESS МОДЕЛЬ: среди открытых на +12h, путь ≤12h → финал
    op = df[df.open_at_12 == 1].copy()
    PATH_F = ['mae6', 'mfe6', 'r1_6', 'mae12', 'mfe12', 'r1_12', 'r2_12', 'risk_pct', 'side_long']
    is_tr = (op['time'] < TRAIN_END).values
    Xtr = op.loc[is_tr, PATH_F].fillna(0).values; ytr = op.loc[is_tr, 'success'].values
    te = op.loc[~is_tr].copy(); Xte = te[PATH_F].fillna(0).values; yte = te['success'].values
    print(f"\n3) IN-PROCESS модель (открытые на +12h: n={len(op)}, база success={op['success'].mean()*100:.1f}%):")
    if len(np.unique(ytr)) == 2 and len(np.unique(yte)) == 2:
        cv, k = purged_cv(Xtr, ytr, op.loc[is_tr, 't_days'].values)
        clf = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, max_leaf_nodes=15,
            min_samples_leaf=20, l2_regularization=1.0, random_state=42).fit(Xtr, ytr)
        oos = roc_auc_score(yte, clf.predict_proba(Xte)[:, 1])
        print(f"   путь≤12h → финал: purgedCV AUC={cv:.3f}  OOS AUC={oos:.3f}  (база t=0 была ~0.52)")
        te['p'] = clf.predict_proba(Xte)[:, 1]
        b2 = yte.mean() * 100
        print(f"   отсев по P (OOS, среди открытых): база success={b2:.1f}%")
        for tau in [0.55, 0.6, 0.65, 0.7]:
            sel = te[te.p >= tau]
            if len(sel) < 15: continue
            print(f"     P≥{tau}: n={len(sel):>4} ({len(sel)/len(te)*100:>3.0f}%)  success%={sel['success'].mean()*100:>4.1f}  Δ={sel['success'].mean()*100-b2:>+4.1f}pp")
        pi = permutation_importance(clf, Xte, yte, n_repeats=8, random_state=0, scoring='roc_auc')
        for nm, mn in sorted(zip(PATH_F, pi.importances_mean), key=lambda x: -x[1])[:6]:
            print(f"     imp {nm:>10}: {mn:+.4f}")

        # mean net_R по квартилям P (сайзинг-потенциал: растёт ли R с P?)
        te['final_R'] = np.where(te.success == 1, te.rr_at_target, -1.0)
        te['pq'] = pd.qcut(te['p'].rank(method='first'), 4, labels=['Q1-низк', 'Q2', 'Q3', 'Q4-выс'])
        print("   mean net_R(full TP) по квартилям P (сайзинг-тест):")
        for b, g in te.groupby('pq'):
            print(f"     P {b:>7}: n={len(g):>3} success%={g['success'].mean()*100:>4.0f} "
                  f"mean R={g['final_R'].mean():+.3f}  rr_med={g['rr_at_target'].median():.2f}")

        # 4) ПОЛИТИКА early-cut: режем открытые-на-12ч с высоким P(bust) на 12ч-close
        dft = df[df.time >= TRAIN_END].copy()
        dft['final_R'] = np.where(dft.success == 1, dft.rr_at_target, -1.0)
        dft['p'] = np.nan
        dft.loc[te.index, 'p'] = te['p']
        base_R = dft['final_R'].sum()
        print(f"\n4) ПОЛИТИКА early-cut (OOS): baseline 'держать всё' ΣR={base_R:+.0f} "
              f"R/tr={dft['final_R'].mean():+.3f} (n={len(dft)})")
        print(f"   {'τcut':>5} {'cut_n':>6} {'ΣR':>7} {'Δ':>7} {'R/tr':>7}")
        for tau in [0.40, 0.45, 0.50, 0.55]:
            cut = dft['open_at_12'].eq(1) & dft['p'].notna() & (dft['p'] < tau)
            managed = np.where(cut, dft['r_at_12'], dft['final_R'])
            tot = managed.sum()
            print(f"   {tau:>5.2f} {int(cut.sum()):>6} {tot:>+7.0f} {tot-base_R:>+7.0f} {managed.mean():>+7.3f}")
        # лучшая по годам
        cut = dft['open_at_12'].eq(1) & dft['p'].notna() & (dft['p'] < 0.45)
        dft['managed_R'] = np.where(cut, dft['r_at_12'], dft['final_R'])
        dft['yr'] = dft['time'].dt.year
        print("   τcut=0.45 по годам (managed vs baseline ΣR):")
        for yr, g in dft.groupby('yr'):
            print(f"     {yr}: managed {g['managed_R'].sum():+6.0f}  baseline {g['final_R'].sum():+6.0f}  Δ={g['managed_R'].sum()-g['final_R'].sum():+5.0f}")

    print("\n" + "=" * 82)
    print("Смотри блок 2: если P(+5%|+2%) >> база — развязка ЧИТАЕТСЯ по ходу (управление,")
    print("не вход). Блок 3 OOS AUC > 0.55 = ранний путь предсказывает финал.")
    print(f"Done in {time.time()-t0:.1f}s")


if __name__ == '__main__':
    main()
